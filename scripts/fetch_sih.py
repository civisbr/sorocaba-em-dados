"""Internações SUS em hospitais de Sorocaba (SIH/SUS, DATASUS). Só agregados por hospital, mês, especialidade e capítulo do CID vão ao repositório."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from pathlib import Path

from scripts import ftp_datasus
from scripts.dbc import ler_dbc
from scripts.saude_codigos import ESPEC_SIH, capitulo_cid

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "sih"
PASTA = "SIHSUS/200801_/Dados"
MUNICIPIO = "355220"
MESES = 12
REVISAO_MESES = 3  # o SIH reprocessa os meses recentes; os mais antigos ficam como já coletados
MAX_DIAS_COMPETENCIA = 200
VARIACAO_MAXIMA = (0.7, 1.3)  # mês já coletado que muda além disso entre coletas indica fonte alterada; o FTP não tem TLS nem checksum
CELULA_MINIMA = 5
OUTROS = "Outros capítulos"
ESPEC_OUTRAS = "99"
CAMPOS = ["competencia", "cnes", "espec", "capitulo", "residente", "internacoes", "dias", "dias_uti"]


def _mes_anterior(c: str) -> str:
    a, m = int(c[:4]), int(c[4:])
    return f"{a - 1}12" if m == 1 else f"{a}{m - 1:02d}"


def janela(disponiveis: list[str]) -> list[str]:
    """Os MESES mais recentes, em ordem crescente, exigindo meses consecutivos."""
    if not disponiveis:
        raise ValueError("nenhum arquivo RD de SP no FTP")
    fim = max(disponiveis)
    meses = [fim]
    while len(meses) < MESES:
        meses.append(_mes_anterior(meses[-1]))
    meses.reverse()
    faltam = [m for m in meses if m not in disponiveis]
    if faltam:
        raise ValueError(f"meses ausentes no FTP: {faltam}")
    return meses


def agregar(rd: list[dict], competencia: str) -> list[dict]:
    """Uma competência de AIH vira contagens por hospital, especialidade, capítulo do CID e residência. Nenhum registro individual sai daqui."""
    acc: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])
    invalidos = 0
    for r in rd:
        try:
            dias, uti = int(r["DIAS_PERM"] or 0), int(r["UTI_MES_TO"] or 0)
        except ValueError:
            invalidos += 1
            continue
        if not (0 <= dias <= 3650 and 0 <= uti <= 3650) or r["ESPEC"] not in ESPEC_SIH:
            invalidos += 1
            continue
        chave = (r["CNES"], r["ESPEC"], capitulo_cid(r["DIAG_PRINC"]) or OUTROS, int(r["MUNIC_RES"] == MUNICIPIO))
        a = acc[chave]
        a[0] += 1
        a[1] += dias
        a[2] += uti
    if rd and invalidos > 0.01 * len(rd):
        raise ValueError(f"{invalidos} de {len(rd)} AIH com campos inválidos em {competencia}")
    fundido: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])
    for (cnes, espec, cap, res), (n, d, u) in acc.items():
        if n < CELULA_MINIMA:
            cap = OUTROS
        f = fundido[(cnes, espec, cap, res)]
        f[0] += n
        f[1] += d
        f[2] += u
    return proteger([{"competencia": competencia, "cnes": c, "espec": e, "capitulo": cap, "residente": res, "internacoes": n, "dias": d, "dias_uti": u}
                     for (c, e, cap, res), (n, d, u) in sorted(fundido.items())])


def proteger(linhas: list[dict]) -> list[dict]:
    """Nenhuma célula publicada com menos de CELULA_MINIMA internações aponta uma especialidade nem traz dias de permanência. Idempotente."""
    acc: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in linhas:
        n = int(r["internacoes"])
        espec = r["espec"] if n >= CELULA_MINIMA else ESPEC_OUTRAS
        cap = r["capitulo"] if n >= CELULA_MINIMA else OUTROS
        a = acc[(r["competencia"], r["cnes"], espec, cap, int(r["residente"]))]
        a[0] += n
        a[1] += int(r["dias"])
        a[2] += int(r["dias_uti"])
    return [{"competencia": c, "cnes": h, "espec": e, "capitulo": cap, "residente": res, "internacoes": n, "dias": d if n >= CELULA_MINIMA else 0, "dias_uti": u if n >= CELULA_MINIMA else 0}
            for (c, h, e, cap, res), (n, d, u) in sorted(acc.items())]


def _csv(linhas: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CAMPOS, delimiter=";", lineterminator="\n")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue()


def _ler_existente(destino: Path) -> tuple[dict[str, list[dict]], dict]:
    arq, man = destino / "internacoes.csv", destino / "manifesto.json"
    if not (arq.exists() and man.exists()):
        return {}, {"competencias": {}}
    por_mes: dict[str, list[dict]] = defaultdict(list)
    for r in csv.DictReader(io.StringIO(arq.read_text(encoding="utf-8")), delimiter=";"):
        por_mes[r["competencia"]].append(r)
    return dict(por_mes), json.loads(man.read_text(encoding="utf-8"))


def coletar(acesso_em: date, destino: Path = DESTINO, listar: Callable[[str], list[str]] = ftp_datasus.listar,
            baixar: Callable[[str], tuple[bytes, str]] = ftp_datasus.baixar, ler=ler_dbc) -> list[str]:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    disponiveis = [("20" + m.group(1)) for n in listar(PASTA) if (m := re.fullmatch(r"RDSP(\d{4})\.dbc", n))]
    meses = janela(disponiveis)
    ultima = meses[-1]
    if (acesso_em - date(int(ultima[:4]), int(ultima[4:]), 1)).days > MAX_DIAS_COMPETENCIA:
        raise ValueError(f"última competência do SIH ({ultima}) é antiga demais; a fonte parece parada")
    antigo, man = _ler_existente(destino)
    refazer = [m for m in meses if m not in antigo or m in meses[-REVISAO_MESES:]]
    novos: dict[str, list[dict]] = {}
    origem: dict[str, dict] = {}
    for m in refazer:
        dados, h = baixar(f"{PASTA}/RDSP{m[2:]}.dbc")
        novos[m] = agregar(list(ler(dados, ("MUNIC_MOV", MUNICIPIO))), m)
        origem[m] = {"bytes": len(dados), "sha256": h}
        if not novos[m]:
            raise ValueError(f"nenhuma internação em Sorocaba em {m}; a fonte mudou?")
        if m in antigo:
            antes, depois = sum(int(r["internacoes"]) for r in antigo[m]), sum(r["internacoes"] for r in novos[m])
            if antes and not VARIACAO_MAXIMA[0] <= depois / antes <= VARIACAO_MAXIMA[1]:
                raise ValueError(f"{m}: internações foram de {antes} para {depois} entre coletas; confira a fonte antes de aceitar")
    linhas: list[dict] = []
    for m in meses:
        linhas += novos[m] if m in novos else proteger(antigo[m])
    texto = _csv(linhas)
    destino.mkdir(parents=True, exist_ok=True)
    tmp = destino / "internacoes.csv.tmp"
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, destino / "internacoes.csv")
    comps = {m: man["competencias"].get(m, {}) for m in meses}
    comps.update({m: {**origem[m], "coletado_em": acesso_em.isoformat()} for m in refazer})
    man = {"fonte": "SIH/SUS (AIH reduzida, RD) de SP, DATASUS; recorte: hospital em Sorocaba", "competencias": comps, "primeira": meses[0], "ultima": ultima,
           "sha256_csv": hashlib.sha256(texto.encode("utf-8")).hexdigest(), "verificado_em": acesso_em.isoformat()}
    tmp = destino / "manifesto.tmp"
    tmp.write_text(json.dumps(man, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, destino / "manifesto.json")
    return refazer


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    print("competências coletadas:", coletar(p.parse_args().acesso_em))


if __name__ == "__main__":
    main()
