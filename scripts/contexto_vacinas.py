"""Contexto de renderização do painel de vacinas."""

from __future__ import annotations

import re
from datetime import date

from scripts.build_vacinas import PUBLICOS

DIAS_CONFERENCIA_VELHA = 120


def _ordem_idade(idade: str) -> tuple:
    partes = idade.split()
    if len(partes) == 2 and partes[0].isdigit() and partes[1] in ("meses", "anos"):
        n = int(partes[0])
        return (0, n * 12 if partes[1] == "anos" else n)
    if idade == "Ao nascer" or idade == "Ao saber da gravidez":
        return (-1, 0)
    m = re.search(r"(\d+)ª semana", idade)
    return (0, int(m.group(1))) if m else (1, 0)


def contexto_vacinas(env: dict, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    d = env["dados"]
    por_publico = []
    for pub in PUBLICOS:
        itens = [r for r in d if r["recorte"] == "calendario" and r["publico"] == pub]
        idades: dict[str, list[dict]] = {}
        for r in itens:
            idades.setdefault(r["idade"], []).append(r)
        ordem = sorted(idades, key=lambda i: (_ordem_idade(i), i))
        por_publico.append({"nome": pub, "idades": [{"idade": i, "vacinas": idades[i]} for i in ordem]})
    campanhas = []
    for r in (x for x in d if x["recorte"] == "campanha"):
        ini, fim = date.fromisoformat(r["inicio"]), date.fromisoformat(r["fim"])
        situacao = "em andamento" if ini <= hoje <= fim else "encerrada" if hoje > fim else "prevista"
        campanhas.append({**r, "situacao": situacao, "inicio_br": ini.strftime("%d/%m/%Y"), "fim_br": fim.strftime("%d/%m/%Y")})
    campanhas.sort(key=lambda c: c["inicio"], reverse=True)
    conferido = date.fromisoformat(env["fonte"]["acesso_em"])
    dias = (hoje - conferido).days
    return {"publicos": por_publico, "campanhas": campanhas, "ativas": [c for c in campanhas if c["situacao"] != "encerrada"], "conferido_em": conferido.isoformat(),
            "dias_conferencia": dias if dias > DIAS_CONFERENCIA_VELHA else None, "ref_vac": f"conferido em {conferido.strftime('%d/%m/%Y')}", "n_vacinas": len({r["vacina"] for r in d if r["recorte"] == "calendario"})}
