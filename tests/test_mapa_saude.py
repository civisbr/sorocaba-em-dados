import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import fetch_osm_base, mapa_base
from scripts.contexto_mapa_saude import contexto_mapa_saude
from scripts.geo import carregar_contorno, dentro

RAIZ = Path(__file__).resolve().parent.parent


def test_simplificar_mantem_pontas_e_remove_ponto_colinear():
    assert fetch_osm_base.simplificar([(0, 0), (0.00001, 0.5), (0, 1)], 0.0001) == [(0, 0), (0, 1)]
    assert len(fetch_osm_base.simplificar([(0, 0), (1, 0.5), (0, 1)], 0.0001)) == 3
    assert fetch_osm_base.simplificar([(0, 0), (1, 1)]) == [(0, 0), (1, 1)]


def test_recortar_divide_a_via_ao_sair_do_municipio():
    contorno = [(0, 0), (0, 10), (10, 10), (10, 0)]
    trechos = fetch_osm_base.recortar([(1, 1), (2, 2), (50, 50), (3, 3), (4, 4)], contorno)
    assert trechos == [[(1, 1), (2, 2)], [(3, 3), (4, 4)]]


def test_consulta_overpass_fica_no_host_permitido():
    import httpx
    with pytest.raises(ValueError):
        fetch_osm_base.so_host_confiavel(httpx.Request("GET", "https://exemplo.com/api"))
    fetch_osm_base.so_host_confiavel(httpx.Request("POST", "https://overpass-api.de/api/interpreter"))


def test_montar_classifica_vias_rios_e_bairros_dentro_do_contorno():
    contorno = [(0, 0), (0, 10), (10, 10), (10, 0)]
    dados = {"elements": [
        {"type": "way", "tags": {"highway": "trunk"}, "geometry": [{"lat": 1, "lon": 1}, {"lat": 2, "lon": 2}]},
        {"type": "way", "tags": {"highway": "tertiary"}, "geometry": [{"lat": 1, "lon": 1}, {"lat": 3, "lon": 3}]},
        {"type": "way", "tags": {"waterway": "river"}, "geometry": [{"lat": 1, "lon": 1}, {"lat": 4, "lon": 4}]},
        {"type": "way", "tags": {"highway": "footway"}, "geometry": [{"lat": 1, "lon": 1}, {"lat": 2, "lon": 2}]},
        {"type": "node", "lat": 5, "lon": 5, "tags": {"name": "Centro", "place": "suburb"}},
        {"type": "node", "lat": 50, "lon": 50, "tags": {"name": "Fora"}},
    ]}
    b = fetch_osm_base.montar(dados, contorno)
    assert len(b["vias"]["rodovia"]) == 1 and len(b["vias"]["rua"]) == 1 and len(b["rios"]) == 1
    assert [x["nome"] for x in b["bairros"]] == ["Centro"]


@pytest.fixture(scope="module")
def base():
    return json.loads((RAIZ / "data" / "raw" / "osm" / "base_sorocaba.json").read_text(encoding="utf-8"))


def test_svg_base_e_xml_valido_sem_script_nem_recursos_externos(base):
    svg, _ = mapa_base.gerar_svg(base)
    raiz = ET.fromstring(svg)
    assert raiz.tag.endswith("svg")
    assert "<script" not in svg and "http" not in svg.replace("http://www.w3.org/2000/svg", "")


def test_projecao_afim_bate_com_a_funcao_de_projecao(base):
    _, aux = mapa_base.gerar_svg(base)
    af = aux["mapa"]["afim"]
    lat, lon = -23.4985, -47.457
    x, y = aux["f"](lat, lon)
    assert x == pytest.approx(lon * af["k"] * af["escala"] + af["dx"], abs=1e-6)
    assert y == pytest.approx(-lat * af["escala"] + af["dy"], abs=1e-6)


def test_pontos_fora_do_municipio_ou_sem_coordenada_nao_vao_ao_mapa(base):
    _, aux = mapa_base.gerar_svg(base)
    u = {"recorte": "unidade", "tipo": "05", "leitos": 10, "nome": "HOSPITAL A", "natureza": "Privado", "atende_sus": 0, "logradouro": "RUA X", "numero": "1", "bairro": "CENTRO", "telefone": ""}
    env = {"dados": [{**u, "lat": -23.5, "lon": -47.45}, {**u, "nome": "FORA", "lat": -22.0, "lon": -47.0}, {**u, "nome": "SEM", "lat": None, "lon": None}, {**u, "tipo": "05", "leitos": 0, "lat": -23.5, "lon": -47.45}]}
    ctx = contexto_mapa_saude(env, lambda n: n.title(), aux["mapa"], aux["f"])
    assert len(ctx["pontos"]) == 1 and ctx["sem_posicao"] == 2
    assert dentro(carregar_contorno(), float(ctx["pontos"][0]["lat"]), float(ctx["pontos"][0]["lon"]))


def test_pagina_tem_mapa_sem_terceiros_e_funciona_sem_js(tmp_path):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "scripts.render", "--saida", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    html = (tmp_path / "hospitais" / "index.html").read_text(encoding="utf-8")
    assert 'class="ms-svg"' in html and html.count('class="ms-u ') >= 30
    assert re.search(r'<g class="ms-voce" hidden>', html) and "data-so-js hidden" in html  # recursos que dependem de JS só aparecem com JS
    assert 'src="../mapa-interativo.js"' in html and "mapa-base.svg" in html
    externos = {h for h in re.findall(r'(?:src|href)="(https?://[^"/]+)', html)}
    assert externos <= {"https://www.openstreetmap.org", "https://datasus.saude.gov.br", "https://github.com"}
    assert (tmp_path / "mapa-base.svg").exists() and (tmp_path / "mapa-interativo.js").exists() and (tmp_path / "data" / "mapa-bairros.json").exists()
    assert "<script" not in (tmp_path / "mapa-base.svg").read_text(encoding="utf-8")


def test_svg_base_so_tem_elementos_de_desenho(base):
    svg, _ = mapa_base.gerar_svg(base)
    tags = {e.tag.split("}")[1] for e in ET.fromstring(svg).iter()}
    assert tags <= {"svg", "style", "path", "title"}


def test_js_do_mapa_nao_envia_nem_guarda_a_posicao():
    js = (RAIZ / "static" / "mapa-interativo.js").read_text(encoding="utf-8")
    assert js.count("fetch(") == 2 and "fetch(svg.dataset.bairros)" in js and "fetch(svg.dataset.pontos)" in js  # só arquivos do próprio site
    for proibido in ("localStorage", "sessionStorage", "XMLHttpRequest", "sendBeacon", "innerHTML", "document.cookie", "console.log"):
        assert proibido not in js
    assert set(re.findall(r"toFixed\((\d)\)", js)) <= {"1", "3", "4"}  # a origem enviada ao OpenStreetMap tem no máximo 3 casas
    assert "posicao.lat.toFixed(3)" in js


def test_nome_de_bairro_sem_caracteres_de_controle_ou_direcao():
    assert fetch_osm_base._nome("Vila\u202e Hortência\n") == "Vila Hortência" and fetch_osm_base._nome(5) == ""
