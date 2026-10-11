"""Previsão do tempo para Sorocaba: INMET (oficial, 5 dias) e Open-Meteo (modelo, 7 dias).

A previsão é efêmera: fica em data/raw/previsao (fora do git) e é regerada a cada deploy.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "previsao"
INMET = "https://apiprevmet3.inmet.gov.br/previsao/3552205"
OPEN_METEO = (
    "https://api.open-meteo.com/v1/forecast?latitude=-23.5015&longitude=-47.4526"
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max"
    "&timezone=America%2FSao_Paulo&forecast_days=7"
)
HOSTS = {"apiprevmet3.inmet.gov.br", "api.open-meteo.com"}
LIMITE_BYTES = 2 * 1024 * 1024
CAMPOS_INMET = ("resumo", "temp_max", "temp_min", "umidade_max", "umidade_min", "dir_vento", "int_vento", "nascer", "ocaso", "dia_semana")


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host not in HOSTS:
        raise ValueError(f"requisição fora dos hosts esperados: {r.url}")


def baixar(c: httpx.Client, url: str) -> dict:
    for n in range(3):
        try:
            with c.stream("GET", url) as r:
                r.raise_for_status()
                corpo = bytearray()
                for pedaco in r.iter_bytes(64 * 1024):
                    corpo += pedaco
                    if len(corpo) > 8 * LIMITE_BYTES:  # a resposta do INMET traz ícones em base64 (~270 KB)
                        raise ValueError(f"{url} acima do limite esperado")
                return json.loads(bytes(corpo))
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if n == 2 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500):
                raise
            time.sleep(2**n * 2)
    raise RuntimeError("inalcançável")


def coletar(acesso_em: date, destino: Path = DESTINO) -> list[str]:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    destino.mkdir(parents=True, exist_ok=True)
    feitos = []
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 SorocabaEmDados/1.0"}, event_hooks={"request": [so_host_confiavel]}) as c:
        for nome, url in (("open_meteo", OPEN_METEO), ("inmet", INMET)):
            try:
                dados = baixar(c, url)
            except (httpx.HTTPError, ValueError) as e:  # uma fonte fora do ar não derruba a outra
                print(f"{nome}: indisponível ({type(e).__name__})")
                (destino / f"{nome}.json").unlink(missing_ok=True)
                continue
            if nome == "inmet":
                dias = dados["3552205"]
                # Nos dias mais distantes o INMET manda um único bloco; nos próximos, manhã/tarde/noite.
                dados = {
                    dia: {per: {k: v.get(k) for k in CAMPOS_INMET} for per, v in ({"dia": periodos} if "resumo" in periodos else periodos).items()}
                    for dia, periodos in dias.items()
                }
            (destino / f"{nome}.json").write_text(json.dumps({"coletado_em": acesso_em.isoformat(), "dados": dados}, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            feitos.append(nome)
    return feitos


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    args = p.parse_args()
    print("coletados:", coletar(args.acesso_em) or "nenhum")


if __name__ == "__main__":
    main()
