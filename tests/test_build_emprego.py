import json
import shutil
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from scripts.build_emprego import construir

FIXTURES = Path(__file__).parent / "fixtures" / "caged"
ACESSO = date(2026, 10, 11)


def _json(env) -> str:
    return json.dumps(env.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


def test_build_deterministico():
    assert _json(construir(FIXTURES, ACESSO, exigir_manifesto=False, janela_meses=2)) == _json(construir(FIXTURES, ACESSO, exigir_manifesto=False, janela_meses=2))


def test_saldo_confere_com_calculo_independente():
    env = construir(FIXTURES, ACESSO, exigir_manifesto=False, janela_meses=2)
    esperado: dict[str, int] = {}
    for pasta in FIXTURES.iterdir():
        for tipo, peso in (("MOV", 1), ("FOR", 1), ("EXC", -1)):
            df = pl.read_csv(pasta / f"{tipo}.csv", separator=";", infer_schema=False)
            for comp, saldo, n in df.select("competênciamov", "saldomovimentação", "n").iter_rows():
                esperado[comp] = esperado.get(comp, 0) + peso * int(saldo) * int(n)
    mensal = {r["competencia"]: r["saldo"] for r in env.dados if r["recorte"] == "mensal"}
    assert mensal == {c: esperado[c] for c in ("202607", "202608")}


def test_exclusao_reduz_saldo_de_admissao():
    env = construir(FIXTURES, ACESSO, exigir_manifesto=False, janela_meses=2)
    for r in env.dados:
        assert r["saldo"] == r["admissoes"] - r["desligamentos"]


def test_envelope_tem_proveniencia():
    env = construir(FIXTURES, ACESSO, exigir_manifesto=False, janela_meses=2)
    assert env.fonte.acesso_em == ACESSO
    assert env.cobertura.ibge == "3552205"
    assert env.qualidade.flag == "real"


def test_janela_incompleta_recusa_em_vez_de_fabricar_meses():
    with pytest.raises(ValueError, match="declarações ausentes"):
        construir(FIXTURES, ACESSO, exigir_manifesto=False)


def test_pasta_sem_manifesto_recusa(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "caged")
    with pytest.raises(FileNotFoundError, match="sem manifesto"):
        construir(tmp_path / "caged", ACESSO, janela_meses=2)


def test_pasta_estranha_nao_vira_ultima_competencia(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "caged")
    (tmp_path / "caged" / "tmp").mkdir()
    env = construir(tmp_path / "caged", ACESSO, exigir_manifesto=False, janela_meses=2)
    assert env.referencia.fim == date(2026, 8, 31)


def test_acesso_em_derivado_dos_manifestos(tmp_path):
    import json
    import shutil
    shutil.copytree(FIXTURES, tmp_path / "caged")
    for comp, data in (("202607", "2026-09-03"), ("202608", "2026-10-11")):
        arquivos = {t: {"sha256_origem": "x", "bytes_origem": 1, "linhas": 1, "sha256_agregado": "x"} for t in ("MOV", "FOR", "EXC")}
        (tmp_path / "caged" / comp / "manifesto.json").write_text(
            json.dumps({"competencia": comp, "acesso_em": data, "arquivos": arquivos}), encoding="utf-8"
        )
    env = construir(tmp_path / "caged", janela_meses=2)
    assert env.fonte.acesso_em == date(2026, 10, 11)
    assert any(n.startswith("SHA-256 dos manifestos") for n in env.qualidade.notas)
