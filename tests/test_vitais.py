import json
from datetime import date

import pytest

from scripts import build_vitais, fetch_vitais
from scripts.contexto_panorama import contexto_panorama

HOJE = date(2026, 10, 11)


def _do(causa="I219", idade="470", tipo="2"):
    return {"TIPOBITO": tipo, "CAUSABAS": causa, "IDADE": idade}


def _dn(parto="1", gest="5", peso="3200", mae="28", cons="4"):
    return {"PARTO": parto, "GESTACAO": gest, "PESO": peso, "IDADEMAE": mae, "CONSULTAS": cons}


def _mapa(linhas):
    return {(l["bloco"], l["categoria"]): l["n"] for l in linhas}


def test_idade_e_faixas():
    assert fetch_vitais.idade_anos("470") == 70 and fetch_vitais.idade_anos("505") == 105
    assert fetch_vitais.idade_anos("215") == 0 and fetch_vitais.idade_anos("999") is None and fetch_vitais.idade_anos("x") is None
    assert fetch_vitais.faixa_etaria(0) == "Menos de 1 ano" and fetch_vitais.faixa_etaria(59) == "30 a 59 anos" and fetch_vitais.faixa_etaria(100) == "80 anos ou mais"


def test_obitos_fetais_ficam_fora_e_causas_externas_sao_agrupadas():
    reg = [_do()] * 6 + [_do("X700", "425")] * 5 + [_do("X950", "430")] * 5 + [_do("V892", "428")] * 5 + [_do("P220", "201")] * 5 + [_do(tipo="1")] * 9
    m = _mapa(fetch_vitais.agregar_obitos(reg, 2024))
    assert m[("obito_total", "")] == 26
    assert m[("obito_externa", "Suicídios")] == 5 and m[("obito_externa", "Homicídios")] == 5 and m[("obito_externa", "Acidentes de transporte")] == 5
    assert m[("obito_infantil", "")] == 5 and m[("obito_faixa", "Menos de 1 ano")] == 5


def test_celulas_pequenas_somem_mas_total_fica():
    m = _mapa(fetch_vitais.agregar_obitos([_do("J189")] * 2, 2024))
    assert m == {("obito_total", ""): 2}


def test_nascimentos_ignoram_valores_invalidos_no_denominador():
    reg = [_dn()] * 6 + [_dn(parto="2", gest="3", peso="2000", mae="17", cons="1")] * 5 + [_dn(parto="9", gest="9", peso="0", mae="99", cons="9")] * 5
    m = _mapa(fetch_vitais.agregar_nascimentos(reg, 2024))
    assert m[("nasc_total", "")] == 16 and m[("nasc_parto_valido", "")] == 11 and m[("nasc_cesarea", "")] == 5
    assert m[("nasc_prematuro", "")] == 5 and m[("nasc_baixo_peso", "")] == 5 and m[("nasc_mae_ate19", "")] == 5
    assert ("nasc_peso_valido", "") in m and m[("nasc_peso_valido", "")] == 11


def _coletar(tmp, anos=("2022", "2023", "2024"), chamadas=None):
    listar = lambda pasta: [f"{'DO' if 'SIM' in pasta else 'DN'}SP{a}.dbc" for a in anos]

    def baixar(caminho):
        if chamadas is not None:
            chamadas.append(caminho)
        return (b"DO" if "/DO" in caminho else b"DN"), "h"

    ler = lambda dados, filtro: iter([_do()] * 6 if dados == b"DO" else [_dn()] * 6)
    return fetch_vitais.coletar(HOJE, tmp, listar, baixar, ler)


def test_coleta_incremental_so_refaz_o_ultimo_ano(tmp_path):
    assert _coletar(tmp_path) == [2022, 2023, 2024]
    chamadas = []
    assert _coletar(tmp_path, chamadas=chamadas) == [2024]
    assert len(chamadas) == 2
    man = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))
    assert man["ultimo"] == 2024 and set(man["anos"]) == {"2022", "2023", "2024"}


def test_coleta_aborta_com_poucos_anos_ou_fonte_parada(tmp_path):
    with pytest.raises(ValueError, match="menos anos"):
        _coletar(tmp_path, anos=("2023", "2024"))
    with pytest.raises(ValueError, match="parada"):
        _coletar(tmp_path, anos=("2015", "2016", "2017"))


def test_build_e_contexto(tmp_path):
    _coletar(tmp_path)
    env = build_vitais.construir(tmp_path)
    assert env.qualidade.flag.value == "real"
    ctx = contexto_panorama(env.model_dump(mode="json"))
    assert ctx["ano_atual"] == 2024 and ctx["obitos"] == 6 and ctx["nascidos"] == 6
    assert ctx["causas"][0]["nome"] == "Doenças do coração e da circulação"
    (tmp_path / "indicadores.csv").write_text("ano;bloco;categoria;n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        build_vitais.construir(tmp_path)


def test_pagina_do_panorama_renderizada(tmp_path):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "scripts.render", "--saida", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    html = (tmp_path / "panorama" / "index.html").read_text(encoding="utf-8")
    assert "Grupos de causas" in html and "Partos cesáreos" in html


def test_variacao_grande_do_ano_recente_aborta(tmp_path):
    _coletar(tmp_path)
    listar = lambda pasta: [f"{'DO' if 'SIM' in pasta else 'DN'}SP{a}.dbc" for a in ("2022", "2023", "2024")]
    with pytest.raises(ValueError, match="entre coletas"):
        fetch_vitais.coletar(HOJE, tmp_path, listar, lambda c: (b"DO" if "/DO" in c else b"DN", "h"), lambda d, f: iter([_do()] * 30 if d == b"DO" else [_dn()] * 6))


def test_numerador_suprimido_nao_vira_zero_por_cento():
    env = {"dados": [{"recorte": "indicador", "ano": 2024, "bloco": b, "categoria": c, "n": n} for b, c, n in
                     [("obito_total", "", 10), ("nasc_total", "", 100), ("nasc_parto_valido", "", 100)]]}
    cesarea = contexto_panorama(env)["nascimentos"][0]["por_ano"][0]["pct"]
    assert cesarea is None
