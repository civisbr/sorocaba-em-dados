import json
from datetime import date

import httpx
import pytest

from scripts import build_inmetro, fetch_inmetro
from scripts.contexto_inmetro import contexto_inmetro


def _medidor(local="AV. X, 10", municipio="SOROCABA", uf="SP", validade="01/01/2027", resultado="Aprovado"):
    return {"SiglaUf": uf, "Municipio": municipio, "LocalVerificacao": local, "DataUltimaVerificacao": "01/01/2026", "DataValidade": validade, "UltimoResultado": resultado, "TipoMedidor": "Fixo",
            "Faixas": [{"NumeroFaixa": "1", "NumeroInmetro": "111", "NumeroSerie": "S1", "Sentido": "N", "VelocidadeNominal": "60"}], "Historico": [{"NumeroCertificado": "9", "DataLaudo": "01/01/2026"}]}


def _coletar(tmp_path, itens):
    t = httpx.MockTransport(lambda req: httpx.Response(200, json=itens))
    return fetch_inmetro.coletar(date(2026, 10, 11), tmp_path, t)


def test_filtra_so_sorocaba_de_sp(tmp_path):
    itens = [_medidor(local=f"L{i}") for i in range(25)] + [_medidor(municipio="VOTORANTIM"), _medidor(uf="MG")]
    assert _coletar(tmp_path, itens) == 25


def test_poucos_medidores_aborta(tmp_path):
    with pytest.raises(ValueError, match="poucos"):
        _coletar(tmp_path, [_medidor()])


def test_formato_inesperado_e_host_errado():
    with pytest.raises(ValueError):
        fetch_inmetro.filtrar({"a": 1})
    with pytest.raises(ValueError):
        fetch_inmetro.so_host_confiavel(httpx.Request("GET", "https://exemplo.com/x"))


def test_classificacao_vencida_reprovada_e_em_dia(tmp_path):
    itens = [_medidor(local=f"L{i}") for i in range(20)] + [_medidor(local="VENCIDO", validade="01/06/2026"), _medidor(local="REPROVADO", resultado="Reprovado")]
    _coletar(tmp_path, itens)
    env = build_inmetro.construir(tmp_path).model_dump(mode="json")
    ctx = contexto_inmetro(env, date(2026, 10, 11))
    por = {m["local"]: m for m in ctx["inm_invalidos"]}
    assert set(por) == {"VENCIDO", "REPROVADO"} and por["VENCIDO"]["situacao"] == "vencida" and por["VENCIDO"]["dias_vencida"] == 132
    assert len(ctx["inm_validos"]) == 20 and ctx["inm_total"] == 22
    assert contexto_inmetro(env, date(2028, 1, 1))["inm_invalidos"].__len__() == 22  # com o tempo, tudo vence


def test_hash_adulterado_e_recusado(tmp_path):
    _coletar(tmp_path, [_medidor(local=f"L{i}") for i in range(25)])
    (tmp_path / "medidores_sorocaba.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        build_inmetro.construir(tmp_path)


def test_pagina_de_transito_tem_secao_e_link_oficial(tmp_path):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "scripts.render", "--saida", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    html = (tmp_path / "transito" / "index.html").read_text(encoding="utf-8")
    assert "Os radares estão com a verificação em dia?" in html and "https://servicos.rbmlq.gov.br/Instrumento" in html and "não se uma multa é válida" in html
