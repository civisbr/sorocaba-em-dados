"""Baixa os arquivos "últimas 4 semanas" do LPC/ANP e guarda só as linhas de Sorocaba.

Cada execução grava um instantâneo em data/raw/anp/<AAAAMMDD>/. O histórico longo nasce da
acumulação desses instantâneos: a ANP só publica as 4 semanas mais recentes nesse formato.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import time
from datetime import date
from pathlib import Path

import httpx

BASE = "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/qus/"
ARQUIVOS = ("ultimas-4-semanas-gasolina-etanol.csv", "ultimas-4-semanas-diesel-gnv.csv")
HOST = "www.gov.br"
# gov.br responde 403 a clientes sem User-Agent de navegador.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) SorocabaEmDados/1.0"
LIMITE_BYTES = 40 * 1024 * 1024
RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "anp"
COLUNAS = [
    "Regiao - Sigla", "Estado - Sigla", "Municipio", "Revenda", "CNPJ da Revenda", "Nome da Rua",
    "Numero Rua", "Complemento", "Bairro", "Cep", "Produto", "Data da Coleta", "Valor de Venda",
    "Valor de Compra", "Unidade de Medida", "Bandeira",
]
MUNICIPIO, UF = "SOROCABA", "SP"


def so_host_confiavel(resposta: httpx.Response) -> None:
    if resposta.url.scheme != "https" or resposta.url.host != HOST:
        raise ValueError(f"resposta fora de https://{HOST}: {resposta.url}")


def baixar(nome: str, tentativas: int = 4) -> bytes:
    url = BASE + nome
    for tentativa in range(tentativas):
        try:
            with httpx.Client(
                headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True,
                event_hooks={"response": [so_host_confiavel]},
            ) as c, c.stream("GET", url) as r:
                r.raise_for_status()
                corpo = bytearray()
                for pedaco in r.iter_bytes(1 << 20):
                    corpo += pedaco
                    if len(corpo) > LIMITE_BYTES:
                        raise ValueError(f"{nome} acima do limite esperado")
                return bytes(corpo)
        except (httpx.TransportError, httpx.HTTPStatusError) as erro:
            # 4xx é erro permanente (URL mudou, bloqueio): repetir só atrasa o alerta.
            permanente = isinstance(erro, httpx.HTTPStatusError) and erro.response.status_code < 500
            if permanente or tentativa == tentativas - 1:
                raise
            time.sleep(2**tentativa * 3)
    raise RuntimeError("inalcançável")


def filtrar(corpo: bytes) -> str:
    """Valida o cabeçalho e devolve o CSV só com Sorocaba/SP (mesmo separador e colunas)."""
    leitor = csv.reader(io.StringIO(corpo.decode("utf-8-sig")), delimiter=";")
    cabecalho = next(leitor)
    if cabecalho != COLUNAS:
        raise ValueError(f"colunas inesperadas no arquivo da ANP: {cabecalho}")
    i_mun, i_uf = COLUNAS.index("Municipio"), COLUNAS.index("Estado - Sigla")
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\n")
    escritor.writerow(COLUNAS)
    for linha in leitor:
        if len(linha) == len(COLUNAS) and linha[i_mun].strip().upper() == MUNICIPIO and linha[i_uf] == UF:
            escritor.writerow(linha)
    return saida.getvalue()


def ultima_coleta(csv_texto: str) -> date | None:
    datas = []
    for linha in csv.DictReader(io.StringIO(csv_texto), delimiter=";"):
        d, m, a = linha["Data da Coleta"].split("/")
        datas.append(date(int(a), int(m), int(d)))
    return max(datas) if datas else None


def coletar(acesso_em: date, destino: Path = DESTINO) -> Path:
    pedacos: dict[str, tuple[str, str]] = {}
    for nome in ARQUIVOS:
        corpo = baixar(nome)
        pedacos[nome] = (hashlib.sha256(corpo).hexdigest(), filtrar(corpo))
    ultima = max((d for d in (ultima_coleta(t) for _, t in pedacos.values()) if d), default=None)
    if ultima is None:
        raise ValueError("nenhuma linha de Sorocaba nos arquivos da ANP")

    pasta = destino / ultima.strftime("%Y%m%d")
    if (pasta / "manifesto.json").exists():
        antigo = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))["arquivos"]
        novo = {n.removeprefix("ultimas-4-semanas-"): hashlib.sha256(t.encode("utf-8")).hexdigest() for n, (_, t) in pedacos.items()}
        # Mesmo conteúdo filtrado: manter o instantâneo evita commit só por mudar a data de acesso.
        if {n: a["sha256_filtrado"] for n, a in antigo.items()} == novo:
            return pasta
    tmp = destino / f".tmp-{ultima:%Y%m%d}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    manifesto = {"acesso_em": acesso_em.isoformat(), "ultima_coleta": ultima.isoformat(), "arquivos": {}}
    for nome, (sha_origem, texto) in pedacos.items():
        local = nome.removeprefix("ultimas-4-semanas-")
        (tmp / local).write_text(texto, encoding="utf-8")
        manifesto["arquivos"][local] = {
            "url": BASE + nome,
            "sha256_origem": sha_origem,
            "sha256_filtrado": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        }
    (tmp / "manifesto.json").write_text(json.dumps(manifesto, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.rmtree(pasta, ignore_errors=True)
    tmp.rename(pasta)
    return pasta


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat, help="AAAA-MM-DD")
    args = p.parse_args()
    print(coletar(args.acesso_em))


if __name__ == "__main__":
    main()
