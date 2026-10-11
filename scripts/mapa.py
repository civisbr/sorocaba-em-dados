"""Contorno do município em SVG, a partir da malha oficial do IBGE."""

from __future__ import annotations

import json
import math
from pathlib import Path

LARGURA = 400
ALTURA = 430
MARGEM = 24


def _anel_externo(geojson: dict) -> list[tuple[float, float]]:
    g = geojson["features"][0]["geometry"]
    poligonos = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    anel = max((p[0] for p in poligonos), key=len)
    return [(lon, lat) for lon, lat in anel]


def _centroide(pontos: list[tuple[float, float]]) -> tuple[float, float]:
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pontos, pontos[1:] + pontos[:1]):
        c = x0 * y1 - x1 * y0
        area += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    area /= 2
    return cx / (6 * area), cy / (6 * area)


def gerar(caminho: Path) -> dict:
    return _projetar(caminho)[0]


def projetar(caminho: Path, largura: int = LARGURA, altura: int = ALTURA, margem: int = MARGEM):
    """(mapa, f) onde f(lat, lon) devolve (x, y) no mesmo quadro do contorno."""
    mapa, f = _projetar(caminho, largura, altura, margem)
    return mapa, f


def _projetar(caminho: Path, largura: int = LARGURA, altura: int = ALTURA, margem: int = MARGEM):
    anel = _anel_externo(json.loads(caminho.read_text(encoding="utf-8")))
    lat0 = sum(lat for _, lat in anel) / len(anel)
    k = math.cos(math.radians(lat0))
    plano = [(lon * k, -lat) for lon, lat in anel]
    xs, ys = [x for x, _ in plano], [y for _, y in plano]
    escala = min((largura - 2 * margem) / (max(xs) - min(xs)), (altura - 2 * margem) / (max(ys) - min(ys)))
    dx = (largura - escala * (max(xs) - min(xs))) / 2 - escala * min(xs)
    dy = (altura - escala * (max(ys) - min(ys))) / 2 - escala * min(ys)

    def px(p: tuple[float, float]) -> tuple[float, float]:
        return p[0] * escala + dx, p[1] * escala + dy

    pts = [px(p) for p in plano]
    caminho_svg = "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"
    clon, clat = _centroide(anel)
    cx, cy = px((clon * k, -clat))
    def ponto(lat: float, lon: float) -> tuple[float, float]:
        return px((lon * k, -lat))

    return {
        "largura": largura,
        "altura": altura,
        "afim": {"k": k, "escala": escala, "dx": dx, "dy": dy},  # x = lon*k*escala + dx; y = -lat*escala + dy
        "caminho": caminho_svg,
        "centro_x": round(cx, 1),
        "centro_y": round(cy, 1),
        "lat": f"{clat:.4f}".replace("-", "−"),
        "lon": f"{clon:.4f}".replace("-", "−"),
    }, ponto
