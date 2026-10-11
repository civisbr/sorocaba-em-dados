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
