import json
import shutil

import pytest

from scripts.build_perfil import RAIZ, construir, series

RAW = RAIZ / "data/raw/ibge/perfil"


def test_reticencias_viram_nulo_e_nao_zero():
    s = series([{"id": "1", "resultados": [{"series": [{"serie": {"2022": "...", "2021": "10"}}]}]}])
    assert s["1"] == {"2022": None, "2021": 10.0}


def test_build_deterministico_e_n_registros():
    a, b = construir(RAW), construir(RAW)
    assert a.model_dump_json() == b.model_dump_json()
    assert a.qualidade.n_registros == len(a.dados)


def test_setores_somam_o_total():
    env = construir(RAW)
    vab = {r["chave"]: r for r in env.dados if r["recorte"] == "vab_setor"}
    assert sum(r["valor"] for k, r in vab.items() if k != "total") == vab["total"]["valor"]


def test_setores_que_nao_somam_quebram(tmp_path):
    raw = tmp_path / "perfil"
    shutil.copytree(RAW, raw)
    arq = raw / "vab.json"
    dados = json.loads(arq.read_text(encoding="utf-8"))
    for v in dados:
        if v["id"] == "517":
            serie = v["resultados"][0]["series"][0]["serie"]
            serie[max(a for a, x in serie.items() if x != "...")] = "1"
    arq.write_text(json.dumps(dados), encoding="utf-8")
    with pytest.raises(ValueError, match="não somam"):
        construir(raw)


def test_pagina_mostra_ano_de_cada_dado(tmp_path):
    from scripts.render import renderizar

    renderizar(RAIZ / "data/public", tmp_path / "dist")
    html = (tmp_path / "dist/cidade/index.html").read_text(encoding="utf-8")
    ano = max(r["ano"] for r in json.loads((RAIZ / "data/public/perfil.json").read_text(encoding="utf-8"))["dados"] if r["recorte"] == "vab_setor")
    assert "Censo 2022" in html and f"({ano})" in html and "sem descontar a inflação" in html


def test_ano_sem_valor_no_pib_nao_quebra(tmp_path):
    raw = tmp_path / "perfil"
    shutil.copytree(RAW, raw)
    arq = raw / "pib.json"
    dados = json.loads(arq.read_text(encoding="utf-8"))
    for v in dados:
        serie = v["resultados"][0]["series"][0]["serie"]
        serie["2024"] = "..."
    arq.write_text(json.dumps(dados), encoding="utf-8")
    env = construir(raw)
    assert max(r["ano"] for r in env.dados if r["recorte"] == "pib_serie") == 2023
