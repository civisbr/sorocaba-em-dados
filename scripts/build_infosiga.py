"""Sinistros de trânsito em data/public/infosiga.json, a partir das contagens agregadas. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent
CELULA_MINIMA = 5
VIA_MINIMA = 10
TOP_VIAS = 15
COBERTURA_MINIMA = 80.0  # % de sinistros com coordenada para o ano entrar no mapa
CELULA_GRAU = 0.005


def ler(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def reg(recorte, ano, n, mes=None, categoria=None, n2=None, pct=None, lat=None, lon=None, grupo=None) -> dict:
    return {"recorte": recorte, "ano": ano, "mes": mes, "grupo": grupo, "categoria": categoria, "n": n, "n2": n2, "pct": pct, "lat": lat, "lon": lon}


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    anos = sorted(int(a) for a in man["anos"])
    completos = [a for a in anos if len(man["anos"][str(a)]["meses"]) == 12]
    ano_ref = completos[-1]
    dados: list[dict] = []
    total_ano: dict[int, int] = {}
    for a in anos:
        meses = defaultdict(lambda: [0, 0, 0, 0])
        for r in ler(raw / str(a) / "mensal.csv"):
            m = meses[int(r["mes"])]
            if r["tipo_registro"] == "NOTIFICACAO":
                m[2] += int(r["sinistros"])
            else:
                m[0] += int(r["sinistros"])
                m[1] += int(r["vitimas_fatais"])
                m[3] += int(r["vitimas_graves"])
        total_ano[a] = sum(v[0] for v in meses.values())
        for mes in sorted(meses):
            s, f, nt, g = meses[mes]
            dados.append(reg("mensal", a, s, mes=mes, n2=f, categoria=f"{nt}|{g}"))  # categoria = notificações|vítimas graves

    horas: dict[str, int] = defaultdict(int)
    dias: dict[str, int] = defaultdict(int)
    for r in ler(raw / str(ano_ref) / "hora.csv"):
        horas[r["hora"]] += int(r["n"])
        dias[r["dia_semana"]] += int(r["n"])
    for h in sorted(horas):
        dados.append(reg("hora", ano_ref, horas[h], categoria=h))
    for d, n in dias.items():
        dados.append(reg("dia_semana", ano_ref, n, categoria=d))
    for r in ler(raw / str(ano_ref) / "tipo.csv"):
        dados.append(reg("tipo", ano_ref, int(r["n"]), categoria=r["tipo"]))
    vias = sorted(((r["logradouro"], int(r["n"])) for r in ler(raw / str(ano_ref) / "via.csv") if int(r["n"]) >= VIA_MINIMA), key=lambda t: (-t[1], t[0]))[:TOP_VIAS]
    for v, n in vias:
        dados.append(reg("via", ano_ref, n, categoria=v))

    anos_mapa, celulas = [], defaultdict(int)
    for a in completos:
        grade = ler(raw / str(a) / "grade.csv")
        cob = sum(int(r["n"]) for r in grade) / total_ano[a] * 100 if total_ano[a] else 0
        if cob >= COBERTURA_MINIMA:
            anos_mapa.append(a)
            for r in grade:
                celulas[(float(r["lat"]), float(r["lon"]))] += int(r["n"])
    if anos_mapa:
        total_mapa = sum(total_ano[a] for a in anos_mapa)
        for (la, lo), n in sorted(celulas.items()):
            if n >= CELULA_MINIMA:
                dados.append(reg("grade", anos_mapa[-1], n, grupo="sinistros", categoria=str(CELULA_GRAU), lat=la, lon=lo))
        dados.append(reg("grade_cobertura", anos_mapa[-1], sum(celulas.values()), mes=anos_mapa[0], grupo="sinistros", categoria=str(CELULA_GRAU), pct=round(sum(celulas.values()) / total_mapa * 100, 1)))

    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    ultimo = max(anos)
    mes_fim = max(man["anos"][str(ultimo)]["meses"])
    return Envelope(
        painel="infosiga",
        fonte=Fonte(nome="Infosiga SP (Detran-SP) — eventos de sinistro", url="https://dadosabertos.sp.gov.br/dataset/eventos-de-sinistro", licenca="Creative Commons Attribution 4.0", acesso_em=date.fromisoformat(man["verificado_em"])),
        referencia=Referencia(inicio=date(anos[0], 1, 1), fim=date(ultimo, mes_fim, 28), granularidade=Granularidade.MENSAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL, n_registros=len(dados),
            notas=[
                "Sinistro é um registro de trânsito com vítima ou dano comunicado às autoridades; “fatal” significa que houve morte, e a contagem de mortes (vítimas fatais) é separada.",
                "Notificações são registros com informação incompleta e ficam fora das contagens principais; o número delas aparece à parte.",
                "Linhas já publicadas podem ser revisadas pelo Detran-SP; o ano corrente e o anterior são refeitos a cada coleta. O mês mais recente costuma subir.",
                f"Hora, dia da semana, tipo e vias usam {ano_ref}, o último ano completo. Vias aparecem só com {VIA_MINIMA} ou mais sinistros no ano; contagem por via não mede perigo, depende do tamanho e do movimento da via.",
                (f"Mapa: sinistros de {anos_mapa[0]} a {anos_mapa[-1]}, em células de cerca de 555 m com {CELULA_MINIMA} ou mais registros; entram só os anos em que ao menos {COBERTURA_MINIMA:.0f}% dos sinistros têm coordenada. Anos com muita coordenada ausente ficam de fora. Pontos individuais e datas de sinistros fatais não são publicados." if anos_mapa else "Mapa indisponível: nenhum ano completo com coordenadas suficientes."),
                f"SHA-256 do manifesto de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "infosiga")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "infosiga.json")
    args = p.parse_args()
    e = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
