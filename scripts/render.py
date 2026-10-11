"""Renderiza data/public/*.json em HTML estático (dist/). Sem rede, sem relógio."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scripts.charts import barras_mensais, linhas, linhas_preco
from scripts.mapa import gerar as gerar_mapa
from scripts.paineis import PAINEIS

RAIZ = Path(__file__).resolve().parent.parent
# Repositório privado: sem URL pública, o rodapé mostra o caminho sem link.
REPO_URL: str | None = None
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
ABREV = [m[:3] for m in MESES]
MARCADOR = ".sorocaba-dist"
ROTULO_STATUS = {"real": "Dado real", "estimativa": "Estimativa", "pendente": "Pendente"}


def num(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def sinal(n: int) -> str:
    return ("+" if n > 0 else "−" if n < 0 else "") + num(abs(n))


def mes_extenso(comp: str) -> str:
    return f"{MESES[int(comp[4:]) - 1]} de {comp[:4]}"


def mes_curto(comp: str) -> str:
    return f"{ABREV[int(comp[4:]) - 1]}/{comp[2:4]}"


def data_br(iso: str) -> str:
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


def contexto_emprego(env: dict) -> dict:
    mensal = [r for r in env["dados"] if r["recorte"] == "mensal"]
    secoes = [r for r in env["dados"] if r["recorte"] == "secao_12m"]
    ultimo = mensal[-1]
    rotulos = {i: mes_curto(r["competencia"]) for i, r in enumerate(mensal) if i % 6 == 5 or i == len(mensal) - 1}
    maximo = max((abs(r["saldo"]) for r in secoes), default=1) or 1
    return {
        "ultimo": ultimo,
        "ultimo_mes": mes_extenso(ultimo["competencia"]),
        "saldo_12m": sum(r["saldo"] for r in mensal[-12:]),
        "grafico": barras_mensais([(mes_curto(r["competencia"]), r["saldo"]) for r in mensal], rotulos),
        "linhas": linhas(
            {"Contratações": [r["admissoes"] for r in mensal], "Desligamentos": [r["desligamentos"] for r in mensal]},
            rotulos,
        ),
        "mensal_tabela": list(reversed(mensal)),
        "secoes": [{**r, "pct": round(abs(r["saldo"]) / maximo * 100, 1)} for r in secoes],
        "inicio_12m": mes_curto(mensal[-12]["competencia"]),
        "fim_12m": mes_curto(ultimo["competencia"]),
        "primeiro_mes": mes_curto(mensal[0]["competencia"]),
    }


def brl(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def pct(v: float) -> str:
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.1f}".replace(".", ",") + "%"


def brl1(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def pct_abs(v: float) -> str:
    return f"{v * 100:.1f}".replace(".", ",") + "%"


def brl2(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


ETAPAS_MATRICULA = [
    ("Infantil", "mat_infantil"), ("Anos iniciais", "mat_anos_iniciais"), ("Anos finais", "mat_anos_finais"),
    ("Médio", "mat_medio"), ("EJA", "mat_eja"),
]
INFRA_ROTULOS = [
    ("biblioteca", "Biblioteca"), ("lab_informatica", "Laboratório de informática"),
    ("lab_ciencias", "Laboratório de ciências"), ("quadra_esportes", "Quadra de esportes"),
    ("internet", "Acesso à internet"), ("refeitorio", "Refeitório"), ("rampas", "Rampas de acesso"),
]


def contexto_escolas(env: dict) -> dict:
    escolas = env["dados"]
    anos = sorted({int(k[-4:]) for k in escolas[0] if k.startswith("ideb_ai_")})
    ano_censo = escolas[0]["ano_censo"]
    contagem: dict[str, int] = {}
    for e in escolas:
        contagem[e["rede"]] = contagem.get(e["rede"], 0) + 1
    ordem_redes = [r for r in ("Municipal", "Estadual", "Federal", "Privada") if r in contagem]
    return {
        "escolas": escolas,
        "anos": anos,
        "ano_censo": ano_censo,
        "ano_ideb": anos[-1],
        "redes": ordem_redes,
        "por_rede": [(r, contagem[r]) for r in ordem_redes],
    }


def contexto_escola(e: dict, base: dict) -> dict:
    etapas = [(r, e[c]) for r, c in ETAPAS_MATRICULA]
    # Total do Censo inclui modalidades que não listamos (ex.: profissionalizante).
    outras = (e["mat_total"] or 0) - sum(v or 0 for _, v in etapas)
    if outras > 0:
        etapas.append(("Outras", outras))
    grafico = barras_mensais([(r, v or 0) for r, v in etapas], {i: r for i, (r, _) in enumerate(etapas)})
    tem_ideb = any(e[f"ideb_{s}_{a}"] is not None for s in ("ai", "af") for a in base["anos"])
    return {"e": e, "etapas": etapas, "grafico": grafico, "tem_ideb": tem_ideb, "infra": INFRA_ROTULOS}


def contexto_combustivel(env: dict) -> dict:
    produtos = []
    for nome in dict.fromkeys(r["produto"] for r in env["dados"]):
        semanal = [r for r in env["dados"] if r["recorte"] == "semanal" and r["produto"] == nome]
        postos = [r for r in env["dados"] if r["recorte"] == "posto" and r["produto"] == nome]
        passo = -(-len(semanal) // 6)
        rotulos = {i: data_br(r["semana_inicio"])[:5] for i, r in enumerate(semanal) if i % passo == 0 or i == len(semanal) - 1}
        ultimo = semanal[-1]
        produtos.append(
            {
                "nome": nome,
                "slug": nome.lower().replace(" ", "-"),
                "ultimo": ultimo,
                "semanas": semanal,
                "variacao": (
                    round((ultimo["mediana"] - semanal[0]["mediana"]) / semanal[0]["mediana"] * 100, 1)
                    if len(semanal) > 1 else None
                ),
                "grafico": linhas_preco(
                    {
                        "Máximo": [r["maximo"] for r in semanal],
                        "Mediana": [r["mediana"] for r in semanal],
                        "Mínimo": [r["minimo"] for r in semanal],
                    },
                    rotulos,
                ),
                "postos": postos,
            }
        )
    base = produtos[0]["ultimo"]
    return {"produtos": produtos, "semana_ini": base["semana_inicio"], "semana_fim": base["semana_fim"]}


def renderizar(public: Path, saida: Path) -> None:
    jinja = Environment(loader=FileSystemLoader(RAIZ / "templates"), autoescape=select_autoescape(["html"]))
    jinja.filters.update(num=num, sinal=sinal, data_br=data_br, mes_curto=mes_curto, brl=brl, pct=pct, brl1=brl1, brl2=brl2, pct_abs=pct_abs)

    emprego = json.loads((public / "emprego.json").read_text(encoding="utf-8"))
    ctx_emprego = contexto_emprego(emprego)
    combustivel = json.loads((public / "combustivel.json").read_text(encoding="utf-8"))
    ctx_comb = contexto_combustivel(combustivel)
    escolas = json.loads((public / "escolas.json").read_text(encoding="utf-8"))
    ctx_esc = contexto_escolas(escolas)
    mapa = gerar_mapa(RAIZ / "data" / "raw" / "ibge" / "malha_3552205.geojson")

    paineis = {}
    for pid, p in PAINEIS.items():
        paineis[pid] = {**p, "id": pid, "status": "pendente", "referencia": None, "rotulo_status": "Pendente"}
    flag = emprego["qualidade"]["flag"]
    paineis["emprego"].update(status=flag, rotulo_status=ROTULO_STATUS[flag], referencia=ctx_emprego["ultimo_mes"])
    flag_c = combustivel["qualidade"]["flag"]
    paineis["combustivel"].update(
        status=flag_c, rotulo_status=ROTULO_STATUS[flag_c],
        referencia=f"semana de {data_br(ctx_comb['semana_ini'])[:5]} a {data_br(ctx_comb['semana_fim'])[:5]}",
    )
    flag_e = escolas["qualidade"]["flag"]
    paineis["escolas"].update(
        status=flag_e, rotulo_status=ROTULO_STATUS[flag_e],
        referencia=f"Censo {ctx_esc['ano_censo']} · IDEB {ctx_esc['ano_ideb']}",
    )
    ordem = list(paineis.values())

    if saida.exists():
        if any(saida.iterdir()) and not (saida / MARCADOR).exists():
            raise SystemExit(f"{saida} não é saída de build anterior (sem {MARCADOR}); recusando apagar")
        shutil.rmtree(saida)
    (saida / "data").mkdir(parents=True)
    (saida / MARCADOR).write_text("saída gerada por scripts/render.py\n", encoding="utf-8")
    for nome in ("style.css", "app.js"):
        shutil.copy(RAIZ / "static" / nome, saida / nome)
    for nome in ("emprego.json", "combustivel.json", "escolas.json"):
        shutil.copy(public / nome, saida / "data" / nome)

    comum = {"paineis": ordem, "repo_url": REPO_URL}

    def escrever(destino: str, template: str, raiz: str, **ctx) -> None:
        alvo = saida / destino
        if not alvo.resolve().is_relative_to(saida.resolve()):
            raise ValueError(f"destino fora de {saida}: {destino}")
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(
            jinja.get_template(template).render(raiz=raiz, **comum, **ctx), encoding="utf-8"
        )

    escrever("index.html", "index.html", "", mapa=mapa, emprego=ctx_emprego, comb=ctx_comb, esc=ctx_esc)
    escrever("sobre/index.html", "sobre.html", "../", fontes=[
        ("Emprego", "Novo CAGED — Ministério do Trabalho e Emprego", flag),
        ("Combustível", "Levantamento de Preços de Combustíveis — ANP", flag_c),
        ("Escolas", "Censo Escolar e IDEB — INEP", flag_e),
    ])
    escrever(
        "emprego/index.html", "paineis/emprego.html", "../",
        p=paineis["emprego"], env=emprego, script="scripts/build_emprego.py", **ctx_emprego,
    )
    escrever(
        "combustivel/index.html", "paineis/combustivel.html", "../",
        p=paineis["combustivel"], env=combustivel, script="scripts/build_combustivel.py", **ctx_comb,
    )
    escrever(
        "escolas/index.html", "paineis/escolas.html", "../",
        p=paineis["escolas"], env=escolas, script="scripts/build_escolas.py", **ctx_esc,
    )
    for e in ctx_esc["escolas"]:
        escrever(
            f"escolas/{e['co_inep']}/index.html", "paineis/escola.html", "../../",
            env=escolas, **ctx_esc, **contexto_escola(e, ctx_esc),
        )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--public", type=Path, default=RAIZ / "data" / "public")
    p.add_argument("--saida", type=Path, default=RAIZ / "dist")
    args = p.parse_args()
    renderizar(args.public, args.saida)


if __name__ == "__main__":
    main()
