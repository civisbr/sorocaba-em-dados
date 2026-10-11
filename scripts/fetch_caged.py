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
    ftp = ftplib.FTP(HOST, timeout=120, encoding="latin-1")
    ftp.login()
    return ftp


def competencias_atras(fim: str, n: int) -> list[str]:
    ano, mes = int(fim[:4]), int(fim[4:])
    saida = []
    for _ in range(n):
        saida.append(f"{ano}{mes:02d}")
        ano, mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    return saida[::-1]


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
    """Grava só o agregado (competência, seção, saldo, n) de Sorocaba; nenhum registro individual."""
    lazy = pl.scan_csv(txt, separator=";", infer_schema=False)
    faltando = COLUNAS_ESPERADAS - set(lazy.collect_schema().names())
    if faltando:
        raise ValueError(f"{txt.name}: layout mudou, colunas ausentes {sorted(faltando)}")
    df = (
        lazy.filter(pl.col("município") == CODIGO_SOROCABA)
        .select("competênciamov", "seção", "saldomovimentação")
        .collect(engine="streaming")
    )
    agregar_para_csv(df, destino)
    return df.height


def agregar_para_csv(df: pl.DataFrame, destino: Path) -> None:
    (
        df.group_by("competênciamov", "seção", "saldomovimentação")
        .len(name="n")
        .sort("competênciamov", "seção", "saldomovimentação")
        .write_csv(destino, separator=";")
    )


def ultima_competencia() -> str:
    with conectar() as ftp:
        nomes = [n.rsplit("/", 1)[-1] for n in ftp.nlst(BASE)]
        for ano in sorted((n for n in nomes if re.fullmatch(r"\d{4}", n)), reverse=True):
            meses = [n.rsplit("/", 1)[-1] for n in ftp.nlst(f"{BASE}/{ano}")]
            validos = [m for m in meses if PADRAO_COMPETENCIA.fullmatch(m)]
            if validos:
                return max(validos)
    raise RuntimeError("nenhuma competência encontrada no FTP")


def completa(pasta: Path) -> bool:
    """CSV restaurado de cache só vale se o hash bate com o manifesto versionado."""
    if not all((pasta / n).exists() for n in ("manifesto.json", *(f"{t}.csv" for t in TIPOS))):
        return False
    arquivos = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))["arquivos"]
    return all(sha256(pasta / f"{t}.csv") == arquivos[t].get("sha256_agregado") for t in TIPOS)


def fetch_competencia(comp: str, acesso_em: str) -> None:
    pasta = RAW / comp
    if completa(pasta):
        return
    anterior = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8")) if (pasta / "manifesto.json").exists() else None
    arquivos = {}
    RAW.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=RAW, prefix=".tmp-") as tmp_str:
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
            arquivos[tipo] = {
                "sha256_origem": hash_origem,
                "bytes_origem": sete_z.stat().st_size,
                "linhas": n,
                "sha256_agregado": sha256(saida / f"{tipo}.csv"),
            }
            sete_z.unlink()
            txt.unlink()
        pasta.parent.mkdir(parents=True, exist_ok=True)
        if anterior is not None:
            # Manifesto versionado fixa o hash: origem mudando sem aviso aborta em vez de
            # republicar números diferentes sob o mesmo registro.
            for tipo, info in arquivos.items():
                if info["sha256_origem"] != anterior["arquivos"][tipo]["sha256_origem"]:
                    raise ValueError(f"{comp}/{tipo}: hash da origem diverge do manifesto versionado")
            for tipo in TIPOS:
                if arquivos[tipo]["sha256_agregado"] != anterior["arquivos"][tipo].get("sha256_agregado"):
                    raise ValueError(f"{comp}/{tipo}: agregado diverge do manifesto versionado")
                shutil.copy(saida / f"{tipo}.csv", pasta / f"{tipo}.csv")
            return
        (saida / "manifesto.json").write_text(
            json.dumps({"competencia": comp, "acesso_em": acesso_em, "arquivos": arquivos}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        if pasta.exists():
            shutil.rmtree(pasta)
        # tmp fica no mesmo sistema de arquivos de RAW, então o rename é atômico.
        saida.rename(pasta)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--inicio", type=competencia_valida, help="AAAAMM")
    p.add_argument("--fim", type=competencia_valida, help="AAAAMM")
    p.add_argument("--auto", type=int, metavar="N", help="últimas N competências publicadas no FTP")
    p.add_argument("--acesso-em", required=True, help="AAAA-MM-DD, registrado no manifesto")
    args = p.parse_args()
    if args.auto is not None and (args.inicio or args.fim):
        p.error("--auto não combina com --inicio/--fim")
    if args.auto is not None and args.auto < 1:
        p.error("--auto exige N >= 1")
    if args.auto:
        args.fim = ultima_competencia()
        args.inicio = competencias_atras(args.fim, args.auto)[0]
    elif not (args.inicio and args.fim):
        p.error("informe --inicio e --fim, ou --auto N")
    if args.inicio > args.fim:
        p.error("--inicio posterior a --fim")

    for comp in competencias(args.inicio, args.fim):
        print(f"{comp}...", flush=True)
        fetch_competencia(comp, args.acesso_em)


if __name__ == "__main__":
    main()
