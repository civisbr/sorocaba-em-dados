"""Baixa as planilhas anuais de ocorrências da SSP-SP e guarda só contagens agregadas de Sorocaba.

Cada linha da fonte é um boletim de ocorrência, com endereço, coordenadas e horário. Nada
disso é gravado: só contagens por mês, período do dia, bairro e tipo de furto, sem número de BO.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import tempfile
import time
from collections import Counter
from datetime import date, time as hora_t
from pathlib import Path

import httpx
from python_calamine import CalamineWorkbook

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "ssp"
URL = "https://www.ssp.sp.gov.br/assets/estatistica/transparencia/spDados/SPDadosCriminais_{ano}.xlsx"
HOST = "www.ssp.sp.gov.br"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) SorocabaEmDados/1.0"
IBGE = 3552205
ANOS_ATRAS = 4
LIMITE_BYTES = 400 * 1024 * 1024

# Os nomes das colunas mudaram entre as edições (ex.: COD IBGE / CD_IBGE).
ALIASES = {
    "ibge": ("COD IBGE", "CD_IBGE"),
    "natureza": ("NATUREZA_APURADA",),
    "mes": ("MES_ESTATISTICA",),
    "ano": ("ANO_ESTATISTICA",),
    "periodo": ("DESC_PERIODO", "DESCR_PERIODO"),
    "hora": ("HORA_OCORRENCIA_BO",),
    "bairro": ("BAIRRO",),
    "conduta": ("DESCR_CONDUTA",),
}
TABELAS = {
    "mensal": ["ano", "mes", "natureza", "n"],
    "hora": ["ano", "natureza", "hora", "n"],
    "bairro": ["ano", "natureza", "bairro", "n"],
    "conduta": ["ano", "natureza", "conduta", "n"],
}


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host != HOST:
        raise ValueError(f"requisição fora de https://{HOST}: {r.url}")


def cliente() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(60, read=600), follow_redirects=True,
        event_hooks={"request": [so_host_confiavel]},
    )


def com_tentativas(fn, tentativas: int = 4):
    for n in range(tentativas):
        try:
            return fn()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            permanente = isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500
            if permanente or n == tentativas - 1:
                raise
            time.sleep(2**n * 3)


def cabecalho(c: httpx.Client, ano: int) -> dict | None:
    r = c.head(URL.format(ano=ano))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return {"last_modified": r.headers.get("last-modified", ""), "bytes": int(r.headers.get("content-length", "0"))}


def baixar(c: httpx.Client, ano: int, destino: Path) -> str:
    h, total = hashlib.sha256(), 0
    with c.stream("GET", URL.format(ano=ano)) as r:
        r.raise_for_status()
        with destino.open("wb") as f:
            for pedaco in r.iter_bytes(1 << 20):
                total += len(pedaco)
                if total > LIMITE_BYTES:
                    raise ValueError(f"planilha de {ano} acima do limite esperado")
                h.update(pedaco)
                f.write(pedaco)
    return h.hexdigest()


def limpar(v) -> str:
    return " ".join(str(v).split()) if v is not None else ""


def indices(cab: list) -> dict[str, int] | None:
    nomes = [str(c).strip() for c in cab]
    achados = {}
    for chave, opcoes in ALIASES.items():
        i = next((nomes.index(o) for o in opcoes if o in nomes), None)
        if i is None:
            return None
        achados[chave] = i
    return achados


def codigo(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def agregar(caminho: Path, ano_arquivo: int) -> tuple[dict[str, Counter], dict]:
    """Percorre as abas de dados e conta ocorrências de Sorocaba por (ano, mês, natureza, ...)."""
    wb = CalamineWorkbook.from_path(str(caminho))
    cont = {t: Counter() for t in TABELAS}
    meta = {"abas": [], "registros_sorocaba": 0, "sem_natureza": 0, "fora_do_ano": 0}
    for nome in wb.sheet_names:
        linhas = wb.get_sheet_by_name(nome).to_python(skip_empty_area=False)
        idx = indices(linhas[0]) if linhas else None
        if idx is None:  # aba de dicionário de campos
            continue
        meta["abas"].append(nome)
        for r in linhas[1:]:
            if codigo(r[idx["ibge"]]) != IBGE:
                continue
            meta["registros_sorocaba"] += 1
            natureza = limpar(r[idx["natureza"]]).upper()
            if natureza in ("", "NULL"):
                meta["sem_natureza"] += 1
                continue
            ano, mes = codigo(r[idx["ano"]]), codigo(r[idx["mes"]])
            if ano != ano_arquivo or mes is None:
                meta["fora_do_ano"] += 1
                continue
            hora = r[idx["hora"]]
            if isinstance(hora, hora_t):
                rotulo_hora = f"{hora.hour:02d}"
            else:
                # Sem horário exato, vale a faixa do dia quando o boletim a informa.
                periodo = limpar(r[idx["periodo"]])
                rotulo_hora = "Sem informação" if periodo.upper() in ("", "NULL", "EM HORA INCERTA") else periodo
            bairro = limpar(r[idx["bairro"]]).upper()
            bairro = "SEM INFORMAÇÃO" if bairro in ("", "NULL") else bairro
            conduta = limpar(r[idx["conduta"]])
            conduta = "Sem informação" if conduta.upper() in ("", "NULL") else conduta
            cont["mensal"][(ano, mes, natureza)] += 1
            cont["hora"][(ano, natureza, rotulo_hora)] += 1
            cont["bairro"][(ano, natureza, bairro)] += 1
            if natureza.startswith("FURTO"):
                cont["conduta"][(ano, natureza, conduta)] += 1
        del linhas
    return cont, meta


def csv_texto(campos: list[str], contagem: Counter) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(campos)
    for chave in sorted(contagem):
        w.writerow([*chave, contagem[chave]])
    return buf.getvalue()


def coletar(acesso_em: date, destino: Path = DESTINO) -> list[int]:
    destino.mkdir(parents=True, exist_ok=True)
    arq_man = destino / "manifesto.json"
    antigo = json.loads(arq_man.read_text(encoding="utf-8")) if arq_man.exists() else {"anos": {}}
    novo = {"anos": dict(antigo["anos"])}
    atualizados = []
    with cliente() as c, tempfile.TemporaryDirectory() as tmp_s:
        for ano in range(acesso_em.year - ANOS_ATRAS, acesso_em.year + 1):
            info = com_tentativas(lambda: cabecalho(c, ano))
            if info is None:
                continue
            anterior = antigo["anos"].get(str(ano))
            if anterior and anterior["last_modified"] == info["last_modified"] and anterior["bytes_xlsx"] == info["bytes"]:
                continue
            xlsx = Path(tmp_s) / f"{ano}.xlsx"
            sha = com_tentativas(lambda: baixar(c, ano, xlsx))
            cont, meta = agregar(xlsx, ano)
            xlsx.unlink()
            if not meta["registros_sorocaba"]:
                raise ValueError(f"nenhum registro de Sorocaba em {ano}")
            pasta = destino / str(ano)
            pasta.mkdir(exist_ok=True)
            hashes = {}
            for tabela, campos in TABELAS.items():
                texto = csv_texto(campos, cont[tabela])
                (pasta / f"{tabela}.csv").write_text(texto, encoding="utf-8")
                hashes[tabela] = hashlib.sha256(texto.encode("utf-8")).hexdigest()
            novo["anos"][str(ano)] = {
                "url": URL.format(ano=ano), "last_modified": info["last_modified"], "bytes_xlsx": info["bytes"],
                "sha256_xlsx": sha, "coletado_em": acesso_em.isoformat(), "sha256_csv": hashes, **meta,
            }
            atualizados.append(ano)
    if atualizados:
        arq_man.write_text(json.dumps(novo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return atualizados


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    args = p.parse_args()
    print("atualizados:", coletar(args.acesso_em) or "nenhum")


if __name__ == "__main__":
    main()
