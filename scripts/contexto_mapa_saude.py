"""Pontos do mapa de unidades de saúde: posição projetada no mesmo quadro do mapa-base."""

from __future__ import annotations

from collections.abc import Callable

from scripts.contexto_hospitais import _endereco, _telefone, nome_unidade
from scripts.geo import carregar_contorno, dentro
from scripts.saude_codigos import ATENCAO_BASICA, HOSPITALAR, URGENCIA

GRUPOS = (("hospital", "Hospitais", HOSPITALAR), ("upa", "UPAs e pronto atendimento", URGENCIA), ("ubs", "Unidades básicas de saúde", ATENCAO_BASICA), ("caps", "CAPS (saúde mental)", ("70",)))


def contexto_mapa_saude(env: dict, nome_br: Callable[[str], str], mapa: dict, f: Callable[[float, float], tuple[float, float]]) -> dict:
    contorno = carregar_contorno()
    pontos, sem_posicao = [], 0
    for u in (r for r in env["dados"] if r["recorte"] == "unidade"):
        grupo = next((g for g, _, tipos in GRUPOS if u["tipo"] in tipos), None)
        if grupo is None or (grupo == "hospital" and u["leitos"] == 0):
            continue
        if u["lat"] is None or u["lon"] is None or not dentro(contorno, u["lat"], u["lon"]):
            sem_posicao += 1
            continue
        x, y = f(u["lat"], u["lon"])
        pontos.append({
            "grupo": grupo, "nome": nome_unidade(u["nome"], nome_br), "natureza": u["natureza"], "endereco": _endereco(u, nome_br), "telefone": _telefone(u["telefone"]),
            "sus": "Atende pelo SUS" if u["atende_sus"] else "Não atende pelo SUS" if grupo == "hospital" else "", "x": round(x, 1), "y": round(y, 1), "lat": f"{u['lat']:.5f}", "lon": f"{u['lon']:.5f}",
        })
        p = pontos[-1]
        p["detalhes"] = [["Natureza", p["natureza"]], ["SUS", p["sus"]], ["Endereço", p["endereco"]], ["Telefone", p["telefone"]]]
    pontos.sort(key=lambda p: (p["y"], p["x"]))  # em baixo por último: sobreposições mostram o ponto da frente
    contagem = {g: sum(1 for p in pontos if p["grupo"] == g) for g, _, _ in GRUPOS}
    return {"pontos": pontos, "sem_posicao": sem_posicao, "grupos": [{"id": g, "nome": n, "n": contagem[g]} for g, n, _ in GRUPOS if contagem[g]],
            "nomes": {g: n for g, n, _ in GRUPOS}, "ordem": ",".join(g for g, _, _ in GRUPOS)}
