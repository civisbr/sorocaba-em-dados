import json

from scripts.build_comparativo import RAIZ, SOROCABA, construir, posicao
from scripts.charts import linhas_posicao

RAW = RAIZ / "data/raw/comparativo"


def test_posicao_com_empate_divide_a_mesma_colocacao():
    v = {"a": 10.0, "b": 8.0, "c": 8.0, "d": 5.0}
    assert posicao(v, "a") == (1, 4, 0)
    assert posicao(v, "b") == (2, 4, 1) and posicao(v, "c") == (2, 4, 1)
    assert posicao(v, "d") == (4, 4, 0)
    assert posicao(v, "z") is None


def test_build_deterministico_e_sorocaba_em_todas_as_series():
    a, b = construir(RAW), construir(RAW)
    assert a.model_dump_json() == b.model_dump_json()
    inds = {r["indicador"] for r in a.dados if r["recorte"] == "posicao"}
    assert inds == {"populacao", "pib", "pib_per_capita", "ideb_anos_iniciais", "ideb_anos_finais"}


def test_posicoes_validas_e_coerentes():
    for r in construir(RAW).dados:
        if r["recorte"] == "posicao":
            assert 1 <= r["pos_sp"] <= r["n_sp"] <= r["n_br"]
            assert r["pos_sp"] <= r["pos_br"] and 1 <= r["pos_br"] <= r["n_br"]


def test_per_capita_so_nos_anos_com_populacao_do_mesmo_ano():
    env = construir(RAW)
    pop_anos = {r["ano"] for r in env.dados if r["recorte"] == "posicao" and r["indicador"] == "populacao"}
    for r in env.dados:
        if r["recorte"] == "posicao" and r["indicador"] == "pib_per_capita":
            assert r["ano"] in pop_anos


def test_vizinhos_incluem_sorocaba():
    env = construir(RAW)
    for ind in {r["indicador"] for r in env.dados}:
        viz = [r for r in env.dados if r["recorte"] == "vizinho" and r["indicador"] == ind]
        assert SOROCABA in {r["codigo"] for r in viz}


def test_grafico_de_posicao_inverte_eixo():
    g = linhas_posicao([(2000, 10), (2010, 50)])
    ys = [m["y"] for m in g["marcas"]]
    assert ys[0] < ys[1]  # posição menor (melhor) fica mais acima
    assert g["grade"][0]["valor"] <= 10 and g["grade"][-1]["valor"] >= 50


def test_raw_so_codigo_ano_valor():
    for nome in ("populacao.csv", "pib.csv", "ideb_anos_iniciais.csv", "ideb_anos_finais.csv"):
        cab = (RAW / nome).read_text(encoding="utf-8").splitlines()[0]
        assert cab.split(";")[:3] == ["ano", "codigo", "valor"]
    assert "sha256" in json.loads((RAW / "manifesto.json").read_text(encoding="utf-8"))["arquivos"]["pib.csv"]
