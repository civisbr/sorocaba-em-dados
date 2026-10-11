"""Contexto de renderização do painel de mortes e nascimentos."""

from __future__ import annotations

INDICADORES_NASC = (
    ("Partos cesáreos", "nasc_cesarea", "nasc_parto_valido"),
    ("Nascimentos prematuros (menos de 37 semanas)", "nasc_prematuro", "nasc_gestacao_valida"),
    ("Baixo peso ao nascer (menos de 2,5 kg)", "nasc_baixo_peso", "nasc_peso_valido"),
    ("Mães com até 19 anos", "nasc_mae_ate19", "nasc_idade_mae_valida"),
    ("Mães com 7 ou mais consultas de pré-natal", "nasc_prenatal_7ou_mais", "nasc_prenatal_valido"),
)
ORDEM_FAIXAS = ("Menos de 1 ano", "1 a 14 anos", "15 a 29 anos", "30 a 59 anos", "60 a 79 anos", "80 anos ou mais")
ORDEM_EXTERNAS = ("Acidentes de transporte", "Homicídios", "Suicídios")


def _pct(n: int, total: int) -> float | None:
    return round(100 * n / total, 1) if total else None


def contexto_panorama(env: dict) -> dict:
    d = env["dados"]
    v = {(r["ano"], r["bloco"], r["categoria"]): r["n"] for r in d}
    anos = sorted({r["ano"] for r in d})
    atual, anterior = anos[-1], anos[-2] if len(anos) > 1 else None

    def total(ano: int, bloco: str) -> int:
        return v.get((ano, bloco, ""), 0)

    def infantis(ano: int) -> int | None:
        return v.get((ano, "obito_infantil", ""))  # ausente quando suprimido (menos de 5)

    obitos, nasc = total(atual, "obito_total"), total(atual, "nasc_total")
    por_ano = [{"ano": a, "obitos": total(a, "obito_total"), "nascidos": total(a, "nasc_total"), "infantis": infantis(a),
                "tmi": round(1000 * infantis(a) / total(a, "nasc_total"), 1) if infantis(a) is not None and total(a, "nasc_total") else None} for a in anos]
    caps = sorted(((c, n) for (a, b, c), n in v.items() if a == atual and b == "obito_capitulo"), key=lambda x: -x[1])
    causas = [{"nome": c, "n": n, "pct": _pct(n, obitos), "anterior": v.get((anterior, "obito_capitulo", c)) if anterior else None} for c, n in caps[:8]]
    faixas = [{"nome": f, "n": v[(atual, "obito_faixa", f)], "pct": _pct(v[(atual, "obito_faixa", f)], obitos)} for f in ORDEM_FAIXAS if (atual, "obito_faixa", f) in v]
    externas = [{"nome": g, "por_ano": [{"ano": a, "n": v.get((a, "obito_externa", g))} for a in anos]} for g in ORDEM_EXTERNAS]
    nascimentos = [{"nome": nome, "por_ano": [{"ano": a, "pct": (_pct(v[(a, num, "")], total(a, den)) if (a, num, "") in v else None)} for a in anos]} for nome, num, den in INDICADORES_NASC]
    return {"anos": anos, "ano_atual": atual, "obitos": obitos, "nascidos": nasc, "por_ano": por_ano, "causas": causas, "faixas": faixas, "externas": externas,
            "nascimentos": nascimentos, "ano_anterior": anterior, "ref_pan": str(atual), "tmi": por_ano[-1]["tmi"], "saldo": nasc - obitos}
