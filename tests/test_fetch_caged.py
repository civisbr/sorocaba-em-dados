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


def test_filtrar_agrega_so_sorocaba_sem_registro_individual(tmp_path):
    cab = "competênciamov;município;seção;saldomovimentação;idade"
    txt = _txt(tmp_path, cab, ["202608;355220;G;1;30", "202608;355220;G;1;41", "202608;355030;G;-1;22", "202608;355220;C;-1;50"])
    n = f.filtrar(txt, tmp_path / "out.csv")
    assert n == 3
    saida = pl.read_csv(tmp_path / "out.csv", separator=";", infer_schema=False)
    assert saida.columns == ["competênciamov", "seção", "saldomovimentação", "n"]
    assert dict(zip(saida["seção"], saida["n"])) == {"C": "1", "G": "2"}


def test_filtrar_recusa_layout_diferente(tmp_path):
    txt = _txt(tmp_path, "competênciamov;cidade;seção;saldomovimentação", ["202608;355220;G;1"])
    with pytest.raises(ValueError, match="layout mudou"):
        f.filtrar(txt, tmp_path / "out.csv")


def test_competencias_atras_atravessa_ano():
    assert f.competencias_atras("202602", 3) == ["202512", "202601", "202602"]
    assert len(f.competencias_atras("202608", 24)) == 24


def _manifesto(pasta, hash_agregado):
    import json
    arquivos = {t: {"sha256_origem": "o", "bytes_origem": 1, "linhas": 1, "sha256_agregado": hash_agregado} for t in f.TIPOS}
    (pasta / "manifesto.json").write_text(json.dumps({"competencia": pasta.name, "acesso_em": "2026-10-11", "arquivos": arquivos}), encoding="utf-8")


def test_completa_exige_hash_do_agregado(tmp_path):
    pasta = tmp_path / "202608"
    pasta.mkdir()
    for t in f.TIPOS:
        (pasta / f"{t}.csv").write_text("competênciamov;seção;saldomovimentação;n\n", encoding="utf-8")
    _manifesto(pasta, f.sha256(pasta / "MOV.csv"))
    assert f.completa(pasta)
    (pasta / "FOR.csv").write_text("adulterado\n", encoding="utf-8")
    assert not f.completa(pasta)


def test_hash_de_origem_divergente_aborta_sem_sobrescrever(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "RAW", tmp_path / "caged")
    pasta = tmp_path / "caged" / "202608"
    pasta.mkdir(parents=True)
    _manifesto(pasta, "h")

    def falso_baixar(remoto, destino, tentativas=4):
        destino.write_bytes(b"conteudo diferente do original")

    def falso_extrair(sete_z, nome_txt, destino):
        txt = destino / nome_txt
        txt.write_text("competênciamov;município;seção;saldomovimentação\n202608;355220;G;1\n", encoding="utf-8")
        return txt

    monkeypatch.setattr(f, "baixar", falso_baixar)
    monkeypatch.setattr(f, "extrair_membro_unico", falso_extrair)
    with pytest.raises(ValueError, match="hash da origem diverge"):
        f.fetch_competencia("202608", "2026-10-12")
    assert not (pasta / "MOV.csv").exists()


def test_ultima_competencia_cai_para_ano_anterior_se_o_novo_estiver_vazio(monkeypatch):
    class FTPFalso:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def nlst(self, caminho):
            if caminho.endswith("CAGED"):
                return [f"{caminho}/2025", f"{caminho}/2026", f"{caminho}/Leia-me.txt"]
            return [] if caminho.endswith("2026") else [f"{caminho}/202511", f"{caminho}/202512"]

    monkeypatch.setattr(f, "conectar", lambda: FTPFalso())
    assert f.ultima_competencia() == "202512"
