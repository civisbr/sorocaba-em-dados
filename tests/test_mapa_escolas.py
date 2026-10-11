import httpx
import pytest

from scripts import geocode_escolas as g
from scripts.contexto_mapa_escolas import contexto_mapa_escolas
from scripts.geo import carregar_contorno


def _escola(cod, rede="Municipal", lat=-23.5, lon=-47.45, posicao="porta", **m):
    base = {"co_inep": cod, "escola": f"ESCOLA {cod}", "bairro": "CENTRO", "endereco": "RUA A, 10", "rede": rede, "lat": lat, "lon": lon, "posicao": posicao,
            "mat_infantil": 0, "mat_anos_iniciais": 0, "mat_anos_finais": 0, "mat_medio": 0, "mat_eja": 0}
    base.update(m)
    return base


def test_contexto_agrupa_por_rede_e_etapa_e_conta_escolas_sem_posicao():
    env = {"dados": [_escola("1", mat_infantil=50), _escola("2", rede="Privada", mat_medio=30, mat_anos_finais=20), _escola("3", lat=None, lon=None, posicao=None)]}
    ctx = contexto_mapa_escolas(env, lambda n: n.title(), lambda la, lo: (la, lo))
    assert len(ctx["pontos"]) == 2 and ctx["sem_posicao"] == 1 and ctx["total"] == 3
    por = {p["n"]: p for p in ctx["pontos"]}
    assert por["Escola 1"]["e"] == "infantil" and por["Escola 2"]["e"] == "finais medio"
    assert [r["id"] for r in ctx["redes"]] == ["municipal", "privada"] and ctx["ordem"] == "municipal,privada"
    assert por["Escola 1"]["u"] == "1/" and por["Escola 1"]["en"] == "Rua A, 10" and por["Escola 1"]["g"] == "municipal"
    assert ctx["valores"]["porta"].startswith("Pelo endereço")


def test_sem_nenhuma_posicao_nao_ha_mapa():
    assert contexto_mapa_escolas({"dados": [_escola("1", lat=None, lon=None, posicao=None)]}, lambda n: n, lambda la, lo: (0, 0)) is None


def test_numero_da_porta_e_rua_curta():
    assert g.numero_da_porta("75") == "75" and g.numero_da_porta("KM 7 5") is None and g.numero_da_porta("S/N") is None and g.numero_da_porta("") is None
    assert g.diagonal_m(["-23.5000", "-23.4990", "-47.4600", "-47.4590"]) < 200
    assert g.diagonal_m(["-23.5", "-23.4", "-47.5", "-47.4"]) > 10_000


def _cliente(resposta):
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=resposta)))


CONTORNO = carregar_contorno()


def test_geocode_aceita_porta_com_mesma_rua_e_numero():
    r = [{"lat": "-23.50", "lon": "-47.45", "category": "amenity", "osm_type": "node", "osm_id": 1, "address": {"road": "Rua Betsaida", "house_number": "75"}}]
    assert g.buscar(_cliente(r), "RUA BETSAIDA", "75", CONTORNO)[2] == "porta"


def test_geocode_descarta_outra_rua_outro_numero_e_fora_do_municipio():
    ok = {"lat": "-23.50", "lon": "-47.45", "category": "amenity", "osm_type": "node", "osm_id": 1, "address": {"road": "Rua Betsaida", "house_number": "75"}}
    assert g.buscar(_cliente([{**ok, "address": {"road": "Rua Outra", "house_number": "75"}}]), "RUA BETSAIDA", "75", CONTORNO) is None
    assert g.buscar(_cliente([{**ok, "address": {"road": "Rua Betsaida", "house_number": "99"}}]), "RUA BETSAIDA", "75", CONTORNO) is None
    assert g.buscar(_cliente([{**ok, "lat": "-22.0", "lon": "-47.0"}]), "RUA BETSAIDA", "75", CONTORNO) is None
    assert g.buscar(_cliente([]), "RUA BETSAIDA", "75", CONTORNO) is None


