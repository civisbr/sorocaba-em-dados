"""Posição aproximada das escolas de Sorocaba a partir do endereço do Censo Escolar (OpenStreetMap/Nominatim, dados ODbL).

O INEP publica endereço (rua, número, CEP), não coordenadas. Este script roda à mão, não no cron, e grava data/raw/inep/coordenadas.csv.
Dois níveis, por ordem: "porta" (o Nominatim achou o imóvel com o número pedido na mesma rua) e "rua" (só a rua, e só quando ela é curta:
o ponto é o centro de um trecho de até 400 m). Resultado fora do município, de rua longa ou de rua diferente da pedida é descartado: é melhor
deixar a escola sem ponto do que apontar o lugar errado. Uso moderado, conforme a política do Nominatim (1 pedido por segundo).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import time
import unicodedata
from datetime import date
from pathlib import Path

import httpx

from scripts.mapa_base import BASE as BASE_OSM
from scripts.geo import carregar_contorno, dentro
from scripts.geocode_radares import NOMINATIM, contexto_http, expandir, palavras

RAIZ = Path(__file__).resolve().parent.parent
CENSO = RAIZ / "data" / "raw" / "inep" / "censo_escolar.csv"
SAIDA = RAIZ / "data" / "raw" / "inep" / "coordenadas.csv"
CAMPOS = ["co_inep", "lat", "lon", "precisao", "osm_ref", "endereco_consultado", "geocodificado_em"]
RUA_CURTA_M = 400
DIST_BAIRRO_PORTA_M = 3000  # ponto muito longe do bairro informado no Censo costuma ser rua homônima de outro bairro
DIST_BAIRRO_RUA_M = 1500


def numero_da_porta(texto: str) -> str | None:
    t = (texto or "").strip()
    if re.fullmatch(r"\d{1,3}( \d{3})", t):  # o Censo grava milhar com espaço ("5 515")
        t = t.replace(" ", "")
    return t if re.fullmatch(r"\d{1,6}", t) else None


def normaliza(texto: str) -> str:
    sem = unicodedata.normalize("NFD", texto.upper()).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", sem).split())


def centros_de_bairro() -> dict[str, list[tuple[float, float]]]:
    base = json.loads(BASE_OSM.read_text(encoding="utf-8"))
    centros: dict[str, list[tuple[float, float]]] = {}
    for b in base["bairros"]:
        centros.setdefault(normaliza(b["nome"]), []).append((b["lat"], b["lon"]))
    return centros


def metros(a: tuple[float, float], lat: float, lon: float) -> float:
    return math.hypot((a[1] - lon) * 111_000 * math.cos(math.radians(lat)), (a[0] - lat) * 111_000)


def diagonal_m(caixa: list[str]) -> float:
    s, n, w, e = (float(x) for x in caixa)
    return math.hypot((e - w) * 111_000 * math.cos(math.radians((s + n) / 2)), (n - s) * 111_000)


def buscar(c: httpx.Client, rua: str, numero: str | None, contorno, cep: str = "", centros: list[tuple[float, float]] | None = None) -> tuple[float, float, str, str] | None:
    consulta = f"{numero} {rua.title()}" if numero else rua.title()
    r = c.get(NOMINATIM, params={"street": consulta, "city": "Sorocaba", "state": "São Paulo", "country": "Brasil", "format": "jsonv2", "addressdetails": 1, "limit": 1})
    r.raise_for_status()
    achados = r.json()
    if not achados:
        return None
    a, end = achados[0], achados[0].get("address", {})
    if palavras(rua) != palavras(end.get("road", "")) or not palavras(rua):  # nome da via igual, não subconjunto
        return None
    postal = re.sub(r"\D", "", end.get("postcode", ""))
    if len(postal) == 8 and len(cep) == 8 and postal[:5] != cep[:5]:
        return None
    lat, lon = float(a["lat"]), float(a["lon"])
    if not dentro(contorno, lat, lon):
        return None
    ref = f"{a.get('osm_type')}/{a.get('osm_id')}"
    if numero and str(end.get("house_number", "")).strip() == numero and a.get("category") != "highway":
        nivel, limite = "porta", DIST_BAIRRO_PORTA_M
    elif not numero and a.get("category") == "highway" and a.get("boundingbox") and diagonal_m(a["boundingbox"]) <= RUA_CURTA_M:
        nivel, limite = "rua", DIST_BAIRRO_RUA_M  # com número pedido e só a via achada, o ponto seria o meio de um trecho qualquer: descarta
    else:
        return None
    if centros and min(metros(c0, lat, lon) for c0 in centros) > limite:
        return None
    return lat, lon, nivel, ref


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--refazer", action="store_true", help="ignora as posições já gravadas")
    p.add_argument("--limite", type=int, default=0, help="só as primeiras N escolas (teste)")
    a = p.parse_args()
    contorno = carregar_contorno()
    centros_bairro = centros_de_bairro()
    feitos: dict[str, dict] = {}
    if SAIDA.exists() and not a.refazer:
        feitos = {r["co_inep"]: r for r in csv.DictReader(SAIDA.open(encoding="utf-8"), delimiter=";")}
    with CENSO.open(encoding="utf-8", newline="") as f:
        escolas = [r for r in csv.DictReader(f, delimiter=";") if r["TP_SITUACAO_FUNCIONAMENTO"] == "1" and r.get("DS_ENDERECO")]
    if a.limite:
        escolas = escolas[: a.limite]
    tentadas = {r["CO_ENTIDADE"] for r in escolas} & set(feitos)
    hoje = date.today().isoformat()
    novas = 0
    with contexto_http() as c:
        for i, e in enumerate(escolas, 1):
            cod = e["CO_ENTIDADE"]
            if cod in tentadas:
                continue
            rua = expandir(e["DS_ENDERECO"])
            try:
                achado = buscar(c, rua, numero_da_porta(e["NU_ENDERECO"]), contorno, re.sub(r"\D", "", e.get("CO_CEP", "")), centros_bairro.get(normaliza(e.get("NO_BAIRRO", ""))))
            except ValueError as err:
                raise SystemExit(f"{cod}: resposta recusada ({err}); abortando") from None
            except httpx.HTTPStatusError as err:
                if err.response.status_code in (403, 429):  # bloqueio ou limite de uso: insistir violaria a política do Nominatim
                    gravar(feitos)
                    raise SystemExit(f"{cod}: Nominatim respondeu {err.response.status_code}; abortando (retry-after: {err.response.headers.get('retry-after')})") from None
                print(f"{cod}: falha HTTP {err.response.status_code}; fica para a próxima rodada")
                time.sleep(5)
                continue
            except httpx.HTTPError as err:
                print(f"{cod}: falha ({type(err).__name__}); fica para a próxima rodada")
                time.sleep(5)
                continue
            feitos[cod] = {"co_inep": cod, "lat": f"{achado[0]:.5f}" if achado else "", "lon": f"{achado[1]:.5f}" if achado else "", "precisao": achado[2] if achado else "", "osm_ref": achado[3] if achado else "", "endereco_consultado": f"{rua}, {e['NU_ENDERECO']}", "geocodificado_em": hoje}
            novas += 1
            if novas % 25 == 0:
                gravar(feitos)
                print(f"{i}/{len(escolas)}")
            time.sleep(1.1)
    gravar(feitos)
    manifesto(feitos, hoje)
    ok = [r for r in feitos.values() if r["precisao"]]
    print(f"{len(ok)} com posição de {len(feitos)} tentadas; porta: {sum(r['precisao'] == 'porta' for r in ok)}, rua: {sum(r['precisao'] == 'rua' for r in ok)}")


def manifesto(feitos: dict[str, dict], hoje: str) -> None:
    ok = [r for r in feitos.values() if r["precisao"]]
    m = {"fonte": "Nominatim (OpenStreetMap, ODbL 1.0) a partir de DS_ENDERECO e NU_ENDERECO do Censo Escolar (INEP)", "endpoint": NOMINATIM, "rua_curta_m": RUA_CURTA_M, "geocodificado_em": hoje,
         "sha256_csv": hashlib.sha256(SAIDA.read_bytes()).hexdigest(), "n_tentadas": len(feitos), "n_porta": sum(r["precisao"] == "porta" for r in ok), "n_rua": sum(r["precisao"] == "rua" for r in ok),
         "n_sem_posicao": len(feitos) - len(ok)}
    (SAIDA.parent / "manifesto_coordenadas.json").write_text(json.dumps(m, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def gravar(feitos: dict[str, dict]) -> None:
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with SAIDA.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(feitos.values(), key=lambda r: r["co_inep"]))


if __name__ == "__main__":
    main()
