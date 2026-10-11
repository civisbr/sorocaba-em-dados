"""Mapa-base de Sorocaba em SVG (contorno, rios e vias do OpenStreetMap), servido como arquivo próprio do site.

Nada é pedido a terceiros no navegador: o desenho é gerado no build a partir de data/raw/osm/base_sorocaba.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.mapa import projetar

LARGURA = 1600
ALTURA = 1560
MARGEM = 40
RAIZ = Path(__file__).resolve().parent.parent
MALHA = RAIZ / "data" / "raw" / "ibge" / "malha_3552205.geojson"
BASE = RAIZ / "data" / "raw" / "osm" / "base_sorocaba.json"
# O SVG é carregado por <image>, onde o CSS da página não vale: as cores ficam aqui.
ESTILO = (".c{fill:#eef3f1;stroke:#7a8f99;stroke-width:3}.r{fill:none;stroke:#a9cfe6;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}"
          ".v{fill:none;stroke-linecap:round;stroke-linejoin:round}.v0{stroke:#fff;stroke-width:1.6}.v1{stroke:#fff;stroke-width:3.4}.v2{stroke:#f6d98c;stroke-width:5}"
          ".b0{fill:none;stroke:#d5dde0;stroke-width:2.6}.b1{fill:none;stroke:#c3ccd1;stroke-width:5}.b2{fill:none;stroke:#e1b94f;stroke-width:7.4}")


def _caminho(trechos: list, f) -> str:
    partes = []
    for t in trechos:
        pts = [f(la, lo) for la, lo in t]
        partes.append("M" + "L".join(f"{x:.0f} {y:.0f}" for x, y in pts))
    return "".join(partes)


def gerar_svg(base: dict, malha: Path = MALHA) -> tuple[str, dict]:
    mapa, f = projetar(malha, LARGURA, ALTURA, MARGEM)
    camadas = []
    for classe, chave in (("0", "rua"), ("1", "avenida"), ("2", "rodovia")):
        d = _caminho(base["vias"][chave], f)
        camadas.append(f'<path class="b{classe}" d="{d}"/>')
    for classe, chave in (("0", "rua"), ("1", "avenida"), ("2", "rodovia")):
        d = _caminho(base["vias"][chave], f)
        camadas.append(f'<path class="v v{classe}" d="{d}"/>')
    rios = f'<path class="r" d="{_caminho(base["rios"], f)}"/>'
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {LARGURA} {ALTURA}" width="{LARGURA}" height="{ALTURA}"><title>Sorocaba: contorno (IBGE), vias e rios (© OpenStreetMap contributors, ODbL 1.0)</title><style>{ESTILO}</style>'
           f'<path class="c" d="{mapa["caminho"]}"/>{rios}{"".join(camadas)}<path d="{mapa["caminho"]}" fill="none" stroke="#7a8f99" stroke-width="3"/></svg>')
    return svg, {"mapa": mapa, "f": f}


def bairros_json(base: dict, f) -> str:
    itens = [{"n": b["nome"], "x": round(f(b["lat"], b["lon"])[0], 1), "y": round(f(b["lat"], b["lon"])[1], 1), "la": b["lat"], "lo": b["lon"]} for b in base["bairros"]]
    return json.dumps({"fonte": base.get("fonte"), "licenca": "ODbL 1.0, https://www.openstreetmap.org/copyright", "acesso_em": base.get("acesso_em"), "bairros": itens}, ensure_ascii=False, separators=(",", ":"))


_PROJ = None


def proj_grande():
    """(mapa, f) do quadro grande, que serve a todos os mapas interativos."""
    global _PROJ
    if _PROJ is None:
        _PROJ = projetar(MALHA, LARGURA, ALTURA, MARGEM)
    return _PROJ


def contexto_base(raiz: str) -> dict:
    """Dados que os macros de templates/_mapa.html precisam para montar um mapa interativo."""
    from scripts.fetch_osm_base import simplificar
    from scripts.geo import carregar_contorno

    mapa, _ = proj_grande()
    contorno = carregar_contorno()
    return {"largura": mapa["largura"], "altura": mapa["altura"], "k": mapa["afim"]["k"], "escala": mapa["afim"]["escala"], "dx": mapa["afim"]["dx"], "dy": mapa["afim"]["dy"],
            "contorno": ";".join(f"{la:.4f},{lo:.4f}" for lo, la in simplificar(contorno, 0.0004)), "base_url": f"{raiz}mapa-base.svg", "bairros_url": f"{raiz}data/mapa-bairros.json"}
