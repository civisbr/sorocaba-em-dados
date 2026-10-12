"""Posição aproximada dos radares da Semob, a partir do texto do local (OpenStreetMap, dados ODbL).

A Semob não publica coordenadas. Este script roda à mão, não no cron, e grava data/raw/radares/coordenadas.csv.
Duas fontes, nesta ordem: (1) endereço com número no Nominatim, só quando o OSM tem o número da porta;
(2) câmera de velocidade mapeada no OSM (Overpass), com maxspeed igual ao do radar, quando uma única câmera casa com a via do radar
e vice-versa. Casos ambíguos ficam sem posição: é melhor omitir do que apontar o lugar errado.
Radar sem posição exata nem câmera candidata recebe posição aproximada de scripts/geo_aprox.py (cruzamento, km da rodovia, número vizinho ou meio da via).
Pontos fora do contorno do município são descartados. Uso moderado, conforme as políticas dos dois serviços.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

from scripts.geo import carregar_contorno, dentro

RAIZ = Path(__file__).resolve().parent.parent
RADARES = RAIZ / "data" / "raw" / "radares" / "radares.csv"
SAIDA = RAIZ / "data" / "raw" / "radares" / "coordenadas.csv"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
HOSTS = {"nominatim.openstreetmap.org", "overpass-api.de"}
CAMPOS = ["ponto", "local", "lat", "lon", "precisao", "fonte_osm", "osm_ref", "geocodificado_em", "candidatas", "detalhe"]
AGENTE = "SorocabaEmDados/1.0 (+https://github.com/civisbr/sorocaba-em-dados)"
TITULOS = {
    "AV": "AVENIDA", "R": "RUA", "DR": "DOUTOR", "DRA": "DOUTORA", "PROF": "PROFESSOR", "PROFA": "PROFESSORA", "ENG": "ENGENHEIRO",
    "CEL": "CORONEL", "PE": "PADRE", "CAP": "CAPITÃO", "GAL": "GENERAL", "MAL": "MARECHAL", "TEN": "TENENTE", "DEP": "DEPUTADO",
    "SEN": "SENADOR", "ALM": "ALMIRANTE", "VER": "VEREADOR", "PRES": "PRESIDENTE", "STA": "SANTA", "STO": "SANTO", "TRAV": "TRAVESSA",
    "ROD": "RODOVIA", "AL": "ALAMEDA", "PC": "PRAÇA", "PÇA": "PRAÇA", "CÔN": "CÔNEGO", "MONS": "MONSENHOR", "CDOR": "COMENDADOR",
}
FONTE = "OpenStreetMap contributors (ODbL)"
CACHE_OSM = RAIZ / "data" / "raw" / "osm" / "cache" / "aproximacao.json"


def so_host_confiavel(r: httpx.Request) -> None:
    if r.url.scheme != "https" or r.url.host not in HOSTS:
        raise ValueError(f"requisição fora dos hosts esperados: {r.url.host}")


def expandir(nome: str) -> str:
    palavras = re.sub(r"[.,]", " ", nome.upper()).split()
    return " ".join(TITULOS.get(p, p) for p in palavras)


REFERENCIA = re.compile(r"\b(?:PR[ÓO]X\.?|APROX\.?|COM)\s+(?=AV|R\b|RUA|PÇA|PRA[ÇC]A|TRAV|ROD|AL\b)")
NUMERO = re.compile(r"N\s*[º°O.]\s*(\d+)\b|,\s*(\d+)\b")


def interpretar(local: str) -> tuple[str, list[str], str | None]:
    """('cruzamento'|'endereco'|'rua', vias, número). Via de referência ("PRÓX RUA X") é descartada."""
    s = re.sub(r"\((?:C/B|B/C)\)", " ", local.upper())
    antes = REFERENCIA.split(s)[0]
    s = antes if antes.strip() else s
    s = re.sub(r"\b(OPOSTO|PR[ÓO]X\.?)\s*(AO|A)?\b", " ", s)
    if re.search(r"\sX\s", s):
        return "cruzamento", [expandir(p) for p in re.split(r"\sX\s", s) if p.strip()], None
    m = NUMERO.search(s)
    rua = expandir(re.split(r",|N\s*[º°O.]\s*\d", s)[0])
    return ("endereco", [rua], m.group(1) or m.group(2)) if m else ("rua", [rua], None)


def contexto_http() -> httpx.Client:
    return httpx.Client(timeout=60, headers={"User-Agent": AGENTE}, follow_redirects=True, max_redirects=3, event_hooks={"request": [so_host_confiavel]})


def buscar_endereco(c: httpx.Client, rua: str, numero: str) -> tuple[float, float, str] | None:
    """Só aceita resultado que seja o próprio imóvel e traga o número pedido; via, bairro ou cidade não servem."""
    r = c.get(NOMINATIM, params={"street": f"{numero} {rua.title()}", "city": "Sorocaba", "state": "São Paulo", "country": "Brasil", "format": "jsonv2", "addressdetails": 1, "limit": 1})
    r.raise_for_status()
    achados = r.json()
    if not achados:
        return None
    a = achados[0]
    end = a.get("address", {})
    pedida = palavras(rua)
    if a.get("addresstype") not in ("house", "building") or str(end.get("house_number", "")).strip() != numero or not pedida or not pedida <= palavras(end.get("road", "")):
        return None
    return float(a["lat"]), float(a["lon"]), f"{a.get('osm_type')}/{a.get('osm_id')}"


STOP = {"AVENIDA", "RUA", "DE", "DA", "DO", "DAS", "DOS", "DOUTOR", "DOUTORA", "PROFESSOR", "PROFESSORA", "TRAVESSA", "RODOVIA", "ALAMEDA", "PRACA"}
RAIO_VIA_M = 30


def palavras(nome: str) -> set[str]:
    sem_acento = unicodedata.normalize("NFD", nome.upper()).encode("ascii", "ignore").decode()
    return {w for w in re.sub(r"[^A-Z ]", " ", sem_acento).split() if w not in STOP}


def distancia_m(lat: float, lon: float, geom: list[dict]) -> float:
    k = 111_000 * math.cos(math.radians(lat))
    pts = [((g["lon"] - lon) * k, (g["lat"] - lat) * 111_000) for g in geom]
    melhor = float("inf")
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        n = dx * dx + dy * dy
        t = 0.0 if n == 0 else max(0.0, min(1.0, -(x0 * dx + y0 * dy) / n))
        melhor = min(melhor, math.hypot(x0 + t * dx, y0 + t * dy))
    return melhor


def overpass(c: httpx.Client, consulta: str) -> list[dict]:
    for t in range(5):
        r = c.post(OVERPASS, data={"data": consulta})
        if r.status_code == 200:
            corpo = r.json()
            if corpo.get("remark") or "elements" not in corpo:  # resposta truncada faria outra câmera parecer única
                raise RuntimeError(f"Overpass devolveu resposta incompleta: {corpo.get('remark')}")
            return corpo["elements"]
        if r.status_code < 500 and r.status_code != 429:
            r.raise_for_status()
        time.sleep(15 * (t + 1))
    raise RuntimeError("Overpass indisponível")


def cameras_osm(c: httpx.Client, contorno: list[tuple[float, float]]) -> list[dict]:
    """Câmeras de velocidade mapeadas no OSM dentro do município, com os nomes das vias a até 30 m."""
    caixa = f"{min(y for _, y in contorno)},{min(x for x, _ in contorno)},{max(y for _, y in contorno)},{max(x for x, _ in contorno)}"
    cams = [e for e in overpass(c, f'[out:json][timeout:60];node({caixa})["highway"="speed_camera"];out;') if dentro(contorno, e["lat"], e["lon"])]
    time.sleep(2)
    vias = overpass(c, f'[out:json][timeout:90];node({caixa})["highway"="speed_camera"]->.c;way(around.c:{RAIO_VIA_M})["highway"]["name"];out tags geom;')
    for cam in cams:
        cam["vias"] = [palavras(v["tags"]["name"]) for v in vias if distancia_m(cam["lat"], cam["lon"], v["geometry"]) <= RAIO_VIA_M]
    return cams


def candidatos(radares: list[dict], cams: list[dict]) -> dict[str, frozenset[int]]:
    out = {}
    for r in radares:
        _, vias, _ = interpretar(r["local"])
        ch = [palavras(v) for v in vias]
        out[r["ponto"]] = frozenset(
            i for i, cam in enumerate(cams)
            if cam["tags"].get("maxspeed") == str(r["velocidade_kmh"])
            and all(any(k and k <= n for n in cam["vias"]) for k in ch)
        )
    return out


def casar_cameras(radares: list[dict], cams: list[dict]) -> dict[str, dict]:
    """Radar -> câmera quando a correspondência é única nos dois sentidos (mesma via e mesma velocidade)."""
    cand = candidatos(radares, cams)
    uso = Counter(i for s in cand.values() for i in s)
    return {p: cams[next(iter(s))] for p, s in cand.items() if len(s) == 1 and uso[next(iter(s))] == 1}


def casar_grupos(radares: list[dict], cams: list[dict]) -> dict[str, list[dict]]:
    """Radar -> câmeras candidatas, quando N radares da lista partilham exatamente as mesmas N câmeras.
    As posições existem, mas não se sabe qual câmera é de qual radar."""
    cand = candidatos(radares, cams)
    por_conjunto: dict[frozenset[int], list[str]] = {}
    for p, s in cand.items():
        if len(s) > 1:
            por_conjunto.setdefault(s, []).append(p)
    return {p: [cams[i] for i in sorted(s)] for s, ps in por_conjunto.items() if len(s) == len(ps) for p in ps}


def ler_csv(p: Path, chave: str = "ponto") -> dict[str, dict]:
    with p.open(encoding="utf-8", newline="") as f:
        return {r[chave]: r for r in csv.DictReader(f, delimiter=";")}


def main() -> None:
    contorno = carregar_contorno()
    radares = list(ler_csv(RADARES).values())
    antigos = ler_csv(SAIDA) if SAIDA.exists() else {}
    hoje = date.today().isoformat()
    saida: dict[str, dict] = {}
    from scripts import geo_aprox

    osm = geo_aprox.montar(geo_aprox.baixar_osm(CACHE_OSM))
    with contexto_http() as c:
        todas = cameras_osm(c, contorno)
        cams = casar_cameras(radares, todas)
        grupos = casar_grupos(radares, todas)
        for i, r in enumerate(radares, 1):
            ant = antigos.get(r["ponto"])
            achado = None
            tipo, vias, numero = interpretar(r["local"])
            # "endereço" é guardado: o OSM raramente muda um número de porta. Apague a linha para refazer.
            if ant and ant["local"] == r["local"] and ant["precisao"] == "endereço" and dentro(contorno, float(ant["lat"]), float(ant["lon"])):
                achado = (float(ant["lat"]), float(ant["lon"]), "endereço", ant.get("osm_ref", ""), ant.get("geocodificado_em", ""))
            elif tipo == "endereco" and numero and "OPOSTO" not in r["local"].upper():  # o OSM aponta o imóvel, não o lado oposto da via
                try:
                    pos = buscar_endereco(c, vias[0], numero)
                except (httpx.HTTPError, json.JSONDecodeError) as e:
                    print(f"{r['ponto']}: falha no Nominatim ({type(e).__name__})")
                    pos = None
                time.sleep(1.2)
                if pos and dentro(contorno, pos[0], pos[1]):
                    achado = (pos[0], pos[1], "endereço", pos[2], hoje)
            if achado is None and r["ponto"] in cams:
                cam = cams[r["ponto"]]
                achado = (cam["lat"], cam["lon"], "câmera no OSM", f"node/{cam['id']}", hoje)
            cand = "" if achado else "|".join(f"{g['lat']:.6f},{g['lon']:.6f},node/{g['id']}" for g in grupos.get(r["ponto"], []))
            detalhe = ""
            if achado is None and not cand:
                aprox = geo_aprox.aproximar(r["local"], osm, lambda la, lo: dentro(contorno, la, lo))
                if aprox:
                    achado, detalhe = (aprox.lat, aprox.lon, aprox.nivel, "", hoje), aprox.detalhe
            saida[r["ponto"]] = {
                "ponto": r["ponto"], "local": r["local"], "lat": f"{achado[0]:.6f}" if achado else "", "lon": f"{achado[1]:.6f}" if achado else "",
                "precisao": achado[2] if achado else "", "fonte_osm": FONTE if achado or cand else "", "osm_ref": achado[3] if achado else "", "geocodificado_em": achado[4] if achado else hoje if cand else "", "candidatas": cand, "detalhe": detalhe,
            }
            print(f"[{i}/{len(radares)}] {r['ponto']} {saida[r['ponto']]['precisao'] or 'sem posição'}")
    perdidos = sorted(p for p, a in antigos.items() if a["lat"] and not saida.get(p, {}).get("lat"))
    ganhos = sum(1 for p, a in saida.items() if a["lat"] and not antigos.get(p, {}).get("lat"))
    print(f"antes: {sum(1 for a in antigos.values() if a['lat'])}; depois: {sum(1 for a in saida.values() if a['lat'])}; novos: {ganhos}; perdidos: {perdidos}; em grupo: {sum(1 for a in saida.values() if a['candidatas'])}")
    tmp = SAIDA.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(saida[k] for k in sorted(saida))
    tmp.replace(SAIDA)


if __name__ == "__main__":
    main()
