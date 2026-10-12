"""Posição aproximada de um local escrito em texto ("AV. X, Nº 100", "AV. X x RUA Y", "RODOVIA SP-270 KM 94+017M") sobre dados do OpenStreetMap (ODbL).

Puro e offline: recebe vias, endereços e marcos de km já baixados (ver `baixar_osm`). Cada resultado traz um nível de precisão, do mais ao menos exato:
cruzamento, km (percorrendo a rodovia a partir do marco de km mais próximo), número (interpolado entre endereços vizinhos do OSM) e via (meio da via).
Rua homônima em trechos distantes só recebe posição se o número ou a via de referência desempatar. Quem chama decide o que fazer com cada nível.
"""

from __future__ import annotations

import difflib
import hashlib
import heapq
import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from scripts.geocode_radares import TITULOS, contexto_http, overpass

BBOX = "-23.62,-47.64,-23.36,-47.30"
MANIFESTO = Path(__file__).resolve().parent.parent / "data" / "raw" / "osm" / "manifesto_aproximacao.json"
RAIO_CRUZAMENTO_M = 60
RAIO_VIAS_PROXIMAS_M = 300  # "próx. à rua X": o OSM nem sempre liga as duas vias no cruzamento
RAIO_AGRUPAR_M = 150
LIMITE_INTERPOLACAO_M = 2000
LIMITE_NUMERO_VIZINHO = 300
LIMITE_AMBIGUIDADE = 0.3
RAIO_ENDERECO_M = 80
M_POR_GRAU = 111_000
STOP = {"AVENIDA", "RUA", "DE", "DA", "DO", "DAS", "DOS", "E", "DOUTOR", "DOUTORA", "PROFESSOR", "PROFESSORA", "TRAVESSA", "RODOVIA", "ALAMEDA", "PRACA", "ESTRADA"}
CLASSES_RODOVIA = {"motorway", "trunk", "primary", "secondary", "tertiary"}

Ponto = tuple[float, float]


@dataclass(frozen=True)
class Posicao:
    lat: float
    lon: float
    nivel: str
    detalhe: str = ""


@dataclass
class Via:
    palavras: frozenset[str]
    pontos: list[Ponto]
    n_palavras: int = 0


@dataclass
class OSM:
    vias: list[Via]
    enderecos: list[tuple[frozenset[str], int, float, float, int]]
    brutas: list[dict]
    marcos: dict[tuple[str, int], dict[int, list[Ponto]]]


