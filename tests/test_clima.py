import json
import shutil

import pytest

from scripts.build_clima import RAIZ, construir as clima
from scripts.build_previsao import construir as previsao, iso


def test_normais_deterministicas_e_coerentes():
    a, b = clima(RAIZ / "data/raw/clima"), clima(RAIZ / "data/raw/clima")
    assert a.model_dump_json() == b.model_dump_json()
    mensais = [r for r in a.dados if r["recorte"] == "mensal"]
    assert [r["mes"] for r in mensais] == list(range(1, 13))
    for r in mensais:
        assert r["tmin_media"] < r["tmax_media"] and r["tmin_recorde"] <= r["tmin_media"] and r["tmax_recorde"] >= r["tmax_media"]
    anual = next(r for r in a.dados if r["recorte"] == "anual")
    assert abs(anual["chuva_mm"] - sum(r["chuva_mm"] for r in mensais)) < 2


def test_clima_declara_ser_modelo_e_nao_estacao():
    env = clima(RAIZ / "data/raw/clima")
    assert env.qualidade.flag.value == "estimativa"
    assert any("não uma estação" in n for n in env.qualidade.notas)


def test_previsao_junta_fontes_sem_misturar(tmp_path):
    (tmp_path / "open_meteo.json").write_text(json.dumps({"coletado_em": "2026-10-11", "dados": {"daily": {
        "time": ["2026-10-11"], "weather_code": [95], "temperature_2m_max": [28.0], "temperature_2m_min": [18.0],
        "precipitation_sum": [3.0], "precipitation_probability_max": [80], "wind_speed_10m_max": [10.0]}}}), encoding="utf-8")
    bloco = {"resumo": "Nublado", "temp_max": 27, "temp_min": 17, "umidade_max": 90, "umidade_min": 40, "dir_vento": "S", "int_vento": "Fracos", "nascer": "05h42", "ocaso": "18h13", "dia_semana": "Domingo"}
    (tmp_path / "inmet.json").write_text(json.dumps({"coletado_em": "2026-10-11", "dados": {"11/10/2026": {"manha": bloco, "tarde": bloco}, "12/10/2026": {"dia": bloco}}}), encoding="utf-8")
    env = previsao(tmp_path)
    fontes = [(r["fonte"], r["dia"]) for r in env.dados]
    assert fontes == [("open-meteo", "2026-10-11"), ("inmet", "2026-10-11"), ("inmet", "2026-10-12")]
    assert env.dados[0]["resumo"] == "Trovoadas" and env.dados[1]["tmax"] == 27


def test_previsao_sem_nenhuma_fonte_falha(tmp_path):
    with pytest.raises(FileNotFoundError):
        previsao(tmp_path)


def test_iso_converte_data_brasileira():
    assert iso("11/10/2026") == "2026-10-11"


def test_pagina_clima_sai_sem_previsao(tmp_path):
    from scripts.render import renderizar

    public = tmp_path / "public"
    shutil.copytree(RAIZ / "data/public", public)
    (public / "previsao.json").unlink(missing_ok=True)
    renderizar(public, tmp_path / "dist")
    html = (tmp_path / "dist/clima/index.html").read_text(encoding="utf-8")
    assert "A previsão não está disponível" in html and "Como é o clima mês a mês" in html


def test_pagina_clima_com_previsao_e_campos_nulos(tmp_path):
    import json as _j

    from scripts.render import renderizar

    public = tmp_path / "public"
    shutil.copytree(RAIZ / "data/public", public)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "open_meteo.json").write_text(_j.dumps({"coletado_em": "2026-10-11", "dados": {"daily": {
        "time": ["2026-10-11", "2026-10-12"], "weather_code": [95, None], "temperature_2m_max": [28.0, None], "temperature_2m_min": [18.0, None],
        "precipitation_sum": [3.0, None], "precipitation_probability_max": [80, None], "wind_speed_10m_max": [10.0, None]}}}), encoding="utf-8")
    (public / "previsao.json").write_text(previsao(raw).model_dump_json(), encoding="utf-8")
    renderizar(public, tmp_path / "dist")
    html = (tmp_path / "dist/clima/index.html").read_text(encoding="utf-8")
    assert "Trovoadas" in html and "None" not in html
