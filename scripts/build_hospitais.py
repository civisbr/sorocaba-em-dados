"""Hospitais, leitos e internações SUS em data/public/saude_hospitais.json. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia
from scripts.saude_codigos import ESPEC_SIH, GRUPO_LEITO, HOSPITALAR, LEITOS, TIPOS_UNIDADE, UTI, natureza

RAIZ = Path(__file__).resolve().parent.parent
LEITOS_SUS_MINIMOS = 20  # abaixo disso o "uso estimado" oscila demais para ser mostrado
TOP_CAPITULOS = 6
CELULA_MINIMA = 5


def _csv(raw: Path, nome: str, esperado: str) -> list[dict]:
    texto = (raw / nome).read_text(encoding="utf-8")
    if hashlib.sha256(texto.encode("utf-8")).hexdigest() != esperado:
        raise ValueError(f"{nome} não confere com o hash do manifesto")
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def _ym(c: str) -> date:
    return date(int(c[:4]), int(c[4:]), 1)


def construir(raw_cnes: Path, raw_sih: Path) -> Envelope:
    mc = json.loads((raw_cnes / "manifesto.json").read_text(encoding="utf-8"))
    ms = json.loads((raw_sih / "manifesto.json").read_text(encoding="utf-8"))
    estab = _csv(raw_cnes, "estabelecimentos.csv", mc["sha256_csv"]["estabelecimentos.csv"])
    leitos = _csv(raw_cnes, "leitos.csv", mc["sha256_csv"]["leitos.csv"])
    sih = _csv(raw_sih, "internacoes.csv", ms["sha256_csv"])
    if not estab or not sih:
        raise ValueError("recortes vazios")
    dados: list[dict] = [{"recorte": "periodo", "competencia_cnes": mc["competencia"], "primeira": ms["primeira"], "ultima": ms["ultima"]}]
    por_cnes = {e["cnes"]: e for e in estab}
    lt: dict[str, dict] = defaultdict(lambda: {"leitos": 0, "sus": 0, "uti": 0, "uti_sus": 0})
    for r in leitos:
        a = lt[r["cnes"]]
        n, s = int(r["existentes"]), int(r["sus"])
        a["leitos"] += n
        a["sus"] += s
        if r["cod_leito"] in UTI:
            a["uti"] += n
            a["uti_sus"] += s
        dados.append({"recorte": "leito", "cnes": r["cnes"], "grupo": GRUPO_LEITO.get(r["tp_leito"], "Outros"), "especialidade": LEITOS.get(r["cod_leito"], f"Código {r['cod_leito']}"),
                      "existentes": n, "sus": s})
    for e in estab:
        a = lt.get(e["cnes"], {"leitos": 0, "sus": 0, "uti": 0, "uti_sus": 0})
        dados.append({"recorte": "unidade", "cnes": e["cnes"], "nome": e["nome"], "tipo": e["tipo"], "tipo_nome": TIPOS_UNIDADE.get(e["tipo"], e["tipo"]), "natureza": natureza(e["nat_jur"]),
                      "atende_sus": int(e["vinc_sus"]), "urgencia": int(e["urgencia"]), "centro_cirurgico": int(e["centro_cirurgico"]), "centro_obstetrico": int(e["centro_obstetrico"]),
                      "neonatal": int(e["neonatal"]), "bairro": e["bairro"], "logradouro": e["logradouro"], "numero": e["numero"], "telefone": e["telefone"],
                      "lat": float(e["lat"]) if e["lat"] else None, "lon": float(e["lon"]) if e["lon"] else None,
                      "leitos": a["leitos"], "leitos_sus": a["sus"], "leitos_uti": a["uti"], "leitos_uti_sus": a["uti_sus"]})
    meses = sorted({r["competencia"] for r in sih})
    tot: dict[str, dict] = defaultdict(lambda: {"n": 0, "dias": 0, "uti": 0, "fora": 0})
    esp: dict[tuple, int] = defaultdict(int)
    cap: dict[tuple, int] = defaultdict(int)
    for r in sih:
        c, n = r["cnes"], int(r["internacoes"])
        if c not in por_cnes or por_cnes[c]["tipo"] not in HOSPITALAR:
            continue
        t = tot[c]
        t["n"] += n
        t["dias"] += int(r["dias"])
        t["uti"] += int(r["dias_uti"])
        t["fora"] += n * (1 - int(r["residente"]))
        esp[(c, ESPEC_SIH[r["espec"]])] += n
        cap[(c, r["capitulo"])] += n
    for (c, nome), n in sorted(esp.items()):
        if n < CELULA_MINIMA:
            continue
        dados.append({"recorte": "internacao_especialidade", "cnes": c, "especialidade": nome, "internacoes": n})
    por_hosp: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (c, nome), n in cap.items():
        por_hosp[c].append((nome, n))
    for c, itens in sorted(por_hosp.items()):
        itens.sort(key=lambda x: (-x[1], x[0]))
        principais = [i for i in itens if i[0] != "Outros capítulos"][:TOP_CAPITULOS]
        for nome, n in principais:
            dados.append({"recorte": "internacao_capitulo", "cnes": c, "capitulo": nome, "internacoes": n})
    for c, t in sorted(tot.items()):
        sus = lt[c]["sus"] if c in lt else 0
        uso = round(100 * t["dias"] / (sus * 365), 1) if sus >= LEITOS_SUS_MINIMOS else None
        dados.append({"recorte": "internacao_total", "cnes": c, "internacoes": t["n"], "dias": t["dias"], "dias_uti": t["uti"], "pct_de_fora": round(100 * t["fora"] / t["n"], 1) if t["n"] else None,
                      "leitos_sus": sus, "uso_estimado_pct": uso, "meses": len(meses)})
    if not any(d["recorte"] == "internacao_total" for d in dados):
        raise ValueError("nenhuma internação em hospital do CNES")
    h = hashlib.sha256((json.dumps(mc["sha256_csv"], sort_keys=True) + ms["sha256_csv"]).encode()).hexdigest()
    return Envelope(
        painel="saude_hospitais",
        fonte=Fonte(nome="CNES e SIH/SUS — DATASUS, Ministério da Saúde", url="https://datasus.saude.gov.br/", licenca="Dados abertos do Ministério da Saúde (DATASUS); citar a fonte", acesso_em=date.fromisoformat(ms["verificado_em"])),
        referencia=Referencia(inicio=_ym(meses[0]), fim=(_ym(meses[-1]) + timedelta(days=31)).replace(day=1) - timedelta(days=1), granularidade=Granularidade.MENSAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.ESTIMATIVA, n_registros=len(dados),
            notas=[
                f"Cadastro de estabelecimentos e leitos do CNES, competência {mc['competencia'][4:]}/{mc['competencia'][:4]}. O cadastro é declarado pelos próprios estabelecimentos e pode estar defasado.",
                f"Internações do SIH/SUS de {meses[0][4:]}/{meses[0][:4]} a {meses[-1][4:]}/{meses[-1][:4]}: só as pagas pelo SUS, sem as de convênios e particulares. Contam hospitais localizados em Sorocaba, inclusive pacientes de outras cidades.",
                "Não existe dado aberto de ocupação ou fila de hospital. O 'uso estimado dos leitos SUS' divide os dias de internação SUS dos últimos 12 meses pelos leitos SUS existentes vezes 365. É uma ordem de grandeza, não a lotação do dia. Os dias de células com menos de 5 internações foram zerados por privacidade, o que subestima um pouco o valor.",
                f"O uso estimado só aparece para hospitais com {LEITOS_SUS_MINIMOS} leitos SUS ou mais.",
                "Contagem de internações e de dias não mede qualidade do hospital: depende do porte, da especialidade e da gravidade dos casos.",
                f"SHA-256 dos recortes de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw-cnes", type=Path, default=RAIZ / "data" / "raw" / "cnes")
    p.add_argument("--raw-sih", type=Path, default=RAIZ / "data" / "raw" / "sih")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "saude_hospitais.json")
    a = p.parse_args()
    e = construir(a.raw_cnes, a.raw_sih)
    a.saida.parent.mkdir(parents=True, exist_ok=True)
    a.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
