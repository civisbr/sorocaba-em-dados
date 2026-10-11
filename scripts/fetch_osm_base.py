"""Base cartográfica de Sorocaba (vias principais, rios e bairros) do OpenStreetMap (ODbL), para o mapa sem terceiros no navegador.

Roda à mão, não no cron: o desenho muda devagar. Grava data/raw/osm/base_sorocaba.json com as linhas já recortadas no contorno do
município e simplificadas. Uso moderado do Overpass, conforme a política do serviço.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import date
from pathlib import Path

import httpx

from scripts.geo import carregar_contorno, dentro

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "data" / "raw" / "osm" / "base_sorocaba.json"
ESPELHOS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
HOSTS = {u.split("/")[2] for u in ESPELHOS}
AGENTE = "SorocabaEmDados/1.0 (+https://github.com/civisbr/sorocaba-em-dados)"
CLASSES = {"motorway": "rodovia", "motorway_link": "rodovia", "trunk": "rodovia", "trunk_link": "rodovia", "primary": "avenida", "primary_link": "avenida",
           "secondary": "avenida", "secondary_link": "avenida", "tertiary": "rua"}
TOLERANCIA = 0.00006  # ~7 m
LIMITE_BYTES = 40 * 1024 * 1024


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host not in HOSTS:
        raise ValueError(f"requisição fora dos hosts do Overpass: {r.url.host}")


def simplificar(pts: list[tuple[float, float]], tol: float = TOLERANCIA) -> list[tuple[float, float]]:
    """Douglas-Peucker iterativo."""
    if len(pts) < 3:
        return pts
    manter = [False] * len(pts)
    manter[0] = manter[-1] = True
    pilha = [(0, len(pts) - 1)]
    while pilha:
        i, j = pilha.pop()
        (x0, y0), (x1, y1) = pts[i], pts[j]
        dx, dy = x1 - x0, y1 - y0
        n = math.hypot(dx, dy)
        melhor, k = -1.0, -1
        for m in range(i + 1, j):
            x, y = pts[m]
            d = math.hypot(x - x0, y - y0) if n == 0 else abs(dy * (x - x0) - dx * (y - y0)) / n
            if d > melhor:
                melhor, k = d, m
        if melhor > tol:
            manter[k] = True
            pilha += [(i, k), (k, j)]
    return [p for p, ok in zip(pts, manter) if ok]


def recortar(pts: list[tuple[float, float]], contorno) -> list[list[tuple[float, float]]]:
    """Trechos consecutivos de pts (lat, lon) que estão dentro do município."""
    trechos, atual = [], []
    for lat, lon in pts:
        if dentro(contorno, lat, lon):
            atual.append((lat, lon))
        else:
            if len(atual) > 1:
                trechos.append(atual)
            atual = []
    if len(atual) > 1:
        trechos.append(atual)
    return trechos


def consulta(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    vias = "|".join(CLASSES)
    return (f'[out:json][timeout:90];(way["highway"~"^({vias})$"]({s},{w},{n},{e});way["waterway"="river"]({s},{w},{n},{e});'
            f'node["place"~"^(suburb|neighbourhood|quarter)$"]["name"]({s},{w},{n},{e}););out geom;')


def baixar(c: httpx.Client, bbox) -> dict:
    for t in range(6):
        try:
            with c.stream("POST", ESPELHOS[t % len(ESPELHOS)], data={"data": consulta(bbox)}) as r:
                r.raise_for_status()
                corpo = bytearray()
                for pedaco in r.iter_bytes(256 * 1024):
                    corpo += pedaco
                    if len(corpo) > LIMITE_BYTES:
                        raise ValueError("resposta do Overpass acima do limite")
            dados = json.loads(bytes(corpo))
            if isinstance(dados.get("elements"), list):
                return dados
        except (httpx.TransportError, httpx.HTTPStatusError):
            pass
        time.sleep(10 * (t + 1))
    raise RuntimeError("Overpass indisponível; tente de novo mais tarde")


def montar(dados: dict, contorno) -> dict:
    vias: dict[str, list] = {"rodovia": [], "avenida": [], "rua": []}
    rios: list = []
    bairros: list = []
    for e in dados["elements"]:
        tags = e.get("tags", {})
        if e["type"] == "node" and tags.get("name"):
            if dentro(contorno, e["lat"], e["lon"]):
                bairros.append({"nome": tags["name"].strip()[:60], "lat": round(e["lat"], 5), "lon": round(e["lon"], 5)})
        elif e["type"] == "way" and e.get("geometry"):
            pts = [(g["lat"], g["lon"]) for g in e["geometry"]]
            alvo = rios if tags.get("waterway") else vias[CLASSES[tags["highway"]]] if tags.get("highway") in CLASSES else None
            if alvo is None:
                continue
            for t in recortar(pts, contorno):
                s = simplificar(t)
                if len(s) > 1:
                    alvo.append([[round(la, 5), round(lo, 5)] for la, lo in s])
    return {"vias": vias, "rios": rios, "bairros": sorted({(b["nome"], b["lat"], b["lon"]): b for b in bairros}.values(), key=lambda b: b["nome"])}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    a = p.parse_args()
    if a.acesso_em > date.today():
        raise SystemExit("acesso_em no futuro")
    contorno = carregar_contorno()
    lons, lats = [x for x, _ in contorno], [y for _, y in contorno]
    bbox = (min(lats), min(lons), max(lats), max(lons))
    with httpx.Client(timeout=120, headers={"User-Agent": AGENTE}, event_hooks={"request": [so_host_confiavel]}) as c:
        base = montar(baixar(c, bbox), contorno)
    if sum(len(v) for v in base["vias"].values()) < 100 or not base["bairros"]:
        raise SystemExit("recorte implausível; a consulta mudou?")
    base.update(fonte="OpenStreetMap contributors (ODbL)", acesso_em=a.acesso_em.isoformat())
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(base, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print({k: len(v) if isinstance(v, list) else {kk: len(vv) for kk, vv in v.items()} for k, v in base.items() if k in ("vias", "rios", "bairros")}, SAIDA.stat().st_size)


if __name__ == "__main__":
    main()
