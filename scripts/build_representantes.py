"""Transforma os recortes do TSE, da Câmara e da Alesp em data/public/representantes.json. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent
TOP_DEPUTADOS = 5
# Prefeito, vice e vereadores tomam posse em 1º de janeiro (CF, art. 29). Para deputados guardamos só
# o período em anos: a data de posse dos estaduais é regimental e não foi verificada em fonte.
MANDATOS = {2024: "2025–2028", 2022: "2023–2027", 2026: "2027–2031"}
GRUPOS = {
    "PREFEITO": "prefeito", "VICE-PREFEITO": "vice_prefeito", "VEREADOR": "vereador",
    "Deputado Federal": "deputado_federal", "Deputado Estadual": "deputado_estadual",
}


# Sigla usada pelo TSE -> sigla usada na tabela dos especialistas (Bolognesi et al., 2025).
# Siglas iguais passam direto; PP aparece como PROGRE (Progressistas) na tabela.
SIGLA_ESPECIALISTAS = {
    "REPUBLICANOS": "REP", "UNIÃO": "UNIAO", "SOLIDARIEDADE": "SDD", "CIDADANIA": "CDD",
    "PC do B": "PCdoB", "PATRIOTA": "PATRI", "PP": "PROGRE",
}
# Três blocos a partir das sete categorias da fonte. É uma escolha deste projeto, não da fonte:
# centro reúne centro-esquerda, centro e centro-direita; a tabela original separa as sete.
BLOCOS = {
    "extrema esquerda": "esquerda", "esquerda": "esquerda",
    "centro-esquerda": "centro", "centro": "centro", "centro-direita": "centro",
    "direita": "direita", "extrema direita": "direita",
}


def classificar(partido: str, tabela: dict[str, str]) -> tuple[str | None, str | None]:
    categoria = tabela.get(SIGLA_ESPECIALISTAS.get(partido, partido))
    return categoria, BLOCOS.get(categoria) if categoria else None


def tokens(nome: str) -> frozenset[str]:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return frozenset(re.findall(r"[A-Z0-9]+", sem_acento.upper()))


def em_exercicio(nome_urna: str, lista: list[str]) -> bool | None:
    """True só se exatamente um nome da lista oficial casar; sem casamento fica None (não confirmado).

    O nome de urna costuma trazer título ("AGENTE FEDERAL DANILO BALAS") e o parlamentar oficial
    não, então vale igualdade de palavras ou o nome menor (2+ palavras) contido no maior.
    """
    t = tokens(nome_urna)
    achados = 0
    for n in lista:
        u = tokens(n)
        menor, maior = sorted((t, u), key=len)
        if t == u or (len(menor) >= 2 and menor <= maior):
            achados += 1
    return True if achados == 1 else None


def ler_csv(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def registro(grupo, eleicao, mandato, nome, partido, situacao, votos=None, pct=None, posicao=None, exercicio=None, tabela=None) -> dict:
    categoria, bloco = classificar(partido, tabela or {})
    return {
        "ideologia": categoria, "bloco": bloco,
        "grupo": grupo, "eleicao": eleicao, "mandato": mandato,
        "nome": nome, "partido": partido, "situacao_tse": situacao, "votos_na_cidade": votos,
        "pct_votos_na_cidade": pct, "posicao_na_cidade": posicao, "em_exercicio": exercicio,
    }


def construir(raw: Path, raw_ideologia: Path | None = None) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    ideo = raw_ideologia or raw.parent / "ideologia"
    tabela = {r["partido"]: r["categoria"] for r in ler_csv(ideo / "classificacao_experts.csv")}
    man_ideo = json.loads((ideo / "manifesto.json").read_text(encoding="utf-8"))
    camara = [d["nome"] for d in json.loads((raw / "camara_deputados_sp.json").read_text(encoding="utf-8"))]
    alesp = [d["nome"] for d in json.loads((raw / "alesp_deputados.json").read_text(encoding="utf-8")) if d["situacao"] == "EXE"]
    listas = {"Deputado Federal": camara, "Deputado Estadual": alesp}

    dados: list[dict] = []
    for r in ler_csv(raw / "eleitos_municipais_2024.csv"):
        dados.append(registro(GRUPOS[r["cargo"]], 2024, MANDATOS[2024], r["nome_urna"], r["partido"], r["situacao"], tabela=tabela))

    for ano in (2022, 2026):
        totais = {r["cargo"]: int(r["votos_nominais_validos"]) for r in ler_csv(raw / f"totais_votos_{ano}.csv")}
        por_cargo: dict[str, list[dict]] = {}
        for r in ler_csv(raw / f"votos_deputados_{ano}.csv"):
            por_cargo.setdefault(r["cargo"], []).append(r)
        for cargo, linhas in por_cargo.items():
            linhas.sort(key=lambda r: (-int(r["votos"]), r["nome_urna"]))
            for pos, r in enumerate(linhas[:TOP_DEPUTADOS], 1):
                v = int(r["votos"])
                # Só a legislatura em curso (eleitos em 2022) tem lista oficial de exercício para conferir.
                ex = em_exercicio(r["nome_urna"], listas[cargo]) if ano == 2022 else None
                dados.append(registro(GRUPOS[cargo], ano, MANDATOS[ano], r["nome_urna"], r["partido"], r["situacao"], v, round(v / totais[cargo] * 100, 1), pos, ex, tabela))

    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    return Envelope(
        painel="representantes",
        fonte=Fonte(
            nome="TSE (resultados), Câmara dos Deputados e Alesp (dados abertos)",
            url="https://dadosabertos.tse.jus.br/",
            licenca="Dados abertos",
            acesso_em=date.fromisoformat(man["verificado_em"]),
        ),
        referencia=Referencia(inicio=date(2022, 1, 1), fim=date(2026, 12, 31), granularidade=Granularidade.ANUAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL,
            n_registros=len(dados),
            notas=[
                "O TSE registra quem foi eleito, não quem exerce o mandato hoje: vereador licenciado ou suplente que assumiu não aparece.",
                "Deputados são eleitos pelo estado inteiro. Mostramos os eleitos mais votados em Sorocaba, com a eleição e o critério explícitos; isso não significa que sejam 'da cidade'.",
                f"Percentual = votos nominais válidos do candidato em Sorocaba ÷ total de votos nominais válidos para o cargo na cidade. Lista dos {TOP_DEPUTADOS} mais votados entre os eleitos.",
                "Em exercício: conferido por nome nas listas oficiais da Câmara e da Alesp na data da coleta. Sem correspondência única fica sem confirmação, o que pode vir de licença, renúncia ou de nome de urna diferente do nome parlamentar.",
                "Eleitos em 2026 assumem em 2027 (resultado do 1º turno; o 2º turno não envolve deputados).",
                f"Posição ideológica do partido: classificação de especialistas em ciência política (survey de 2022; Bolognesi, Ribeiro, Codato e Silva, Opinião Pública, 2025, doi {man_ideo['doi']}). É a posição do partido, não do político, e a fonte avalia partidos, não pessoas.",
                "Blocos: esquerda = extrema esquerda e esquerda; centro = centro-esquerda, centro e centro-direita; direita = direita e extrema direita. É um agrupamento deste projeto sobre as sete categorias da fonte, mostradas no detalhe.",
                "Partido sem classificação na fonte (por exemplo, criado depois de 2022) fica fora das porcentagens e é contado à parte.",
                f"SHA-256 do manifesto de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "representantes")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "representantes.json")
    args = p.parse_args()
    e = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
