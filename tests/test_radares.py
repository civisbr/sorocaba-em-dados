import pytest

from scripts.build_radares import RAIZ, construir
from scripts.fetch_radares import linhas

LINHA = '<tr><td>1194</td><td>F013</td><td>AV. DR. AFONSO VERGUEIRO Nº 2635 (B/C)</td><td>FIXO - CONTROLADOR</td><td>60 Km/h</td><td>x</td></tr>'


def test_linha_da_semob_vira_registro_sem_numero_de_serie():
    r = linhas(f"<table>{LINHA}</table>")
    assert r == [{"ponto": "F013", "local": "AV. DR. AFONSO VERGUEIRO Nº 2635 (B/C)", "tipo": "FIXO - CONTROLADOR", "velocidade_kmh": "60"}]


def test_velocidade_nao_reconhecida_quebra():
    with pytest.raises(ValueError, match="velocidade"):
        linhas(LINHA.replace("60 Km/h", "rápido"))


def test_build_deterministico_e_publicado_coerente():
    a, b = construir(RAIZ / "data/raw/radares"), construir(RAIZ / "data/raw/radares")
    assert a.model_dump_json() == b.model_dump_json()
    assert all(r["velocidade_kmh"] in (40, 50, 60, 70) for r in a.dados)
    assert len({r["ponto"] for r in a.dados}) == len(a.dados)
    assert not any("serie" in k for r in a.dados for k in r)


def test_interpreta_local_da_semob():
    from scripts.geocode_radares import interpretar
    assert interpretar("RUA MICHEL CHICRI MALUF , 660 (C/B)") == ("endereco", ["RUA MICHEL CHICRI MALUF"], "660")
    assert interpretar("AV. DR. ARMANDO PANNUNZIO X R. VICÊNCIA LEONETTI (C/B)")[:2] == ("cruzamento", ["AVENIDA DOUTOR ARMANDO PANNUNZIO", "RUA VICÊNCIA LEONETTI"])
    assert interpretar("AV. DOM AGUIRRE (B/C) , Nº 3303")[2] == "3303"


def test_casamento_de_camera_exige_unicidade_nos_dois_sentidos():
    from scripts.geocode_radares import casar_cameras, palavras
    cam = lambda i, via, v: {"lat": -23.5, "lon": -47.4 + i / 100, "tags": {"maxspeed": str(v)}, "vias": [palavras(via)]}
    rad = lambda p, local, v: {"ponto": p, "local": local, "velocidade_kmh": v}
    cams = [cam(0, "Avenida Santa Cruz", 50), cam(1, "Rua Aparecida", 40), cam(2, "Rua Aparecida", 40)]
    r = casar_cameras([rad("A", "AV. SANTA CRUZ , Nº 290", 50), rad("B", "RUA APARECIDA , Nº 10", 40)], cams)
    assert list(r) == ["A"]  # Rua Aparecida tem duas câmeras: ambíguo


def test_posicoes_publicadas_estao_no_municipio():
    from scripts.fetch_infosiga import carregar_contorno, dentro
    c = carregar_contorno()
    com = [r for r in construir(RAIZ / "data/raw/radares").dados if "lat" in r]
    assert all(dentro(c, r["lat"], r["lon"]) and r["precisao"] in ("endereço", "câmera no OSM") for r in com)


def _cam(via, **tags):
    from scripts.geocode_radares import palavras
    return {"lat": -23.5, "lon": -47.4, "tags": tags, "vias": [palavras(via)]}


def test_casamento_exige_maxspeed_igual_e_nome_contido():
    from scripts.geocode_radares import casar_cameras
    rad = {"ponto": "A", "local": "AV. SANTA CRUZ , Nº 290", "velocidade_kmh": 50}
    assert casar_cameras([rad], [_cam("Avenida Santa Cruz", maxspeed="50")]) != {}
    assert casar_cameras([rad], [_cam("Avenida Santa Cruz")]) == {}
    assert casar_cameras([rad], [_cam("Avenida Santa Cruz", maxspeed="60")]) == {}
    assert casar_cameras([rad], [_cam("Rua Cruz", maxspeed="50")]) == {}
    assert casar_cameras([rad, dict(rad, ponto="B")], [_cam("Avenida Santa Cruz", maxspeed="50")]) == {}


def test_interpretar_numero_com_espaco_via_de_referencia_e_cdor():
    from scripts.geocode_radares import interpretar
    assert interpretar("RUA PAES , N º 1560 (C/B)")[2] == "1560"
    assert interpretar("AV. Y N.567")[2] == "567"
    assert interpretar("RUA A , PRÓX RUA B , Nº 10")[:2] == ("rua", ["RUA A"])  # número da via de referência não vale
    assert interpretar("CDOR. PEREIRA , Nº 5")[1] == ["COMENDADOR PEREIRA"]


def test_vista_aproxima_e_nao_sai_do_quadro():
    from scripts.render import vista_dos_pontos
    mapa = {"largura": 400, "altura": 430}
    for pts in ([{"x": 5.0, "y": 5.0}], [{"x": 395.0, "y": 425.0}], [{"x": 10.0, "y": 10.0}, {"x": 390.0, "y": 420.0}]):
        x, y, w, h = map(float, vista_dos_pontos(pts, mapa).split())
        assert x >= 0 and y >= 0 and x + w <= 400.01 and y + h <= 430.01


def test_todo_painel_esta_em_exatamente_um_grupo():
    from scripts.paineis import GRUPOS, PAINEIS
    assert sorted(i for _, ids in GRUPOS for i in ids) == sorted(PAINEIS)
