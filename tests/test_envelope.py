from datetime import date

import pytest
from pydantic import ValidationError

from schemas.envelope import Envelope


def _base(**sobre):
    env = {
        "painel": "teste",
        "fonte": {"nome": "n", "url": "https://exemplo.test/dados", "licenca": "l", "acesso_em": "2026-10-11"},
        "referencia": {"inicio": "2026-01-01", "fim": "2026-01-31", "granularidade": "mensal"},
        "cobertura": {"municipio": "Sorocaba", "ibge": "3552205", "uf": "SP"},
        "qualidade": {"flag": "real", "n_registros": 1},
        "dados": [{"a": 1}],
    }
    env.update(sobre)
    return env


def test_envelope_valido():
    assert Envelope(**_base()).referencia.fim == date(2026, 1, 31)


def test_sem_data_de_referencia_quebra():
    env = _base()
    del env["referencia"]
    with pytest.raises(ValidationError):
        Envelope(**env)


def test_flag_invalido_quebra():
    with pytest.raises(ValidationError):
        Envelope(**_base(qualidade={"flag": "chute", "n_registros": 1}))


def test_registro_aninhado_quebra():
    with pytest.raises(ValidationError):
        Envelope(**_base(dados=[{"a": {"b": 1}}]))


def test_n_registros_diverge_quebra():
    with pytest.raises(ValidationError):
        Envelope(**_base(qualidade={"flag": "real", "n_registros": 5}))


def test_fim_antes_do_inicio_quebra():
    with pytest.raises(ValidationError):
        Envelope(**_base(referencia={"inicio": "2026-02-01", "fim": "2026-01-01", "granularidade": "mensal"}))


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "u"])
def test_url_de_fonte_com_esquema_proibido_quebra(url):
    env = _base()
    env["fonte"] = {**env["fonte"], "url": url}
    with pytest.raises(ValidationError):
        Envelope(**env)
