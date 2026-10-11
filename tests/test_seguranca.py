import json

from scripts.build_seguranca import RAIZ, construir
from scripts.seguranca_grupos import chave

RAW = RAIZ / "data/raw/ssp"


def test_normaliza_grafias_de_natureza_entre_anos():
    assert chave("TRÁFICO DE ENTORPECENTES") == chave("TRAFICO DE ENTORPECENTES")
    assert chave("ROUBO – OUTROS") == chave("ROUBO - OUTROS")
    assert chave("HOMICÍDIO DOLOSO") == "HOMICIDIO DOLOSO"


def test_build_deterministico():
    assert construir(RAW).model_dump_json() == construir(RAW).model_dump_json()


def test_mensal_sem_duplicidade_e_janelas_de_12_meses():
    env = construir(RAW)
    chaves = [(r["ano"], r["mes"], r["grupo"]) for r in env.dados if r["recorte"] == "mensal"]
    assert len(chaves) == len(set(chaves))
    atual = {r["grupo"]: r["n"] for r in env.dados if r["recorte"] == "janela_atual"}
    ultimo = max((a, m) for a, m, _ in chaves)
    meses = sorted({(a, m) for a, m, _ in chaves})
    ult12 = meses[meses.index(ultimo) - 11: meses.index(ultimo) + 1]
    esperado = sum(r["n"] for r in env.dados if r["recorte"] == "mensal" and r["grupo"] == "roubos" and (r["ano"], r["mes"]) in ult12)
    assert atual["roubos"] == esperado


def test_horas_cobrem_24_e_percentuais_fecham():
    env = construir(RAW)
    for g in ("roubos", "furtos"):
        horas = [r for r in env.dados if r["recorte"] == "hora" and r["grupo"] == g]
        assert [r["categoria"] for r in horas] == [f"{h:02d}" for h in range(24)]
        faixas = [r for r in env.dados if r["recorte"] == "periodo" and r["grupo"] == g]
        assert abs(sum(r["pct"] for r in faixas) - 100) < 0.6


def test_bairros_em_ordem_alfabetica_sem_ranking_e_com_demais():
    env = construir(RAW)
    nomes = [r["categoria"] for r in env.dados if r["recorte"] == "bairro" and r["grupo"] == "roubos"]
    corpo, resto = nomes[:-1], nomes[-1]
    assert resto.startswith("Demais")
    import unicodedata
    chaves = [unicodedata.normalize("NFKD", n) for n in corpo]
    assert chaves == sorted(chaves)


def test_raw_sem_identificador_de_boletim_ou_endereco():
    for arq in RAW.rglob("*.csv"):
        cab = arq.read_text(encoding="utf-8").splitlines()[0].lower()
        for proibido in ("num_bo", "logradouro", "latitude", "longitude", "numero"):
            assert proibido not in cab, arq
    assert "sha256_xlsx" in json.loads((RAW / "manifesto.json").read_text(encoding="utf-8"))["anos"]["2025"]


def test_pagina_traz_ranking_de_bairro_com_ressalva(tmp_path):
    from scripts.render import renderizar

    renderizar(RAIZ / "data/public", tmp_path / "dist")
    html = (tmp_path / "dist/seguranca/index.html").read_text(encoding="utf-8")
    assert "não significa bairro mais perigoso" in html and "ordem alfabética" in html
    assert "Mapa de calor" in html and "têm coordenada válida" in html


def test_serie_mensal_sem_buracos_nem_para_tipo_raro():
    env = construir(RAW)
    por = {}
    for r in env.dados:
        if r["recorte"] == "mensal":
            por.setdefault(r["grupo"], []).append((r["ano"], r["mes"]))
    ref = por["roubos"]
    assert all(v == ref for v in por.values())
    assert len(ref) == len(set(ref))


def test_raw_so_tem_grupos_conhecidos_e_detalhe_so_para_patrimonio():
    import csv

    from scripts.seguranca_grupos import GRUPOS, GRUPOS_DETALHADOS

    for pasta in RAW.iterdir():
        if not pasta.is_dir():
            continue
        for tabela in ("mensal", "hora", "bairro", "conduta"):
            with (pasta / f"{tabela}.csv").open(encoding="utf-8") as f:
                grupos = {r["grupo"] for r in csv.DictReader(f, delimiter=";")}
            assert grupos <= set(GRUPOS), (pasta, tabela, grupos)
            if tabela != "mensal":
                assert grupos <= set(GRUPOS_DETALHADOS), (pasta, tabela, grupos)


def test_raw_sem_coluna_de_natureza_fina():
    for arq in RAW.rglob("*.csv"):
        assert "natureza" not in arq.read_text(encoding="utf-8").splitlines()[0], arq


def test_data_de_acesso_no_futuro_e_rejeitada(tmp_path):
    import datetime as dt

    import pytest

    from scripts import fetch_ssp

    with pytest.raises(ValueError, match="futuro"):
        fetch_ssp.coletar(dt.date.today() + dt.timedelta(days=1), tmp_path)
