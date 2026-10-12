"""Contexto de renderização da situação metrológica dos radares (Inmetro)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from scripts.texto_local import legivel, rotulo_posicao

LINK_CONSULTA = "https://servicos.rbmlq.gov.br/Instrumento"
DIAS_RECENTE = 180  # registro vencido há mais que isso, no mesmo endereço de um vigente, é quase sempre equipamento trocado
DIAS_COLETA_VELHA = 14


def _br(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "sem data"


def _endereco(local: str) -> str:
    """Rua e número normalizados, para reconhecer o mesmo endereço escrito de formas diferentes."""
    t = unicodedata.normalize("NFD", local.upper()).encode("ascii", "ignore").decode()
    t = re.sub(r"\((C/B|B/C)\)", " ", t)
    t = re.sub(r"\bN\s*[O.]?\s*(\d+)", r"N \1", t)
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", t).split())


def contexto_inmetro(env: dict, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    linhas = []
    for m in (r for r in env["dados"] if r["recorte"] == "medidor"):
        validade = m["validade"] or (m.get("validade_laudo") if m["resultado"].strip().lower() == "reparado" else None)
        venc = validade is not None and date.fromisoformat(validade) < hoje
        reprovado = m["resultado"].strip().lower() in ("reprovado", "reprovada")
        dias = (hoje - date.fromisoformat(validade)).days if venc else None
        situacao = "vencida" if venc else "reprovado" if reprovado else "em dia" if validade else "sem validade informada"
        linhas.append({**m, "validade_efetiva": validade, "situacao": situacao, "dias_vencida": dias, "validade_br": _br(validade), "verificacao_br": _br(m["ultima_verificacao"]),
                       "reparado": m["resultado"].strip().lower() == "reparado", "end": _endereco(m["local"]), "via_estadual": bool(re.match(r"\s*(SP|SPM|SPA|BR)[ -]?\d", m["local"].upper())),
                       "busca": " ".join([m["local"], m["inmetros"], m["series"]]).lower(), "digitos": re.sub(r"\D", "", m["inmetros"] + m["series"]), "local": legivel(m["local"])})
    vigentes = {l["end"] for l in linhas if l["situacao"] == "em dia"}
    for l in linhas:
        l["substituido"] = l["situacao"] == "vencida" and l["end"] in vigentes
        l["recente"] = l["situacao"] == "reprovado" or (l["situacao"] == "vencida" and not l["substituido"] and l["dias_vencida"] <= DIAS_RECENTE)
        l["antigo"] = l["situacao"] in ("vencida",) and not l["recente"]
        l["invalido"] = l["recente"]
    recentes = sorted((l for l in linhas if l["recente"]), key=lambda l: (l["validade_efetiva"] or "", l["local"]))
    antigos = sorted((l for l in linhas if l["antigo"]), key=lambda l: (l["validade_efetiva"] or "", l["local"]))
    validos = sorted((l for l in linhas if l["situacao"] == "em dia"), key=lambda l: l["local"])
    coleta = date.fromisoformat(env["fonte"]["acesso_em"])
    return {"inm_invalidos": recentes, "inm_antigos": antigos, "inm_validos": validos, "inm_total": len(linhas), "inm_link": LINK_CONSULTA, "inm_coleta": _br(env["fonte"]["acesso_em"]), "inm_hoje": _br(hoje.isoformat()),
            "inm_defasagem": (hoje - coleta).days if (hoje - coleta).days > DIAS_COLETA_VELHA else None, "inm_linhas": linhas,
            "inm_dados": "https://dados.gov.br/dados/conjuntos-dados/portal-de-servicos-do-inmetro-nos-estados-psie"}


def pontos_mapa(linhas: list[dict], f) -> list[dict]:
    """Medidores com posição: em dia ou com problema recente. Registros antigos (provável troca) não vão ao mapa."""
    pontos = []
    for l in linhas:
        if l.get("lat") is None or not (l["situacao"] == "em dia" or l["recente"]):
            continue
        x, y = f(l["lat"], l["lon"])
        ok = l["situacao"] == "em dia"
        det = [["Situação", "Verificação em dia" if ok else ("Reprovado" if l["situacao"] == "reprovado" else f"Verificação vencida há {l['dias_vencida']} dias")], ["Validade", l["validade_br"]],
               ["Nº do Inmetro", l["inmetros"]], ["Nº de série", l["series"]], ["Velocidade", (l["velocidades"] + " km/h") if l["velocidades"] else ""], ["Local no cadastro", l["local"]], ["Posição", rotulo_posicao(l.get("posicao") or "porta", l.get("posicao_detalhe") or "")]]
        pontos.append({"x": round(x, 1), "y": round(y, 1), "g": "inmetro-ok" if ok else "inmetro-alerta", "aprox": (l.get("posicao") or "porta") != "porta", "nome": l["local"], "vel": (l["velocidades"] or "0").split(";")[0].strip(), "lat": f"{l['lat']:.5f}", "lon": f"{l['lon']:.5f}", "detalhes": det})
    return pontos
