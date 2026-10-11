"""Transforma os CSVs brutos do CAGED em data/public/emprego.json.

Puro e offline: nenhuma leitura de relógio ou rede. `acesso_em` entra por parâmetro.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
from datetime import date
from pathlib import Path

import polars as pl

from schemas.envelope import (
    Cobertura,
    Envelope,
    Flag,
    Fonte,
    Granularidade,
    Qualidade,
    Referencia,
)

RAIZ = Path(__file__).resolve().parent.parent
JANELA_MESES = 24
MESES_SECAO = 12

SECOES_CNAE = {
    "A": "Agricultura, pecuária e pesca",
    "B": "Indústrias extrativas",
    "C": "Indústria de transformação",
    "D": "Eletricidade e gás",
    "E": "Água, esgoto e resíduos",
    "F": "Construção",
    "G": "Comércio e reparação de veículos",
    "H": "Transporte e armazenagem",
    "I": "Alojamento e alimentação",
    "J": "Informação e comunicação",
    "K": "Finanças e seguros",
    "L": "Atividades imobiliárias",
    "M": "Atividades profissionais e técnicas",
    "N": "Serviços administrativos",
    "O": "Administração pública",
    "P": "Educação",
    "Q": "Saúde e assistência social",
    "R": "Artes, cultura e esporte",
    "S": "Outros serviços",
    "T": "Serviços domésticos",
    "U": "Organismos internacionais",
}

COL_COMP = "competênciamov"
COL_SALDO = "saldomovimentação"
COL_SECAO = "seção"


def pastas_declaradas(raw: Path) -> list[Path]:
    return sorted(p for p in raw.iterdir() if p.is_dir() and re.fullmatch(r"\d{6}", p.name))


def meses_ate(ultima: str, n: int) -> list[str]:
    ano, mes = int(ultima[:4]), int(ultima[4:])
    saida = []
    for _ in range(n):
        saida.append(f"{ano}{mes:02d}")
        ano, mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    return saida[::-1]


def carregar(raw: Path) -> pl.DataFrame:
    """Une os agregados MOV/FOR/EXC. Exclusão inverte o evento, então pesa -n."""
    partes = []
    for pasta in pastas_declaradas(raw):
        for tipo in ("MOV", "FOR", "EXC"):
            df = pl.read_csv(
                pasta / f"{tipo}.csv",
                separator=";",
                infer_schema=False,
                columns=[COL_COMP, COL_SECAO, COL_SALDO, "n"],
            )
            partes.append(
                df.with_columns(
                    pl.col(COL_SALDO).cast(pl.Int8).alias("evento"),
                    (pl.col("n").cast(pl.Int64) * (-1 if tipo == "EXC" else 1)).alias("peso"),
                ).select(COL_COMP, COL_SECAO, "evento", "peso")
            )
    return pl.concat(partes)


def agregar(df: pl.DataFrame, por: list[str]) -> pl.DataFrame:
    return (
        df.group_by(por)
        .agg(
            ((pl.col("evento") == 1) * pl.col("peso")).sum().alias("admissoes"),
            ((pl.col("evento") == -1) * pl.col("peso")).sum().alias("desligamentos"),
        )
        .with_columns((pl.col("admissoes") - pl.col("desligamentos")).alias("saldo"))
        .sort(por)
    )


def mes_a_data(comp: str) -> date:
    return date(int(comp[:4]), int(comp[4:]), 1)


def fim_do_mes(comp: str) -> date:
    ano, mes = int(comp[:4]), int(comp[4:])
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def hashes_dos_manifestos(raw: Path, exigir: bool) -> str | None:
    pastas = pastas_declaradas(raw)
    faltam = [p.name for p in pastas if not (p / "manifesto.json").exists()]
    if faltam and exigir:
        raise FileNotFoundError(f"competências sem manifesto: {faltam}")
    if faltam:
        return None
    h = hashlib.sha256()
    for p in pastas:
        h.update((p / "manifesto.json").read_bytes())
    return h.hexdigest()


def acesso_mais_recente(raw: Path) -> date | None:
    datas = [
        json.loads((p / "manifesto.json").read_text(encoding="utf-8"))["acesso_em"]
        for p in pastas_declaradas(raw)
        if (p / "manifesto.json").exists()
    ]
    return date.fromisoformat(max(datas)) if datas else None


def construir(
    raw: Path, acesso_em: date | None = None, exigir_manifesto: bool = True, janela_meses: int = JANELA_MESES
) -> Envelope:
    # Data de coleta vem dos manifestos (quando cada competência foi de fato baixada), não do
    # relógio da execução: rodar o build de novo sem dado novo não pode mudar o JSON.
    acesso_em = acesso_em or acesso_mais_recente(raw)
    if acesso_em is None:
        raise ValueError("sem manifestos para derivar a data de coleta; informe --acesso-em")
    insumos = hashes_dos_manifestos(raw, exigir_manifesto)
    declaradas = [p.name for p in pastas_declaradas(raw)]
    if not declaradas:
        raise FileNotFoundError(f"nenhuma competência em {raw}")
    ultima = declaradas[-1]

    # A janela vem das declarações presentes, não das competências citadas por FOR/EXC, que
    # chegam a 4 anos atrás. Mês sem MOV publicado seria número fabricado.
    janela = meses_ate(ultima, janela_meses)
    ausentes = [c for c in janela if c not in declaradas]
    if ausentes:
        raise ValueError(f"declarações ausentes na janela: {ausentes}")

    bruto = carregar(raw)
    na_janela = bruto.filter(pl.col(COL_COMP).is_in(janela))
    mensal = agregar(na_janela, [COL_COMP])

    ultimas = janela[-MESES_SECAO:]
    secoes = agregar(bruto.filter(pl.col(COL_COMP).is_in(ultimas)), [COL_SECAO])

    dados: list[dict] = []
    for r in mensal.iter_rows(named=True):
        dados.append(
            {
                "recorte": "mensal",
                "competencia": r[COL_COMP],
                "secao": None,
                "secao_nome": None,
                "admissoes": r["admissoes"],
                "desligamentos": r["desligamentos"],
                "saldo": r["saldo"],
            }
        )
    for r in secoes.sort(["saldo", COL_SECAO], descending=[True, False]).iter_rows(named=True):
        if r[COL_SECAO] not in SECOES_CNAE:
            raise ValueError(f"seção CNAE desconhecida: {r[COL_SECAO]!r}")
        dados.append(
            {
                "recorte": "secao_12m",
                "competencia": None,
                "secao": r[COL_SECAO],
                "secao_nome": SECOES_CNAE[r[COL_SECAO]],
                "admissoes": r["admissoes"],
                "desligamentos": r["desligamentos"],
                "saldo": r["saldo"],
            }
        )

    return Envelope(
        painel="emprego",
        fonte=Fonte(
            nome="MTE — Novo CAGED (microdados)",
            url="ftp://ftp.mtps.gov.br/pdet/microdados/NOVO%20CAGED/",
            licenca="Dados abertos do governo federal",
            acesso_em=acesso_em,
        ),
        referencia=Referencia(
            inicio=mes_a_data(janela[0]),
            fim=fim_do_mes(janela[-1]),
            granularidade=Granularidade.MENSAL,
        ),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL,
            n_registros=len(dados),
            notas=[
                "Saldo = admissões − desligamentos, com movimentações fora do prazo somadas e exclusões subtraídas.",
                f"Competências recentes podem mudar: declarações até {ultima} já incorporadas.",
                "Faixa salarial de admissão ainda não publicada: falta tabela de salário mínimo com fonte.",
                f"Recorte por seção CNAE cobre os {MESES_SECAO} meses até {janela[-1]}.",
                *([f"SHA-256 dos manifestos de coleta: {insumos}"] if insumos else []),
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "caged")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "emprego.json")
    p.add_argument("--acesso-em", type=date.fromisoformat, help="padrão: data mais recente nos manifestos")
    args = p.parse_args()

    envelope = construir(args.raw, args.acesso_em)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(
        json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