def _registrar(destino: Path) -> None:
    """Manifesto versionado do extrato (o cache em si fica fora do git): data, hash e contagens, para auditar de onde saiu cada posição aproximada."""
    corpo = destino.read_bytes()
    dados = json.loads(corpo)
    MANIFESTO.write_text(json.dumps({
        "acesso_em": date.fromtimestamp(destino.stat().st_mtime).isoformat(), "fonte": "OpenStreetMap via Overpass (ODbL 1.0)", "bbox": BBOX,
        "sha256": hashlib.sha256(corpo).hexdigest(), "contagens": {k: len(v) for k, v in sorted(dados.items())},
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def baixar_osm(destino: Path) -> dict:
    """Vias nomeadas, endereços com número e marcos de km do município; guarda em `destino` para não repetir a consulta."""
    if destino.exists():
        if not MANIFESTO.exists():
            _registrar(destino)
        elif json.loads(MANIFESTO.read_text(encoding="utf-8"))["sha256"] != hashlib.sha256(destino.read_bytes()).hexdigest():
            raise ValueError("o cache do OSM não confere com o manifesto; apague data/raw/osm/cache/ para baixar de novo")
        return json.loads(destino.read_text(encoding="utf-8"))
    saida = {}
    with contexto_http() as c:
        for nome, consulta in (
            ("vias", f'[out:json][timeout:180];way({BBOX})["highway"]["name"];out tags geom;'),
            ("rodovias", f'[out:json][timeout:180];way({BBOX})["highway"]["ref"~"^(SP|BR)"];out tags geom;'),
            ("enderecos", f'[out:json][timeout:180];nwr({BBOX})["addr:housenumber"]["addr:street"];out tags center;'),
            ("marcos", f'[out:json][timeout:120];node({BBOX})["highway"="milestone"]["distance"];out;'),
        ):
            saida[nome] = overpass(c, consulta)
            time.sleep(5)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(saida, ensure_ascii=False), encoding="utf-8")
    _registrar(destino)
    return saida


def palavras(nome: str, juntar: bool = False) -> frozenset[str]:
    """Palavras significativas de um nome de via, sem acento e com "quinze" = "15". Com `juntar` (nomes do OSM), inclui a junção de vizinhas: "Fru-Fru" casa com "FRUFRU"."""
    s = unicodedata.normalize("NFD", nome.upper()).encode("ascii", "ignore").decode()
    s = re.sub(r"\bQUINZE\b", "15", s)
    ps = re.findall(r"[A-Z0-9]+", s)
    return frozenset({p for p in ps if p not in STOP} | ({a + b for a, b in zip(ps, ps[1:]) if a not in STOP and b not in STOP} if juntar else set()))


def _ref_rodovia(ref: str) -> set[tuple[str, int]]:
    return {("BR" if t == "BR" else "SP", int(n)) for t, n in re.findall(r"\b(SPA|SPI|SPM|SP|BR)[- ]?0*(\d+)", ref.upper())}


def montar(bruto: dict) -> OSM:
    vias = [Via(palavras(e["tags"]["name"], juntar=True), [(g["lat"], g["lon"]) for g in e["geometry"]], len(palavras(e["tags"]["name"]))) for e in bruto["vias"] if e.get("geometry")]
    enderecos = []
    for e in bruto["enderecos"]:
        n = re.match(r"\d+", e["tags"]["addr:housenumber"].strip())
        centro = e if "lat" in e else e.get("center")
        if n and centro:
            enderecos.append((palavras(e["tags"]["addr:street"], juntar=True), int(n.group()), centro["lat"], centro["lon"], len(palavras(e["tags"]["addr:street"]))))
    marcos: dict[tuple[str, int], dict[int, list[Ponto]]] = {}
    for e in bruto["marcos"]:
        if str(e["tags"].get("distance", "")).isdigit():
            for r in _ref_rodovia(e["tags"].get("ref", "")):
                marcos.setdefault(r, {}).setdefault(int(e["tags"]["distance"]), []).append((e["lat"], e["lon"]))
    return OSM(vias, enderecos, bruto.get("rodovias", []), marcos)


def _semelhante(pedida: str, nome: str) -> bool:
    if pedida == nome:
        return True
    if len(pedida) <= 4:  # sigla ou abreviatura ("M" = Maria, "COM" = Comendador)
        return nome.startswith(pedida)
    return len(pedida) >= 5 and len(nome) >= 5 and pedida[0] == nome[0] and difflib.SequenceMatcher(None, pedida, nome).ratio() >= 0.84


def casa(pedidas: frozenset[str], nome: frozenset[str]) -> bool:
    return bool(pedidas) and all(any(_semelhante(p, n) for n in nome) for p in pedidas)


def _metros(a: Ponto, b: Ponto) -> float:
    return math.hypot((a[0] - b[0]) * M_POR_GRAU, (a[1] - b[1]) * M_POR_GRAU * math.cos(math.radians(a[0])))


def _no_segmento(p: Ponto, a: Ponto, b: Ponto) -> tuple[float, Ponto]:
    k = math.cos(math.radians(p[0]))
    ax, ay, bx, by = (a[1] - p[1]) * k, a[0] - p[0], (b[1] - p[1]) * k, b[0] - p[0]
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / n))
    q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return _metros(p, q), q


def _mais_proximo(p: Ponto, pontos: list[Ponto]) -> tuple[float, Ponto]:
    if len(pontos) == 1:
        return _metros(p, pontos[0]), pontos[0]
    return min((_no_segmento(p, a, b) for a, b in zip(pontos, pontos[1:])), key=lambda r: r[0])


