"""Renderiza data/public/*.json em HTML estático (dist/). Sem rede, sem relógio."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
import shutil
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scripts.infosiga_regras import CELULA_MINIMA, VIA_MINIMA
from scripts.charts import barras_mensais, linhas, linhas_posicao, linhas_preco
from scripts.mapa import gerar as gerar_mapa
from scripts.mapa import projetar as projetar_mapa
from scripts.contexto_hospitais import contexto_hospitais
from scripts.contexto_mapa_saude import contexto_mapa_saude
from scripts.contexto_panorama import contexto_panorama
from scripts.mapa_base import BASE as BASE_OSM, bairros_json, contexto_base, gerar_svg, proj_grande
from scripts.contexto_vacinas import contexto_vacinas
from scripts.paineis import GRUPOS, PAINEIS

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


def brl1(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}".replace(".", ",")


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
    rotulos_bloco = {"esquerda": "Esquerda", "centro": "Centro", "direita": "Direita"}
    classificados = [r for r in vereadores if r["bloco"]]
    por_bloco = []
    for b in ("esquerda", "centro", "direita"):
        membros = [r for r in classificados if r["bloco"] == b]
        partidos_b: dict[tuple[str, str], int] = {}
        for r in membros:
            partidos_b[(r["partido"], r["ideologia"])] = partidos_b.get((r["partido"], r["ideologia"]), 0) + 1
        por_bloco.append({
            "id": b, "nome": rotulos_bloco[b], "n": len(membros),
            "pct": round(len(membros) / len(classificados) * 100, 1) if classificados else 0,
            "partidos": sorted(((p, c, n) for (p, c), n in partidos_b.items()), key=lambda t: (-t[2], t[0])),
        })
    return {
        "blocos": por_bloco,
        "bloco_classificados": len(classificados),
        "bloco_sem_classificacao": [(r["nome"], r["partido"]) for r in vereadores if not r["bloco"]],
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


def mapa_de_calor(d: list[dict], grupo: str, malha: Path) -> dict:
    mapa, ponto = proj_grande()  # o quadro grande é o dos mapas interativos
    celulas = [r for r in d if r["recorte"] == "grade" and r["grupo"] == grupo]
    cob = next(r for r in d if r["recorte"] == "grade_cobertura" and r["grupo"] == grupo)
    valores = sorted(r["n"] for r in celulas)
    # Cinco faixas por quintil dos valores das células; a legenda mostra os limites reais.
    cortes = [valores[min(len(valores) - 1, (len(valores) * k) // 5)] for k in range(1, 5)]
    def nivel(n: int) -> int:
        return 1 + sum(1 for c in cortes if n >= c)
    lado = float(cob["categoria"])
    retangulos = []
    for r in celulas:
        x0, y0 = ponto(r["lat"] + lado / 2, r["lon"] - lado / 2)
        x1, y1 = ponto(r["lat"] - lado / 2, r["lon"] + lado / 2)
        retangulos.append({"x": round(x0), "y": round(y0), "w": round(x1 - x0, 1), "h": round(y1 - y0, 1), "n": r["n"], "nivel": nivel(r["n"])})
    retangulos.sort(key=lambda q: (q["y"], q["x"]))
    limites = [valores[0], *cortes, valores[-1]]
    legenda = []
    for k in range(1, 6):
        ini = limites[k - 1] if k == 1 else limites[k - 1]
        fim = limites[k] - 1 if k < 5 else limites[5]
        legenda.append({"nivel": k, "ini": ini, "fim": max(ini, fim)})
    return {
        "mapa": mapa, "celulas": retangulos, "legenda": legenda, "cobertura": cob["pct"], "com_coordenada": cob["n"],
        "vista": vista_dos_pontos([{"x": q["x"] + q["w"] / 2, "y": q["y"] + q["h"] / 2} for q in retangulos], mapa, folga=0.25, minimo=300.0), "cw": retangulos[0]["w"], "ch": retangulos[0]["h"], "ano": cob["ano"], "ano_ini": cob["n2"] if grupo == "sinistros" else cob["ano"], "lado_m": round(lado * 111_000), "n_celulas": len(retangulos),
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
    ranking = {}
    for g in ("roubos", "furtos"):
        itens = sorted(
            ((r["categoria"], r["n"]) for r in d if r["recorte"] == "bairro" and r["grupo"] == g and not r["categoria"].startswith("Demais")),
            key=lambda kv: (-kv[1], chave_alfabetica(kv[0])),
        )[:15]
        topo = itens[0][1] if itens else 1
        ranking[g] = [{"bairro": b, "n": n, "pct": round(n / topo * 100, 1)} for b, n in itens]
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
        "ranking": ranking,
        "calor": {g: mapa_de_calor(d, g, RAIZ / "data" / "raw" / "ibge" / "malha_3552205.geojson") for g in ("roubos", "furtos")},
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


NIVEIS = {1: "Verde: baixa incidência", 2: "Amarelo: condições favoráveis ao mosquito", 3: "Laranja: transmissão em curso", 4: "Vermelho: incidência alta"}
NOMES_DOENCA = {"dengue": "Dengue", "chikungunya": "Chikungunya", "zika": "Zika"}


def contexto_saude_doencas(env: dict, hoje: date | None = None) -> dict:
    d = env["dados"]
    sit = {r["grupo"]: r for r in d if r["recorte"] == "situacao"}
    doencas, antigas = [], []
    for nome in ("dengue", "chikungunya", "zika"):
        if nome not in sit:
            continue
        sem = sorted((r for r in d if r["recorte"] == "semanal" and r["grupo"] == nome), key=lambda r: r["se"])
        ultima = sem[-1]
        rotulo = NOMES_DOENCA[nome]
        if sit[nome]["categoria"] != "atual":
            antigas.append({"nome": nome, "rotulo": rotulo, "ultima_semana": f"semana {ultima['semana']} de {ultima['ano']}"})
            continue
        janela = sem[-8:]
        cruza_ano = ultima["semana"] < 8
        comparacao = None
        if not cruza_ano:
            comparacao = [{"ano": ultima["ano"], "casos": sum(r["casos"] for r in janela)}]
            for ano in sorted({r["ano"] for r in sem if r["ano"] != ultima["ano"]}, reverse=True):
                fim = ultima["semana"] if any(r["ano"] == ano and r["semana"] == ultima["semana"] for r in sem) else 52  # ano sem semana 53
                alvo = [r for r in sem if r["ano"] == ano and fim - 7 <= r["semana"] <= fim]
                if len(alvo) == 8:
                    comparacao.append({"ano": ano, "casos": sum(r["casos"] for r in alvo)})
        ult52 = sem[-52:]
        passo = 13
        rot = {i: f"S{r['semana']}/{str(r['ano'])[2:]}" for i, r in enumerate(ult52) if i % passo == 0 or i == len(ult52) - 1}
        doencas.append({
            "nome": nome, "rotulo": rotulo, "se": ultima["se"], "semana": ultima["semana"], "ano": ultima["ano"], "nivel": ultima["nivel"], "nivel_rotulo": NIVEIS[ultima["nivel"]],
            "inc100k": ultima["inc100k"], "casos_8s": sum(r["casos"] for r in janela), "casos_est_ultima": ultima["casos_est"], "est_min": ultima["est_min"], "est_max": ultima["est_max"],
            "comparacao": comparacao,
            "grafico": barras_mensais([(f"S{r['semana']}/{str(r['ano'])[2:]}", r["casos"]) for r in ult52], rot),
            "tabela": [{"rotulo": f"S{r['semana']}/{r['ano']}", "casos": r["casos"], "casos_est": r["casos_est"], "nivel_rotulo": NIVEIS[r["nivel"]]} for r in reversed(ult52)],
        })
    ref = f"semana {doencas[0]['semana']} de {doencas[0]['ano']}" if doencas else "sem dado recente"
    sem_coleta = (hoje - date.fromisoformat(env["fonte"]["acesso_em"])).days if hoje else 0
    return {"doencas": doencas, "sem_dado_recente": antigas, "ref_saude": ref, "niveis": NIVEIS, "dias_sem_coleta": sem_coleta if sem_coleta > 21 else None}


def contexto_clima(clima: dict, previsao: dict | None) -> dict:
    mensal = [r for r in clima["dados"] if r["recorte"] == "mensal"]
    anual = next(r for r in clima["dados"] if r["recorte"] == "anual")
    rot = {i: MESES[i][:3] for i in range(12)}
    chuva = barras_mensais([(MESES[i], r["chuva_mm"]) for i, r in enumerate(mensal)], rot)
    temp = linhas_preco(
        {"Máxima": [r["tmax_media"] for r in mensal], "Mínima": [r["tmin_media"] for r in mensal]}, rot,
    )
    prev = None
    if previsao:
        por_fonte: dict[str, list[dict]] = {}
        for r in previsao["dados"]:
            por_fonte.setdefault(r["fonte"], []).append(r)
        prev = {"inmet": por_fonte.get("inmet", []), "modelo": por_fonte.get("open-meteo", []), "env": previsao}
    return {"mensal": mensal, "anual": anual, "grafico_chuva": chuva, "grafico_temp": temp, "meses": MESES, "prev": prev,
            "mes_mais_chuvoso": max(mensal, key=lambda r: r["chuva_mm"]), "mes_mais_seco": min(mensal, key=lambda r: r["chuva_mm"])}


def dia_semana(iso_data: str) -> str:
    return ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][date.fromisoformat(iso_data).weekday()]


def janelas_12_meses(por_mes: dict[tuple[int, int], dict]) -> tuple[list[dict], list[dict]]:
    """Últimos 12 meses do calendário e os 12 anteriores; lista vazia se faltar algum mês."""
    if not por_mes:
        return [], []
    ano, mes = max(por_mes)
    n = ano * 12 + mes - 1
    def janela(fim: int) -> list[dict]:
        ks = [((fim - i) // 12, (fim - i) % 12 + 1) for i in range(11, -1, -1)]
        return [por_mes[k] for k in ks] if all(k in por_mes for k in ks) else []
    return janela(n), janela(n - 12)


def parcela_notificacoes(janela: list[dict]) -> float:
    nt = sum(int(r["categoria"].split("|")[0]) for r in janela)
    total = nt + sum(r["n"] for r in janela)
    return nt / total if total else 0.0


def comparacao_anterior(ult12: list[dict], ant12: list[dict]) -> int | None:
    """Total dos 12 meses anteriores, ou None quando a comparação enganaria: as notificações ficam
    fora da contagem e a parcela delas muda muito de um ano para outro, o que parece queda ou alta real."""
    if not ult12 or not ant12 or abs(parcela_notificacoes(ult12) - parcela_notificacoes(ant12)) > 0.10:
        return None
    return sum(r["n"] for r in ant12)


def notificacoes_do_ano(mensal: list[dict], ano: int) -> int:
    ano_m = [r for r in mensal if r["ano"] == ano]
    return round(parcela_notificacoes(ano_m) * 100)


def contexto_acidentes(env: dict) -> dict:
    d = env["dados"]
    mensal = [r for r in d if r["recorte"] == "mensal"]
    rot = {i: f"{ABREV[r['mes'] - 1]}/{str(r['ano'])[2:]}" for i, r in enumerate(mensal) if (i % 12 == 0 and len(mensal) - 1 - i >= 9) or i == len(mensal) - 1}
    por_mes = {(r["ano"], r["mes"]): r for r in mensal}
    ult12, ant12 = janelas_12_meses(por_mes)
    horas = [r for r in d if r["recorte"] == "hora"]
    dias_ord = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
    dias = sorted((r for r in d if r["recorte"] == "dia_semana"), key=lambda r: dias_ord.index(r["categoria"]) if r["categoria"] in dias_ord else 99)
    topo_d = max((r["n"] for r in dias), default=1)
    tipos = sorted((r for r in d if r["recorte"] == "tipo"), key=lambda r: -r["n"])
    total_t = sum(r["n"] for r in tipos) or 1
    vias = [r for r in d if r["recorte"] == "via"]
    tem_mapa = any(r["recorte"] == "grade" for r in d)
    return {
        "ac_ano": horas[0]["ano"] if horas else None,
        "ac_mensal": barras_mensais([(f"{ABREV[r['mes'] - 1]}/{r['ano']}", r["n"]) for r in mensal], rot),
        "ac_ult12": sum(r["n"] for r in ult12) if ult12 else None, "ac_ant12": comparacao_anterior(ult12, ant12),
        "ac_mortes12": sum(r["n2"] for r in ult12) if ult12 else None,
        "ac_notif_ano": notificacoes_do_ano(mensal, horas[0]["ano"]) if horas else None,
        "ac_tabela": [{"rotulo": f"{ABREV[r['mes'] - 1]}/{r['ano']}", "n": r["n"], "mortes": r["n2"], "notif": int(r["categoria"].split("|")[0])} for r in mensal],
        "ac_celula_min": CELULA_MINIMA, "ac_via_min": VIA_MINIMA,
        "ac_fim": f"{ABREV[mensal[-1]['mes'] - 1]}/{mensal[-1]['ano']}",
        "ac_horas": barras_mensais([(f"{r['categoria']}h", r["n"]) for r in horas], {i: f"{i:02d}h" for i in range(0, 24, 3)}) if horas else None,
        "ac_dias": [{"nome": r["categoria"], "n": r["n"], "pct": round(r["n"] / topo_d * 100, 1)} for r in dias],
        "ac_tipos": [{"nome": {"COLISAO": "Colisão", "NAO DISPONIVEL": "Não informado"}.get(r["categoria"], r["categoria"].capitalize()), "n": r["n"], "pct": round(r["n"] / total_t * 100, 1)} for r in tipos],
        "ac_vias": [{"nome": r["categoria"], "n": r["n"], "pct": round(r["n"] / vias[0]["n"] * 100, 1)} for r in vias],
        "ac_calor": mapa_de_calor(d, "sinistros", RAIZ / "data" / "raw" / "ibge" / "malha_3552205.geojson") if tem_mapa else None,
    }


def vista_dos_pontos(pontos: list[dict], mapa: dict, folga: float = 0.35, minimo: float = 120.0) -> str:
    """viewBox que aproxima o mapa da região dos pontos, mantendo a proporção do quadro inteiro e sem sair dele."""
    xs, ys = [p["x"] for p in pontos], [p["y"] for p in pontos]
    w = max(max(xs) - min(xs), minimo) * (1 + 2 * folga)
    h = max(max(ys) - min(ys), minimo) * (1 + 2 * folga)
    razao = mapa["largura"] / mapa["altura"]
    w, h = max(w, h * razao), max(h, w / razao)
    w, h = min(w, mapa["largura"]), min(h, mapa["altura"])
    x = min(max((min(xs) + max(xs)) / 2 - w / 2, 0), mapa["largura"] - w)
    y = min(max((min(ys) + max(ys)) / 2 - h / 2, 0), mapa["altura"] - h)
    return f"{x:.1f} {y:.1f} {w:.1f} {h:.1f}"


def contexto_transito(env: dict) -> dict:
    radares = env["dados"]
    por_vel: dict[int, int] = {}
    for r in radares:
        por_vel[r["velocidade_kmh"]] = por_vel.get(r["velocidade_kmh"], 0) + 1
    topo = max(por_vel.values())
    mapa, ponto = proj_grande()
    pontos, grupos = [], {}
    for r in radares:
        if "lat" in r:
            x, y = ponto(r["lat"], r["lon"])
            pontos.append({"x": round(x, 1), "y": round(y, 1), "v": r["velocidade_kmh"], "local": r["local"], "precisao": r["precisao"], "lat": f"{r['lat']:.5f}", "lon": f"{r['lon']:.5f}"})
        for texto in filter(None, r.get("posicoes_candidatas", "").split("|")):
            lat, lon = (float(x) for x in texto.split(","))
            g = grupos.setdefault((lat, lon), {"v": r["velocidade_kmh"], "locais": [], "xy": ponto(lat, lon), "lat": f"{lat:.5f}", "lon": f"{lon:.5f}"})
            g["locais"].append(r["local"])
    pontos_grupo = [{"x": round(g["xy"][0], 1), "y": round(g["xy"][1], 1), "v": g["v"], "locais": sorted(set(g["locais"])), "lat": g["lat"], "lon": g["lon"]} for g in grupos.values()]
    todos = pontos + pontos_grupo
    vel_comum = max(por_vel, key=lambda v: (por_vel[v], -v))  # empate: vale a menor velocidade
    return {
        "vel_comum": vel_comum,
        "radar_mapa": {"mapa": mapa, "pontos": pontos, "pontos_grupo": pontos_grupo, "velocidades": sorted({p["v"] for p in todos}), "vista": vista_dos_pontos(todos, mapa)} if todos else None,
        "radares": sorted(radares, key=lambda r: (chave_alfabetica(r["local"]), r["ponto"])),
        "por_vel": [{"v": v, "n": n, "pct": round(n / topo * 100, 1)} for v, n in sorted(por_vel.items())],
        "n_radares": len(radares),
    }


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
    jinja.globals["dia_semana"] = dia_semana
    jinja.globals["rotulo_bloco"] = lambda b: {"esquerda": "Esquerda", "centro": "Centro", "direita": "Direita"}.get(b, "Sem classificação")
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
    clima = json.loads((public / "clima.json").read_text(encoding="utf-8"))
    arq_prev = public / "previsao.json"
    previsao = json.loads(arq_prev.read_text(encoding="utf-8")) if arq_prev.exists() else None
    ctx_clima = contexto_clima(clima, previsao)
    saude = json.loads((public / "saude_doencas.json").read_text(encoding="utf-8"))
    ctx_saude = contexto_saude_doencas(saude, date.today())
    hospitais = json.loads((public / "saude_hospitais.json").read_text(encoding="utf-8"))
    ctx_hosp = contexto_hospitais(hospitais, nome_br)
    base_osm = json.loads(BASE_OSM.read_text(encoding="utf-8"))
    mapa_svg, proj = gerar_svg(base_osm)
    ctx_hosp["mapa_saude"] = contexto_mapa_saude(hospitais, nome_br, proj["mapa"], proj["f"])
    panorama = json.loads((public / "saude_panorama.json").read_text(encoding="utf-8"))
    ctx_pan = contexto_panorama(panorama)
    vacinas = json.loads((public / "saude_vacinas.json").read_text(encoding="utf-8"))
    ctx_vac = contexto_vacinas(vacinas, date.today())
    radares = json.loads((public / "radares.json").read_text(encoding="utf-8"))
    ctx_trans = contexto_transito(radares)
    acidentes = json.loads((public / "infosiga.json").read_text(encoding="utf-8"))
    ctx_trans.update(contexto_acidentes(acidentes))
    ctx_trans["env_ac"] = acidentes
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
    paineis["clima"].update(
        status="real", rotulo_status="Dado real",
        referencia=("previsão de " + data_br(previsao["referencia"]["inicio"])[:5] + " a " + data_br(previsao["referencia"]["fim"])[:5]) if previsao else "normais 1991–2020",
    )
    paineis["transito"].update(status="real", rotulo_status="Dado real", referencia=f"sinistros até {ctx_trans['ac_fim']}; {ctx_trans['n_radares']} radares fixos listados")
    if sorted(p for _, ids in GRUPOS for p in ids) != sorted(paineis):
        raise ValueError("todo painel precisa estar em exatamente um grupo de scripts.paineis.GRUPOS")
    grupos = [{"nome": nome, "paineis": [paineis[i] for i in ids]} for nome, ids in GRUPOS]
    flag_sa = saude["qualidade"]["flag"]
    paineis["saude"].update(status=flag_sa, rotulo_status=ROTULO_STATUS[flag_sa], referencia=ctx_saude["ref_saude"])
    flag_h = hospitais["qualidade"]["flag"]
    paineis["hospitais"].update(status=flag_h, rotulo_status=ROTULO_STATUS[flag_h], referencia=ctx_hosp["ref_hosp"])
    flag_pa = panorama["qualidade"]["flag"]
    paineis["panorama"].update(status=flag_pa, rotulo_status=ROTULO_STATUS[flag_pa], referencia=ctx_pan["ref_pan"])
    flag_v = vacinas["qualidade"]["flag"]
    paineis["vacinas"].update(status=flag_v, rotulo_status=ROTULO_STATUS[flag_v], referencia=ctx_vac["ref_vac"])
    ordem = [p for g in grupos for p in g["paineis"]]

    if saida.exists():
        if any(saida.iterdir()) and not (saida / MARCADOR).exists():
            raise SystemExit(f"{saida} não é saída de build anterior (sem {MARCADOR}); recusando apagar")
        shutil.rmtree(saida)
    (saida / "data").mkdir(parents=True)
    (saida / MARCADOR).write_text("saída gerada por scripts/render.py\n", encoding="utf-8")
    for nome in ("style.css", "app.js", "mapa-interativo.js"):
        shutil.copy(RAIZ / "static" / nome, saida / nome)
    for nome in ("favicon.svg", "favicon-32.png", "apple-touch-icon.png", "logo-icone.svg"):
        shutil.copy(RAIZ / "static" / nome, saida / nome)
    shutil.copytree(RAIZ / "static" / "fonts", saida / "fonts")
    (saida / "mapa-base.svg").write_text(mapa_svg, encoding="utf-8")
    (saida / "data" / "mapa-bairros.json").write_text(bairros_json(base_osm, proj["f"]), encoding="utf-8")
    for nome in ("emprego.json", "combustivel.json", "escolas.json", "perfil.json", "representantes.json", "seguranca.json", "comparativo.json", "clima.json", "radares.json", "infosiga.json", "saude_doencas.json", "saude_hospitais.json", "saude_panorama.json", "saude_vacinas.json"):
        shutil.copy(public / nome, saida / "data" / nome)

    comum = {"paineis": ordem, "grupos": grupos, "repo_url": REPO_URL}

    def escrever(destino: str, template: str, raiz: str, **ctx) -> None:
        alvo = saida / destino
        if not alvo.resolve().is_relative_to(saida.resolve()):
            raise ValueError(f"destino fora de {saida}: {destino}")
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(
            jinja.get_template(template).render(raiz=raiz, mb=contexto_base(raiz), **comum, **ctx), encoding="utf-8"
        )

    escrever("index.html", "index.html", "", mapa=mapa, emprego=ctx_emprego, comb=ctx_comb, esc=ctx_esc, cid=ctx_cid, rep=ctx_rep, seg=ctx_seg, comp=ctx_comp, clima=ctx_clima, trans=ctx_trans, saude=ctx_saude, hosp=ctx_hosp, pan=ctx_pan, vac=ctx_vac)
    escrever("sobre/index.html", "sobre.html", "../", fontes=[
        ("Emprego", "Novo CAGED — Ministério do Trabalho e Emprego", flag),
        ("Combustível", "Levantamento de Preços de Combustíveis — ANP", flag_c),
        ("Escolas", "Censo Escolar e IDEB — INEP", flag_e),
        ("A cidade", "Censo 2022, estimativas e PIB dos Municípios — IBGE", flag_p),
        ("Representantes", "TSE, Câmara dos Deputados e Alesp", flag_r),
        ("Segurança", "SSP-SP — ocorrências registradas", flag_s),
        ("Comparativo", "IBGE e INEP — posição entre municípios", flag_c2),
        ("Clima", "INMET e Open-Meteo (ERA5)", "real"),
        ("Doenças do momento", "InfoDengue (Fiocruz/FGV)", flag_sa),
        ("Hospitais e leitos", "CNES e SIH/SUS — DATASUS", flag_h),
        ("Mortes e nascimentos", "SIM e SINASC — DATASUS", flag_pa),
        ("Vacinas", "Ministério da Saúde e Prefeitura de Sorocaba (curadoria manual)", flag_v),
        ("Trânsito", "Semob Sorocaba (radares) e Infosiga SP (Detran-SP)", "real"),
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
    escrever("saude/index.html", "paineis/saude.html", "../", p=paineis["saude"], env=saude, script="scripts/build_infodengue.py", **ctx_saude)
    escrever("vacinas/index.html", "paineis/vacinas.html", "../", p=paineis["vacinas"], env=vacinas, script="scripts/build_vacinas.py", **ctx_vac)
    escrever("panorama/index.html", "paineis/panorama.html", "../", p=paineis["panorama"], env=panorama, script="scripts/build_vitais.py", **ctx_pan)
    escrever("hospitais/index.html", "paineis/hospitais.html", "../", p=paineis["hospitais"], env=hospitais, script="scripts/build_hospitais.py", **ctx_hosp)
    escrever(
        "clima/index.html", "paineis/clima.html", "../",
        p=paineis["clima"], env=clima, script="scripts/build_clima.py", **ctx_clima,
    )
    escrever(
        "transito/index.html", "paineis/transito.html", "../",
        p=paineis["transito"], env=radares, script="scripts/build_radares.py", **ctx_trans,
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
