"""Renderiza data/public/*.json em HTML estático (dist/). Sem rede, sem relógio."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scripts.charts import barras_mensais, linhas
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


def renderizar(public: Path, saida: Path) -> None:
    jinja = Environment(loader=FileSystemLoader(RAIZ / "templates"), autoescape=select_autoescape(["html"]))
    jinja.filters.update(num=num, sinal=sinal, data_br=data_br, mes_curto=mes_curto)

    emprego = json.loads((public / "emprego.json").read_text(encoding="utf-8"))
    ctx_emprego = contexto_emprego(emprego)
    mapa = gerar_mapa(RAIZ / "data" / "raw" / "ibge" / "malha_3552205.geojson")

    paineis = {}
    for pid, p in PAINEIS.items():
        paineis[pid] = {**p, "id": pid, "status": "pendente", "referencia": None, "rotulo_status": "Pendente"}
    flag = emprego["qualidade"]["flag"]
    paineis["emprego"].update(status=flag, rotulo_status=ROTULO_STATUS[flag], referencia=ctx_emprego["ultimo_mes"])
    ordem = list(paineis.values())

    if saida.exists():
        if any(saida.iterdir()) and not (saida / MARCADOR).exists():
            raise SystemExit(f"{saida} não é saída de build anterior (sem {MARCADOR}); recusando apagar")
        shutil.rmtree(saida)
    (saida / "data").mkdir(parents=True)
    (saida / MARCADOR).write_text("saída gerada por scripts/render.py\n", encoding="utf-8")
    for nome in ("style.css", "app.js"):
        shutil.copy(RAIZ / "static" / nome, saida / nome)
    shutil.copy(public / "emprego.json", saida / "data" / "emprego.json")

    comum = {"paineis": ordem, "repo_url": REPO_URL}

    def escrever(destino: str, template: str, raiz: str, **ctx) -> None:
        alvo = saida / destino
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(
            jinja.get_template(template).render(raiz=raiz, **comum, **ctx), encoding="utf-8"
        )

    escrever("index.html", "index.html", "", mapa=mapa, emprego=ctx_emprego)
    escrever("sobre/index.html", "sobre.html", "../", fontes=[
        ("Emprego", "Novo CAGED — Ministério do Trabalho e Emprego", flag),
        ("Combustível", "Levantamento de Preços de Combustíveis — ANP", "pendente"),
        ("Escolas", "Censo Escolar e IDEB — INEP", "pendente"),
    ])
    escrever(
        "emprego/index.html", "paineis/emprego.html", "../",
        p=paineis["emprego"], env=emprego, script="scripts/build_emprego.py", **ctx_emprego,
    )
    for pid in ("combustivel", "escolas"):
        escrever(f"{pid}/index.html", "paineis/pendente.html", "../", p=paineis[pid])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--public", type=Path, default=RAIZ / "data" / "public")
    p.add_argument("--saida", type=Path, default=RAIZ / "dist")
    args = p.parse_args()
    renderizar(args.public, args.saida)


if __name__ == "__main__":
    main()
