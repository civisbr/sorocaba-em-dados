"""Medidores de velocidade verificados pelo Inmetro (PSIE, dados abertos), só os de Sorocaba."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "inmetro"
HOST = "servicos.rbmlq.gov.br"
URL = f"https://{HOST}/dados-abertos/SP/medidores.json"
LIMITE_BYTES = 60 * 1024 * 1024
CAMPOS = ("LocalVerificacao", "DataUltimaVerificacao", "DataValidade", "UltimoResultado", "TipoMedidor", "Faixas", "Historico")


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host != HOST:
        raise ValueError(f"requisição fora de https://{HOST}: {r.url.host}")


def filtrar(dados: object) -> list[dict]:
    if not isinstance(dados, list) or not dados or not all(isinstance(x, dict) for x in dados):
        raise ValueError("arquivo do Inmetro em formato inesperado")
    saida = []
    for x in dados:
        if str(x.get("SiglaUf", "")).upper() == "SP" and str(x.get("Municipio", "")).strip().upper() == "SOROCABA":
            saida.append({k: x.get(k) for k in CAMPOS})
    return sorted(saida, key=lambda m: (str(m["LocalVerificacao"]), str(m["DataValidade"])))


def coletar(acesso_em: date, destino: Path = DESTINO, transporte: httpx.BaseTransport | None = None) -> int:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    corpo = bytearray()
    with httpx.Client(timeout=180, follow_redirects=False, headers={"User-Agent": "SorocabaEmDados/1.0 (+https://github.com/civisbr/sorocaba-em-dados)", "Accept-Encoding": "identity"},
                      event_hooks={"request": [so_host_confiavel]}, transport=transporte) as c, c.stream("GET", URL) as r:
        r.raise_for_status()
        for pedaco in r.iter_bytes(256 * 1024):
            corpo += pedaco
            if len(corpo) > LIMITE_BYTES:
                raise ValueError("resposta acima do limite esperado")
    medidores = filtrar(json.loads(bytes(corpo)))
    if len(medidores) < 20:
        raise ValueError("poucos medidores de Sorocaba no arquivo do Inmetro; a fonte mudou?")
    destino.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(medidores, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    tmp = destino / "medidores_sorocaba.json.tmp"
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, destino / "medidores_sorocaba.json")
    man = {"fonte": URL, "acesso_em": acesso_em.isoformat(), "bytes_origem": len(corpo), "sha256_origem": hashlib.sha256(bytes(corpo)).hexdigest(),
           "sha256_filtrado": hashlib.sha256(texto.encode("utf-8")).hexdigest(), "n_medidores": len(medidores), "licenca": "Creative Commons CCZero (dados.gov.br)"}
    (destino / "manifesto.json").write_text(json.dumps(man, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(medidores)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    print("medidores de Sorocaba:", coletar(p.parse_args().acesso_em))


if __name__ == "__main__":
    main()
