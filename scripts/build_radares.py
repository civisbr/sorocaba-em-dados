"""Radares fixos da Semob em data/public/radares.json. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    with (raw / "radares.csv").open(encoding="utf-8", newline="") as f:
        dados = [{"ponto": r["ponto"], "local": r["local"], "tipo": r["tipo"], "velocidade_kmh": int(r["velocidade_kmh"])} for r in csv.DictReader(f, delimiter=";")]
    if len(dados) != man["n_radares"]:
        raise ValueError("radares.csv diverge do manifesto")
    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    declarado = man.get("n_declarado_pela_pagina")
    d = date.fromisoformat(man["verificado_em"])
    return Envelope(
        painel="transito",
        fonte=Fonte(nome="Semob Sorocaba — locais de operação dos radares", url=man["url"], licenca="Informação pública publicada pela Prefeitura (sem licença explícita)", acesso_em=d),
        referencia=Referencia(inicio=d, fim=d, granularidade=Granularidade.SEMANAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL, n_registros=len(dados),
            notas=[
                "Lista oficial de radares fixos em operação, publicada pela Semob. Não informa quantas multas cada radar aplicou.",
                *([f"A página declara {declarado} radares, mas a paginação oficial lista {man['n_radares']}; os {declarado - man['n_radares']} restantes não são acessíveis pela página e ficam fora." ] if declarado and declarado != man["n_radares"] else []),
                "O número de série dos equipamentos não é reproduzido aqui.",
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
