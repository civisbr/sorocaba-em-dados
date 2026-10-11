"""Normais climatológicas de Sorocaba (1991-2020, reanálise ERA5) em data/public/clima.json. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent
DIA_CHUVOSO_MM = 1.0


def registro(recorte, mes=None, **kw) -> dict:
    base = {"recorte": recorte, "mes": mes, "tmax_media": None, "tmin_media": None, "chuva_mm": None, "dias_chuva": None, "tmax_recorde": None, "tmin_recorde": None, "chuva_max_dia_mm": None}
    base.update(kw)
    return base


def construir(raw: Path) -> Envelope:
    meta = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    with (raw / "era5_1991_2020.csv").open(encoding="utf-8", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    por_mes: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    chuva_mes_ano: dict[tuple[int, int], float] = defaultdict(float)
    dias_mes_ano: dict[tuple[int, int], int] = defaultdict(int)
    for r in linhas:
        ano, mes = int(r["data"][:4]), int(r["data"][5:7])
        tmax, tmin, chuva = float(r["tmax"]), float(r["tmin"]), float(r["chuva_mm"])
        por_mes[mes]["tmax"].append(tmax)
        por_mes[mes]["tmin"].append(tmin)
        por_mes[mes]["chuva_dia"].append(chuva)
        chuva_mes_ano[(ano, mes)] += chuva
        if chuva >= DIA_CHUVOSO_MM:
            dias_mes_ano[(ano, mes)] += 1
    anos = sorted({a for a, _ in chuva_mes_ano})
    dados = []
    for mes in range(1, 13):
        m = por_mes[mes]
        dados.append(registro(
            "mensal", mes,
            tmax_media=round(mean(m["tmax"]), 1), tmin_media=round(mean(m["tmin"]), 1),
            chuva_mm=round(mean(chuva_mes_ano[(a, mes)] for a in anos), 1),
            dias_chuva=round(mean(dias_mes_ano[(a, mes)] for a in anos), 1),
            tmax_recorde=round(max(m["tmax"]), 1), tmin_recorde=round(min(m["tmin"]), 1), chuva_max_dia_mm=round(max(m["chuva_dia"]), 1),
        ))
    mensais = [r for r in dados if r["recorte"] == "mensal"]
    todos_tmax = [float(r["tmax"]) for r in linhas]
    todos_tmin = [float(r["tmin"]) for r in linhas]
    dados.append(registro(
        "anual", None,
        tmax_media=round(mean(todos_tmax), 1), tmin_media=round(mean(todos_tmin), 1),
        chuva_mm=round(mean(sum(chuva_mes_ano[(a, m)] for m in range(1, 13)) for a in anos), 0),
        dias_chuva=round(mean(sum(dias_mes_ano[(a, m)] for m in range(1, 13)) for a in anos), 0),
        tmax_recorde=max(r["tmax_recorde"] for r in mensais), tmin_recorde=min(r["tmin_recorde"] for r in mensais),
        chuva_max_dia_mm=max(r["chuva_max_dia_mm"] for r in mensais),
    ))
    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    return Envelope(
        painel="clima",
        fonte=Fonte(nome="Open-Meteo (reanálise ERA5, Copernicus/ECMWF)", url="https://open-meteo.com/en/docs/historical-weather-api", licenca=meta["licenca"], acesso_em=date.fromisoformat(meta["coletado_em"])),
        referencia=Referencia(inicio=date.fromisoformat(meta["periodo"][0]), fim=date.fromisoformat(meta["periodo"][1]), granularidade=Granularidade.MENSAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.ESTIMATIVA,
            n_registros=len(dados),
            notas=[
                f"Normais de 30 anos (1991 a 2020), a janela padrão da Organização Meteorológica Mundial, calculadas aqui sobre a série diária da reanálise ERA5.",
                f"ERA5 é um modelo que combina observações do mundo todo, não uma estação meteorológica em Sorocaba. Os valores são da célula de grade em {meta['grade_y']:.2f}°, {meta['grade_x']:.2f}° (altitude do modelo {meta['altitude_grade_m']:.0f} m), de cerca de 25 km; podem diferir do que um termômetro na cidade mede, sobretudo na chuva.",
                "Temperaturas médias são médias das máximas e das mínimas diárias de cada mês. Chuva do mês é a média, entre os 30 anos, do total de cada mês. Dia de chuva = 1 mm ou mais.",
                "Recordes são os extremos diários do modelo nos 30 anos, não registros oficiais de estação.",
                f"SHA-256 do manifesto de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "clima")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "clima.json")
    args = p.parse_args()
    e = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
