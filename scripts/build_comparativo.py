"""Posição de Sorocaba entre os municípios, ano a ano, em data/public/comparativo.json. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent
SOROCABA = "3552205"
UF_SP = "35"
VIZINHOS = 3

INDICADORES = {
    "populacao": ("População", "pessoas"),
    "pib": ("PIB a preços correntes", "R$ mil"),
    "pib_per_capita": ("PIB per capita (calculado)", "R$ por habitante"),
    "ideb_anos_iniciais": ("IDEB, anos iniciais (rede pública)", "nota de 0 a 10"),
    "ideb_anos_finais": ("IDEB, anos finais (rede pública)", "nota de 0 a 10"),
}


def ler(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def por_ano(linhas: list[dict[str, str]]) -> dict[int, dict[str, float]]:
    saida: dict[int, dict[str, float]] = {}
    for r in linhas:
        saida.setdefault(int(r["ano"]), {})[r["codigo"]] = float(r["valor"])
    return saida


def posicao(valores: dict[str, float], cod: str) -> tuple[int, int, int] | None:
    """(posição, total, empatados): 1 = maior valor; empate divide a mesma posição (1, 2, 2, 4)."""
    if cod not in valores:
        return None
    v = valores[cod]
    acima = sum(1 for x in valores.values() if x > v)
    iguais = sum(1 for x in valores.values() if x == v) - 1
    return acima + 1, len(valores), iguais


def registro(recorte, indicador, ano, **kw) -> dict:
    base = {
        "recorte": recorte, "indicador": indicador, "ano": ano, "valor": None, "origem": None,
        "pos_sp": None, "n_sp": None, "empatados_sp": None, "pos_br": None, "n_br": None, "empatados_br": None,
        "codigo": None, "municipio": None,
    }
    base.update(kw)
    return base


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    nomes = {r["codigo"]: r["nome"] for r in ler(raw / "municipios_sp.csv")}
    pop_linhas = ler(raw / "populacao.csv")
    origem_pop = {(int(r["ano"]), r["codigo"]): r["origem"] for r in pop_linhas}
    pop = por_ano(pop_linhas)
    pib = por_ano(ler(raw / "pib.csv"))
    series = {
        "populacao": pop,
        "pib": pib,
        # Mesmo ano nos dois lados; PIB em R$ mil, por isso o fator 1000. Anos sem população ficam de fora.
        "pib_per_capita": {
            a: {c: v * 1000 / pop[a][c] for c, v in pib[a].items() if c in pop.get(a, {}) and pop[a][c] > 0}
            for a in pib if a in pop
        },
        "ideb_anos_iniciais": por_ano(ler(raw / "ideb_anos_iniciais.csv")),
        "ideb_anos_finais": por_ano(ler(raw / "ideb_anos_finais.csv")),
    }

    dados: list[dict] = []
    for ind, por in series.items():
        for ano in sorted(por):
            valores_br = por[ano]
            valores_sp = {c: v for c, v in valores_br.items() if c.startswith(UF_SP)}
            br, sp = posicao(valores_br, SOROCABA), posicao(valores_sp, SOROCABA)
            if not br or not sp:
                continue
            dados.append(registro(
                "posicao", ind, ano, valor=round(valores_br[SOROCABA], 3),
                origem=origem_pop.get((ano, SOROCABA)) if ind == "populacao" else None,
                pos_sp=sp[0], n_sp=sp[1], empatados_sp=sp[2], pos_br=br[0], n_br=br[1], empatados_br=br[2],
            ))
        # Vizinhos no ranking paulista do ano mais recente com Sorocaba presente.
        anos_validos = [a for a in sorted(por) if SOROCABA in por[a]]
        a = anos_validos[-1]
        sp_vals = sorted(((c, v) for c, v in por[a].items() if c.startswith(UF_SP)), key=lambda cv: (-cv[1], cv[0]))
        i = next(k for k, (c, _) in enumerate(sp_vals) if c == SOROCABA)
        for k in range(max(0, i - VIZINHOS), min(len(sp_vals), i + VIZINHOS + 1)):
            c, v = sp_vals[k]
            dados.append(registro("vizinho", ind, a, valor=round(v, 3), pos_sp=posicao({x: y for x, y in sp_vals}, c)[0], codigo=c, municipio=nomes[c]))

    anos_todos = sorted({r["ano"] for r in dados})
    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    return Envelope(
        painel="comparativo",
        fonte=Fonte(
            nome="IBGE (população e PIB dos municípios) e INEP (IDEB municipal)",
            url="https://sidra.ibge.gov.br/",
            licenca="Dados abertos do IBGE e do INEP",
            acesso_em=date.fromisoformat(man["verificado_em"]),
        ),
        referencia=Referencia(inicio=date(anos_todos[0], 1, 1), fim=date(anos_todos[-1], 12, 31), granularidade=Granularidade.ANUAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL,
            n_registros=len(dados),
            notas=[
                "Posição 1 = maior valor do indicador. Em empate, os municípios dividem a mesma posição (1, 2, 2, 4).",
                "Cada ano é comparado só com os municípios que têm dado naquele ano; o total de municípios muda ao longo do tempo.",
                "População: Censos (1970 a 2022), contagem de 2007 e estimativas anuais do IBGE. A troca de método entre estimativa e Censo pode mudar a posição de um ano para o outro sem mudança real.",
                "Tamanho não é qualidade: população e PIB medem volume. PIB per capita pode ser distorcido por um grande empreendimento em município pequeno.",
                "PIB per capita é calculado aqui (PIB do ano ÷ população do mesmo ano, ambos do IBGE), porque o IBGE não o publica na tabela usada. Anos sem população do mesmo ano ficam de fora.",
                "PIB a preços correntes: valores nominais. A posição não depende da inflação, mas o valor em reais sim.",
                "IDEB reflete também o perfil socioeconômico dos alunos; comparar municípios é uma leitura entre outras, não um veredito sobre a rede de ensino.",
                f"SHA-256 do manifesto de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "comparativo")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "comparativo.json")
    args = p.parse_args()
    e = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
