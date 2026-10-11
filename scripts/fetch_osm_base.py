"""Base cartográfica de Sorocaba (vias principais, rios e bairros) do OpenStreetMap (ODbL), para o mapa sem terceiros no navegador.

Roda à mão, não no cron: o desenho muda devagar. Grava data/raw/osm/base_sorocaba.json com as linhas já recortadas no contorno do
município e simplificadas. Uso moderado do Overpass, conforme a política do serviço.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import unicodedata
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


def _nome(v) -> str:
    """Nome de bairro do OSM: só texto, sem caracteres de controle ou de direção (categorias Cc e Cf), até 60 caracteres."""
    if not isinstance(v, str):
        return ""
    return "".join(ch for ch in v if unicodedata.category(ch) not in ("Cc", "Cf")).strip()[:60]


def consulta(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    vias = "|".join(CLASSES)
    return (f'[out:json][timeout:90];(way["highway"~"^({vias})$"]({s},{w},{n},{e});way["waterway"="river"]({s},{w},{n},{e});'
            f'node["place"~"^(suburb|neighbourhood|quarter)$"]["name"]({s},{w},{n},{e}););out geom;')


def baixar(c: httpx.Client, bbox) -> tuple[dict, str]:
    """(resposta, espelho que respondeu). O espelho padrão vem primeiro; os outros só entram se ele falhar."""
    for t in range(6):
        espelho = ESPELHOS[t % len(ESPELHOS)]
        try:
            with c.stream("POST", espelho, data={"data": consulta(bbox)}) as r:
                r.raise_for_status()
                corpo = bytearray()
                for pedaco in r.iter_bytes(256 * 1024):
                    corpo += pedaco
                    if len(corpo) > LIMITE_BYTES:
                        raise ValueError("resposta do Overpass acima do limite")
            dados = json.loads(bytes(corpo))
            if isinstance(dados.get("elements"), list) and not dados.get("remark"):  # "remark" indica timeout ou falta de memória: resposta parcial
                return dados, espelho
        except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError, httpx.DecodingError):
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
            if _nome(tags["name"]) and dentro(contorno, e["lat"], e["lon"]):
                bairros.append({"nome": _nome(tags["name"]), "lat": round(e["lat"], 5), "lon": round(e["lon"], 5)})
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


def _linhas(base: dict) -> str:
    """JSON com uma via por linha, para que as próximas atualizações possam ser revisadas no diff."""
    def lista(itens: list) -> str:
        return "[\n" + ",\n".join(json.dumps(i, ensure_ascii=False, separators=(",", ":")) for i in itens) + "\n]"
    vias = ",\n".join(f'"{k}":{lista(v)}' for k, v in sorted(base["vias"].items()))
    resto = {k: v for k, v in base.items() if k not in ("vias", "rios", "bairros")}
    meta = json.dumps(resto, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)[1:-1]
    return f'{{{meta},\n"bairros":{lista(base["bairros"])},\n"rios":{lista(base["rios"])},\n"vias":{{\n{vias}\n}}}}\n'


def main() -> None:
    contorno = carregar_contorno()
    lons, lats = [x for x, _ in contorno], [y for _, y in contorno]
    bbox = (min(lats), min(lons), max(lats), max(lons))
    with httpx.Client(timeout=120, headers={"User-Agent": AGENTE}, event_hooks={"request": [so_host_confiavel]}) as c:
        dados, espelho = baixar(c, bbox)
    anterior = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else None
    base = montar(dados, contorno)
    n_vias = sum(len(v) for v in base["vias"].values())
    if n_vias < 100 or not base["bairros"]:
        raise SystemExit("recorte implausível; a consulta mudou?")
    if anterior:
        antes = sum(len(v) for v in anterior["vias"].values())
        if not 0.8 <= n_vias / antes <= 1.25 or not 0.8 <= len(base["bairros"]) / len(anterior["bairros"]) <= 1.25:
            raise SystemExit(f"vias foram de {antes} para {n_vias}; confira o espelho antes de aceitar")
    hoje = date.today().isoformat()
    base.update(fonte="OpenStreetMap contributors (ODbL 1.0)", acesso_em=hoje)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    texto = _linhas(base)
    SAIDA.write_text(texto, encoding="utf-8")
    man = {"fonte": base["fonte"], "licenca": "ODbL 1.0 (https://opendatacommons.org/licenses/odbl/1-0/)", "acesso_em": hoje, "espelho": espelho,
           "timestamp_osm_base": dados.get("osm3s", {}).get("timestamp_osm_base"), "consulta": consulta(bbox), "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
           "n_vias": n_vias, "n_rios": len(base["rios"]), "n_bairros": len(base["bairros"])}
    (SAIDA.parent / "manifesto.json").write_text(json.dumps(man, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(man["n_vias"], man["n_rios"], man["n_bairros"], espelho)


if __name__ == "__main__":
    main()
