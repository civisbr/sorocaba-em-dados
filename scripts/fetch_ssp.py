"""Baixa as planilhas anuais de ocorrências da SSP-SP e guarda só contagens agregadas de Sorocaba.

Cada linha da fonte é um boletim de ocorrência, com endereço, coordenadas e horário. Nada
disso é gravado. Entram só contagens por mês e grupo de natureza (cidade inteira); hora, bairro
e tipo de furto existem apenas para roubos e furtos (ver seguranca_grupos.py).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import tempfile
import zipfile
import time
from collections import Counter
from datetime import date, time as hora_t
from pathlib import Path

import httpx
from python_calamine import CalamineWorkbook

from scripts.seguranca_grupos import GRUPOS_DETALHADOS, grupo_de

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
    "lat": ("LATITUDE",),
    "lon": ("LONGITUDE",),
    "bairro": ("BAIRRO",),
    "conduta": ("DESCR_CONDUTA",),
}
TABELAS = {
    "mensal": ["ano", "mes", "grupo", "n"],
    "hora": ["ano", "grupo", "hora", "n"],
    "bairro": ["ano", "grupo", "bairro", "n"],
    "conduta": ["ano", "grupo", "conduta", "n"],
    "grade": ["ano", "grupo", "lat", "lon", "n"],
}
CELULA = 0.005  # graus; ~550 m de lado. Só o centro da célula é gravado, nunca a coordenada do boletim.
LIMITE_DESCOMPRIMIDO = 4 * 1024**3


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
    info = {"last_modified": r.headers.get("last-modified", ""), "bytes": int(r.headers.get("content-length", "0"))}
    if not info["last_modified"] or not info["bytes"]:
        raise ValueError(f"a SSP-SP não informou Last-Modified/Content-Length de {ano}; sem eles não dá para detectar mudança")
    return info


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
    esperado = int(r.headers.get("content-length", "0"))
    if esperado and total != esperado:
        raise ValueError(f"download de {ano} incompleto: {total} de {esperado} bytes")
    return h.hexdigest()


def limpar(v) -> str:
    texto = " ".join(str(v).split()) if v is not None else ""
    # Valor da fonte começando por = + - @ viraria fórmula se o CSV fosse aberto em planilha.
    return texto.lstrip("=+-@") if texto[:1] in "=+-@" else texto


def indices(cab: list) -> dict[str, int] | None:
    nomes = [str(c).strip() for c in cab]
    achados = {}
    for chave, opcoes in ALIASES.items():
        i = next((nomes.index(o) for o in opcoes if o in nomes), None)
        if i is None:
            return None
        achados[chave] = i
    return achados


def limites_do_municipio(margem: float = 0.01) -> tuple[float, float, float, float]:
    """(lat_min, lat_max, lon_min, lon_max) da malha do IBGE; descarta coordenadas fora da cidade."""
    geo = json.loads((RAIZ / "data" / "raw" / "ibge" / "malha_3552205.geojson").read_text(encoding="utf-8"))
    g = geo["features"][0]["geometry"]
    pols = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    pts = [p for pol in pols for p in pol[0]]
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    return min(lats) - margem, max(lats) + margem, min(lons) - margem, max(lons) + margem


def celula(lat, lon, limites) -> tuple[float, float] | None:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (limites[0] <= la <= limites[1] and limites[2] <= lo <= limites[3]):
        return None
    return round((math.floor(la / CELULA) + 0.5) * CELULA, 4), round((math.floor(lo / CELULA) + 0.5) * CELULA, 4)


def codigo(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def agregar(caminho: Path, ano_arquivo: int) -> tuple[dict[str, Counter], dict]:
    """Percorre as abas de dados e conta ocorrências de Sorocaba por (ano, mês, natureza, ...)."""
    with zipfile.ZipFile(caminho) as z:  # o xlsx é um zip: recusa explosão de descompressão antes de carregar
        if sum(i.file_size for i in z.infolist()) > LIMITE_DESCOMPRIMIDO:
            raise ValueError(f"{caminho.name} descomprime acima do limite esperado")
    wb = CalamineWorkbook.from_path(str(caminho))
    cont = {t: Counter() for t in TABELAS}
    limites = limites_do_municipio()
    meta = {"abas": [], "registros_sorocaba": 0, "sem_natureza": 0, "fora_dos_grupos": 0, "fora_do_ano": 0, "sem_coordenada_valida": 0}
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
            grupo = grupo_de(natureza)
            if grupo is None:
                meta["fora_dos_grupos"] += 1
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
            cont["mensal"][(ano, mes, grupo)] += 1
            if grupo in GRUPOS_DETALHADOS:
                cont["hora"][(ano, grupo, rotulo_hora)] += 1
                cont["bairro"][(ano, grupo, bairro)] += 1
                c = celula(r[idx["lat"]], r[idx["lon"]], limites)
                if c:
                    cont["grade"][(ano, grupo, *c)] += 1
                else:
                    meta["sem_coordenada_valida"] += 1
                if grupo == "furtos":
                    cont["conduta"][(ano, grupo, conduta)] += 1
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
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
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
    novo["verificado_em"] = acesso_em.isoformat()
    arq_man.write_text(json.dumps(novo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return atualizados


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    args = p.parse_args()
    print("atualizados:", coletar(args.acesso_em) or "nenhum")


if __name__ == "__main__":
    main()
