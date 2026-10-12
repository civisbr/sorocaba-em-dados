"""Posição dos medidores do Inmetro em Sorocaba a partir do endereço do cadastro (OpenStreetMap/Nominatim, dados ODbL).

Só endereços com número de porta e achados pelo Nominatim no próprio imóvel entram; trechos de rodovia (km), cruzamentos e vias sem número ficam sem ponto
(é melhor omitir do que apontar o lugar errado). Roda à mão, não no cron. Grava data/raw/inmetro/coordenadas.csv.
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
from scripts.geocode_radares import NOMINATIM, contexto_http, interpretar, palavras

RAIZ = Path(__file__).resolve().parent.parent
RAW = RAIZ / "data" / "raw" / "inmetro"
SAIDA = RAW / "coordenadas.csv"
CAMPOS = ["chave", "lat", "lon", "precisao", "osm_ref", "geocodificado_em"]


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
    with contexto_http() as c:
        for m in medidores:
            k = chave(m)
            if k in feitos:
                continue
            tipo, vias, numero = interpretar(" ".join(str(m["LocalVerificacao"]).replace("N°", "N º").split()))
            achado = None
            if tipo == "endereco" and numero:
                try:
                    achado = buscar(c, vias[0], numero)
                except httpx.HTTPError as e:
                    print(f"{m['LocalVerificacao']}: falha ({type(e).__name__}); fica para a próxima rodada")
                    continue
                time.sleep(1.1)
            if achado and not dentro(contorno, achado[0], achado[1]):
                achado = None
            feitos[k] = {"chave": k, "lat": f"{achado[0]:.5f}" if achado else "", "lon": f"{achado[1]:.5f}" if achado else "", "precisao": "porta" if achado else "", "osm_ref": achado[2] if achado else "", "geocodificado_em": hoje}
    RAW.mkdir(parents=True, exist_ok=True)
    with SAIDA.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(feitos.values(), key=lambda r: r["chave"]))
    print(f"{sum(1 for r in feitos.values() if r['precisao'])} com posição de {len(medidores)} medidores")


if __name__ == "__main__":
    main()
