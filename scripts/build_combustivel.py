"""Transforma os instantâneos da ANP em data/public/combustivel.json.

Puro e offline. A semana da ANP vai de domingo a sábado. Semana ainda aberta na data de
coleta do instantâneo mais recente não entra: contaria menos postos do que a amostra real.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import median

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent
PRODUTOS = {"GASOLINA": "Gasolina comum", "ETANOL": "Etanol", "DIESEL S10": "Diesel S10"}
UNIDADE = "R$ / litro"
AMOSTRA_MINIMA = 15
SEMANAS_MIN_HISTORICO = 3


def centavos(texto: str) -> int:
    return int((Decimal(texto.replace(",", ".")) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def preco(c: float) -> float:
    return round(c / 100, 3)


def inicio_da_semana(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


def pastas(raw: Path) -> list[Path]:
    return sorted(p for p in raw.iterdir() if p.is_dir() and not p.name.startswith("."))


def carregar(raw: Path) -> dict[tuple[str, str, date], dict]:
    """Une os instantâneos; para a mesma (CNPJ, produto, coleta) vale o instantâneo mais novo."""
    obs: dict[tuple[str, str, date], dict] = {}
    for pasta in pastas(raw):
        for arquivo in sorted(pasta.glob("*.csv")):
            with arquivo.open(encoding="utf-8", newline="") as f:
                for linha in csv.DictReader(f, delimiter=";"):
                    produto = linha["Produto"].strip()
                    if produto not in PRODUTOS or not linha["Valor de Venda"].strip():
                        continue
                    if linha["Unidade de Medida"].strip() != UNIDADE:
                        raise ValueError(f"unidade inesperada: {linha['Unidade de Medida']!r}")
                    d, m, a = linha["Data da Coleta"].split("/")
                    coleta = date(int(a), int(m), int(d))
                    cnpj = "".join(ch for ch in linha["CNPJ da Revenda"] if ch.isdigit())
                    if not cnpj:
                        raise ValueError(f"revenda sem CNPJ: {linha['Revenda']!r}")
                    obs[(cnpj, produto, coleta)] = {
                        "revenda": " ".join(linha["Revenda"].split()),
                        "bairro": linha["Bairro"].strip(),
                        "bandeira": linha["Bandeira"].strip(),
                        "centavos": centavos(linha["Valor de Venda"]),
                    }
    return obs


def hashes(raw: Path) -> str:
    h = hashlib.sha256()
    for p in pastas(raw):
        h.update((p / "manifesto.json").read_bytes())
    return h.hexdigest()


def construir(raw: Path) -> Envelope:
    if not pastas(raw):
        raise FileNotFoundError(f"nenhum instantâneo em {raw}")
    manifestos = [json.loads((p / "manifesto.json").read_text(encoding="utf-8")) for p in pastas(raw)]
    acesso_em = date.fromisoformat(max(m["acesso_em"] for m in manifestos))
    ultima_coleta = max(date.fromisoformat(m["ultima_coleta"]) for m in manifestos)
    obs = carregar(raw)

    # Sem relógio no build: semana fecha quando o sábado é anterior à data de acesso do último instantâneo.
    fechadas = {inicio_da_semana(c) for (_, _, c) in obs if inicio_da_semana(c) + timedelta(days=6) < acesso_em}
    if not fechadas:
        raise ValueError("nenhuma semana fechada nos dados")

    por_semana: dict[tuple[date, str], dict[str, tuple[date, dict]]] = {}
    for (cnpj, produto, coleta), o in obs.items():
        ini = inicio_da_semana(coleta)
        if ini not in fechadas:
            continue
        atual = por_semana.setdefault((ini, produto), {}).get(cnpj)
        if atual is None or coleta > atual[0]:
            por_semana[(ini, produto)][cnpj] = (coleta, o)

    dados: list[dict] = []
    pequenas: dict[str, list[int]] = {}
    semanas = sorted(fechadas)
    for ini in semanas:
        for produto in PRODUTOS:
            postos = por_semana.get((ini, produto))
            if not postos:
                continue
            cs = [o["centavos"] for _, o in postos.values()]
            dados.append(
                {
                    "recorte": "semanal",
                    "semana_inicio": ini.isoformat(),
                    "semana_fim": (ini + timedelta(days=6)).isoformat(),
                    "produto": PRODUTOS[produto],
                    "n_postos": len(cs),
                    "mediana": preco(median(cs)),
                    "minimo": preco(min(cs)),
                    "maximo": preco(max(cs)),
                    "amostra_pequena": len(cs) < AMOSTRA_MINIMA,
                    "posto": None, "bairro": None, "bandeira": None, "preco": None,
                    "dif_mediana_pct": None, "semanas_observadas": None, "semanas_acima_mediana": None,
                }
            )
            if len(cs) < AMOSTRA_MINIMA:
                pequenas.setdefault(PRODUTOS[produto], []).append(len(cs))

    # Posição relativa dos postos na última semana fechada, com histórico de semanas acima da mediana.
    ultima = semanas[-1]
    for produto, rotulo in PRODUTOS.items():
        atual = por_semana.get((ultima, produto), {})
        if not atual:
            continue
        medianas = {ini: median([o["centavos"] for _, o in por_semana[(ini, produto)].values()]) for ini in semanas if (ini, produto) in por_semana}
        for cnpj, (_, o) in sorted(atual.items(), key=lambda kv: (kv[1][1]["centavos"], kv[1][1]["revenda"], kv[0])):
            vistas = acima = 0
            for ini in semanas:
                reg = por_semana.get((ini, produto), {}).get(cnpj)
                if reg:
                    vistas += 1
                    acima += reg[1]["centavos"] > medianas[ini]
            dados.append(
                {
                    "recorte": "posto",
                    "semana_inicio": ultima.isoformat(),
                    "semana_fim": (ultima + timedelta(days=6)).isoformat(),
                    "produto": rotulo,
                    "n_postos": len(atual),
                    "mediana": preco(medianas[ultima]),
                    "minimo": None, "maximo": None, "amostra_pequena": None,
                    "posto": o["revenda"], "bairro": o["bairro"], "bandeira": o["bandeira"],
                    "preco": preco(o["centavos"]),
                    "dif_mediana_pct": round((o["centavos"] - medianas[ultima]) / medianas[ultima] * 100, 1),
                    "semanas_observadas": vistas,
                    "semanas_acima_mediana": acima if vistas >= SEMANAS_MIN_HISTORICO else None,
                }
            )

    return Envelope(
        painel="combustivel",
        fonte=Fonte(
            nome="ANP — Levantamento de Preços de Combustíveis",
            url="https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas",
            licenca="Creative Commons Attribution (dados abertos ANP)",
            acesso_em=acesso_em,
        ),
        referencia=Referencia(inicio=semanas[0], fim=semanas[-1] + timedelta(days=6), granularidade=Granularidade.SEMANAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL,
            n_registros=len(dados),
            notas=[
                "Pesquisa amostral: a ANP visita só alguns postos por semana; os números descrevem os postos pesquisados, não todos da cidade.",
                "Semana da ANP vai de domingo a sábado; semana ainda aberta na coleta não é publicada.",
                "Histórico acumulado a cada coleta, a partir das últimas 4 semanas que a ANP disponibiliza.",
                f"Instantâneos da coleta: {len(pastas(raw))}; última coleta de preço em {ultima_coleta:%d/%m/%Y}.",
                *(
                    f"{nome}: amostra de {min(ns)} a {max(ns)} postos por semana, abaixo de {AMOSTRA_MINIMA}; comparar com cautela."
                    for nome, ns in pequenas.items()
                ),
                f"SHA-256 dos manifestos de coleta: {hashes(raw)}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "anp")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "combustivel.json")
    args = p.parse_args()
    envelope = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(
        json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
