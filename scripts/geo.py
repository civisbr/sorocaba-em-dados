"""Geometria do município (malha oficial do IBGE), sem dependências de rede."""

from __future__ import annotations

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MALHA = RAIZ / "data" / "raw" / "ibge" / "malha_3552205.geojson"


def _area(anel: list[list[float]]) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0, *_), (x1, y1, *_) in zip(anel, anel[1:] + anel[:1]))) / 2


def carregar_contorno(p: Path = MALHA) -> list[tuple[float, float]]:
    """Anel externo do município como (lon, lat); em MultiPolygon, o de maior área."""
    geo = json.loads(p.read_text(encoding="utf-8"))["features"][0]["geometry"]
    aneis = [geo["coordinates"][0]] if geo["type"] == "Polygon" else [poly[0] for poly in geo["coordinates"]]
    return [(x, y) for x, y, *_ in max(aneis, key=_area)]


def dentro(contorno: list[tuple[float, float]], lat: float, lon: float) -> bool:
    ok = False
    j = len(contorno) - 1
    for i, (xi, yi) in enumerate(contorno):
        xj, yj = contorno[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            ok = not ok
        j = i
    return ok
