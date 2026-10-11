"""Transforma as contagens agregadas da SSP-SP em data/public/seguranca.json. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent
BAIRRO_MINIMO = 50  # roubos + furtos no ano; abaixo disso o bairro entra em "demais"
JANELA = 12

# Só categorias presentes com o mesmo nome em todos os anos da série.
GRUPOS = {
    "roubos": ("Roubos", {"ROUBO - OUTROS", "ROUBO DE VEICULO", "ROUBO DE CARGA"}),
    "furtos": ("Furtos", {"FURTO - OUTROS", "FURTO DE VEICULO", "FURTO DE CARGA"}),
    "mortes_dolosas": ("Mortes por crime doloso", {"HOMICIDIO DOLOSO", "LATROCINIO", "LESAO CORPORAL SEGUIDA DE MORTE"}),
    "lesao_dolosa": ("Lesão corporal dolosa", {"LESAO CORPORAL DOLOSA"}),
    "estupros": ("Estupros", {"ESTUPRO", "ESTUPRO DE VULNERAVEL"}),
    "trafico": ("Tráfico de entorpecentes", {"TRAFICO DE ENTORPECENTES"}),
}
DE_PARA = {n: g for g, (_, ns) in GRUPOS.items() for n in ns}
FAIXAS = {"De madrugada": range(0, 6), "Pela manhã": range(6, 12), "A tarde": range(12, 18), "A noite": range(18, 24)}


def chave(natureza: str) -> str:
    sem = unicodedata.normalize("NFKD", natureza.replace("–", "-").replace("—", "-")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s*[-–]\s*", " - ", " ".join(sem.split()))


def ler(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def registro(recorte, ano, grupo, n, mes=None, categoria=None, pct=None) -> dict:
    return {"recorte": recorte, "ano": ano, "mes": mes, "grupo": grupo, "categoria": categoria, "n": n, "pct": pct}


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    anos = sorted(int(a) for a in man["anos"])
    mensal: Counter = Counter()
    por_ano: dict[int, dict[str, list[dict]]] = {}
    for ano in anos:
        pasta = raw / str(ano)
        por_ano[ano] = {t: ler(pasta / f"{t}.csv") for t in ("hora", "bairro", "conduta")}
        for r in ler(pasta / "mensal.csv"):
            g = DE_PARA.get(chave(r["natureza"]))
            if g:
                mensal[(int(r["ano"]), int(r["mes"]), g)] += int(r["n"])

    meses = sorted({(a, m) for a, m, _ in mensal})
    ultimo = meses[-1]
    completos = [a for a in anos if all((a, m) in {(x, y) for x, y in meses} for m in range(1, 13))]
    if not completos:
        raise ValueError("nenhum ano completo na série")
    ano_ref = completos[-1]

    dados: list[dict] = []
    for (a, m, g), n in sorted(mensal.items()):
        dados.append(registro("mensal", a, g, n, mes=m))

    # Janela dos últimos 12 meses contra os 12 anteriores, terminando no último mês publicado.
    idx = meses.index(ultimo)
    if idx + 1 < 2 * JANELA:
        raise ValueError("série curta demais para comparar duas janelas de 12 meses")
    atual, anterior = meses[idx + 1 - JANELA: idx + 1], meses[idx + 1 - 2 * JANELA: idx + 1 - JANELA]
    for g in GRUPOS:
        dados.append(registro("janela_atual", atual[-1][0], g, sum(mensal[(a, m, g)] for a, m in atual), mes=atual[-1][1]))
        dados.append(registro("janela_anterior", anterior[-1][0], g, sum(mensal[(a, m, g)] for a, m in anterior), mes=anterior[-1][1]))

    # Horário: contagem por hora exata quando o boletim a traz; sem hora, vale a faixa do dia informada.
    horas: dict[tuple[str, str], int] = defaultdict(int)
    for r in por_ano[ano_ref]["hora"]:
        g = DE_PARA.get(chave(r["natureza"]))
        if g in ("roubos", "furtos"):
            horas[(g, r["hora"])] += int(r["n"])
    for g in ("roubos", "furtos"):
        com_hora = {h: horas[(g, f"{h:02d}")] for h in range(24)}
        total = sum(horas[(gg, h)] for gg, h in horas if gg == g)
        for h, n in com_hora.items():
            dados.append(registro("hora", ano_ref, g, n, categoria=f"{h:02d}", pct=round(n / total * 100, 1) if total else None))
        for faixa in ("De madrugada", "Pela manhã", "A tarde", "A noite"):
            n = horas[(g, faixa)] + sum(com_hora[h] for h in FAIXAS[faixa])
            dados.append(registro("periodo", ano_ref, g, n, categoria=faixa, pct=round(n / total * 100, 1) if total else None))
        sem = horas[(g, "Sem informação")]
        dados.append(registro("periodo", ano_ref, g, sem, categoria="Horário não informado", pct=round(sem / total * 100, 1) if total else None))

    # Tipos de furto, pelo campo de conduta do boletim.
    con: dict[str, int] = defaultdict(int)
    for r in por_ano[ano_ref]["conduta"]:
        if DE_PARA.get(chave(r["natureza"])) == "furtos":
            con["Sem informação" if r["conduta"].upper() in ("NULL", "") else r["conduta"]] += int(r["n"])
    total_c = sum(con.values())
    for nome, n in sorted(con.items(), key=lambda kv: (-kv[1], kv[0])):
        dados.append(registro("furto_tipo", ano_ref, "furtos", n, categoria=nome, pct=round(n / total_c * 100, 1)))

    # Bairros: contagem, em ordem alfabética (ver notas). Bairros pequenos e grafias isoladas vão para "demais".
    bai: dict[tuple[str, str], int] = defaultdict(int)
    for r in por_ano[ano_ref]["bairro"]:
        g = DE_PARA.get(chave(r["natureza"]))
        if g in ("roubos", "furtos"):
            bai[(r["bairro"], g)] += int(r["n"])
    bairros = {b for b, _ in bai}
    soma = {b: bai[(b, "roubos")] + bai[(b, "furtos")] for b in bairros}
    grandes = sorted((b for b in bairros if soma[b] >= BAIRRO_MINIMO and b != "SEM INFORMAÇÃO"), key=lambda b: unicodedata.normalize("NFKD", b))
    for b in grandes:
        for g in ("roubos", "furtos"):
            dados.append(registro("bairro", ano_ref, g, bai[(b, g)], categoria=b))
    resto = [b for b in bairros if b not in grandes]
    for g in ("roubos", "furtos"):
        dados.append(registro("bairro", ano_ref, g, sum(bai[(b, g)] for b in resto), categoria="Demais bairros, grafias variantes e sem informação"))

    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    acesso = max(v["coletado_em"] for v in man["anos"].values())
    return Envelope(
        painel="seguranca",
        fonte=Fonte(
            nome="SSP-SP — Estatísticas de segurança (SPDados, ocorrências registradas)",
            url="https://www.ssp.sp.gov.br/estatistica/dados-mensais",
            licenca="Dados abertos da SSP-SP",
            acesso_em=date.fromisoformat(acesso),
        ),
        referencia=Referencia(inicio=date(meses[0][0], meses[0][1], 1), fim=date(ultimo[0], ultimo[1], 28), granularidade=Granularidade.MENSAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL,
            n_registros=len(dados),
            notas=[
                "Os números são boletins de ocorrência registrados, não crimes: crime não registrado não entra, e mudanças na forma de registrar alteram a série.",
                f"Ocorrências com município de circunscrição igual a Sorocaba (código IBGE 3552205), por mês de registro na estatística oficial, de {meses[0][1]:02d}/{meses[0][0]} a {ultimo[1]:02d}/{ultimo[0]}.",
                "O mês mais recente tende a subir quando registros atrasados são incluídos pela SSP-SP.",
                "Mortes por crime doloso = homicídio doloso + latrocínio + lesão corporal seguida de morte. Não inclui mortes por intervenção policial nem homicídio no trânsito.",
                f"Período do dia, tipos de furto e bairros usam o ano completo mais recente ({ano_ref}). Horário: usa a hora exata do boletim e, sem ela, a faixa do dia informada; a parcela sem nenhuma das duas é mostrada. A hora 00h pode estar inflada por preenchimento padrão (00:00 exato).",
                f"Bairros em ordem alfabética, sem ranking. O campo é digitado no boletim (grafias variam) e bairros com menos de {BAIRRO_MINIMO} roubos e furtos no ano ficam em 'demais'. Contagem não mede risco: depende de população, comércio e fluxo de pessoas.",
                "Séries antigas usam as mesmas categorias com grafia normalizada (ex.: TRAFICO e TRÁFICO). Categorias que só aparecem a partir de 2023 ficaram de fora para não distorcer a comparação.",
                f"SHA-256 do manifesto de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "ssp")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "seguranca.json")
    args = p.parse_args()
    e = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
