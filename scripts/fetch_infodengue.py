"""Situação semanal de arboviroses em Sorocaba (InfoDengue, Fiocruz). Só o agregado municipal vai ao repositório."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "infodengue"
HOST = "info.dengue.mat.br"
API = f"https://{HOST}/api/alertcity"
IBGE = "3552205"
DOENCAS = ("dengue", "chikungunya", "zika")
ANO_INICIAL = 2023  # fixo: janela móvel faria a série "encolher" a cada virada de ano e travaria a coleta
DIAS_FONTE_PARADA = 56
LIMITE_BYTES = 4 * 1024 * 1024
CAMPOS = ["se", "data_inicio", "casos", "casos_est", "casos_est_min", "casos_est_max", "nivel", "p_inc100k", "rt"]


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host != HOST:
        raise ValueError(f"requisição fora de https://{HOST}: {r.url.host}")


def _numero(r: dict, campo: str, se: int) -> float | None:
    v = r.get(campo)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        raise ValueError(f"{campo} inválido na SE {se}: {v!r}")
    return v


def normalizar(r: dict) -> dict:
    """Uma linha da API vira um registro validado. `notif_accum_year` é descartado de propósito: não bate com a soma semanal."""
    if not isinstance(r, dict):
        raise ValueError("item da resposta não é um objeto")
    se = r.get("SE")
    if not isinstance(se, int) or isinstance(se, bool) or not (190001 <= se <= 299953 and 1 <= se % 100 <= 53):
        raise ValueError(f"SE inválida: {se!r}")
    if r.get("nivel") not in (1, 2, 3, 4):
        raise ValueError(f"nível inválido na SE {se}: {r.get('nivel')!r}")
    casos = r.get("casos")
    if isinstance(casos, bool) or not isinstance(casos, (int, float)) or not math.isfinite(casos) or casos < 0:
        raise ValueError(f"casos inválidos na SE {se}")
    ms = r.get("data_iniSE")
    if isinstance(ms, bool) or not isinstance(ms, int) or not 0 < ms < 4_000_000_000_000:
        raise ValueError(f"data_iniSE inválida na SE {se}")
    est, lo, hi = (_numero(r, c, se) for c in ("casos_est", "casos_est_min", "casos_est_max"))
    if lo is not None and hi is not None and lo > hi:
        raise ValueError(f"intervalo de estimativa invertido na SE {se}")
    if est is not None and lo is not None and est < lo:
        raise ValueError(f"estimativa abaixo do mínimo na SE {se}")
    inicio = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()
    return {"se": se, "data_inicio": inicio, "casos": int(casos), "casos_est": est, "casos_est_min": lo, "casos_est_max": hi,
            "nivel": r["nivel"], "p_inc100k": _numero(r, "p_inc100k", se), "rt": _numero(r, "Rt", se)}


def _constante_invalida(nome: str):
    raise ValueError(f"constante JSON inválida na resposta: {nome}")


def baixar(c: httpx.Client, doenca: str, ano_ini: int, ano_fim: int) -> tuple[list[dict], str | None]:
    params = {"geocode": IBGE, "disease": doenca, "format": "json", "ew_start": 1, "ew_end": 53, "ey_start": ano_ini, "ey_end": ano_fim}
    for t in range(3):
        try:
            with c.stream("GET", API, params=params) as r:
                r.raise_for_status()
                corpo = bytearray()
                for pedaco in r.iter_bytes(64 * 1024):
                    corpo += pedaco
                    if len(corpo) > LIMITE_BYTES:
                        raise ValueError("resposta acima do limite esperado")
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if t == 2 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500):
                raise RuntimeError(f"falha ao consultar {doenca} ({type(e).__name__})") from None
            time.sleep(2**t * 2)
    dados = json.loads(bytes(corpo), parse_constant=_constante_invalida)
    if not isinstance(dados, list):
        raise ValueError(f"resposta inesperada para {doenca}")
    linhas = {r["se"]: r for r in map(normalizar, dados)}
    versao = max((d["versao_modelo"] for d in dados if isinstance(d.get("versao_modelo"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["versao_modelo"])), default=None)
    return [linhas[k] for k in sorted(linhas)], versao


def csv_texto(linhas: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CAMPOS, delimiter=";", lineterminator="\n")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue()


def coletar(acesso_em: date, destino: Path = DESTINO, transporte: httpx.BaseTransport | None = None) -> list[str]:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    destino.mkdir(parents=True, exist_ok=True)
    arq = destino / "manifesto.json"
    man = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"doencas": {}}
    pendentes: dict[str, tuple[str, dict]] = {}
    with httpx.Client(timeout=30, follow_redirects=True, max_redirects=3, headers={"User-Agent": "SorocabaEmDados/1.0 (+https://github.com/civisbr/sorocaba-em-dados)", "Accept-Encoding": "identity"},
                      event_hooks={"request": [so_host_confiavel]}, transport=transporte) as c:
        for d in DOENCAS:
            linhas, versao = baixar(c, d, ANO_INICIAL, acesso_em.year)
            if not linhas:
                if d == "dengue":
                    raise ValueError("InfoDengue não devolveu nenhuma semana de dengue")
                continue
            antigo = man["doencas"].get(d)
            if antigo and len(linhas) < antigo["n_semanas"]:
                raise ValueError(f"{d}: a série encolheu de {antigo['n_semanas']} para {len(linhas)} semanas")
            parada = (acesso_em - date.fromisoformat(linhas[-1]["data_inicio"])).days
            if d in ("dengue", "chikungunya") and parada > DIAS_FONTE_PARADA:
                raise ValueError(f"{d}: última semana publicada tem {parada} dias; a fonte parece parada")
            texto = csv_texto(linhas)
            pendentes[d] = (texto, {"n_semanas": len(linhas), "primeira_se": linhas[0]["se"], "ultima_se": linhas[-1]["se"],
                                    "sha256_csv": hashlib.sha256(texto.encode("utf-8")).hexdigest(), "versao_modelo": versao, "coletado_em": acesso_em.isoformat()})
    for d, (texto, meta) in pendentes.items():  # só grava depois que tudo foi baixado e validado
        tmp = destino / f"{d}.csv.tmp"
        tmp.write_text(texto, encoding="utf-8")
        os.replace(tmp, destino / f"{d}.csv")
        man["doencas"][d] = meta
    man["fonte"] = "InfoDengue (Fiocruz/FGV), alertcity, geocódigo IBGE 3552205"
    man["verificado_em"] = acesso_em.isoformat()
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(man, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, arq)
    return list(pendentes)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    print("atualizadas:", coletar(p.parse_args().acesso_em) or "nenhuma")


if __name__ == "__main__":
    main()
