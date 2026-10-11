"""Junta as previsões coletadas em data/public/previsao.json (não versionado). Puro e offline."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent
CODIGOS_WMO = {
    0: "Céu limpo", 1: "Predominantemente limpo", 2: "Parcialmente nublado", 3: "Nublado", 45: "Neblina", 48: "Neblina com geada",
    51: "Garoa fraca", 53: "Garoa moderada", 55: "Garoa forte", 61: "Chuva fraca", 63: "Chuva moderada", 65: "Chuva forte",
    80: "Pancadas de chuva fracas", 81: "Pancadas de chuva moderadas", 82: "Pancadas de chuva fortes",
    95: "Trovoadas", 96: "Trovoadas com granizo fraco", 99: "Trovoadas com granizo forte",
}


def iso(dia_br: str) -> str:
    d, m, a = dia_br.split("/")
    return f"{a}-{m}-{d}"


def construir(raw: Path) -> Envelope:
    om = json.loads((raw / "open_meteo.json").read_text(encoding="utf-8")) if (raw / "open_meteo.json").exists() else None
    inmet = json.loads((raw / "inmet.json").read_text(encoding="utf-8")) if (raw / "inmet.json").exists() else None
    if not om and not inmet:
        raise FileNotFoundError("nenhuma previsão coletada")
    dados: list[dict] = []
    coleta = max(x["coletado_em"] for x in (om, inmet) if x)
    if om:
        d = om["dados"]["daily"]
        for i, dia in enumerate(d["time"]):
            cod = d["weather_code"][i]
            dados.append({
                "fonte": "open-meteo", "dia": dia, "resumo": CODIGOS_WMO.get(cod, "Condição não classificada"),
                "tmax": d["temperature_2m_max"][i], "tmin": d["temperature_2m_min"][i], "chuva_mm": d["precipitation_sum"][i],
                "prob_chuva": d["precipitation_probability_max"][i], "vento_kmh": d["wind_speed_10m_max"][i],
                "umidade_max": None, "umidade_min": None, "vento": None, "nascer": None, "ocaso": None,
                "resumo_manha": None, "resumo_noite": None,
            })
    if inmet:
        for dia_br, periodos in sorted(inmet["dados"].items(), key=lambda kv: iso(kv[0])):
            p = periodos.get("tarde") or next(iter(periodos.values()))
            dados.append({
                "fonte": "inmet", "dia": iso(dia_br), "resumo": p["resumo"], "tmax": p["temp_max"], "tmin": p["temp_min"],
                "chuva_mm": None, "prob_chuva": None, "vento_kmh": None, "umidade_max": p["umidade_max"], "umidade_min": p["umidade_min"],
                "vento": f"{p['dir_vento']}, {str(p['int_vento']).lower()}" if p.get("dir_vento") else None,
                "nascer": p.get("nascer"), "ocaso": p.get("ocaso"),
                "resumo_manha": (periodos.get("manha") or {}).get("resumo"), "resumo_noite": (periodos.get("noite") or {}).get("resumo"),
            })
    dias = sorted(r["dia"] for r in dados)
    return Envelope(
        painel="previsao",
        fonte=Fonte(nome="INMET (previsão oficial, 5 dias) e Open-Meteo (modelo numérico, 7 dias)", url="https://previsaodotempo.inmet.gov.br/", licenca="INMET: dados abertos; Open-Meteo: CC BY 4.0", acesso_em=date.fromisoformat(coleta)),
        referencia=Referencia(inicio=date.fromisoformat(dias[0]), fim=date.fromisoformat(dias[-1]), granularidade=Granularidade.SEMANAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.ESTIMATIVA, n_registros=len(dados),
            notas=[
                "Previsão não é dado observado: muda a cada atualização e perde precisão com os dias. Em caso de alerta, vale a Defesa Civil.",
                "INMET é a previsão oficial para o município (até 5 dias). Open-Meteo vem de modelo numérico para o ponto central da cidade (até 7 dias); as duas fontes podem divergir e não são misturadas.",
                "Chuva do Open-Meteo é a soma prevista do dia em milímetros; probabilidade é a máxima do dia.",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "previsao")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "previsao.json")
    args = p.parse_args()
    e = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