def _caixa(pontos: list[Ponto], folga_m: float) -> tuple[float, float, float, float]:
    f = folga_m / M_POR_GRAU
    return min(p[0] for p in pontos) - f, max(p[0] for p in pontos) + f, min(p[1] for p in pontos) - f, max(p[1] for p in pontos) + f


def _caixas_cruzam(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1] and a[2] <= b[3] and b[2] <= a[3]


def _agrupar(vias: list[Via]) -> list[list[Via]]:
    """Vias de mesmo nome encostadas (até 150 m) formam um trecho; trechos distantes são ruas homônimas."""
    caixas = [_caixa(v.pontos, RAIO_AGRUPAR_M) for v in vias]
    pai = list(range(len(vias)))

    def raiz(i: int) -> int:
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    for i in range(len(vias)):
        for j in range(i + 1, len(vias)):
            if raiz(i) != raiz(j) and _caixas_cruzam(caixas[i], caixas[j]) and min(_mais_proximo(p, vias[j].pontos)[0] for p in vias[i].pontos) <= RAIO_AGRUPAR_M:
                pai[raiz(i)] = raiz(j)
    por_raiz: dict[int, list[Via]] = {}
    for i, v in enumerate(vias):
        por_raiz.setdefault(raiz(i), []).append(v)
    return list(por_raiz.values())


def _comprimento(vias: list[Via]) -> float:
    return sum(_metros(a, b) for v in vias for a, b in zip(v.pontos, v.pontos[1:]))


def trechos(osm: OSM, pedidas: frozenset[str]) -> list[list[Via]]:
    """Trechos com o nome pedido, do maior ao menor, descartando os muito menores que o maior (vielas e ruas sem importância)."""
    achadas = [v for v in osm.vias if casa(pedidas, v.palavras)]
    exatas = [v for v in achadas if v.n_palavras == len(pedidas)]  # "Rua Aparecida" não é "Rua Maria Aparecida Souza"
    achadas = exatas or achadas
    grupos = sorted(_agrupar(achadas), key=_comprimento, reverse=True) if achadas else []
    return [g for g in grupos if _comprimento(g) >= LIMITE_AMBIGUIDADE * _comprimento(grupos[0])]


def _dist_ao_trecho(p: Ponto, trecho: list[Via]) -> float:
    return min(_mais_proximo(p, v.pontos)[0] for v in trecho)


def _snap(p: Ponto, trecho: list[Via]) -> Ponto:
    return min((_mais_proximo(p, v.pontos) for v in trecho), key=lambda r: r[0])[1]


def _interseccao(a0: Ponto, a1: Ponto, b0: Ponto, b1: Ponto) -> Ponto | None:
    """Ponto onde dois segmentos se cruzam (em plano local), ou None."""
    k = math.cos(math.radians(a0[0]))
    ax, ay, bx, by = (a1[1] - a0[1]) * k, a1[0] - a0[0], (b1[1] - b0[1]) * k, b1[0] - b0[0]
    den = ax * by - ay * bx
    if den == 0:
        return None
    cx, cy = (b0[1] - a0[1]) * k, b0[0] - a0[0]
    t, u = (cx * by - cy * bx) / den, (cx * ay - cy * ax) / den
    return (a0[0] + t * (a1[0] - a0[0]), a0[1] + t * (a1[1] - a0[1])) if 0 <= t <= 1 and 0 <= u <= 1 else None


