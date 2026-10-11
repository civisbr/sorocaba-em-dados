"""Coleta eleitos (TSE) e mandatos em exercício (Câmara e Alesp), guardando só o recorte de Sorocaba.

Os arquivos do TSE trazem CPF, e-mail e título de eleitor. Eles são lidos em fluxo e nada disso
é gravado: só as colunas de CAMPOS_* chegam a data/raw/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import tempfile
import time
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import httpx
from defusedxml import ElementTree as ET

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "representantes"
TSE = "https://cdn.tse.jus.br/estatistica/sead/odsele/"
CAMARA = "https://dadosabertos.camara.leg.br/api/v2/deputados?siglaUf=SP&itens=100"
ALESP = "https://www.al.sp.gov.br/repositorioDados/deputados/deputados.xml"
HOSTS = {"cdn.tse.jus.br", "dadosabertos.camara.leg.br", "www.al.sp.gov.br"}
TSE_MUNICIPIO = "71455"  # Sorocaba no TSE (não é o código do IBGE)
ANOS_MUNICIPAL = (2024,)
ANOS_GERAIS = (2022, 2026)
LIMITE_ZIP = 900 * 1024 * 1024
LIMITE_JSON = 5 * 1024 * 1024
LIMITE_MEMBRO = 3 * 1024 * 1024 * 1024
ENCERRADAS = (2022, 2024)  # resultado final: não vale baixar 600 MB de novo se o recorte já existe
CARGOS_MUNICIPAIS = ("PREFEITO", "VICE-PREFEITO", "VEREADOR")
CARGOS_DEPUTADO = ("Deputado Federal", "Deputado Estadual")
CAMPOS_ELEITOS = ["ano", "cargo", "nome_urna", "partido", "situacao", "turno"]
CAMPOS_VOTOS = ["ano", "cargo", "nome_urna", "partido", "situacao", "votos"]
CAMPOS_TOTAIS = ["ano", "cargo", "votos_nominais_validos"]


def so_host_confiavel(r: httpx.Request) -> None:
    # Hook de requisição: barra o salto de redirecionamento antes de ele ser enviado.
    if r.url.scheme != "https" or r.url.host not in HOSTS:
        raise ValueError(f"requisição fora dos hosts esperados: {r.url}")


def cliente() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(60, read=900), follow_redirects=True, event_hooks={"request": [so_host_confiavel]},
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SorocabaEmDados/1.0"},
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


def baixar_zip(c: httpx.Client, url: str, destino: Path) -> str:
    h, total = hashlib.sha256(), 0
    with c.stream("GET", url) as r:
        r.raise_for_status()
        with destino.open("wb") as f:
            for pedaco in r.iter_bytes(1 << 20):
                total += len(pedaco)
                if total > LIMITE_ZIP:
                    raise ValueError(f"{url} acima do limite esperado")
                h.update(pedaco)
                f.write(pedaco)
    return h.hexdigest()


def baixar_curto(c: httpx.Client, url: str) -> bytes:
    with c.stream("GET", url) as r:
        r.raise_for_status()
        corpo = bytearray()
        for pedaco in r.iter_bytes(64 * 1024):
            corpo += pedaco
            if len(corpo) > LIMITE_JSON:
                raise ValueError(f"{url} acima do limite esperado")
    return bytes(corpo)


def linhas_csv(z: zipfile.ZipFile, membro: str):
    if z.getinfo(membro).file_size > LIMITE_MEMBRO:
        raise ValueError(f"{membro} acima do limite esperado")
    with z.open(membro) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="latin-1", newline=""), delimiter=";")


def espaco(s: str) -> str:
    return " ".join(s.split())


def eleitos_municipais(z: zipfile.ZipFile, ano: int) -> list[dict]:
    saida = []
    for r in linhas_csv(z, f"consulta_cand_{ano}_SP.csv"):
        # A mesma planilha traz eleições suplementares de outros municípios; o código do TSE isola Sorocaba.
        if r["SG_UE"] != TSE_MUNICIPIO or r["ANO_ELEICAO"] != str(ano) or r["DS_CARGO"] not in CARGOS_MUNICIPAIS:
            continue
        if r["DS_SIT_TOT_TURNO"].startswith("ELEITO"):
            saida.append({
                "ano": ano, "cargo": r["DS_CARGO"], "nome_urna": espaco(r["NM_URNA_CANDIDATO"]),
                "partido": r["SG_PARTIDO"], "situacao": r["DS_SIT_TOT_TURNO"], "turno": r["NR_TURNO"],
            })
    return sorted(saida, key=lambda d: (d["cargo"], d["nome_urna"]))


def votos_deputados(z: zipfile.ZipFile, ano: int) -> tuple[list[dict], list[dict]]:
    votos: dict[tuple, int] = defaultdict(int)
    meta: dict[tuple, tuple[str, str]] = {}
    totais: dict[str, int] = defaultdict(int)
    for r in linhas_csv(z, f"votacao_candidato_munzona_{ano}_SP.csv"):
        if r["CD_MUNICIPIO"] != TSE_MUNICIPIO or r["DS_CARGO"] not in CARGOS_DEPUTADO or r["NR_TURNO"] != "1":
            continue
        v = int(r["QT_VOTOS_NOMINAIS_VALIDOS"])
        chave = (r["DS_CARGO"], r["SQ_CANDIDATO"])
        votos[chave] += v
        totais[r["DS_CARGO"]] += v
        meta[chave] = (espaco(r["NM_URNA_CANDIDATO"]), r["SG_PARTIDO"], r["DS_SIT_TOT_TURNO"])
    eleitos = [
        {"ano": ano, "cargo": c, "nome_urna": meta[(c, sq)][0], "partido": meta[(c, sq)][1], "situacao": meta[(c, sq)][2], "votos": v}
        for (c, sq), v in votos.items() if meta[(c, sq)][2].startswith("ELEITO")
    ]
    eleitos.sort(key=lambda d: (d["cargo"], -d["votos"], d["nome_urna"]))
    return eleitos, [{"ano": ano, "cargo": c, "votos_nominais_validos": v} for c, v in sorted(totais.items())]


def camara(c: httpx.Client) -> list[dict]:
    dados = json.loads(com_tentativas(lambda: baixar_curto(c, CAMARA)))["dados"]
    if len(dados) >= 100:
        raise ValueError("lista da Câmara no limite de itens por página; implementar paginação")
    return sorted(({"id": d["id"], "nome": d["nome"], "partido": d["siglaPartido"], "uf": d["siglaUf"]} for d in dados), key=lambda d: d["id"])


def alesp(c: httpx.Client) -> list[dict]:
    corpo = com_tentativas(lambda: baixar_curto(c, ALESP))
    raiz = ET.fromstring(corpo)
    saida = [
        {"id": d.findtext("IdDeputado"), "nome": espaco(d.findtext("NomeParlamentar") or ""), "partido": d.findtext("Partido"), "situacao": d.findtext("Situacao")}
        for d in raiz.findall("Deputado")
    ]
    return sorted(saida, key=lambda d: int(d["id"]))


def csv_texto(campos: list[str], linhas: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=campos, delimiter=";", lineterminator="\n")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue()


def coletar(acesso_em: date, destino: Path = DESTINO, forcar: bool = False) -> list[str]:
    produtos: dict[str, tuple[str, str]] = {}  # arquivo -> (texto, url de origem)
    origens: dict[str, str] = {}
    with cliente() as c, tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        for ano in ANOS_MUNICIPAL:
            if ano in ENCERRADAS and (destino / f"eleitos_municipais_{ano}.csv").exists() and not forcar:
                continue
            url = f"{TSE}consulta_cand/consulta_cand_{ano}.zip"
            sha = com_tentativas(lambda: baixar_zip(c, url, tmp / "m.zip"))
            with zipfile.ZipFile(tmp / "m.zip") as z:
                linhas = eleitos_municipais(z, ano)
            if not linhas:
                raise ValueError(f"nenhum eleito de Sorocaba em {ano}")
            cargos = [r["cargo"] for r in linhas]
            if cargos.count("PREFEITO") != 1 or cargos.count("VICE-PREFEITO") != 1:
                raise ValueError(f"esperava 1 prefeito e 1 vice eleitos em {ano}: {cargos.count('PREFEITO')}/{cargos.count('VICE-PREFEITO')}")
            produtos[f"eleitos_municipais_{ano}.csv"] = (csv_texto(CAMPOS_ELEITOS, linhas), url)
            origens[url] = sha
            (tmp / "m.zip").unlink()
        for ano in ANOS_GERAIS:
            if ano in ENCERRADAS and (destino / f"votos_deputados_{ano}.csv").exists() and not forcar:
                continue
            url = f"{TSE}votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip"
            sha = com_tentativas(lambda: baixar_zip(c, url, tmp / "g.zip"))
            with zipfile.ZipFile(tmp / "g.zip") as z:
                eleitos, totais = votos_deputados(z, ano)
            if not eleitos:
                raise ValueError(f"nenhum deputado eleito com votos em Sorocaba em {ano}")
            produtos[f"votos_deputados_{ano}.csv"] = (csv_texto(CAMPOS_VOTOS, eleitos), url)
            produtos[f"totais_votos_{ano}.csv"] = (csv_texto(CAMPOS_TOTAIS, totais), url)
            origens[url] = sha
            (tmp / "g.zip").unlink()
        produtos["camara_deputados_sp.json"] = (json.dumps(camara(c), ensure_ascii=False, indent=1) + "\n", CAMARA)
        produtos["alesp_deputados.json"] = (json.dumps(alesp(c), ensure_ascii=False, indent=1) + "\n", ALESP)

    destino.mkdir(parents=True, exist_ok=True)
    antigo = json.loads((destino / "manifesto.json").read_text(encoding="utf-8")) if (destino / "manifesto.json").exists() else {}
    novo = {"verificado_em": acesso_em.isoformat(), "arquivos": {}}
    mudou = []
    for nome in sorted(set(antigo.get("arquivos", {})) - set(produtos)):
        novo["arquivos"][nome] = antigo["arquivos"][nome]  # eleição encerrada, mantida sem novo download
    for nome, (texto, url) in produtos.items():
        sha = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        anterior = antigo.get("arquivos", {}).get(nome)
        if anterior and anterior["sha256"] == sha:
            novo["arquivos"][nome] = anterior
            continue
        (destino / nome).write_text(texto, encoding="utf-8")
        mudou.append(nome)
        # O zip do TSE é regerado todo dia: o hash do zip e a data só entram para o arquivo que mudou.
        novo["arquivos"][nome] = {
            "url": url, "sha256": sha, "coletado_em": acesso_em.isoformat(),
            **({"sha256_zip": origens[url]} if url in origens else {}),
        }
    # `verificado_em` muda a cada execução: o site mostra a data da última conferência das listas de exercício.
    (destino / "manifesto.json").write_text(json.dumps(novo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return mudou


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    p.add_argument("--forcar", action="store_true", help="rebaixa também as eleições encerradas")
    args = p.parse_args()
    print("atualizados:", coletar(args.acesso_em, forcar=args.forcar) or "nenhum")


if __name__ == "__main__":
    main()
