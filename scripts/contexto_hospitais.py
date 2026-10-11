"""Contexto de renderização do painel de hospitais e leitos."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable

from scripts.saude_codigos import ATENCAO_BASICA, HOSPITALAR, URGENCIA

MAX_ESPECIALIDADES = 6


PALAVRAS = {
    "americo": "Américo", "andre": "André", "angelica": "Angélica", "antonio": "Antônio", "antonia": "Antônia", "arvore": "Árvore", "associacao": "Associação",
    "barao": "Barão", "cecilia": "Cecília", "claudio": "Cláudio", "colombia": "Colômbia", "crianca": "Criança", "eden": "Éden", "emilia": "Emília", "erico": "Érico",
    "esperanca": "Esperança", "eugenia": "Eugênia", "evangelico": "Evangélico", "familia": "Família", "hortencia": "Hortência", "inacio": "Inácio", "jose": "José",
    "julio": "Júlio", "marcia": "Márcia", "mario": "Mário", "medico": "Médico", "mineirao": "Mineirão", "oftalmologico": "Oftalmológico", "olimpia": "Olímpia",
    "parana": "Paraná", "pre": "Pré", "refugio": "Refúgio", "regia": "Régia", "sabia": "Sabiá", "sao": "São", "saude": "Saúde", "sonia": "Sônia", "vitoria": "Vitória",
    "lirios": "Lírios", "trujilo": "Trujillo", "jd": "Jardim", "jad": "Jardim", "jadim": "Jardim", "prq": "Parque", "pq": "Parque", "v": "Vila", "vil": "Vila",
    "av": "Avenida", "dr": "Dr.", "atend": "Atendimento", "pa": "PA", "upa": "UPA", "caps": "CAPS", "gpaci": "GPACI", "amhe": "AMHE", "ij": "IJ", "ad": "AD",
    "i": "I", "iii": "III", "em": "em", "unimed": "Unimed",
}


def _embelezar(texto: str, nome_br: Callable[[str], str]) -> str:
    return " ".join(PALAVRAS.get(w.lower(), w) for w in nome_br(texto).split())


def nome_unidade(nome: str, nome_br: Callable[[str], str]) -> str:
    n = nome.strip()
    curto = re.sub(r"\s+SOROCABA$", "", n)
    if len(curto.split()) >= 3 and curto.split()[-1] not in ("DE", "DO", "DA", "EM"):  # "Santa Casa de" ou "Conjunto Hospitalar" sem a cidade ficam ambíguos
        n = curto
    return _embelezar(n, nome_br)


def _endereco(u: dict, nome_br: Callable[[str], str]) -> str:
    via = _embelezar(u["logradouro"], nome_br)
    num = u["numero"] if u["numero"] and u["numero"].upper() not in ("S/N", "SN", "0") else "s/n"
    bairro = _embelezar(u["bairro"], nome_br) if len(u["bairro"]) != 20 else ""  # o CNES corta o bairro em 20 caracteres
    return ", ".join(x for x in (f"{via}, {num}" if via else "", bairro) if x)


def _telefone(t: str) -> str:
    d = re.sub(r"\D", "", t or "")
    if len(d) in (10, 11) and d[:2] == "15":
        d = d[2:]
    if len(d) == 8:
        return f"(15) {d[:4]}-{d[4:]}"
    if len(d) == 9:
        return f"(15) {d[:5]}-{d[5:]}"
    return ""


def contexto_hospitais(env: dict, nome_br: Callable[[str], str]) -> dict:
    d = env["dados"]
    per = next(r for r in d if r["recorte"] == "periodo")
    unidades = [r for r in d if r["recorte"] == "unidade"]
    leitos_por: dict[str, list[dict]] = defaultdict(list)
    for r in d:
        if r["recorte"] == "leito":
            leitos_por[r["cnes"]].append(r)
    totais = {r["cnes"]: r for r in d if r["recorte"] == "internacao_total"}
    caps: dict[str, list[dict]] = defaultdict(list)
    esp: dict[str, list[dict]] = defaultdict(list)
    meses: dict[str, list[dict]] = defaultdict(list)
    for r in d:
        if r["recorte"] == "internacao_capitulo":
            caps[r["cnes"]].append(r)
        elif r["recorte"] == "internacao_especialidade":
            esp[r["cnes"]].append(r)
        elif r["recorte"] == "internacao_mes":
            meses[r["cnes"]].append(r)
    hospitais = []
    for u in unidades:
        if u["tipo"] not in HOSPITALAR or u["leitos"] == 0:
            continue
        agrup: dict[str, dict] = defaultdict(lambda: {"existentes": 0, "sus": 0})
        for l in leitos_por[u["cnes"]]:
            a = agrup[l["especialidade"]]
            a["existentes"] += l["existentes"]
            a["sus"] += l["sus"]
        especialidades = sorted(({"nome": k, **v} for k, v in agrup.items()), key=lambda x: (-x["existentes"], x["nome"]))
        t = totais.get(u["cnes"])
        servicos = [rot for rot, ativo in (("Urgência e emergência", u["urgencia"]), ("Centro cirúrgico", u["centro_cirurgico"]), ("Centro obstétrico (partos)", u["centro_obstetrico"]),
                                           ("Atendimento neonatal", u["neonatal"])) if ativo]
        hospitais.append({
            "cnes": u["cnes"], "nome": nome_unidade(u["nome"], nome_br), "natureza": u["natureza"], "atende_sus": bool(u["atende_sus"]), "endereco": _endereco(u, nome_br), "telefone": _telefone(u["telefone"]),
            "leitos": u["leitos"], "leitos_sus": u["leitos_sus"], "leitos_uti": u["leitos_uti"], "leitos_uti_sus": u["leitos_uti_sus"], "servicos": servicos,
            "especialidades": especialidades[:MAX_ESPECIALIDADES], "n_especialidades": len(especialidades),
            "internacoes": t["internacoes"] if t else None, "dias": t["dias"] if t else None, "pct_de_fora": t["pct_de_fora"] if t else None, "uso": t["uso_estimado_pct"] if t else None,
            "tratamentos": sorted(({"nome": c["capitulo"], "n": c["internacoes"]} for c in caps.get(u["cnes"], [])), key=lambda x: -x["n"])[:4],
            "por_especialidade": sorted(({"nome": e["especialidade"], "n": e["internacoes"]} for e in esp.get(u["cnes"], [])), key=lambda x: -x["n"]),
        })
    hospitais.sort(key=lambda h: (-(h["internacoes"] or 0), -h["leitos"], h["nome"]))
    maxima = max((h["internacoes"] or 0 for h in hospitais), default=0)
    for h in hospitais:
        h["barra_internacoes"] = round(100 * (h["internacoes"] or 0) / maxima) if maxima else 0

    def lista(tipos: tuple[str, ...]) -> list[dict]:
        itens = [{"nome": nome_unidade(u["nome"], nome_br), "tipo": u["tipo_nome"], "endereco": _endereco(u, nome_br), "telefone": _telefone(u["telefone"]), "natureza": u["natureza"]}
                 for u in unidades if u["tipo"] in tipos]
        return sorted(itens, key=lambda i: i["nome"])

    sus_hosp = [h for h in hospitais if h["atende_sus"]]
    tot_int = sum(h["internacoes"] or 0 for h in hospitais)
    fora = sum((h["internacoes"] or 0) * (h["pct_de_fora"] or 0) / 100 for h in hospitais)
    resumo = {
        "n_hospitais": len(hospitais), "n_hospitais_sus": len(sus_hosp), "leitos": sum(h["leitos"] for h in hospitais), "leitos_sus": sum(h["leitos_sus"] for h in hospitais),
        "uti": sum(h["leitos_uti"] for h in hospitais), "uti_sus": sum(h["leitos_uti_sus"] for h in hospitais), "internacoes": tot_int, "pct_de_fora": round(100 * fora / tot_int) if tot_int else None,
    }
    maiores = [h for h in hospitais if h["uso"] is not None]
    return {"hospitais": hospitais, "resumo": resumo, "urgencias": lista(URGENCIA), "ubs": lista(ATENCAO_BASICA), "caps": lista(("70",)),
            "ref_hosp": f"leitos em {per['competencia_cnes'][4:]}/{per['competencia_cnes'][:4]}; internações até {per['ultima'][4:]}/{per['ultima'][:4]}",
            "maiores_uso": sorted(maiores, key=lambda h: -h["uso"])[:2]}
