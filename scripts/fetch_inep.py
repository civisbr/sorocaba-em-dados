"""Baixa IDEB por escola e Censo Escolar do INEP e guarda só as linhas de Sorocaba.

O servidor download.inep.gov.br não envia o certificado intermediário (RNP ICPEdu). Em vez de
desligar a verificação TLS, o intermediário público fica em certs/ e é somado às raízes do
sistema; a cadeia continua validada até a GlobalSign Root R46.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import ssl
import tempfile
import time
import zipfile
from datetime import date
from pathlib import Path

import httpx
from python_calamine import CalamineWorkbook

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "inep"
CERT_INTERMEDIARIO = RAIZ / "certs" / "rnp-icpedu-gr46-ov-tls-ca-2025.pem"
BASE = "https://download.inep.gov.br/"
HOST = "download.inep.gov.br"
CODIGO_MUNICIPIO = "3552205"
LIMITE_ZIP = 300 * 1024 * 1024
LIMITE_MEMBRO = 800 * 1024 * 1024
ANOS_A_TESTAR = 4

CENSO_COLUNAS = [
    "NU_ANO_CENSO", "CO_ENTIDADE", "NO_ENTIDADE", "NO_BAIRRO", "TP_DEPENDENCIA", "TP_LOCALIZACAO",
    "TP_SITUACAO_FUNCIONAMENTO", "QT_MAT_INF", "QT_MAT_FUND_AI", "QT_MAT_FUND_AF", "QT_MAT_MED",
    "QT_MAT_EJA", "QT_MAT_ESP", "QT_MAT_BAS", "IN_BIBLIOTECA", "IN_LABORATORIO_INFORMATICA",
    "IN_LABORATORIO_CIENCIAS", "IN_QUADRA_ESPORTES", "IN_INTERNET", "IN_REFEITORIO",
    "IN_ACESSIBILIDADE_RAMPAS", "DS_ENDERECO", "NU_ENDERECO", "CO_CEP",
]
IDEB_FIXAS = ["SG_UF", "CO_MUNICIPIO", "NO_MUNICIPIO", "ID_ESCOLA", "NO_ESCOLA", "REDE"]
IDEB_PREFIXOS = ("VL_OBSERVADO_", "VL_INDICADOR_REND_", "VL_NOTA_MEDIA_")
IDEB_RECENTES = 4


def contexto_tls() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=str(CERT_INTERMEDIARIO))
    # Python 3.13 liga PARTIAL_CHAIN por padrão, o que tornaria o intermediário uma âncora de
    # confiança. Desligado, a cadeia precisa chegar a uma raiz do sistema.
    ctx.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
    return ctx


def so_host_confiavel(resposta: httpx.Response) -> None:
    # Hook em toda resposta, inclusive saltos de redirecionamento e HEAD.
    if resposta.url.scheme != "https" or resposta.url.host != HOST:
        raise ValueError(f"resposta fora de https://{HOST}: {resposta.url}")


def cliente() -> httpx.Client:
    return httpx.Client(
        verify=contexto_tls(), timeout=httpx.Timeout(60, read=600), follow_redirects=True,
        event_hooks={"response": [so_host_confiavel]},
    )


def com_tentativas(fn, tentativas: int = 4):
    # O servidor do INEP derruba conexões de vez em quando; falha de rede não é motivo para abortar.
    for n in range(tentativas):
        try:
            return fn()
        except httpx.TransportError:
            if n == tentativas - 1:
                raise
            time.sleep(2**n * 3)


def cabecalho(c: httpx.Client, caminho: str) -> dict | None:
    r = c.head(BASE + caminho)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return {"last_modified": r.headers.get("last-modified", ""), "bytes": int(r.headers.get("content-length", "0"))}


def descobrir(c: httpx.Client, modelo: str, hoje: date) -> tuple[int, str, dict]:
    for ano in range(hoje.year, hoje.year - ANOS_A_TESTAR, -1):
        caminho = modelo.format(ano=ano)
        info = com_tentativas(lambda: cabecalho(c, caminho))
        if info:
            return ano, caminho, info
    raise FileNotFoundError(f"nenhuma edição de {modelo} entre {hoje.year - ANOS_A_TESTAR + 1} e {hoje.year}")


def baixar_zip(c: httpx.Client, caminho: str, destino: Path) -> str:
    h = hashlib.sha256()
    total = 0
    with c.stream("GET", BASE + caminho) as r:
        r.raise_for_status()
        with destino.open("wb") as f:
            for pedaco in r.iter_bytes(1 << 20):
                total += len(pedaco)
                if total > LIMITE_ZIP:
                    raise ValueError(f"{caminho} acima do limite esperado")
                h.update(pedaco)
                f.write(pedaco)
    return h.hexdigest()


def membro_unico(z: zipfile.ZipFile, padrao: str) -> zipfile.ZipInfo:
    achados = [i for i in z.infolist() if re.fullmatch(padrao, i.filename) and not i.is_dir()]
    if len(achados) != 1:
        raise ValueError(f"esperava 1 membro para {padrao!r}, achei {len(achados)}")
    if achados[0].file_size > LIMITE_MEMBRO:
        raise ValueError(f"{achados[0].filename} acima do limite esperado")
    return achados[0]


def md5_declarado(z: zipfile.ZipFile, alvo: str) -> str:
    for i in z.infolist():
        if i.filename.lower().rsplit("/", 1)[-1].startswith("md5") and i.file_size < 4096:
            for linha in z.read(i).decode("utf-8", "replace").splitlines():
                partes = linha.strip().split()
                if len(partes) >= 2 and partes[1].lstrip("*") == alvo:
                    return partes[0].lower()
    raise ValueError(f"md5 de {alvo} não declarado no zip")


def extrair_verificando(z: zipfile.ZipFile, info: zipfile.ZipInfo, destino: Path) -> str:
    esperado = md5_declarado(z, info.filename.rsplit("/", 1)[-1])
    h = hashlib.md5(usedforsecurity=False)
    with z.open(info) as origem, destino.open("wb") as saida:
        while pedaco := origem.read(1 << 20):
            h.update(pedaco)
            saida.write(pedaco)
    if h.hexdigest() != esperado:
        raise ValueError(f"md5 de {info.filename} não confere com o declarado pelo INEP")
    return esperado


def numero(v) -> str:
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else repr(v)
    return str(v).strip()


def filtrar_ideb(xlsx: Path) -> str:
    linhas = CalamineWorkbook.from_path(str(xlsx)).get_sheet_by_index(0).to_python()
    i = next((k for k, r in enumerate(linhas) if r and r[0] == "SG_UF"), None)
    if i is None:
        raise ValueError("cabeçalho do IDEB não encontrado")
    cab = [str(c) for c in linhas[i]]
    if cab[: len(IDEB_FIXAS)] != IDEB_FIXAS:
        raise ValueError(f"colunas inesperadas no IDEB: {cab[:8]}")
    anos = sorted({int(c[-4:]) for c in cab if c.startswith("VL_OBSERVADO_") and c[-4:].isdigit()})
    mantidas = [
        c for c in cab[len(IDEB_FIXAS):]
        if c.startswith(IDEB_PREFIXOS) and c[-4:].isdigit() and int(c[-4:]) in anos[-IDEB_RECENTES:]
    ]
    idx = [cab.index(c) for c in [*IDEB_FIXAS, *mantidas]]
    saida = io.StringIO()
    w = csv.writer(saida, delimiter=";", lineterminator="\n")
    w.writerow([*IDEB_FIXAS, *mantidas])
    for r in linhas[i + 1:]:
        if len(r) > 1 and numero(r[1]) == CODIGO_MUNICIPIO:
            w.writerow([numero(r[k]) for k in idx])
    return saida.getvalue()


def filtrar_censo(csv_path: Path) -> str:
    with csv_path.open(encoding="latin-1", newline="") as f:
        leitor = csv.reader(f, delimiter=";")
        cab = next(leitor)
        faltam = [c for c in [*CENSO_COLUNAS, "CO_MUNICIPIO"] if c not in cab]
        if faltam:
            raise ValueError(f"colunas ausentes no Censo Escolar: {faltam}")
        i_mun = cab.index("CO_MUNICIPIO")
        idx = [cab.index(c) for c in CENSO_COLUNAS]
        saida = io.StringIO()
        w = csv.writer(saida, delimiter=";", lineterminator="\n")
        w.writerow(CENSO_COLUNAS)
        for r in leitor:
            if len(r) == len(cab) and r[i_mun] == CODIGO_MUNICIPIO:
                w.writerow([r[k] for k in idx])
    return saida.getvalue()


def coletar(acesso_em: date, destino: Path = DESTINO) -> list[str]:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    destino.mkdir(parents=True, exist_ok=True)
    manifesto_atual = (
        json.loads((destino / "manifesto.json").read_text(encoding="utf-8")) if (destino / "manifesto.json").exists() else {}
    )
    novo = {"acesso_em": acesso_em.isoformat(), "arquivos": {}}
    feitos = []
    prontos: list[str] = []
    fontes = {
        "ideb_anos_iniciais": ("ideb/resultados/divulgacao_anos_iniciais_escolas_{ano}.zip", r".*\.xlsx"),
        "ideb_anos_finais": ("ideb/resultados/divulgacao_anos_finais_escolas_{ano}.zip", r".*\.xlsx"),
        "censo_escolar": ("dados_abertos/microdados_censo_escolar_{ano}.zip", r".*/dados/microdados_ed_basica_\d{4}\.csv"),
    }
    with cliente() as c, tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        for nome, (modelo, padrao) in fontes.items():
            ano, caminho, info = descobrir(c, modelo, acesso_em)
            anterior = manifesto_atual.get("arquivos", {}).get(nome)
            colunas_ok = nome != "censo_escolar" or ((destino / "censo_escolar.csv").exists() and (destino / "censo_escolar.csv").read_text(encoding="utf-8").split("\n", 1)[0] == ";".join(CENSO_COLUNAS))  # coluna nova no código pede nova extração
            if colunas_ok and anterior and anterior["ano"] == ano and anterior["last_modified"] == info["last_modified"] and anterior["bytes_zip"] == info["bytes"]:
                novo["arquivos"][nome] = anterior
                continue
            zip_path = tmp / f"{nome}.zip"
            sha_zip = com_tentativas(lambda: baixar_zip(c, caminho, zip_path))
            with zipfile.ZipFile(zip_path) as z:
                membro = membro_unico(z, padrao)
                bruto = tmp / f"{nome}.bruto"
                md5 = extrair_verificando(z, membro, bruto)
            texto = filtrar_ideb(bruto) if nome.startswith("ideb") else filtrar_censo(bruto)
            if texto.count("\n") < 2:
                raise ValueError(f"{nome}: nenhuma linha de Sorocaba")
            arquivo = f"{nome}.csv"
            (tmp / arquivo).write_text(texto, encoding="utf-8")
            prontos.append(arquivo)
            novo["arquivos"][nome] = {
                "arquivo": arquivo,
                "ano": ano,
                "url": BASE + caminho,
                "last_modified": info["last_modified"],
                "bytes_zip": info["bytes"],
                "sha256_zip": sha_zip,
                "md5_declarado_inep": md5,
                "sha256_filtrado": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
            }
            feitos.append(nome)
        # CSVs e manifesto só vão para o repositório juntos, depois de todas as fontes passarem.
        for arquivo in prontos:
            shutil.copy(tmp / arquivo, destino / arquivo)
    # Sem edição nova, o manifesto fica intacto: mudar só `acesso_em` geraria commit vazio.
    if feitos:
        (destino / "manifesto.json").write_text(json.dumps(novo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return feitos


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    args = p.parse_args()
    print("atualizados:", coletar(args.acesso_em) or "nenhum")


if __name__ == "__main__":
    main()
