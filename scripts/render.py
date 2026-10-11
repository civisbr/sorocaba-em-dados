"""Renderiza data/public/*.json em HTML estático (dist/). Sem rede, sem relógio."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scripts.charts import barras_mensais, linhas, linhas_posicao, linhas_preco
from scripts.mapa import gerar as gerar_mapa
from scripts.paineis import PAINEIS

RAIZ = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/civisbr/sorocaba-em-dados"
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


def nome_br(nome: str) -> str:
    miudas = {"da", "de", "do", "das", "dos", "e"}
    romanos = {"ii", "iii", "iv", "jr", "pm", "pt", "pl", "mc"}

    def parte(w: str, primeira: bool) -> str:
        if w in romanos:
            return w.upper()
        if not primeira and w in miudas:
            return w
        return re.sub(r"(^|[-'’])(\w)", lambda m: m.group(1) + m.group(2).upper(), w)

    return " ".join(parte(w, i == 0) for i, w in enumerate(nome.lower().split()))


def chave_alfabetica(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def bi(v: float) -> str:
    return f"{v / 1_000_000:.1f}".replace(".", ",")


def inteiro_br(v: float) -> str:
    return num(int(round(v)))


def contexto_cidade(env: dict) -> dict:
    por = {}
    for r in env["dados"]:
        por.setdefault(r["recorte"], []).append(r)
    ind = {r["chave"]: r for r in por["indicador"]}
    pib = por["pib_serie"]
    rotulos = {i: str(r["ano"]) for i, r in enumerate(pib)}
    vab = [r for r in por.get("vab_setor", []) if r["chave"] != "total"]
    return {
        "territorio": por["territorio"],
        "ind": ind,
        "pib": pib,
        "pib_ultimo": pib[-1],
        "pib_grafico": barras_mensais([(str(r["ano"]), round(r["valor"] / 1_000_000, 1)) for r in pib], rotulos),
        "participacoes": por["pib_participacao"],
        "vab": vab,
        "vab_total": next((r for r in por.get("vab_setor", []) if r["chave"] == "total"), None),
        "ref_cidade": f"Censo {ind['populacao_censo']['ano']} · PIB {pib[-1]['ano']}",
        "ano_vab": vab[0]["ano"] if vab else None,
    }


def contexto_representantes(env: dict) -> dict:
    d = env["dados"]
    def grupo(g, ano=None):
        return [r for r in d if r["grupo"] == g and (ano is None or r["eleicao"] == ano)]
    vereadores = sorted(grupo("vereador"), key=lambda r: chave_alfabetica(r["nome"]))
    partidos: dict[str, int] = {}
    for r in vereadores:
        partidos[r["partido"]] = partidos.get(r["partido"], 0) + 1
    return {
        "prefeito": grupo("prefeito")[0],
        "vice": grupo("vice_prefeito")[0],
        "vereadores": vereadores,
        "partidos": sorted(partidos.items(), key=lambda kv: (-kv[1], kv[0])),
        "deputados": [
            ("Deputados federais", [("Mandato atual: eleitos em 2022", grupo("deputado_federal", 2022)), ("Eleitos em 2026, assumem em 2027", grupo("deputado_federal", 2026))]),
            ("Deputados estaduais", [("Mandato atual: eleitos em 2022", grupo("deputado_estadual", 2022)), ("Eleitos em 2026, assumem em 2027", grupo("deputado_estadual", 2026))]),
        ],
        "topo": max(r["posicao_na_cidade"] for r in d if r["posicao_na_cidade"]),
        "ref_rep": "Eleições de " + ", ".join(str(a) for a in sorted({r["eleicao"] for r in d})),
    }


GRUPOS_SEG = {
    "roubos": "Roubos", "furtos": "Furtos", "mortes_dolosas": "Mortes por crime doloso",
    "lesao_dolosa": "Lesão corporal dolosa", "estupros": "Estupros", "trafico": "Tráfico de entorpecentes",
}


def contexto_seguranca(env: dict) -> dict:
    d = env["dados"]
    mensal = {g: [r for r in d if r["recorte"] == "mensal" and r["grupo"] == g] for g in GRUPOS_SEG}
    atual = {r["grupo"]: r for r in d if r["recorte"] == "janela_atual"}
    anterior = {r["grupo"]: r for r in d if r["recorte"] == "janela_anterior"}
    series = {}
    for g in ("roubos", "furtos", "mortes_dolosas"):
        pts = mensal[g]
        passo = 12
        rot = {i: f"{ABREV[r['mes'] - 1]}/{str(r['ano'])[2:]}" for i, r in enumerate(pts) if (i % passo == 0 and len(pts) - 1 - i >= 9) or i == len(pts) - 1}
        series[g] = barras_mensais([(f"{ABREV[r['mes'] - 1]}/{r['ano']}", r["n"]) for r in pts], rot)
    horas = {}
    for g in ("roubos", "furtos"):
        pts = [r for r in d if r["recorte"] == "hora" and r["grupo"] == g]
        horas[g] = barras_mensais([(f"{r['categoria']}h", r["n"]) for r in pts], {i: f"{i:02d}h" for i in range(0, 24, 3)})
    comparacao = []
    for g, nome in GRUPOS_SEG.items():
        a, b = atual[g]["n"], anterior[g]["n"]
        comparacao.append({"grupo": nome, "atual": a, "anterior": b, "var": round((a - b) / b * 100, 1) if b >= 30 else None})
    bairros: dict[str, dict[str, int]] = {}
    for r in d:
        if r["recorte"] == "bairro":
            bairros.setdefault(r["categoria"], {})[r["grupo"]] = r["n"]
    demais = [k for k in bairros if k.startswith("Demais")]
    lista_bairros = [(k, v.get("roubos", 0), v.get("furtos", 0)) for k, v in bairros.items() if k not in demais]
    ano_ref = next(r["ano"] for r in d if r["recorte"] == "periodo")
    ult = atual["roubos"]
    return {
        "grupos_nome": GRUPOS_SEG,
        "series": series,
        "horas": horas,
        "faixas": {g: [r for r in d if r["recorte"] == "periodo" and r["grupo"] == g] for g in ("roubos", "furtos")},
        "tipos_furto": [r for r in d if r["recorte"] == "furto_tipo"][:10],
        "comparacao": comparacao,
        "bairros": lista_bairros,
        "bairros_demais": [(k, bairros[k].get("roubos", 0), bairros[k].get("furtos", 0)) for k in demais],
        "ano_ref": ano_ref,
        "mes_fim": f"{MESES[ult['mes'] - 1]} de {ult['ano']}",
        "mes_fim_curto": f"{ABREV[ult['mes'] - 1]}/{str(ult['ano'])[2:]}",
        "mes_ini_curto": f"{ABREV[(ult['mes']) % 12]}/{str(ult['ano'] - (0 if ult['mes'] == 12 else 1))[2:]}",
        "roubos_atual": atual["roubos"]["n"],
        "ref_seg": f"até {MESES[ult['mes'] - 1]} de {ult['ano']}",
    }


ROTULO_IND = {
    "populacao": ("População", "habitantes", "hab"),
    "pib": ("PIB a preços correntes", "R$ bilhões", "bi"),
    "pib_per_capita": ("PIB per capita (calculado)", "R$ por habitante", "rs"),
    "ideb_anos_iniciais": ("IDEB, anos iniciais (rede pública)", "nota de 0 a 10", "nota"),
    "ideb_anos_finais": ("IDEB, anos finais (rede pública)", "nota de 0 a 10", "nota"),
}


def formata_ind(tipo: str, v: float) -> str:
    if tipo == "bi":
        return f"R$ {v / 1_000_000:.1f}".replace(".", ",") + " bi"
    if tipo == "rs":
        return "R$ " + num(int(round(v)))
    if tipo == "nota":
        return f"{v:.1f}".replace(".", ",")
    return num(int(round(v)))


def contexto_comparativo(env: dict) -> dict:
    blocos = []
    for ind, (nome, unidade, tipo) in ROTULO_IND.items():
        pos = [r for r in env["dados"] if r["recorte"] == "posicao" and r["indicador"] == ind]
        viz = [r for r in env["dados"] if r["recorte"] == "vizinho" and r["indicador"] == ind]
        ult, prim = pos[-1], pos[0]
        blocos.append({
            "id": ind, "nome": nome, "unidade": unidade, "tipo": tipo, "ultimo": ult, "primeiro": prim,
            "grafico_sp": linhas_posicao([(r["ano"], r["pos_sp"]) for r in pos]),
            "grafico_br": linhas_posicao([(r["ano"], r["pos_br"]) for r in pos]),
            "anos": list(reversed(pos)),
            "vizinhos": viz,
            "ano_viz": viz[0]["ano"] if viz else None,
        })
    return {"blocos": blocos, "ref_comp": "posição " + str(max(b["ultimo"]["ano"] for b in blocos))}


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
    jinja.globals["fmt_ind"] = formata_ind
    jinja.filters.update(num=num, sinal=sinal, data_br=data_br, mes_curto=mes_curto, brl=brl, pct=pct, brl1=brl1, brl2=brl2, pct_abs=pct_abs, bi=bi, inteiro_br=inteiro_br, nome_br=nome_br)

    emprego = json.loads((public / "emprego.json").read_text(encoding="utf-8"))
    ctx_emprego = contexto_emprego(emprego)
    combustivel = json.loads((public / "combustivel.json").read_text(encoding="utf-8"))
    ctx_comb = contexto_combustivel(combustivel)
    perfil = json.loads((public / "perfil.json").read_text(encoding="utf-8"))
    ctx_cid = contexto_cidade(perfil)
    rep = json.loads((public / "representantes.json").read_text(encoding="utf-8"))
    ctx_rep = contexto_representantes(rep)
    seg = json.loads((public / "seguranca.json").read_text(encoding="utf-8"))
    ctx_seg = contexto_seguranca(seg)
    comp = json.loads((public / "comparativo.json").read_text(encoding="utf-8"))
    ctx_comp = contexto_comparativo(comp)
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
    flag_p = perfil["qualidade"]["flag"]
    paineis["cidade"].update(status=flag_p, rotulo_status=ROTULO_STATUS[flag_p], referencia=ctx_cid["ref_cidade"])
    flag_r = rep["qualidade"]["flag"]
    paineis["representantes"].update(status=flag_r, rotulo_status=ROTULO_STATUS[flag_r], referencia=ctx_rep["ref_rep"])
    flag_s = seg["qualidade"]["flag"]
    paineis["seguranca"].update(status=flag_s, rotulo_status=ROTULO_STATUS[flag_s], referencia=ctx_seg["ref_seg"])
    flag_c2 = comp["qualidade"]["flag"]
    paineis["comparativo"].update(status=flag_c2, rotulo_status=ROTULO_STATUS[flag_c2], referencia="anos de " + str(comp["referencia"]["inicio"][:4]) + " a " + str(comp["referencia"]["fim"][:4]))
    ordem = list(paineis.values())

    if saida.exists():
        if any(saida.iterdir()) and not (saida / MARCADOR).exists():
            raise SystemExit(f"{saida} não é saída de build anterior (sem {MARCADOR}); recusando apagar")
        shutil.rmtree(saida)
    (saida / "data").mkdir(parents=True)
    (saida / MARCADOR).write_text("saída gerada por scripts/render.py\n", encoding="utf-8")
    for nome in ("style.css", "app.js"):
        shutil.copy(RAIZ / "static" / nome, saida / nome)
    for nome in ("emprego.json", "combustivel.json", "escolas.json", "perfil.json", "representantes.json", "seguranca.json", "comparativo.json"):
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

    escrever("index.html", "index.html", "", mapa=mapa, emprego=ctx_emprego, comb=ctx_comb, esc=ctx_esc, cid=ctx_cid, rep=ctx_rep, seg=ctx_seg, comp=ctx_comp)
    escrever("sobre/index.html", "sobre.html", "../", fontes=[
        ("Emprego", "Novo CAGED — Ministério do Trabalho e Emprego", flag),
        ("Combustível", "Levantamento de Preços de Combustíveis — ANP", flag_c),
        ("Escolas", "Censo Escolar e IDEB — INEP", flag_e),
        ("A cidade", "Censo 2022, estimativas e PIB dos Municípios — IBGE", flag_p),
        ("Representantes", "TSE, Câmara dos Deputados e Alesp", flag_r),
        ("Segurança", "SSP-SP — ocorrências registradas", flag_s),
        ("Comparativo", "IBGE e INEP — posição entre municípios", flag_c2),
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
    escrever(
        "cidade/index.html", "paineis/cidade.html", "../",
        p=paineis["cidade"], env=perfil, script="scripts/build_perfil.py", **ctx_cid,
    )
    escrever(
        "representantes/index.html", "paineis/representantes.html", "../",
        p=paineis["representantes"], env=rep, script="scripts/build_representantes.py", **ctx_rep,
    )
    escrever(
        "seguranca/index.html", "paineis/seguranca.html", "../",
        p=paineis["seguranca"], env=seg, script="scripts/build_seguranca.py", **ctx_seg,
    )
    escrever(
        "comparativo/index.html", "paineis/comparativo.html", "../",
        p=paineis["comparativo"], env=comp, script="scripts/build_comparativo.py", **ctx_comp,
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
