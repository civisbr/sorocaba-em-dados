"""Rede de saúde de Sorocaba no CNES (DATASUS): estabelecimentos e leitos. Só o recorte do município vai ao repositório."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx

from scripts import ftp_datasus
from scripts.dbc import ler_dbc
from scripts.saude_codigos import ATENCAO_BASICA, HOSPITALAR, TIPOS_UNIDADE, URGENCIA

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "cnes"
PASTA = "CNES/200508_/Dados"
MUNICIPIO = "355220"
HOST_API = "apidadosabertos.saude.gov.br"
API = f"https://{HOST_API}/cnes/estabelecimentos"
MAX_DIAS_COMPETENCIA = 150
VARIACAO_LEITOS = (0.8, 1.2)  # entre coletas; o FTP não tem TLS nem checksum
TAM_TEXTO = 120
TIPOS_MANTIDOS = frozenset(HOSPITALAR + URGENCIA + ATENCAO_BASICA + ("70",))
CAMPOS_ESTAB = ["cnes", "tipo", "nat_jur", "vinc_sus", "urgencia", "centro_cirurgico", "centro_obstetrico", "neonatal", "nome", "logradouro", "numero", "bairro", "telefone", "lat", "lon"]
CAMPOS_LEITO = ["cnes", "tp_leito", "cod_leito", "existentes", "sus"]
Baixador = Callable[[str], tuple[bytes, str]]
Lista = Callable[[str], list[str]]


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host != HOST_API:
        raise ValueError(f"requisição fora de https://{HOST_API}: {r.url.host}")


def competencia_mais_recente(nomes: list[str], prefixo: str) -> list[str]:
    """Competências aaaamm disponíveis no diretório, da mais nova para a mais antiga."""
    achados = sorted({m.group(1) for n in nomes if (m := re.fullmatch(rf"{prefixo}SP(\d{{4}})\.dbc", n))}, reverse=True)
    return [("20" + a) for a in achados]


def _idade_dias(comp: str, hoje: date) -> int:
    return (hoje - date(int(comp[:4]), int(comp[4:]), 1)).days


def _inteiro(v: str) -> int:
    return int(v) if v.strip().isdigit() else 0


def nomes_api(c: httpx.Client, tipos: set[str]) -> dict[str, dict]:
    """Nome, endereço e coordenadas do cadastro aberto do Ministério (a API só entrega 20 por página)."""
    saida: dict[str, dict] = {}
    for tipo in sorted(tipos):
        off = 0
        while True:
            r = c.get(API, params={"codigo_municipio": MUNICIPIO, "codigo_tipo_unidade": int(tipo), "limit": 20, "offset": off})
            r.raise_for_status()
            lote = r.json().get("estabelecimentos")
            if not isinstance(lote, list):
                raise ValueError("resposta inesperada do cadastro de estabelecimentos")
            for e in lote:
                if isinstance(e, dict) and e.get("codigo_cnes") is not None:
                    saida[str(int(e["codigo_cnes"]))] = e
            if len(lote) < 20:
                break
            off += 20
            if off > 5000:
                raise ValueError("paginação do cadastro não termina")
    return saida


def _texto(v) -> str:
    """Texto de campo vindo da API: só str, sem quebra de linha, tamanho limitado e sem prefixo que planilhas leiam como fórmula."""
    if not isinstance(v, str):
        return ""
    t = " ".join(v.split())[:TAM_TEXTO]
    return "'" + t if t[:1] in ("=", "+", "-", "@") else t


def _coord(v) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and -90 <= v <= 90:
        return f"{v:.5f}"
    return ""


def _mantem(r: dict) -> bool:
    t = r["TP_UNID"]
    if t not in TIPOS_MANTIDOS or r["PF_PJ"] != "3":
        return False
    if t == "01":  # os "postos" de Sorocaba no CNES são enfermarias de presídio e da Fundação Casa; só vale posto municipal
        return r["NAT_JUR"] == "1244"
    if t in URGENCIA:
        return _inteiro(r["VINC_SUS"]) == 1
    return True


def montar(st_rows: list[dict], lt_rows: list[dict], nomes: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    estab: list[dict] = []
    for r in st_rows:
        if not _mantem(r):
            continue
        n = nomes.get(str(int(r["CNES"])), {})
        estab.append({
            "cnes": r["CNES"], "tipo": r["TP_UNID"], "nat_jur": r["NAT_JUR"], "vinc_sus": _inteiro(r["VINC_SUS"]),
            "urgencia": _inteiro(r["URGEMERG"]), "centro_cirurgico": _inteiro(r["CENTRCIR"]), "centro_obstetrico": _inteiro(r["CENTROBS"]), "neonatal": _inteiro(r["CENTRNEO"]),
            "nome": _texto(n.get("nome_fantasia")), "logradouro": _texto(n.get("endereco_estabelecimento")),
            "numero": _texto(str(n.get("numero_estabelecimento") or "")), "bairro": _texto(n.get("bairro_estabelecimento")),
            "telefone": _texto(n.get("numero_telefone_estabelecimento")),
            "lat": _coord(n.get("latitude_estabelecimento_decimo_grau")), "lon": _coord(n.get("longitude_estabelecimento_decimo_grau")),
        })
    estab.sort(key=lambda e: (e["tipo"], e["cnes"]))
    mantidos = {e["cnes"] for e in estab if e["tipo"] in HOSPITALAR or e["tipo"] in URGENCIA}
    leitos = [{"cnes": r["CNES"], "tp_leito": r["TP_LEITO"], "cod_leito": r["CODLEITO"], "existentes": _inteiro(r["QT_EXIST"]), "sus": _inteiro(r["QT_SUS"])}
              for r in lt_rows if r["CNES"] in mantidos and _inteiro(r["QT_EXIST"]) > 0]
    leitos.sort(key=lambda r: (r["cnes"], r["tp_leito"], r["cod_leito"]))
    return estab, leitos


def _csv(linhas: list[dict], campos: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=campos, delimiter=";", lineterminator="\n")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue()


def coletar(acesso_em: date, destino: Path = DESTINO, listar: Lista = ftp_datasus.listar, baixar: Baixador = ftp_datasus.baixar,
            ler=ler_dbc, transporte: httpx.BaseTransport | None = None) -> str:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    lt_nomes, st_nomes = listar(f"{PASTA}/LT"), listar(f"{PASTA}/ST")
    em_comum = [c for c in competencia_mais_recente(lt_nomes, "LT") if c in competencia_mais_recente(st_nomes, "ST")]
    if not em_comum:
        raise ValueError("nenhuma competência com LT e ST no FTP")
    comp = em_comum[0]
    if _idade_dias(comp, acesso_em) > MAX_DIAS_COMPETENCIA:
        raise ValueError(f"competência mais recente ({comp}) tem mais de {MAX_DIAS_COMPETENCIA} dias; a fonte parece parada")
    yymm = comp[2:]
    arquivos: dict[str, dict] = {}
    linhas: dict[str, list[dict]] = {}
    for sigla in ("LT", "ST"):
        dados, h = baixar(f"{PASTA}/{sigla}/{sigla}SP{yymm}.dbc")
        arquivos[sigla] = {"arquivo": f"{sigla}SP{yymm}.dbc", "bytes": len(dados), "sha256": h}
        linhas[sigla] = list(ler(dados, ("CODUFMUN", MUNICIPIO)))
    tipos = {r["TP_UNID"] for r in linhas["ST"] if r["TP_UNID"] in TIPOS_MANTIDOS}
    with httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": "SorocabaEmDados/1.0 (+https://github.com/civisbr/sorocaba-em-dados)", "Accept-Encoding": "identity"},
                      event_hooks={"request": [so_host_confiavel]}, transport=transporte) as c:
        nomes = nomes_api(c, tipos)
    estab, leitos = montar(linhas["ST"], linhas["LT"], nomes)
    hospitais = [e for e in estab if e["tipo"] in HOSPITALAR]
    if len(hospitais) < 5 or sum(r["existentes"] for r in leitos) < 500:
        raise ValueError("recorte de Sorocaba implausível (poucos hospitais ou leitos); a fonte mudou?")
    total_leitos = sum(r["existentes"] for r in leitos)
    mant = destino / "manifesto.json"
    if mant.exists():
        antes = json.loads(mant.read_text(encoding="utf-8")).get("leitos_total")
        if antes and not VARIACAO_LEITOS[0] <= total_leitos / antes <= VARIACAO_LEITOS[1]:
            raise ValueError(f"leitos foram de {antes} para {total_leitos} entre coletas; confira a fonte antes de aceitar")
    sem_nome = [e for e in estab if not e["nome"]]
    if len(sem_nome) > 0.2 * len(estab):
        raise ValueError(f"{len(sem_nome)} de {len(estab)} estabelecimentos sem nome no cadastro aberto")
    for e in sem_nome:
        e["nome"] = f"{TIPOS_UNIDADE.get(e['tipo'], 'Estabelecimento')} (CNES {e['cnes']})"
    textos = {"estabelecimentos.csv": _csv(estab, CAMPOS_ESTAB), "leitos.csv": _csv(leitos, CAMPOS_LEITO)}
    destino.mkdir(parents=True, exist_ok=True)
    for nome, texto in textos.items():  # só grava depois de validar tudo
        tmp = destino / f"{nome}.tmp"
        tmp.write_text(texto, encoding="utf-8")
        os.replace(tmp, destino / nome)
    man = {"fonte": "CNES/DATASUS: arquivos ST e LT de SP (FTP) + cadastro aberto de estabelecimentos (nomes e endereços)", "competencia": comp, "verificado_em": acesso_em.isoformat(),
           "origem": arquivos, "sha256_csv": {n: hashlib.sha256(t.encode("utf-8")).hexdigest() for n, t in textos.items()},
           "n_estabelecimentos": len(estab), "leitos_total": total_leitos, "n_hospitais": len(hospitais), "n_sem_nome": len(sem_nome)}
    tmp = destino / "manifesto.tmp"
    tmp.write_text(json.dumps(man, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, destino / "manifesto.json")
    return comp


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    print("competência:", coletar(p.parse_args().acesso_em))


if __name__ == "__main__":
    main()
