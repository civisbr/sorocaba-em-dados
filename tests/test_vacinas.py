import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from scripts import build_vacinas
from scripts.contexto_vacinas import contexto_vacinas

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "vacinas"


@pytest.fixture
def raw(tmp_path):
    shutil.copytree(RAW, tmp_path / "v")
    return tmp_path / "v"


def _env(raw):
    return build_vacinas.construir(raw).model_dump(mode="json")


def test_dados_reais_constroem_e_cobrem_todos_os_publicos(raw):
    ctx = contexto_vacinas(_env(raw), date(2026, 10, 11))
    assert [p["nome"] for p in ctx["publicos"]] == list(build_vacinas.PUBLICOS)
    assert all(p["idades"] for p in ctx["publicos"])
    criancas = ctx["publicos"][0]["idades"]
    assert criancas[0]["idade"] == "Ao nascer" and criancas[1]["idade"] == "2 meses"
    assert [i["idade"] for i in criancas].index("12 meses") < [i["idade"] for i in criancas].index("4 anos")


def test_situacao_da_campanha_depende_da_data(raw):
    env = _env(raw)
    assert contexto_vacinas(env, date(2026, 8, 10))["ativas"][0]["situacao"] == "em andamento"
    assert contexto_vacinas(env, date(2026, 10, 11))["ativas"] == []
    assert contexto_vacinas(env, date(2026, 7, 1))["ativas"][0]["situacao"] == "prevista"


def test_aviso_quando_conferencia_esta_velha(raw):
    env = _env(raw)
    assert contexto_vacinas(env, date(2026, 10, 20))["dias_conferencia"] is None
    assert contexto_vacinas(env, date(2027, 3, 1))["dias_conferencia"] > 120


def test_publico_desconhecido_e_linha_repetida_sao_recusados(raw):
    cal = (raw / "calendario.csv").read_text(encoding="utf-8")
    (raw / "calendario.csv").write_text(cal + "Marcianos;1 ano;X;Y;\n", encoding="utf-8")
    with pytest.raises(ValueError, match="público"):
        build_vacinas.construir(raw)
    linhas = cal.splitlines()
    (raw / "calendario.csv").write_text(cal + linhas[1] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="repetida"):
        build_vacinas.construir(raw)


def test_campanha_com_url_insegura_ou_datas_invertidas_e_recusada(raw):
    camp = (raw / "campanhas.csv").read_text(encoding="utf-8")
    (raw / "campanhas.csv").write_text(camp.replace("https://", "http://"), encoding="utf-8")
    with pytest.raises(ValueError, match="https"):
        build_vacinas.construir(raw)
    (raw / "campanhas.csv").write_text(camp.replace("2026-09-01", "2026-07-01"), encoding="utf-8")
    with pytest.raises(ValueError, match="fim antes"):
        build_vacinas.construir(raw)


def test_colunas_trocadas_sao_recusadas(raw):
    (raw / "campanhas.csv").write_text("nome;inicio\nx;2026-01-01\n", encoding="utf-8")
    with pytest.raises(ValueError, match="colunas"):
        build_vacinas.construir(raw)


def test_json_publico_confere_com_a_curadoria(raw):
    publico = json.loads((RAW.parent.parent / "public" / "saude_vacinas.json").read_text(encoding="utf-8"))
    assert publico == _env(RAW)


def test_pagina_de_vacinas_renderizada(tmp_path):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "scripts.render", "--saida", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    html = (tmp_path / "vacinas" / "index.html").read_text(encoding="utf-8")
    assert "Calendário de vacinação do SUS" in html and "Tríplice viral" in html
