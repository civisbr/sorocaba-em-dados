"""Baixa o contorno oficial do município (malha IBGE) sem transformar."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx

URL = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/municipios/3552205"
    "?formato=application/vnd.geo+json&qualidade=maxima"
)
LIMITE_BYTES = 5 * 1024 * 1024
DESTINO = Path(__file__).resolve().parent.parent / "data" / "raw" / "ibge"


def baixar(tentativas: int = 4) -> bytes:
    for tentativa in range(tentativas):
        try:
            r = httpx.get(URL, timeout=60, follow_redirects=True)
            r.raise_for_status()
            if len(r.content) > LIMITE_BYTES:
                raise ValueError("malha acima do limite esperado")
            return r.content
        except httpx.HTTPError:
            if tentativa == tentativas - 1:
                raise
            time.sleep(2**tentativa * 3)
    raise RuntimeError("inalcançável")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, help="AAAA-MM-DD")
    args = p.parse_args()
    corpo = baixar()
    json.loads(corpo)
    DESTINO.mkdir(parents=True, exist_ok=True)
    (DESTINO / "malha_3552205.geojson").write_bytes(corpo)
    manifesto = {"url": URL, "acesso_em": args.acesso_em, "sha256": hashlib.sha256(corpo).hexdigest(), "bytes": len(corpo)}
    (DESTINO / "manifesto.json").write_text(json.dumps(manifesto, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