def cruzamento(a: list[Via], b: list[Via]) -> tuple[float, Posicao | None]:
    """(distância entre as vias, posição); a posição só existe se as vias se encontram ou passam a até 300 m uma da outra."""
    melhor: tuple[float, Ponto, Ponto] | None = None
    for va in a:
        ca = _caixa(va.pontos, 2000)
        for vb in b:
            if not _caixas_cruzam(ca, _caixa(vb.pontos, 2000)):
                continue
            for s0, s1 in zip(va.pontos, va.pontos[1:]):
                for t0, t1 in zip(vb.pontos, vb.pontos[1:]):
                    x = _interseccao(s0, s1, t0, t1)
                    if x:
                        return 0.0, Posicao(x[0], x[1], "cruzamento")
            for p, outra in [(p, vb.pontos) for p in va.pontos] + [(p, va.pontos) for p in vb.pontos]:
                d, q = _mais_proximo(p, outra)
                if melhor is None or d < melhor[0]:
                    melhor = (d, p, q)
    if melhor is None:
        return float("inf"), None
    d, p, q = melhor
    if d > RAIO_VIAS_PROXIMAS_M:
        return d, None
    return d, Posicao((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, "cruzamento", "" if d <= RAIO_CRUZAMENTO_M else f"as duas vias passam a {round(d, -1):.0f} m uma da outra")


def meio_da_via(trecho: list[Via]) -> Posicao:
    pts = [p for v in trecho for p in v.pontos]
    centro = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    q = min(pts, key=lambda p: _metros(p, centro))
    return Posicao(q[0], q[1], "via")


def por_numero(osm: OSM, pedidas: frozenset[str], trecho: list[Via], numero: int) -> Posicao | None:
    """Interpola entre os dois endereços do OSM que cercam o número, ou usa o vizinho mais próximo; só endereços colados ao trecho valem."""
    candidatos = [(n, (la, lo)) for ps, n, la, lo, _ in osm.enderecos if casa(pedidas, ps) and _dist_ao_trecho((la, lo), trecho) <= RAIO_ENDERECO_M]
    if not candidatos:
        return None
    exato = next((c for c in candidatos if c[0] == numero), None)
    if exato:
        return Posicao(exato[1][0], exato[1][1], "número", f"endereço nº {numero} no OSM")
    abaixo = max((c for c in candidatos if c[0] < numero), key=lambda c: c[0], default=None)
    acima = min((c for c in candidatos if c[0] > numero), key=lambda c: c[0], default=None)
    if abaixo and acima and _metros(abaixo[1], acima[1]) <= LIMITE_INTERPOLACAO_M:
        t = (numero - abaixo[0]) / (acima[0] - abaixo[0])
        p = (abaixo[1][0] + t * (acima[1][0] - abaixo[1][0]), abaixo[1][1] + t * (acima[1][1] - abaixo[1][1]))
        q = _snap(p, trecho)
        return Posicao(q[0], q[1], "número", f"entre os nº {abaixo[0]} e {acima[0]}")
    vizinho = min(candidatos, key=lambda c: abs(c[0] - numero))
    if abs(vizinho[0] - numero) <= LIMITE_NUMERO_VIZINHO:
        return Posicao(vizinho[1][0], vizinho[1][1], "número", f"perto do nº {vizinho[0]}")
    return None


def _km(texto: str) -> float | None:
    m = re.search(r"KM\s*[:.]?\s*0*(\d+)(?:\s*[+,]\s*(\d+))?(?:\s*M(?:ETROS)?\s*[:.]?\s*(\d+))?", texto.upper())
    if not m:
        return None
    metros = m.group(2) or m.group(3) or "0"
    return int(m.group(1)) + int(metros.ljust(3, "0")[:3]) / 1000 if len(metros) <= 3 else None


def _grafo(osm: OSM, rodovia: tuple[str, int]) -> dict[Ponto, list[tuple[Ponto, float]]]:
    g: dict[Ponto, list[tuple[Ponto, float]]] = {}
    for e in osm.brutas:
        t = e.get("tags", {})
        if rodovia in _ref_rodovia(t.get("ref", "")) and t.get("highway") in CLASSES_RODOVIA and e.get("geometry"):
            pts = [(round(p["lat"], 6), round(p["lon"], 6)) for p in e["geometry"]]
            for a, b in zip(pts, pts[1:]):
                d = _metros(a, b)
                g.setdefault(a, []).append((b, d))
                g.setdefault(b, []).append((a, d))
    return g


def _percorrer(g: dict[Ponto, list[tuple[Ponto, float]]], inicio: Ponto, alvo_m: float, sentido: Ponto | None, dentro) -> Ponto | None:
    """Ponto do grafo a `alvo_m` metros do início, no sentido do vetor `sentido` (Dijkstra; as duas pistas da rodovia dão resultados a poucos metros um do outro).
    Sem sentido conhecido, vale se os candidatos dentro do município estiverem todos juntos."""
    if not g:
        return None
    partida = min(g, key=lambda p: _metros(p, inicio))
    if _metros(partida, inicio) > 150:
        return None
    dist = {partida: 0.0}
    fila = [(0.0, partida)]
    while fila:
        d, p = heapq.heappop(fila)
        if d > dist.get(p, float("inf")) or d > alvo_m + 100:
            continue
        for q, w in g[p]:
            if d + w < dist.get(q, float("inf")):
                dist[q] = d + w
                heapq.heappush(fila, (d + w, q))
    cands = [p for p, d in dist.items() if abs(d - alvo_m) <= 100]
    if sentido is not None:
        cands = [p for p in cands if (p[0] - partida[0]) * sentido[0] + (p[1] - partida[1]) * sentido[1] > 0]
    else:
        cands = [p for p in cands if dentro(p[0], p[1])]
    if not cands or (sentido is None and any(_metros(p, cands[0]) > 1000 for p in cands)):
        return None
    return min(cands, key=lambda p: abs(dist[p] - alvo_m))


def por_km(osm: OSM, rodovia: tuple[str, int], km: float, dentro) -> Posicao | None:
    """Anda pela rodovia (OSM) a partir do marco de km mais próximo. O sentido do aumento do km vem de outro marco da mesma rodovia."""
    marcos = osm.marcos.get(rodovia, {})
    if not marcos:
        return None
    ancora = min(marcos, key=lambda k: abs(k - km))
    a = marcos[ancora][0]
    outro = min((k for k in marcos if k != ancora), key=lambda k: (abs(k - ancora), k), default=None)
    sentido = None
    if outro is not None:
        b = min(marcos[outro], key=lambda p: _metros(a, p))
        sinal = (1 if outro > ancora else -1) * (1 if km >= ancora else -1)
        sentido = ((b[0] - a[0]) * sinal, (b[1] - a[1]) * sinal)
    achado = a if km == ancora else _percorrer(_grafo(osm, rodovia), a, abs(km - ancora) * 1000, sentido, dentro)
    if not achado:
        return None
    dist = f"{abs(km - ancora):g}".replace(".", ",")
    return Posicao(achado[0], achado[1], "km", f"km {km:g}".replace(".", ",") + f", a {dist} km do marco {ancora}" + ("; marco distante, erro maior" if abs(km - ancora) > 5 else ""))


@dataclass
class Local:
    via: str | None = None
    numero: int | None = None
    outra: str | None = None
    rodovia: tuple[str, int] | None = None
    km: float | None = None


def _titulos(nome: str) -> str:
    return " ".join(TITULOS.get(p, p) for p in re.sub(r"[.,]", " ", nome).split())


VIA = r"(?:AV|R|RUA|AVENIDA|PÇA|PRA[ÇC]A|TRAV|ROD|AL|PONTE|ESTRADA)\b"


def interpretar(local: str) -> Local:
    s = " ".join(local.upper().split())
    s = re.sub(r"\(\s*(?:C\s*/\s*B|B\s*/\s*C|CB|BC)\s*\)", " ", s)
    rod = re.search(r"\b(SPM|SPA|SP|BR)[- ]?0*(\d+)\b", s)
    if rod and "KM" in s:
        return Local(rodovia=("BR" if rod.group(1) == "BR" else "SP", int(rod.group(2))), km=_km(s))
    s = re.sub(r"\bN\s*[º°]\s*\.?|\bN\.\s*(?=\d)|\bN\s+(?=\d)", " NUM ", s)
    s = re.sub(r"[ºª°]", "", s)
    numero = None
    m = re.search(r"\bNUM\s*(\d+)|\bPR[ÓO]X\w*\.?\s*(\d{2,5})\b|[,\s](\d{2,5})\s*$|,\s*(\d{1,5})\b", s)
    if m:
        numero = int(next(g for g in m.groups() if g))
    corte = re.split(r",|\bNUM\b|\bOPOSTO\b|\bPR[ÓO]X\w*\.?|\bAPROX\.?|\bX\b|\bCOM\b(?=\s+(?:A\s+)?" + VIA + ")", s, maxsplit=1)[0]
    via = _titulos(re.sub(r"\s\d+\s*$", "", corte).strip())
    outra = None
    ref = re.search(r"\bX\s+(.+)|\bCOM\s+(?:A\s+)?(" + VIA + r".+)|\b(?:PR[ÓO]X\w*\.?|APROX\.?)\s*(?:AO?\s+|À\s+)?(?:\d+\s*M\s+AP[ÓO]S\s+(?:A\s+)?)?(" + VIA + r".+)|\bOPOSTO\s+(?:AO?\s+|À\s+)?(" + VIA + r".+)", s)
    if ref:
        outra = _titulos(re.split(r",|\bNUM\b|\(", next(g for g in ref.groups() if g))[0].strip())
        if outra.startswith("A "):
            outra = outra[2:]
    return Local(via=via or None, numero=numero, outra=outra or None)


def _centro(trecho: list[Via]) -> Ponto:
    pts = [p for v in trecho for p in v.pontos]
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _mesma_via(candidatos: list[list[Via]]) -> bool:
    """Trechos a até 3 km do maior: o mesmo logradouro cortado no mapa, não ruas homônimas."""
    return all(_metros(_centro(candidatos[0]), _centro(t)) <= 3000 for t in candidatos[1:])


def aproximar(local: str, osm: OSM, dentro) -> Posicao | None:
    """Melhor posição aproximada para o texto do local, ou None quando não há dado confiável o bastante. `dentro(lat, lon)` limita ao município."""
    l = interpretar(local)
    if l.rodovia:
        achado = por_km(osm, l.rodovia, l.km, dentro) if l.km is not None else None
        return achado if achado and dentro(achado.lat, achado.lon) else None
    if not l.via:
        return None
    pedidas = palavras(l.via)
    candidatos = trechos(osm, pedidas)
    if not candidatos:
        return None
    escolha = candidatos[0] if len(candidatos) == 1 else None
    if l.outra:
        b = trechos(osm, palavras(l.outra))
        pares = [(cruzamento(t, tb), t) for t in candidatos for tb in b]
        if pares:
            (d, pos), t = min(pares, key=lambda x: x[0][0])
            if pos and dentro(pos.lat, pos.lon):
                return pos
            if escolha is None and d <= 300:
                escolha = t
    if escolha is None and l.numero is not None:
        com_numero = [(t, por_numero(osm, pedidas, t, l.numero)) for t in candidatos]
        com_numero = [(t, p) for t, p in com_numero if p]
        if com_numero:  # o endereço que cerca o número vale mais que o vizinho; empate fica com o trecho mais longo (a lista já vem do maior ao menor)
            escolha = min(com_numero, key=lambda tp: tp[1].detalhe.startswith("perto"))[0]
    nota = ""
    if escolha is None and _mesma_via(candidatos):
        escolha = candidatos[0]
    elif escolha is None and _comprimento(candidatos[0]) >= 1.5 * _comprimento(candidatos[1]):
        escolha, nota = candidatos[0], "nome repetido em outro trecho do município; escolhido o maior"
    if escolha is None:
        return None
    if l.numero is not None:
        achado = por_numero(osm, pedidas, escolha, l.numero)
        if achado and dentro(achado.lat, achado.lon):
            return achado
    achado = meio_da_via(escolha)
    return Posicao(achado.lat, achado.lon, achado.nivel, nota) if dentro(achado.lat, achado.lon) else None