def test_geocode_rua_so_quando_curta():
    via = {"lat": "-23.50", "lon": "-47.45", "category": "highway", "osm_type": "way", "osm_id": 2, "address": {"road": "Rua Betsaida"}}
    curta = {**via, "boundingbox": ["-23.5005", "-23.4995", "-47.4505", "-47.4495"]}
    longa = {**via, "boundingbox": ["-23.55", "-23.45", "-47.5", "-47.4"]}
    assert g.buscar(_cliente([curta]), "RUA BETSAIDA", None, CONTORNO)[2] == "rua"
    assert g.buscar(_cliente([longa]), "RUA BETSAIDA", None, CONTORNO) is None
    assert g.buscar(_cliente([curta]), "RUA BETSAIDA", "75", CONTORNO)[2] == "rua"  # sem a porta, a rua curta ainda serve como aproximação


def test_pagina_de_escolas_tem_mapa_quando_ha_coordenadas(tmp_path):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "scripts.render", "--saida", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    html = (tmp_path / "escolas" / "index.html").read_text(encoding="utf-8")
    assert 'class="ms-svg"' in html and "Mapa das escolas" in html and "Não há ranking" in html


def test_coordenadas_de_escola_inativa_nao_quebram_o_build(tmp_path):
    from scripts.build_escolas import _coordenadas
    arq = tmp_path / "coordenadas.csv"
    arq.write_text("co_inep;lat;lon;precisao;osm_ref;geocodificado_em\n111;-23.50000;-47.45000;porta;node/1;2026-10-11\n", encoding="utf-8")
    assert _coordenadas(arq, {"111", "222"})["111"]["posicao"] == "porta"
    with pytest.raises(ValueError, match="inexistente"):
        _coordenadas(arq, {"222"})


def test_coordenadas_invalidas_sao_recusadas(tmp_path):
    from scripts.build_escolas import _coordenadas
    cab = "co_inep;lat;lon;precisao;osm_ref;geocodificado_em\n"
    fora = tmp_path / "a.csv"; fora.write_text(cab + "111;-22.00000;-47.00000;porta;node/1;2026-10-11\n", encoding="utf-8")
    nivel = tmp_path / "b.csv"; nivel.write_text(cab + "111;-23.50000;-47.45000;chute;node/1;2026-10-11\n", encoding="utf-8")
    for arq in (fora, nivel):
        with pytest.raises(ValueError, match="inválida"):
            _coordenadas(arq, {"111"})


def test_manifesto_de_coordenadas_confere_o_hash(tmp_path):
    import json
    from scripts.build_escolas import _manifesto_coordenadas
    (tmp_path / "coordenadas.csv").write_text("x", encoding="utf-8")
    (tmp_path / "manifesto_coordenadas.json").write_text(json.dumps({"sha256_csv": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        _manifesto_coordenadas(tmp_path)
    assert _manifesto_coordenadas(tmp_path / "vazio") is None


def test_unidades_prisionais_e_socioeducativas_ficam_fora_do_mapa():
    env = {"dados": [_escola("1"), _escola("2", atendimento_restrito=True), _escola("3", lat=None, lon=None, posicao=None, atendimento_restrito=True)]}
    ctx = contexto_mapa_escolas(env, lambda n: n, lambda la, lo: (la, lo))
    assert [p["u"] for p in ctx["pontos"]] == ["1/"] and ctx["restritas"] == 2 and ctx["total"] == 1 and ctx["sem_posicao"] == 0


def test_dados_publicos_marcam_as_unidades_restritas():
    import json
    from pathlib import Path
    d = json.loads((Path(__file__).resolve().parent.parent / "data" / "public" / "escolas.json").read_text(encoding="utf-8"))["dados"]
    restritas = [e["escola"] for e in d if e["atendimento_restrito"]]
    assert any("PENITENCIARIA" in n or "SOCIOEDUC" in n or "CASA" in n for n in restritas)
