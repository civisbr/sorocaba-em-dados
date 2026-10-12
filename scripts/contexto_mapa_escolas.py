"""Pontos do mapa de escolas: posição aproximada (geocode_escolas.py) projetada no quadro dos mapas interativos."""

from __future__ import annotations

import re
from collections.abc import Callable

REDES = (("municipal", "Municipal", "Escola municipal"), ("estadual", "Estadual", "Escola estadual"), ("federal", "Federal", "Escola federal"), ("privada", "Privada", "Escola privada"))
ETAPAS = (("infantil", "Educação infantil", "mat_infantil"), ("iniciais", "Anos iniciais (1º ao 5º)", "mat_anos_iniciais"), ("finais", "Anos finais (6º ao 9º)", "mat_anos_finais"),
          ("medio", "Ensino médio", "mat_medio"), ("eja", "Educação de jovens e adultos", "mat_eja"),
          ("outras", "Outras (técnica, profissional, especial ou sem matrícula regular)", None))
POSICAO = {"porta": "pelo endereço do Censo Escolar", "rua": "pela rua, em trecho curto (aproximada)"}  # "rua" só para endereço sem número


def _endereco(e: dict, nome_br: Callable[[str], str]) -> str:
    if not e.get("endereco"):
        return ""
    rua, _, numero = e["endereco"].rpartition(", ")
    return f"{nome_br(rua)}, {numero}" if rua else nome_br(e["endereco"])


def contexto_mapa_escolas(env: dict, nome_br: Callable[[str], str], f: Callable[[float, float], tuple[float, float]]) -> dict | None:
    pontos, sem_posicao, restritas = [], 0, 0
    for e in env["dados"]:
        if e.get("atendimento_restrito"):  # unidade prisional ou socioeducativa: não é opção de matrícula e não vai ao mapa
            restritas += 1
            continue
        if e.get("lat") is None:
            sem_posicao += 1
            continue
        grupo = next(g for g, rede, _ in REDES if rede == e["rede"])
        etapas = [k for k, _, campo in ETAPAS if campo and (e.get(campo) or 0) > 0] or ["outras"]
        x, y = f(e["lat"], e["lon"])
        pontos.append({"g": grupo, "n": nome_br(re.sub(r"\s+", " ", e["escola"])), "e": " ".join(etapas), "x": round(x), "y": round(y), "la": f"{e['lat']:.4f}", "lo": f"{e['lon']:.4f}",
                       "u": f"{e['co_inep']}/", "en": _endereco(e, nome_br), "b": nome_br(e["bairro"]) if e.get("bairro") else "", "p": e["posicao"]})
    if not pontos:
        return None
    pontos.sort(key=lambda p: (p["y"], p["x"]))
    contagem = {g: sum(1 for p in pontos if p["g"] == g) for g, _, _ in REDES}
    cont_etapa = {k: sum(1 for p in pontos if k in p["e"].split()) for k, _, _ in ETAPAS}
    valores = {**{k: n for k, n, _ in ETAPAS}, **{k: v[0].upper() + v[1:] for k, v in POSICAO.items()}}
    return {"pontos": pontos, "campos": [["etapas", "Etapas"], ["end", "Endereço"], ["bairro", "Bairro"], ["pos", "Posição no mapa"]], "valores": valores, "sem_posicao": sem_posicao, "total": len(env["dados"]) - restritas, "restritas": restritas,
            "redes": [{"id": g, "nome": r, "n": contagem[g]} for g, r, _ in REDES if contagem[g]],
            "etapas": [{"id": k, "nome": n, "n": cont_etapa[k]} for k, n, _ in ETAPAS if cont_etapa[k]],
            "nomes": {g: rotulo for g, _, rotulo in REDES}, "ordem": ",".join(g for g, _, _ in REDES if contagem[g]),
            "n_porta": sum(1 for p in pontos if p["p"] == "porta"), "n_rua": sum(1 for p in pontos if p["p"] == "rua")}
