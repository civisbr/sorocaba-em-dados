"""Baixa os microdados do Novo CAGED e guarda só as linhas de Sorocaba.

O arquivo nacional de uma competência tem ~450 MB descompactado; manter todos os meses da
janela inviabiliza CI e disco. O filtro por município é a única operação aplicada ao bruto,
e o SHA-256 do .7z de origem fica no manifesto para auditoria.

O MTE publica por FTP sem TLS e sem hash oficial. O SHA-256 registrado atesta o que foi
recebido, não a autenticidade; por isso um hash já gravado é fixado e divergência aborta.
"""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import json
import re
import shutil
import tempfile
import time
from pathlib import Path

import polars as pl
import py7zr

HOST = "ftp.mtps.gov.br"
BASE = "/pdet/microdados/NOVO CAGED"
CODIGO_SOROCABA = "355220"
TIPOS = ("MOV", "FOR", "EXC")
RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "caged"
LIMITE_DESCOMPACTADO = 2 * 1024**3
COLUNAS_ESPERADAS = {"competênciamov", "município", "seção", "saldomovimentação"}
PADRAO_COMPETENCIA = re.compile(r"\d{4}(0[1-9]|1[0-2])")


def competencia_valida(valor: str) -> str:
    if not PADRAO_COMPETENCIA.fullmatch(valor):
        raise argparse.ArgumentTypeError(f"competência inválida: {valor!r} (esperado AAAAMM)")
    return valor


def competencias(inicio: str, fim: str) -> list[str]:
    ano, mes = int(inicio[:4]), int(inicio[4:])
    saida = []
    while f"{ano}{mes:02d}" <= fim:
        saida.append(f"{ano}{mes:02d}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return saida


def conectar() -> ftplib.FTP:
    ftp = ftplib.FTP(HOST, timeout=120)
    ftp.login()
    return ftp


def baixar(remoto: str, destino: Path, tentativas: int = 4) -> None:
    """Cada tentativa abre conexão nova: após timeout a conexão anterior fica inutilizável."""
    for tentativa in range(tentativas):
        try:
            with conectar() as ftp:
                esperado = ftp.size(remoto)
                with destino.open("wb") as f:
                    ftp.retrbinary(f"RETR {remoto}", f.write)
            if esperado is not None and destino.stat().st_size != esperado:
                raise ftplib.Error(f"download truncado: {destino.stat().st_size} != {esperado}")
            return
        except ftplib.error_perm:
            raise
        except (*ftplib.all_errors, EOFError):
            if tentativa == tentativas - 1:
                raise
            time.sleep(2**tentativa * 5)


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def extrair_membro_unico(sete_z: Path, nome_txt: str, destino: Path) -> Path:
    """Extrai só o .txt esperado, recusando membros extras, caminhos e tamanho abusivo."""
    with py7zr.SevenZipFile(sete_z) as z:
        membros = z.list()
        if [m.filename for m in membros] != [nome_txt]:
            raise ValueError(f"{sete_z.name}: conteúdo inesperado {[m.filename for m in membros]}")
        if membros[0].is_symlink or membros[0].uncompressed > LIMITE_DESCOMPACTADO:
            raise ValueError(f"{sete_z.name}: membro recusado (symlink ou tamanho)")
        z.extract(path=destino, targets=[nome_txt])
    return destino / nome_txt


def filtrar(txt: Path, destino: Path) -> int:
    lazy = pl.scan_csv(txt, separator=";", infer_schema=False)
    faltando = COLUNAS_ESPERADAS - set(lazy.collect_schema().names())
    if faltando:
        raise ValueError(f"{txt.name}: layout mudou, colunas ausentes {sorted(faltando)}")
    df = lazy.filter(pl.col("município") == CODIGO_SOROCABA).collect(engine="streaming")
    df.write_csv(destino, separator=";")
    return df.height


def fetch_competencia(comp: str, acesso_em: str) -> None:
    pasta = RAW / comp
    if (pasta / "manifesto.json").exists():
        return
    arquivos = {}
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        saida = tmp / "saida"
        saida.mkdir()
        for tipo in TIPOS:
            nome = f"CAGED{tipo}{comp}"
            sete_z = tmp / f"{nome}.7z"
            baixar(f"{BASE}/{comp[:4]}/{comp}/{nome}.7z", sete_z)
            hash_origem = sha256(sete_z)
            txt = extrair_membro_unico(sete_z, f"{nome}.txt", tmp)
            n = filtrar(txt, saida / f"{tipo}.csv")
            if tipo == "MOV" and n == 0:
                raise ValueError(f"{nome}: nenhuma linha de Sorocaba, recusando gravar manifesto")
            arquivos[tipo] = {"sha256_origem": hash_origem, "bytes_origem": sete_z.stat().st_size, "linhas": n}
            sete_z.unlink()
            txt.unlink()
        (saida / "manifesto.json").write_text(
            json.dumps({"competencia": comp, "acesso_em": acesso_em, "arquivos": arquivos}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        pasta.parent.mkdir(parents=True, exist_ok=True)
        # Manifesto é o último arquivo escrito e a pasta só aparece completa.
        shutil.move(str(saida), str(pasta))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--inicio", required=True, type=competencia_valida, help="AAAAMM")
    p.add_argument("--fim", required=True, type=competencia_valida, help="AAAAMM")
    p.add_argument("--acesso-em", required=True, help="AAAA-MM-DD, registrado no manifesto")
    args = p.parse_args()
    if args.inicio > args.fim:
        p.error("--inicio posterior a --fim")

    for comp in competencias(args.inicio, args.fim):
        print(f"{comp}...", flush=True)
        fetch_competencia(comp, args.acesso_em)


if __name__ == "__main__":
    main()
