"""Posição dos medidores do Inmetro em Sorocaba a partir do endereço do cadastro (OpenStreetMap/Nominatim, dados ODbL).

Primeiro tenta o imóvel exato (número de porta achado pelo Nominatim); o que não achar recebe posição aproximada de scripts/geo_aprox.py
(cruzamento, km da rodovia, número vizinho ou meio da via), marcada na coluna precisao. Roda à mão, não no cron. Grava data/raw/inmetro/coordenadas.csv.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from datetime import date
from pathlib import Path

import httpx

from scripts.geo import carregar_contorno, dentro
from scripts.geocode_radares import CACHE_OSM, NOMINATIM, contexto_http, interpretar, palavras

RAIZ = Path(__file__).resolve().parent.parent
RAW = RAIZ / "data" / "raw" / "inmetro"
SAIDA = RAW / "coordenadas.csv"
CAMPOS = ["chave", "lat", "lon", "precisao", "osm_ref", "geocodificado_em", "detalhe"]


def chave(m: dict) -> str:
    """Identifica o medidor pelo local e pelos números do Inmetro; muda se o cadastro trocar o equipamento."""
    inmetros = "|".join(sorted({str(f.get("NumeroInmetro")) for f in (m.get("Faixas") or [])}))
    return hashlib.sha1(f"{m['LocalVerificacao']}#{inmetros}".encode("utf-8")).hexdigest()[:16]


def buscar(c: httpx.Client, rua: str, numero: str) -> tuple[float, float, str] | None:
    """Busca livre ("1930 Avenida Conde Zeppelin, Sorocaba"): só vale resultado com o mesmo número de porta e o mesmo nome de via."""
    r = c.get(NOMINATIM, params={"q": f"{numero} {rua.title()}, Sorocaba, SP", "format": "jsonv2", "addressdetails": 1, "limit": 3, "countrycodes": "br"})
    r.raise_for_status()
    pedida = palavras(rua)
    for a in r.json():
        end = a.get("address", {})
        if a.get("category") != "highway" and str(end.get("house_number", "")).strip() == numero and pedida and pedida == palavras(end.get("road", "")):
            return float(a["lat"]), float(a["lon"]), f"{a.get('osm_type')}/{a.get('osm_id')}"
    return None


def main() -> None:
    medidores = json.loads((RAW / "medidores_sorocaba.json").read_text(encoding="utf-8"))
    contorno = carregar_contorno()
    feitos = {r["chave"]: r for r in csv.DictReader(SAIDA.open(encoding="utf-8"), delimiter=";")} if SAIDA.exists() else {}
    hoje = date.today().isoformat()
    from scripts import geo_aprox

    osm = geo_aprox.montar(geo_aprox.baixar_osm(CACHE_OSM))
    with contexto_http() as c:
        for m in medidores:
            k = chave(m)
            if k in feitos and feitos[k]["precisao"] == "porta":
                continue
            tipo, vias, numero = interpretar(" ".join(str(m["LocalVerificacao"]).replace("N°", "N º").split()))
            achado = None
            if k not in feitos and tipo == "endereco" and numero:
                try:
                    achado = buscar(c, vias[0], numero)
                except httpx.HTTPError as e:
                    print(f"{m['LocalVerificacao']}: falha ({type(e).__name__}); fica para a próxima rodada")
                    continue
                time.sleep(1.1)
            if achado and not dentro(contorno, achado[0], achado[1]):
                achado = None
            if achado:
                feitos[k] = {"chave": k, "lat": f"{achado[0]:.5f}", "lon": f"{achado[1]:.5f}", "precisao": "porta", "osm_ref": achado[2], "geocodificado_em": hoje, "detalhe": ""}
                continue
            aprox = geo_aprox.aproximar(str(m["LocalVerificacao"]), osm, lambda la, lo: dentro(contorno, la, lo))
            feitos[k] = {"chave": k, "lat": f"{aprox.lat:.5f}" if aprox else "", "lon": f"{aprox.lon:.5f}" if aprox else "", "precisao": aprox.nivel if aprox else "", "osm_ref": "", "geocodificado_em": hoje, "detalhe": aprox.detalhe if aprox else ""}
    RAW.mkdir(parents=True, exist_ok=True)
    with SAIDA.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(({c: r.get(c, "") for c in CAMPOS} for r in feitos.values()), key=lambda r: r["chave"]))
    exatos = sum(1 for r in feitos.values() if r["precisao"] == "porta")
    print(f"{sum(1 for r in feitos.values() if r['precisao'])} com posição ({exatos} exatas) de {len(medidores)} medidores")


if __name__ == "__main__":
    main()
