"""Download de arquivos do FTP público do DATASUS (só leitura, sem credenciais)."""

from __future__ import annotations

import ftplib
import hashlib
import time

HOST = "ftp.datasus.gov.br"
BASE = "/dissemin/publicos"
LIMITE_BYTES = 200 * 1024 * 1024


def _tentar(fn, tentativas: int = 3):
    for t in range(tentativas):
        try:
            return fn()
        except (ftplib.Error, OSError, EOFError) as e:
            if t == tentativas - 1:
                raise RuntimeError(f"falha no FTP do DATASUS ({type(e).__name__})") from None
            time.sleep(2 ** t * 2)


def listar(pasta: str) -> list[str]:
    def _go() -> list[str]:
        with ftplib.FTP(HOST, timeout=60) as f:
            f.login()
            return f.nlst(f"{BASE}/{pasta}")
    return [n.rsplit("/", 1)[-1] for n in _tentar(_go)]


def baixar(caminho: str, limite: int = LIMITE_BYTES) -> tuple[bytes, str]:
    """Devolve (conteúdo, sha256). Aborta se passar do limite."""
    def _go() -> bytes:
        buf = bytearray()

        def _recebe(b: bytes) -> None:
            buf.extend(b)
            if len(buf) > limite:
                raise ValueError("arquivo acima do limite esperado")

        with ftplib.FTP(HOST, timeout=120) as f:
            f.login()
            f.set_pasv(True)
            f.retrbinary(f"RETR {BASE}/{caminho}", _recebe)
        return bytes(buf)

    dados = _tentar(_go)
    return dados, hashlib.sha256(dados).hexdigest()
