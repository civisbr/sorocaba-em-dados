"""Coleta valores de todos os municípios brasileiros para comparar a posição de Sorocaba.

Guarda só (ano, código do município, valor) por indicador. As fontes são as APIs do IBGE
(população e PIB) e o IDEB municipal do INEP (rede pública).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import httpx
from python_calamine import CalamineWorkbook

from scripts import fetch_inep, fetch_perfil

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "comparativo"
AGREGADOS = fetch_perfil.API + "/v3/agregados"
CENSOS_ANTIGOS = "1970|1980|1991|2000|2010"
LIMITE_JSON = 40 * 1024 * 1024  # população de ~5.600 municípios em vários anos passa de 1 MB

ORIGEM_POP = {"censo": "Censo", "contagem": "Contagem", "estimativa": "Estimativa"}


def baixar_json(c: httpx.Client, caminho: str) -> list[dict]:
    url = AGREGADOS + caminho
    def uma() -> bytes:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            corpo = bytearray()
            for pedaco in r.iter_bytes(1 << 20):
                corpo += pedaco
                if len(corpo) > LIMITE_JSON:
                    raise ValueError(f"{caminho} acima do limite esperado")
        return bytes(corpo)
    return json.loads(fetch_inep.com_tentativas(uma))


def valores(resposta: list[dict], origem: str | None = None) -> list[tuple]:
    """(ano, código, valor[, origem]) sem os que o IBGE não publica ('...', '-', 'X')."""
    saida = []
    for v in resposta:
        for s in v["resultados"][0]["series"]:
            cod = s["localidade"]["id"]
            for ano, x in s["serie"].items():
                if x in ("...", "-", "X", "", None):
                    continue
                saida.append((int(ano), cod, float(x), origem))
    return saida


def populacao(c: httpx.Client) -> list[tuple]:
    linhas = valores(baixar_json(c, f"/202/periodos/{CENSOS_ANTIGOS}/variaveis/93?localidades=N6[all]&classificacao=1[0]|2[0]"), "censo")
    linhas += valores(baixar_json(c, "/793/periodos/2007/variaveis/93?localidades=N6[all]"), "contagem")
    linhas += valores(baixar_json(c, "/4714/periodos/2022/variaveis/93?localidades=N6[all]"), "censo")
    anos = [p["id"] for p in fetch_inep.com_tentativas(lambda: baixar_json(c, "/6579/periodos"))]
    for ano in anos:
        linhas += valores(baixar_json(c, f"/6579/periodos/{ano}/variaveis/9324?localidades=N6[all]"), "estimativa")
    return sorted(set(linhas), key=lambda t: (t[0], t[1]))


def pib(c: httpx.Client) -> list[tuple]:
    anos = [p["id"] for p in baixar_json(c, "/5938/periodos")]
    linhas = []
    for ano in anos:
        linhas += valores(baixar_json(c, f"/5938/periodos/{ano}/variaveis/37?localidades=N6[all]"))
    return sorted(set(linhas), key=lambda t: (t[0], t[1]))


def ideb_municipal(c: httpx.Client, etapa: str, hoje: date, tmp: Path) -> tuple[list[tuple], dict]:
    ano, caminho, info = fetch_inep.descobrir(c, f"ideb/resultados/divulgacao_{etapa}_municipios_{{ano}}.zip", hoje)
    zip_path = tmp / f"{etapa}.zip"
    sha_zip = fetch_inep.com_tentativas(lambda: fetch_inep.baixar_zip(c, caminho, zip_path))
    with zipfile.ZipFile(zip_path) as z:
        membro = fetch_inep.membro_unico(z, r".*\.xlsx")
        bruto = tmp / f"{etapa}.xlsx"
        md5 = fetch_inep.extrair_verificando(z, membro, bruto)
    zip_path.unlink()
    linhas = CalamineWorkbook.from_path(str(bruto)).get_sheet_by_index(0).to_python()
    i = next(k for k, r in enumerate(linhas) if r and r[0] == "SG_UF")
    cab = [str(x) for x in linhas[i]]
    if cab[:4] != ["SG_UF", "CO_MUNICIPIO", "NO_MUNICIPIO", "REDE"]:
        raise ValueError(f"colunas inesperadas no IDEB municipal: {cab[:5]}")
    colunas = {int(h[-4:]): k for k, h in enumerate(cab) if h.startswith("VL_OBSERVADO_") and h[-4:].isdigit()}
    saida = []
    for r in linhas[i + 1:]:
        if len(r) > 3 and r[3] == "Pública":
            cod = str(int(float(r[1])))
            for a, k in colunas.items():
                if isinstance(r[k], (int, float)):
                    saida.append((a, cod, float(r[k]), None))
    meta = {"url": fetch_inep.BASE + caminho, "ano": ano, "sha256_zip": sha_zip, "md5_declarado_inep": md5, "last_modified": info["last_modified"]}
    return sorted(set(saida), key=lambda t: (t[0], t[1])), meta


def nomes_sp(c: httpx.Client) -> str:
    def uma() -> bytes:
        with c.stream("GET", f"{fetch_perfil.API}/v1/localidades/estados/35/municipios") as r:
            r.raise_for_status()
            return r.read()
    dados = json.loads(fetch_inep.com_tentativas(uma))
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(["codigo", "nome"])
    for m in sorted(dados, key=lambda m: m["id"]):
        w.writerow([m["id"], m["nome"]])
    return buf.getvalue()


def csv_texto(linhas: list[tuple], com_origem: bool) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(["ano", "codigo", "valor", *(["origem"] if com_origem else [])])
    for a, cod, v, o in linhas:
        w.writerow([a, cod, repr(int(v)) if v == int(v) else repr(v), *([o] if com_origem else [])])
    return buf.getvalue()


def coletar(acesso_em: date, destino: Path = DESTINO) -> list[str]:
    destino.mkdir(parents=True, exist_ok=True)
    arq = destino / "manifesto.json"
    antigo = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"arquivos": {}}
    novo = {"arquivos": {}}
    mudou = []
    with fetch_perfil_cliente() as ibge, fetch_inep.cliente() as inep, tempfile.TemporaryDirectory() as tmp_s:
        produtos = {
            "populacao.csv": (csv_texto(populacao(ibge), True), {"url": AGREGADOS, "tabelas": "202, 793, 4714, 6579"}),
            "pib.csv": (csv_texto(pib(ibge), False), {"url": AGREGADOS, "tabelas": "5938"}),
            "municipios_sp.csv": (nomes_sp(ibge), {"url": fetch_perfil.API + "/v1/localidades/estados/35/municipios"}),
        }
        for etapa in ("anos_iniciais", "anos_finais"):
            linhas, meta = ideb_municipal(inep, etapa, acesso_em, Path(tmp_s))
            produtos[f"ideb_{etapa}.csv"] = (csv_texto(linhas, False), meta)
    for nome, (texto, meta) in produtos.items():
        sha = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        anterior = antigo["arquivos"].get(nome)
        if anterior and anterior["sha256"] == sha:
            novo["arquivos"][nome] = anterior
            continue
        (destino / nome).write_text(texto, encoding="utf-8")
        mudou.append(nome)
        novo["arquivos"][nome] = {"sha256": sha, "coletado_em": acesso_em.isoformat(), **meta}
    novo["verificado_em"] = acesso_em.isoformat()
    arq.write_text(json.dumps(novo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return mudou


def fetch_perfil_cliente() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=True, event_hooks={"request": [fetch_perfil.so_host_confiavel]})


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    args = p.parse_args()
    print("atualizados:", coletar(args.acesso_em) or "nenhum")


if __name__ == "__main__":
    main()
