"""Óbitos (SIM) e nascimentos (SINASC) de moradores de Sorocaba. Só contagens agregadas por ano vão ao repositório."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

from scripts import ftp_datasus
from scripts.dbc import ler_dbc
from scripts.saude_codigos import capitulo_cid

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "vitais"
PASTA_SIM = "SIM/CID10/DORES"
PASTA_SINASC = "SINASC/1996_/Dados/DNRES"
MUNICIPIO = "355220"
ANOS = 3
VARIACAO_MAXIMA = (0.85, 1.15)  # ano já coletado que muda além disso entre coletas indica fonte alterada (FTP sem TLS)
CELULA_MINIMA = 5
CAMPOS = ["ano", "bloco", "categoria", "n"]
FAIXAS = ((0, 1, "Menos de 1 ano"), (1, 15, "1 a 14 anos"), (15, 30, "15 a 29 anos"), (30, 60, "30 a 59 anos"), (60, 80, "60 a 79 anos"), (80, 200, "80 anos ou mais"))
EXTERNAS = (("X60", "X84", "Suicídios"), ("X85", "Y09", "Homicídios"), ("V01", "V99", "Acidentes de transporte"))


def idade_anos(codigo: str) -> int | None:
    """IDADE do SIM: primeiro dígito é a unidade (0 a 3: menos de 1 ano; 4: anos; 5: 100 anos ou mais)."""
    if len(codigo) != 3 or not codigo.isdigit() or codigo in ("000", "999"):
        return None
    u, v = int(codigo[0]), int(codigo[1:])
    if u in (0, 1, 2, 3):
        return 0
    return v if u == 4 else 100 + v if u == 5 else None


def faixa_etaria(anos: int) -> str:
    return next(nome for ini, fim, nome in FAIXAS if ini <= anos < fim)


def grupo_externo(causa: str) -> str | None:
    c = (causa or "").upper()[:3]
    return next((nome for ini, fim, nome in EXTERNAS if ini <= c <= fim), None)


def agregar_obitos(registros: Iterable[dict], ano: int) -> list[dict]:
    cont: Counter = Counter()
    for r in registros:
        if r["TIPOBITO"] != "2":  # óbito fetal fica fora; é outro indicador
            continue
        cont[("obito_total", "")] += 1
        cap = capitulo_cid(r["CAUSABAS"])
        cont[("obito_capitulo", cap or "Causa não classificada")] += 1
        anos = idade_anos(r["IDADE"])
        if anos is not None:
            cont[("obito_faixa", faixa_etaria(anos))] += 1
            if anos == 0:
                cont[("obito_infantil", "")] += 1
        g = grupo_externo(r["CAUSABAS"])
        if g:
            cont[("obito_externa", g)] += 1
    return _linhas(cont, ano)


def agregar_nascimentos(registros: Iterable[dict], ano: int) -> list[dict]:
    cont: Counter = Counter()
    for r in registros:
        cont[("nasc_total", "")] += 1
        if r["PARTO"] in ("1", "2"):
            cont[("nasc_parto_valido", "")] += 1
            cont[("nasc_cesarea", "")] += r["PARTO"] == "2"
        if r["GESTACAO"] in ("1", "2", "3", "4", "5", "6"):
            cont[("nasc_gestacao_valida", "")] += 1
            cont[("nasc_prematuro", "")] += r["GESTACAO"] in ("1", "2", "3", "4")
        if r["PESO"].isdigit() and 100 <= int(r["PESO"]) <= 9000:
            cont[("nasc_peso_valido", "")] += 1
            cont[("nasc_baixo_peso", "")] += int(r["PESO"]) < 2500
        if r["IDADEMAE"].isdigit() and 9 <= int(r["IDADEMAE"]) <= 60:
            cont[("nasc_idade_mae_valida", "")] += 1
            cont[("nasc_mae_ate19", "")] += int(r["IDADEMAE"]) <= 19
        if r["CONSULTAS"] in ("1", "2", "3", "4"):
            cont[("nasc_prenatal_valido", "")] += 1
            cont[("nasc_prenatal_7ou_mais", "")] += r["CONSULTAS"] == "4"
    return _linhas(cont, ano)


def _linhas(cont: Counter, ano: int) -> list[dict]:
    """Células com menos de CELULA_MINIMA ocorrências são omitidas (as de total, não)."""
    return [{"ano": ano, "bloco": b, "categoria": c, "n": n} for (b, c), n in sorted(cont.items())
            if n >= CELULA_MINIMA or b in ("obito_total", "nasc_total")]


def anos_disponiveis(nomes: list[str], prefixo: str) -> set[int]:
    return {int(m.group(1)) for n in nomes if (m := re.fullmatch(rf"{prefixo}SP(\d{{4}})\.dbc", n))}


def _csv(linhas: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CAMPOS, delimiter=";", lineterminator="\n")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue()


def coletar(acesso_em: date, destino: Path = DESTINO, listar: Callable[[str], list[str]] = ftp_datasus.listar,
            baixar: Callable[[str], tuple[bytes, str]] = ftp_datasus.baixar, ler=ler_dbc) -> list[int]:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    comuns = sorted(anos_disponiveis(listar(PASTA_SIM), "DO") & anos_disponiveis(listar(PASTA_SINASC), "DN"))
    if len(comuns) < ANOS:
        raise ValueError("SIM e SINASC com menos anos em comum do que o esperado")
    anos = comuns[-ANOS:]
    if anos[-1] < acesso_em.year - 3:
        raise ValueError(f"último ano publicado ({anos[-1]}) é antigo demais; a fonte parece parada")
    arq, marq = destino / "indicadores.csv", destino / "manifesto.json"
    existente: list[dict] = []
    man = {"anos": {}}
    if arq.exists() and marq.exists():
        if hashlib.sha256(arq.read_bytes()).hexdigest() != json.loads(marq.read_text(encoding="utf-8")).get("sha256_csv"):
            raise ValueError("indicadores.csv existente não confere com o hash do manifesto")
        existente = [{"ano": int(r["ano"]), "bloco": r["bloco"], "categoria": r["categoria"], "n": int(r["n"])} for r in csv.DictReader(io.StringIO(arq.read_text(encoding="utf-8")), delimiter=";")]
        man = json.loads(marq.read_text(encoding="utf-8"))
    refazer = [a for a in anos if str(a) not in man["anos"] or a == anos[-1]]  # o último ano ainda é revisado pelo Ministério
    novas: list[dict] = []
    origem: dict[str, dict] = {}
    for a in refazer:
        for pasta, sigla, agregar in ((PASTA_SIM, "DO", agregar_obitos), (PASTA_SINASC, "DN", agregar_nascimentos)):
            dados, h = baixar(f"{pasta}/{sigla}SP{a}.dbc")
            linhas = agregar(ler(dados, ("CODMUNRES", MUNICIPIO)), a)
            if not linhas:
                raise ValueError(f"nenhum registro de Sorocaba em {sigla}SP{a}")
            novas += linhas
            origem.setdefault(str(a), {})[sigla] = {"bytes": len(dados), "sha256": h}
    for a in refazer:
        for bloco in ("obito_total", "nasc_total"):
            antes = next((r["n"] for r in existente if r["ano"] == a and r["bloco"] == bloco), None)
            depois = next(r["n"] for r in novas if r["ano"] == a and r["bloco"] == bloco)
            if antes and not VARIACAO_MAXIMA[0] <= depois / antes <= VARIACAO_MAXIMA[1]:
                raise ValueError(f"{a} {bloco}: foi de {antes} para {depois} entre coletas; confira a fonte antes de aceitar")
    todas = [r for r in existente if r["ano"] in anos and r["ano"] not in refazer] + novas
    todas.sort(key=lambda r: (r["ano"], r["bloco"], r["categoria"]))
    texto = _csv(todas)
    destino.mkdir(parents=True, exist_ok=True)
    tmp = destino / "indicadores.csv.tmp"
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, arq)
    man = {"fonte": "SIM (DO) e SINASC (DN) de SP, DATASUS; recorte: residentes em Sorocaba (CODMUNRES 355220)",
           "anos": {str(a): {**man["anos"].get(str(a), {}), **origem.get(str(a), {})} for a in anos}, "primeiro": anos[0], "ultimo": anos[-1],
           "sha256_csv": hashlib.sha256(texto.encode("utf-8")).hexdigest(), "verificado_em": acesso_em.isoformat()}
    tmp = destino / "manifesto.tmp"
    tmp.write_text(json.dumps(man, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, marq)
    return refazer


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    print("anos coletados:", coletar(p.parse_args().acesso_em))


if __name__ == "__main__":
    main()
