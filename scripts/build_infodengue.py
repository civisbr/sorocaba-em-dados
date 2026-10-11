"""Situação de dengue e chikungunya em data/public/saude_doencas.json. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent
DIAS_DESATUALIZADO = 56
ORDEM = ("dengue", "chikungunya", "zika")


def _num(v: str, tipo=float):
    return tipo(v) if v not in ("", None) else None


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    if "dengue" not in man["doencas"]:
        raise ValueError("manifesto sem dengue")
    hoje = date.fromisoformat(man["verificado_em"])
    dados: list[dict] = []
    inicios: list[date] = []
    for d in (x for x in ORDEM if x in man["doencas"]):
        with (raw / f"{d}.csv").open(encoding="utf-8", newline="") as f:
            linhas = list(csv.DictReader(f, delimiter=";"))
        for r in linhas:
            se = int(r["se"])
            ini = date.fromisoformat(r["data_inicio"])
            inicios.append(ini)
            dados.append({"recorte": "semanal", "grupo": d, "se": se, "ano": se // 100, "semana": se % 100, "data_inicio": r["data_inicio"],
                          "casos": int(r["casos"]), "casos_est": _num(r["casos_est"]), "est_min": _num(r["casos_est_min"]), "est_max": _num(r["casos_est_max"]),
                          "nivel": int(r["nivel"]), "inc100k": _num(r["p_inc100k"]), "rt": _num(r["rt"])})
        ultima = linhas[-1]
        idade = (hoje - date.fromisoformat(ultima["data_inicio"])).days
        dados.append({"recorte": "situacao", "grupo": d, "se": int(ultima["se"]), "categoria": "atual" if idade <= DIAS_DESATUALIZADO else "desatualizado", "n": idade})
    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    return Envelope(
        painel="saude_doencas",
        fonte=Fonte(nome="InfoDengue (Fiocruz/FGV) — alertas municipais de arboviroses", url="https://info.dengue.mat.br/", licenca="Dados abertos do InfoDengue; citar a fonte", acesso_em=hoje),
        referencia=Referencia(inicio=min(inicios), fim=max(inicios) + timedelta(days=6), granularidade=Granularidade.SEMANAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.ESTIMATIVA, n_registros=len(dados),
            notas=[
                "Casos notificados são suspeitas registradas no sistema de vigilância; não são casos confirmados.",
                "As últimas semanas costumam subir depois, porque as notificações chegam com atraso. O InfoDengue estima o número final (casos estimados, com intervalo).",
                "O nível de alerta (verde, amarelo, laranja, vermelho) é calculado pelo modelo do InfoDengue com casos, clima e transmissão; não é um aviso oficial da Prefeitura.",
                "O campo de notificações acumuladas do ano da API não é usado: não bate com a soma das semanas.",
                f"Uma doença sem semanas nos últimos {DIAS_DESATUALIZADO} dias (hoje, o zika) aparece como sem dado recente.",
                f"SHA-256 do manifesto de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "infodengue")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "saude_doencas.json")
    a = p.parse_args()
    e = construir(a.raw)
    a.saida.parent.mkdir(parents=True, exist_ok=True)
    a.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
