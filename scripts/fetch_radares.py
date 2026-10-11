"""Lista oficial de radares da Semob de Sorocaba (página pública de locais de operação)."""

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
DESTINO = RAIZ / "data" / "raw" / "radares"
PAGINA = "https://www.semobsorocaba.com.br/radares/locais-operacao"
URL = "https://www.semobsorocaba.com.br/views/radares/tools/lista-radares.php"  # o mesmo endereço que a página chama
HOST = "www.semobsorocaba.com.br"
MAX_PAGINAS = 60
LIMITE_BYTES = 1024 * 1024
CAMPOS = ["ponto", "local", "tipo", "velocidade_kmh"]


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host != HOST:
        raise ValueError(f"requisição fora de https://{HOST}: {r.url}")


def pagina(c: httpx.Client, n: int) -> str:
    for t in range(3):
        try:
            with c.stream("POST", URL, data={"pag": n, "tipo": "tabela"}) as r:
                r.raise_for_status()
                corpo = bytearray()
                for pedaco in r.iter_bytes(64 * 1024):
                    corpo += pedaco
                    if len(corpo) > LIMITE_BYTES:
                        raise ValueError("página acima do limite esperado")
                return bytes(corpo).decode("utf-8", "replace")
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if t == 2 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500):
                raise
            time.sleep(2**t * 2)
    raise RuntimeError("inalcançável")


def linhas(fragmento: str) -> list[dict[str, str]]:
    saida = []
    for tr in re.findall(r"<tr.*?</tr>", fragmento, flags=re.S):
        cel = [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<td.*?</td>", tr, flags=re.S)]
        if len(cel) >= 5 and re.fullmatch(r"\d+", cel[0]):
            m = re.search(r"(\d+)\s*Km/h", cel[4])
            if not m:
                raise ValueError(f"velocidade não reconhecida: {cel[4]!r}")
            # O número de série do equipamento não é gravado: não é necessário e não agrega ao painel.
            saida.append({"ponto": cel[1], "local": cel[2], "tipo": cel[3], "velocidade_kmh": m.group(1)})
    return saida


def coletar(acesso_em: date, destino: Path = DESTINO) -> bool:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    todos: list[dict[str, str]] = []
    total_declarado = None
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 SorocabaEmDados/1.0"}, event_hooks={"request": [so_host_confiavel]}) as c:
        for n in range(1, MAX_PAGINAS + 1):
            frag = pagina(c, n)
            if total_declarado is None:
                m = re.search(r"Encontrado\(s\)\s*(\d+)\s*radar", re.sub(r"<[^>]+>", " ", frag))
                total_declarado = int(m.group(1)) if m else None
            novas = linhas(frag)
            if not novas or all(r in todos for r in novas):
                break
            todos += novas
    # A página declara 172 radares, mas a paginação (16 páginas de 10) só lista 160; o manifesto guarda os dois números.
    if not todos or (total_declarado is not None and len(todos) > total_declarado):
        raise ValueError(f"contagem incoerente: declarados {total_declarado}, coletados {len(todos)}")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CAMPOS, delimiter=";", lineterminator="\n")
    w.writeheader()
    w.writerows(sorted(todos, key=lambda r: (r["ponto"], r["local"])))
    texto = buf.getvalue()
    sha = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    destino.mkdir(parents=True, exist_ok=True)
    arq = destino / "manifesto.json"
    antigo = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    novo = {"url": PAGINA, "n_radares": len(todos), "n_declarado_pela_pagina": total_declarado, "sha256_csv": sha, "coletado_em": antigo.get("coletado_em", acesso_em.isoformat()), "verificado_em": acesso_em.isoformat()}
    mudou = antigo.get("sha256_csv") != sha
    if mudou:
        (destino / "radares.csv").write_text(texto, encoding="utf-8")
        novo["coletado_em"] = acesso_em.isoformat()
    arq.write_text(json.dumps(novo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return mudou


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    args = p.parse_args()
    print("atualizado" if coletar(args.acesso_em) else "sem mudança")


if __name__ == "__main__":
    main()
