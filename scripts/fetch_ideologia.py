"""Guarda a classificação ideológica dos partidos feita por especialistas (Bolognesi, Ribeiro, Codato e Silva, 2025).

Fonte: Opinião Pública, v. 31, doi 10.1590/1807-0191202531120, tabela com a média das notas dos
especialistas (0 = extrema esquerda, 10 = extrema direita) em 2018 e 2022 e a categoria final.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import time
from datetime import date
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "ideologia"
URL = "https://www.scielo.br/j/op/a/hv8GBg9hfCCZLwcWktfYhtC/?lang=pt"
DOI = "10.1590/1807-0191202531120"
HOST = "www.scielo.br"
LIMITE_BYTES = 5 * 1024 * 1024
CATEGORIAS = {"extrema esquerda", "esquerda", "centro-esquerda", "centro", "centro-direita", "direita", "extrema direita"}


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host != HOST:
        raise ValueError(f"requisição fora de https://{HOST}: {r.url}")


def baixar() -> bytes:
    for n in range(4):
        try:
            with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 SorocabaEmDados/1.0"}, event_hooks={"request": [so_host_confiavel]}) as c, c.stream("GET", URL) as r:
                r.raise_for_status()
                corpo = bytearray()
                for pedaco in r.iter_bytes(64 * 1024):
                    corpo += pedaco
                    if len(corpo) > LIMITE_BYTES:
                        raise ValueError("página acima do limite esperado")
                return bytes(corpo)
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if n == 3 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500):
                raise
            time.sleep(2**n * 2)
    raise RuntimeError("inalcançável")


def extrair(pagina: str) -> list[dict[str, str]]:
    tabelas = re.findall(r"<table.*?</table>", pagina, flags=re.S)
    if len(tabelas) != 1:
        raise ValueError(f"esperava 1 tabela na página, achei {len(tabelas)}")
    linhas = []
    for tr in re.findall(r"<tr.*?</tr>", tabelas[0], flags=re.S):
        cel = [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<t[dh].*?</t[dh]>", tr, flags=re.S)]
        if len(cel) == 9 and cel[0] != "Partido":
            partido, m18, m22, *_, ponderada, categoria = cel
            if categoria not in CATEGORIAS:
                raise ValueError(f"categoria desconhecida: {categoria!r}")
            linhas.append({"partido": partido, "media_2018": m18, "media_2022": m22, "media_ponderada": ponderada.replace(",", "."), "categoria": categoria})
    if len(linhas) < 25:
        raise ValueError(f"tabela com poucas linhas: {len(linhas)}")
    return linhas


def coletar(acesso_em: date, destino: Path = DESTINO) -> bool:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    corpo = baixar()
    linhas = extrair(corpo.decode("utf-8", "replace"))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(linhas[0]), delimiter=";", lineterminator="\n")
    w.writeheader()
    w.writerows(linhas)
    texto = buf.getvalue()
    destino.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    arq = destino / "manifesto.json"
    antigo = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    if antigo.get("sha256_csv") == sha:
        return False
    (destino / "classificacao_experts.csv").write_text(texto, encoding="utf-8")
    meta = {
        "fonte": "Bolognesi, Ribeiro, Codato e Silva (2025), Opinião Pública, v. 31", "doi": DOI, "url": URL,
        "survey": "classificação de especialistas, 2018 e 2022; 0 = extrema esquerda, 10 = extrema direita",
        "coletado_em": acesso_em.isoformat(), "sha256_csv": sha, "sha256_pagina": hashlib.sha256(corpo).hexdigest(),
    }
    arq.write_text(json.dumps(meta, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    args = p.parse_args()
    print("atualizado" if coletar(args.acesso_em) else "sem mudança")


if __name__ == "__main__":
    main()
