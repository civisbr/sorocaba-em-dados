"""Erro da estimativa por numeração (geo_aprox.por_numeracao) em avenidas com muitos endereços no OSM. Manual; usa o cache de data/raw/osm/cache/.

Testes por avenida: (1) validação cruzada, tirando um endereço por vez (interpolação); (2) extrapolação, escondendo os 20% (e os 40%) de maiores números
e prevendo-os com os demais (é o que acontece quando o número do radar passa do último endereço conhecido).
"""

from __future__ import annotations

import json
import statistics

from scripts.geo_aprox import RAIO_ENDERECO_M, _ajuste, _eixo, _projetar, casa, montar, palavras, trechos
from scripts.geo_aprox import baixar_osm
from scripts.geocode_radares import CACHE_OSM

AVENIDAS = ("DOM AGUIRRE", "LUIZ MENDES ALMEIDA", "VICTOR ANDREWS", "ITAVUVU", "ARMANDO PANNUNZIO", "AFONSO VERGUEIRO", "GUALBERTO MOREIRA")


def pares(osm, nome):
    ps = palavras(nome)
    ts = trechos(osm, ps)
    eixo = _eixo(ts[0]) if ts else None
    if not eixo:
        return []
    achados = [(n, _projetar(eixo, (la, lo))) for p, n, la, lo, _ in osm.enderecos if casa(ps, p)]
    return [(n, s) for n, (d, s) in achados if d <= RAIO_ENDERECO_M]


def main() -> None:
    osm = montar(baixar_osm(CACHE_OSM))
    cruzada, extrap, extrap40 = [], [], []
    for nome in AVENIDAS:
        ps = pares(osm, nome)
        if len(ps) < 12:
            print(f"{nome}: {len(ps)} endereços, ignorada")
            continue
        for i, (n, s) in enumerate(ps):
            a, b, _ = _ajuste(ps[:i] + ps[i + 1 :])
            cruzada.append(abs(a * n + b - s))
        ordenados = sorted(ps)
        for fracao, destino in ((0.8, extrap), (0.6, extrap40)):
            corte = int(len(ordenados) * fracao)
            a, b, r2 = _ajuste(ordenados[:corte])
            destino += [abs(a * n + b - s) for n, s in ordenados[corte:]]
        print(f"{nome}: {len(ps)} endereços")
    for rotulo, e in (("cruzada (interpolação)", cruzada), ("extrapolação (20% maiores números)", extrap), ("extrapolação (40% maiores números)", extrap40)):
        if e:
            e = sorted(e)
            print(f"{rotulo}: n={len(e)} mediana={statistics.median(e):.0f} m p90={e[int(0.9 * len(e))]:.0f} m máx={e[-1]:.0f} m")


if __name__ == "__main__":
    main()
