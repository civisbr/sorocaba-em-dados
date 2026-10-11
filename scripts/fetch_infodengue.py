"""Situação semanal de arboviroses em Sorocaba (InfoDengue, Fiocruz). Só o agregado municipal vai ao repositório."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
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
ANOS_ATRAS = 3
LIMITE_BYTES = 4 * 1024 * 1024
CAMPOS = ["se", "data_inicio", "casos", "casos_est", "casos_est_min", "casos_est_max", "nivel", "p_inc100k", "rt"]


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host != HOST:
        raise ValueError(f"requisição fora de https://{HOST}: {r.url.host}")


def normalizar(r: dict) -> dict:
    """Uma linha da API vira um registro validado. `notif_accum_year` é descartado de propósito: não bate com a soma semanal."""
    se = r.get("SE")
    if not isinstance(se, int) or not 190001 <= se <= 299953:
        raise ValueError(f"SE inválida: {se!r}")
    if r.get("nivel") not in (1, 2, 3, 4):
        raise ValueError(f"nível inválido na SE {se}: {r.get('nivel')!r}")
    if not isinstance(r.get("casos"), (int, float)) or r["casos"] < 0:
        raise ValueError(f"casos inválidos na SE {se}")
    inicio = datetime.fromtimestamp(r["data_iniSE"] / 1000, tz=timezone.utc).date().isoformat()
    return {
        "se": se, "data_inicio": inicio, "casos": int(r["casos"]),
        "casos_est": r.get("casos_est"), "casos_est_min": r.get("casos_est_min"), "casos_est_max": r.get("casos_est_max"),
        "nivel": r["nivel"], "p_inc100k": r.get("p_inc100k"), "rt": r.get("Rt"),
    }


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
    dados = json.loads(bytes(corpo))
    if not isinstance(dados, list):
        raise ValueError(f"resposta inesperada para {doenca}")
    linhas = {r["se"]: r for r in map(normalizar, dados)}
    versao = max((d.get("versao_modelo") for d in dados if d.get("versao_modelo")), default=None)
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
    with httpx.Client(timeout=30, follow_redirects=True, max_redirects=3, headers={"User-Agent": "SorocabaEmDados/1.0 (+https://github.com/civisbr/sorocaba-em-dados)"},
                      event_hooks={"request": [so_host_confiavel]}, transport=transporte) as c:
        for d in DOENCAS:
            linhas, versao = baixar(c, d, acesso_em.year - ANOS_ATRAS, acesso_em.year)
            if not linhas:
                if d == "dengue":
                    raise ValueError("InfoDengue não devolveu nenhuma semana de dengue")
                continue
            antigo = man["doencas"].get(d)
            if antigo and len(linhas) < antigo["n_semanas"]:
                raise ValueError(f"{d}: a série encolheu de {antigo['n_semanas']} para {len(linhas)} semanas")
            texto = csv_texto(linhas)
            pendentes[d] = (texto, {"n_semanas": len(linhas), "primeira_se": linhas[0]["se"], "ultima_se": linhas[-1]["se"],
                                    "sha256_csv": hashlib.sha256(texto.encode("utf-8")).hexdigest(), "versao_modelo": versao, "coletado_em": acesso_em.isoformat()})
    for d, (texto, meta) in pendentes.items():  # só grava depois que tudo foi baixado e validado
        (destino / f"{d}.csv").write_text(texto, encoding="utf-8")
        man["doencas"][d] = meta
    man["fonte"] = "InfoDengue (Fiocruz/FGV), alertcity, geocódigo IBGE 3552205"
    man["verificado_em"] = acesso_em.isoformat()
    arq.write_text(json.dumps(man, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return list(pendentes)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    print("atualizadas:", coletar(p.parse_args().acesso_em) or "nenhuma")


if __name__ == "__main__":
    main()
