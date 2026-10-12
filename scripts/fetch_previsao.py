"""Previsão do tempo para Sorocaba: INMET (oficial, 5 dias) e Open-Meteo (modelo, 7 dias).

A previsão é efêmera: fica em data/raw/previsao (fora do git) e é regerada a cada deploy.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from datetime import date
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "raw" / "previsao"
INMET = "https://apiprevmet3.inmet.gov.br/previsao/3552205"
OPEN_METEO = (
    "https://api.open-meteo.com/v1/forecast?latitude=-23.5015&longitude=-47.4526"
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max"
    "&timezone=America%2FSao_Paulo&forecast_days=7"
)
HOSTS = {"apiprevmet3.inmet.gov.br", "api.open-meteo.com"}
LIMITE_BYTES = 2 * 1024 * 1024
CAMPOS_INMET = ("resumo", "temp_max", "temp_min", "umidade_max", "umidade_min", "dir_vento", "int_vento", "nascer", "ocaso", "dia_semana")


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host not in HOSTS:
        raise ValueError(f"requisição fora dos hosts esperados: {r.url}")


def baixar(c: httpx.Client, url: str) -> dict:
    for n in range(3):
        try:
            with c.stream("GET", url) as r:
                r.raise_for_status()
                corpo = bytearray()
                for pedaco in r.iter_bytes(64 * 1024):
                    corpo += pedaco
                    if len(corpo) > LIMITE_BYTES:  # a resposta do INMET traz ícones em base64 (~270 KB)
                        raise ValueError(f"{url} acima do limite esperado")
                return json.loads(bytes(corpo))
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if n == 2 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500):
                raise
            time.sleep(2**n * 2)
    raise RuntimeError("inalcançável")


DIA_BR = re.compile(r"\d{2}/\d{2}/\d{4}")
HORA_INMET = re.compile(r"\d{2}h\d{2}")
TEXTOS_INMET = {"resumo": 240, "dir_vento": 12, "int_vento": 40, "dia_semana": 24}


MAX_DIAS_INMET, MAX_PERIODOS = 10, 4


def _texto_limpo(x: object, limite: int) -> str | None:
    """Texto curto sem caracteres de controle nem de direção (bidi), que poderiam enganar a leitura."""
    if not isinstance(x, str):
        return None
    t = x.strip()
    return t if 0 < len(t) <= limite and not any(unicodedata.category(c) in ("Cc", "Cf") for c in t) else None


def bloco_inmet(v: object) -> dict | None:
    """Não grava no site o que o INMET mandar fora do formato conhecido; pares incompletos (umidade, vento) são anulados juntos."""
    if not isinstance(v, dict):
        return None
    saida: dict = {}
    for k in CAMPOS_INMET:
        x = v.get(k)
        if k in TEXTOS_INMET:
            saida[k] = _texto_limpo(x, TEXTOS_INMET[k])
        elif k in ("temp_max", "temp_min"):
            saida[k] = x if isinstance(x, (int, float)) and not isinstance(x, bool) and -20 <= x <= 55 else None
        elif k in ("umidade_max", "umidade_min"):
            saida[k] = x if isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 100 else None
        else:  # nascer, ocaso
            saida[k] = x if isinstance(x, str) and HORA_INMET.fullmatch(x) else None
    if saida["temp_max"] is None or saida["temp_min"] is None or saida["temp_min"] > saida["temp_max"] or not saida["resumo"]:
        return None
    if saida["umidade_max"] is None or saida["umidade_min"] is None or saida["umidade_min"] > saida["umidade_max"]:
        saida["umidade_max"] = saida["umidade_min"] = None  # a faixa só vale inteira
    if saida["dir_vento"] is None or saida["int_vento"] is None:
        saida["dir_vento"] = saida["int_vento"] = None
    return saida


def validar_inmet(dias: object) -> dict:
    """Dias dd/mm/aaaa válidos, com blocos manhã/tarde/noite ou um bloco único; levanta ValueError se nada se aproveitar."""
    if not isinstance(dias, dict):
        raise ValueError("resposta do INMET em formato inesperado")
    saida = {}
    for dia, periodos in list(dias.items())[:MAX_DIAS_INMET]:
        if not isinstance(dia, str) or not DIA_BR.fullmatch(dia) or not isinstance(periodos, dict):
            continue
        try:
            date(int(dia[6:]), int(dia[3:5]), int(dia[:2]))
        except ValueError:
            continue
        blocos = {"dia": bloco_inmet(periodos)} if "resumo" in periodos else {per: bloco_inmet(v) for per, v in list(periodos.items())[:MAX_PERIODOS] if isinstance(per, str) and len(per) <= 12}
        blocos = {per: b for per, b in blocos.items() if b}
        if blocos:
            saida[dia] = blocos
    if not saida:
        raise ValueError("nenhum dia do INMET passou na validação")
    return saida


def coletar(acesso_em: date, destino: Path = DESTINO) -> list[str]:
    if acesso_em > date.today():
        raise ValueError(f"acesso_em {acesso_em} está no futuro")
    destino.mkdir(parents=True, exist_ok=True)
    feitos = []
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 SorocabaEmDados/1.0"}, event_hooks={"request": [so_host_confiavel]}) as c:
        for nome, url in (("open_meteo", OPEN_METEO), ("inmet", INMET)):
            try:
                dados = baixar(c, url)
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as e:  # uma fonte fora do ar não derruba a outra
                print(f"{nome}: indisponível ({type(e).__name__})")
                (destino / f"{nome}.json").unlink(missing_ok=True)
                continue
            if nome == "inmet":
                # Nos dias mais distantes o INMET manda um único bloco; nos próximos, manhã/tarde/noite.
                try:
                    dados = validar_inmet(dados["3552205"])
                except (ValueError, KeyError, TypeError, RecursionError) as e:
                    print(f"{nome}: resposta rejeitada ({type(e).__name__}: {e})")
                    (destino / f"{nome}.json").unlink(missing_ok=True)
                    continue
            (destino / f"{nome}.json").write_text(json.dumps({"coletado_em": acesso_em.isoformat(), "dados": dados}, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            feitos.append(nome)
    return feitos


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acesso-em", required=True, type=date.fromisoformat)
    args = p.parse_args()
    print("coletados:", coletar(args.acesso_em) or "nenhum")


if __name__ == "__main__":
    main()
