"""Contexto de renderização da situação metrológica dos radares (Inmetro)."""

from __future__ import annotations

from datetime import date

LINK_CONSULTA = "https://servicos.rbmlq.gov.br/Instrumento"


def _br(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "sem data"


def contexto_inmetro(env: dict, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    linhas = []
    for m in (r for r in env["dados"] if r["recorte"] == "medidor"):
        venc = m["validade"] is not None and date.fromisoformat(m["validade"]) < hoje
        reprovado = m["resultado"].strip().lower() in ("reprovado", "reprovada")
        situacao = "vencida" if venc else "reprovado" if reprovado else "em dia" if m["validade"] else "sem validade informada"
        linhas.append({**m, "situacao": situacao, "invalido": situacao != "em dia", "validade_br": _br(m["validade"]), "verificacao_br": _br(m["ultima_verificacao"]),
                       "busca": " ".join([m["local"], m["inmetros"], m["series"]]).lower(), "dias_vencida": (hoje - date.fromisoformat(m["validade"])).days if venc else None})
    invalidos = sorted((l for l in linhas if l["invalido"]), key=lambda l: (l["validade"] or "", l["local"]))
    validos = sorted((l for l in linhas if not l["invalido"]), key=lambda l: l["local"])
    return {"inm_invalidos": invalidos, "inm_validos": validos, "inm_total": len(linhas), "inm_link": LINK_CONSULTA, "inm_coleta": _br(env["fonte"]["acesso_em"]),
            "inm_dados": "https://dados.gov.br/dados/conjuntos-dados/portal-de-servicos-do-inmetro-nos-estados-psie"}
