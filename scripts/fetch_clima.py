"""Séries diárias de clima de Sorocaba (reanálise ERA5 via Open-Meteo) para as normais 1991-2020."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
from datetime import date
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "clima"
HOST = "archive-api.open-meteo.com"
# Centro de Sorocaba; a API usa a célula de grade mais próxima (~25 km) e informa a posição e a altitude usadas.
LAT, LON = -23.5015, -47.4526
INICIO, FIM = "1991-01-01", "2020-12-31"
LIMITE_BYTES = 5 * 1024 * 1024
URL = (
    f"https://{HOST}/v1/archive?latitude={LAT}&longitude={LON}&start_date={INICIO}&end_date={FIM}"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=America%2FSao_Paulo"
)


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host != HOST:
        raise ValueError(f"requisição fora de https://{HOST}: {r.url}")


def baixar() -> dict:
    for n in range(4):
        try:
            with httpx.Client(timeout=120, follow_redirects=True, event_hooks={"request": [so_host_confiavel]}) as c, c.stream("GET", URL) as r:
                r.raise_for_status()
                corpo = bytearray()
                for pedaco in r.iter_bytes(64 * 1024):
                    corpo += pedaco
                    if len(corpo) > LIMITE_BYTES:
                        raise ValueError("resposta acima do limite esperado")
                return json.loads(bytes(corpo))
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if n == 3 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500):
                raise
            time.sleep(2**n * 3)
    raise RuntimeError("inalcançável")


def coletar(acesso_em: date, destino: Path = DESTINO, forcar: bool = False) -> bool:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    arq = destino / "era5_1991_2020.csv"
    if arq.exists() and not forcar:
        return False  # período encerrado em 2020: não muda
    d = baixar()
    dias = d["daily"]
    n = len(dias["time"])
    if n != 10958 or any(len(dias[k]) != n for k in ("temperature_2m_max", "temperature_2m_min", "precipitation_sum")):
        raise ValueError(f"série inesperada: {n} dias")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(["data", "tmax", "tmin", "chuva_mm"])
    for i in range(n):
        w.writerow([dias["time"][i], dias["temperature_2m_max"][i], dias["temperature_2m_min"][i], dias["precipitation_sum"][i]])
    texto = buf.getvalue()
    destino.mkdir(parents=True, exist_ok=True)
    arq.write_text(texto, encoding="utf-8")
    meta = {
        "fonte": "Open-Meteo Historical Weather API (reanálise ERA5, Copernicus/ECMWF)", "url": URL,
        "licenca": "CC BY 4.0 (Open-Meteo; dados Copernicus)", "grade_y": d["latitude"], "grade_x": d["longitude"], "altitude_grade_m": d["elevation"],
        "periodo": [INICIO, FIM], "coletado_em": acesso_em.isoformat(), "sha256_csv": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
    }
    (destino / "manifesto.json").write_text(json.dumps(meta, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    p.add_argument("--forcar", action="store_true")
    args = p.parse_args()
    print("atualizado" if coletar(args.acesso_em, forcar=args.forcar) else "sem mudança")


if __name__ == "__main__":
    main()
