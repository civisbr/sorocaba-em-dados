import argparse

import polars as pl
import pytest

from scripts import fetch_caged as f


def test_competencias_atravessa_ano():
    assert f.competencias("202411", "202502") == ["202411", "202412", "202501", "202502"]


@pytest.mark.parametrize("ruim", ["2024-1", "202413", "202400", "abc", "20241"])
def test_competencia_invalida(ruim):
    with pytest.raises(argparse.ArgumentTypeError):
        f.competencia_valida(ruim)


def _txt(tmp_path, cabecalho, linhas):
    txt = tmp_path / "x.txt"
    txt.write_text("\n".join([cabecalho, *linhas]) + "\n", encoding="utf-8")
    return txt


def test_filtrar_so_sorocaba(tmp_path):
    cab = "competênciamov;município;seção;saldomovimentação"
    txt = _txt(tmp_path, cab, ["202608;355220;G;1", "202608;355030;G;-1", "202608;355220;C;-1"])
    n = f.filtrar(txt, tmp_path / "out.csv")
    assert n == 2
    assert pl.read_csv(tmp_path / "out.csv", separator=";", infer_schema=False)["município"].unique().to_list() == ["355220"]


def test_filtrar_recusa_layout_diferente(tmp_path):
    txt = _txt(tmp_path, "competênciamov;cidade;seção;saldomovimentação", ["202608;355220;G;1"])
    with pytest.raises(ValueError, match="layout mudou"):
        f.filtrar(txt, tmp_path / "out.csv")
