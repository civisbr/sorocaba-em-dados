"""Ocorrências nas rodovias em data/public/artesp.json, a partir das contagens agregadas. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia
from scripts.fetch_artesp import DETALHE_MINIMO, PRIMEIRO_DIA, TRECHO_KM, TRECHO_MINIMO

RAIZ = Path(__file__).resolve().parent.parent
TOP_TRECHOS = 10
MESES_DEFASAGEM_MAX = 2


def ler(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    verificado = date.fromisoformat(man["verificado_em"])
    anos = sorted(int(a) for a in man["anos"])
    mensal: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0, 0, 0])  # acidentes, fatais, feridos, outras ocorrências
    for a in anos:
        for r in ler(raw / str(a) / "mensal.csv"):
            m = mensal[(int(r["ano"]), int(r["mes"]))]
            if r["classe"] == "Acidente":
                m[0] += int(r["ocorrencias"])
                m[1] += int(r["vitimas_fatais"])
                m[2] += int(r["feridos"])
            elif r["classe"] != "Obra":
                m[3] += int(r["ocorrencias"])
    # a série começa em 16/11/2021 e o mês de coleta ainda está aberto: só meses inteiros entram
    fim = (verificado.year, verificado.month)
    chaves = [(n // 12, n % 12 + 1) for n in range(PRIMEIRO_DIA.year * 12 + PRIMEIRO_DIA.month, fim[0] * 12 + fim[1] - 1)]  # dez/2021 até o mês anterior; mês sem registro entra com zero e a marca “sem registro”
    if len(chaves) < 12:
        raise ValueError("menos de 12 meses completos na coleta da ARTESP")
    dados: list[dict] = []
    for ano, mes in chaves:
        ac, fatais, feridos, outras = mensal[(ano, mes)] if (ano, mes) in mensal else [0, 0, 0, 0]
        dados.append({"recorte": "mensal", "ano": ano, "mes": mes, "categoria": None if (ano, mes) in mensal else "sem registro", "n": ac, "n2": fatais, "n3": feridos, "n4": outras})
    ano_ref = max(a for a in anos if PRIMEIRO_DIA.year < a < verificado.year)
    for recorte, arquivo, campo in (("rodovia", "rodovia.csv", "rodovia"), ("tipo", "tipo.csv", "tipo")):
        for r in sorted(ler(raw / str(ano_ref) / arquivo), key=lambda r: (-int(r["acidentes"]), r[campo])):
            if int(r["acidentes"]) >= DETALHE_MINIMO:
                dados.append({"recorte": recorte, "ano": ano_ref, "mes": None, "categoria": r[campo], "n": int(r["acidentes"]), "n2": None, "n3": None, "n4": None})
    trechos = [r for r in ler(raw / str(ano_ref) / "trecho.csv") if int(r["acidentes"]) >= TRECHO_MINIMO]
    for r in sorted(trechos, key=lambda r: (-int(r["acidentes"]), r["rodovia"], int(r["km_ini"])))[:TOP_TRECHOS]:
        dados.append({"recorte": "trecho", "ano": ano_ref, "km": int(r["km_ini"]), "mes": None, "categoria": r["rodovia"], "n": int(r["acidentes"]), "n2": None, "n3": None, "n4": None})
    ultimo = chaves[-1]
    defasagem = (verificado.year - ultimo[0]) * 12 + verificado.month - ultimo[1]
    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    return Envelope(
        painel="artesp",
        fonte=Fonte(nome="ARTESP — Centro de Controle Multimodal (CCM), ocorrências rodoviárias", url="https://ccm.artesp.sp.gov.br/rodovias/ocorrencias", licenca="Creative Commons Atribuição-NãoComercial 4.0 (CC BY-NC 4.0)", acesso_em=verificado),
        referencia=Referencia(inicio=date(chaves[0][0], chaves[0][1], 1), fim=date(ultimo[0], ultimo[1], 28), granularidade=Granularidade.MENSAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL, n_registros=len(dados),
            notas=[
                "Só rodovias concedidas monitoradas pelo CCM da ARTESP (como SP-270, SP-075 e SP-280); ruas e avenidas da cidade não entram. Parte desses acidentes também aparece no Infosiga SP: as fontes se sobrepõem e os números não devem ser somados.",
                "Os dados são enviados pelas concessionárias e podem ser corrigidos depois; a ARTESP não garante exatidão nem completude. Vítimas fatais e feridos são os registrados na ocorrência e podem diferir de outras bases (Infosiga, boletins policiais).",
                f"Contagem por mês de ocorrência, em meses inteiros (a série começa em 16/11/2021). Acidente é o que a ARTESP classifica como tal; “outras ocorrências” reúne as demais classes publicadas, sem obras. A API traz só as ocorrências publicadas pelo CCM (algumas dezenas de acidentes por ano em Sorocaba, com proporção alta de mortes): não é o total de acidentes nas rodovias. Meses sem nenhum registro na fonte aparecem como “sem registro” e podem ser lacuna, não ausência de acidentes. Rodovia e tipo de acidente usam {ano_ref}, o último ano fechado, e só aparecem com {DETALHE_MINIMO} ou mais acidentes.",
                f"Trechos de {TRECHO_KM} km com {TRECHO_MINIMO} ou mais acidentes em {ano_ref}; contagem por trecho não mede perigo, depende do tráfego e da extensão. Não são publicados pontos individuais nem relatos.",
                "Um acidente que cruza o limite do município pode entrar em mais de uma cidade. Rodovias são mostradas com o nome da fonte (SPI e SPM, por exemplo, são vias de ligação e marginais de outra rodovia).",
                *([f"Atenção: o último mês completo é {ultimo[1]:02d}/{ultimo[0]}, {defasagem} meses antes da coleta; a fonte pode estar parada."] if defasagem > MESES_DEFASAGEM_MAX else []),
                f"SHA-256 do manifesto de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "artesp")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "artesp.json")
    args = p.parse_args()
    e = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
