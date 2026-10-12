"""Radares fixos da Semob em data/public/radares.json. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

PRECISOES_EXATAS = {"endereço", "câmera no OSM"}
PRECISOES_APROXIMADAS = {"cruzamento", "km", "número", "via"}
PRECISOES = PRECISOES_EXATAS | PRECISOES_APROXIMADAS
FONTE_POSICAO = "© colaboradores do OpenStreetMap, ODbL 1.0"
RAIZ = Path(__file__).resolve().parent.parent


def ler_coordenadas(p: Path) -> dict[str, dict[str, str]]:
    if not p.exists():
        return {}
    with p.open(encoding="utf-8", newline="") as f:
        return {r["ponto"]: r for r in csv.DictReader(f, delimiter=";")}


def ponto_valido(texto: str, ponto: str) -> dict[str, float]:
    lat, lon, *_ = texto.split(",")
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon) and -24 < lat < -23 and -48 < lon < -47):
        raise ValueError(f"coordenada candidata implausível em {ponto}")
    return {"lat": lat, "lon": lon}


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    with (raw / "radares.csv").open(encoding="utf-8", newline="") as f:
        dados = [{"ponto": r["ponto"], "local": r["local"], "tipo": r["tipo"], "velocidade_kmh": int(r["velocidade_kmh"])} for r in csv.DictReader(f, delimiter=";")]
    coord = ler_coordenadas(raw / "coordenadas.csv")
    for r in dados:
        c = coord.get(r["ponto"])
        if c and c["local"] == r["local"] and c["lat"]:  # o texto do local mudou: a posição antiga não vale
            lat, lon = float(c["lat"]), float(c["lon"])
            if not (math.isfinite(lat) and math.isfinite(lon) and -24 < lat < -23 and -48 < lon < -47) or c["precisao"] not in PRECISOES:
                raise ValueError(f"coordenada implausível em {r['ponto']}")
            r.update(lat=lat, lon=lon, precisao=c["precisao"], detalhe=c.get("detalhe", ""), fonte_posicao=FONTE_POSICAO)
        elif c and c["local"] == r["local"] and c.get("candidatas"):
            r["posicoes_candidatas"] = "|".join(f"{q['lat']:.6f},{q['lon']:.6f}" for q in (ponto_valido(x, r["ponto"]) for x in c["candidatas"].split("|")))
            r["fonte_posicao"] = FONTE_POSICAO
    desatualizados = [r["ponto"] for r in dados if r["ponto"] not in coord or coord[r["ponto"]]["local"] != r["local"]]
    if desatualizados:
        print(f"aviso: {len(desatualizados)} radares novos ou com local alterado sem geocodificação: {desatualizados[:10]}; rode scripts.geocode_radares")
    n_pos = sum(1 for r in dados if r.get("precisao") in PRECISOES_EXATAS)
    n_aprox = sum(1 for r in dados if r.get("precisao") in PRECISOES_APROXIMADAS)
    n_grupo = sum(1 for r in dados if "posicoes_candidatas" in r)
    if len(dados) != man["n_radares"]:
        raise ValueError("radares.csv diverge do manifesto")
    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    declarado = man.get("n_declarado_pela_pagina")
    d = date.fromisoformat(man["verificado_em"])
    return Envelope(
        painel="transito",
        fonte=Fonte(nome="Semob Sorocaba — locais de operação dos radares", url=man["url"], licenca="Informação pública publicada pela Prefeitura (sem licença explícita); coordenadas (lat, lon, precisao): © colaboradores do OpenStreetMap, ODbL 1.0", acesso_em=d),
        referencia=Referencia(inicio=d, fim=d, granularidade=Granularidade.MENSAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL, n_registros=len(dados),
            notas=[
                "Lista oficial de radares fixos em operação, publicada pela Semob. Não informa quantas multas cada radar aplicou.",
                *([f"A página declara {declarado} radares, mas a paginação oficial lista {man['n_radares']}; os {declarado - man['n_radares']} restantes não são acessíveis pela página e ficam fora." ] if declarado and declarado != man["n_radares"] else []),
                "O número de série dos equipamentos não é reproduzido aqui.",
                f"A Semob não publica coordenadas. Posição com erro típico de dezenas de metros (o ponto do OSM é colaborativo e não confirmado pela Semob) para {n_pos} dos {len(dados)} radares: endereço com número ou câmera de velocidade mapeada que casa de forma única com a via e a velocidade da lista. Para outros {n_aprox}, posição só aproximada, calculada a partir do texto do local sobre as vias, endereços e marcos de km do OpenStreetMap (© colaboradores do OpenStreetMap, licença ODbL): cruzamento das duas vias, km da rodovia, número entre endereços vizinhos ou meio da via. O erro vai de dezenas de metros (cruzamento, número) a centenas ou alguns quilômetros (meio da via, km). Para os últimos {n_grupo}, só o conjunto de posições possíveis na via (não se sabe qual câmera é de qual radar).",
                f"SHA-256 do manifesto de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "radares")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "radares.json")
    args = p.parse_args()
    e = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
