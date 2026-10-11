"""Transforma os recortes do INEP em data/public/escolas.json (uma linha por escola em atividade).

Puro e offline. Sem ranking: a ordem é alfabética e nenhum campo compara escolas entre si.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia
from scripts.geo import carregar_contorno, dentro

RAIZ = Path(__file__).resolve().parent.parent
REDES = {"1": "Federal", "2": "Estadual", "3": "Municipal", "4": "Privada"}
LOCALIZACAO = {"1": "Urbana", "2": "Rural"}
EM_ATIVIDADE = "1"
INFRA = {
    "biblioteca": "IN_BIBLIOTECA",
    "lab_informatica": "IN_LABORATORIO_INFORMATICA",
    "lab_ciencias": "IN_LABORATORIO_CIENCIAS",
    "quadra_esportes": "IN_QUADRA_ESPORTES",
    "internet": "IN_INTERNET",
    "refeitorio": "IN_REFEITORIO",
    "rampas": "IN_ACESSIBILIDADE_RAMPAS",
}
MATRICULAS = {
    "mat_infantil": "QT_MAT_INF",
    "mat_anos_iniciais": "QT_MAT_FUND_AI",
    "mat_anos_finais": "QT_MAT_FUND_AF",
    "mat_medio": "QT_MAT_MED",
    "mat_eja": "QT_MAT_EJA",
    "mat_total": "QT_MAT_BAS",
}
ETAPAS = {"ai": "ideb_anos_iniciais", "af": "ideb_anos_finais"}


def inteiro(v: str) -> int | None:
    return int(v) if v.strip() else None


def decimal(v: str) -> float | None:
    v = v.strip()
    try:
        return round(float(v), 3)
    except ValueError:
        return None  # "-" e afins: o INEP não calculou para a escola nessa edição


def ler(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def bool_ou_nulo(v: str) -> bool | None:
    v = v.strip()
    return None if v == "" else v == "1"


def _endereco(r: dict) -> str | None:
    rua = " ".join(r["DS_ENDERECO"].split())
    numero = " ".join(r["NU_ENDERECO"].split())
    return f"{rua}, {numero}" if rua and numero else rua or None


def _coordenadas(arq: Path, codigos: set[str]) -> dict[str, dict]:
    """Posição aproximada de data/raw/inep/coordenadas.csv (geocode_escolas.py). Valida formato, nível e contorno do município."""
    if not arq.exists():
        return {}
    contorno = carregar_contorno()
    saida: dict[str, dict] = {}
    for r in csv.DictReader(arq.open(encoding="utf-8", newline=""), delimiter=";"):
        if r["co_inep"] not in codigos:  # escola que deixou de funcionar continua no Censo; só código desconhecido é erro
            raise ValueError(f"coordenadas de escola inexistente no Censo: {r['co_inep']}")
        if not r["precisao"]:
            continue
        lat, lon = float(r["lat"]), float(r["lon"])
        if r["precisao"] not in ("porta", "rua") or not dentro(contorno, lat, lon):
            raise ValueError(f"coordenada inválida para {r['co_inep']}")
        saida[r["co_inep"]] = {"lat": round(lat, 5), "lon": round(lon, 5), "posicao": r["precisao"]}
    return saida


def _manifesto_coordenadas(raw: Path) -> dict | None:
    arq = raw / "manifesto_coordenadas.json"
    if not arq.exists():
        return None
    m = json.loads(arq.read_text(encoding="utf-8"))
    if hashlib.sha256((raw / "coordenadas.csv").read_bytes()).hexdigest() != m["sha256_csv"]:
        raise ValueError("coordenadas.csv não confere com o hash do manifesto de coordenadas")
    return m


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    arqs = man["arquivos"]
    ano_censo = arqs["censo_escolar"]["ano"]
    ideb: dict[str, dict[str, dict[str, str]]] = {}
    anos_ideb: dict[str, list[int]] = {}
    for sigla, nome in ETAPAS.items():
        linhas = ler(raw / arqs[nome]["arquivo"])
        ideb[sigla] = {r["ID_ESCOLA"]: r for r in linhas}
        anos_ideb[sigla] = sorted({int(c[-4:]) for c in linhas[0] if c.startswith("VL_OBSERVADO_")})
    ultimo_ideb = max(a[-1] for a in anos_ideb.values())
    primeiro_ideb = min(a[0] for a in anos_ideb.values())

    censo = list(ler(raw / arqs["censo_escolar"]["arquivo"]))
    escolas = [r for r in censo if r["TP_SITUACAO_FUNCIONAMENTO"] == EM_ATIVIDADE]
    ativas = {r["CO_ENTIDADE"] for r in escolas}
    sem_cadastro = sum(1 for s in ideb.values() for k in s if k not in ativas)

    invalidos = [r["CO_ENTIDADE"] for r in escolas if not re.fullmatch(r"\d{8}", r["CO_ENTIDADE"])]
    if invalidos:
        raise ValueError(f"código INEP fora do formato de 8 dígitos: {invalidos[:3]}")
    coords = _coordenadas(raw / "coordenadas.csv", {r["CO_ENTIDADE"] for r in censo})
    dados = []
    for r in sorted(escolas, key=lambda r: (r["NO_ENTIDADE"], r["CO_ENTIDADE"])):
        reg: dict = {
            "co_inep": r["CO_ENTIDADE"],
            "escola": " ".join(r["NO_ENTIDADE"].split()),
            "bairro": " ".join(r["NO_BAIRRO"].split()) or None,
            "ano_censo": int(r["NU_ANO_CENSO"]),
            "endereco": _endereco(r),
            **coords.get(r["CO_ENTIDADE"], {"lat": None, "lon": None, "posicao": None}),
            "rede": REDES[r["TP_DEPENDENCIA"]],
            "localizacao": LOCALIZACAO[r["TP_LOCALIZACAO"]],
            **{k: inteiro(r[c]) for k, c in MATRICULAS.items()},
            **{k: bool_ou_nulo(r[c]) for k, c in INFRA.items()},
        }
        for sigla in ETAPAS:
            linha = ideb[sigla].get(r["CO_ENTIDADE"])
            for ano in anos_ideb[sigla]:
                reg[f"ideb_{sigla}_{ano}"] = decimal(linha[f"VL_OBSERVADO_{ano}"]) if linha else None
            reg[f"aprovacao_{sigla}"] = decimal(linha[f"VL_INDICADOR_REND_{anos_ideb[sigla][-1]}"]) if linha else None
            reg[f"saeb_{sigla}"] = decimal(linha[f"VL_NOTA_MEDIA_{anos_ideb[sigla][-1]}"]) if linha else None
        dados.append(reg)

    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    mc = _manifesto_coordenadas(raw)
    return Envelope(
        painel="escolas",
        fonte=Fonte(
            nome="INEP — Censo Escolar e IDEB por escola",
            url="https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos",
            licenca="Dados abertos do governo federal",
            acesso_em=date.fromisoformat(man["acesso_em"]),
        ),
        referencia=Referencia(
            inicio=date(min(ano_censo, primeiro_ideb), 1, 1), fim=date(max(ano_censo, ultimo_ideb), 12, 31), granularidade=Granularidade.ANUAL
        ),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL,
            n_registros=len(dados),
            notas=[
                f"Matrículas e infraestrutura: Censo Escolar {ano_censo}, declarado pelas próprias escolas. IDEB: edição {ultimo_ideb}.",
                "Só escolas em atividade no Censo. IDEB existe apenas para escolas públicas com número suficiente de alunos avaliados.",
                "Campo vazio significa que o INEP não publicou o valor para aquela escola; não é zero.",
                "Sem ranking e sem nota agregada: o IDEB reflete também o perfil socioeconômico dos alunos.",
                *([f"{sem_cadastro} escola(s) do IDEB não constam como em atividade no Censo e ficaram de fora."] if sem_cadastro else []),
                *(["Posições (lat, lon, posicao): © colaboradores do OpenStreetMap, ODbL 1.0, obtidas pelo Nominatim a partir do endereço do Censo Escolar; aproximadas, nível \"porta\" ou \"rua\" (trecho curto). " + f"SHA-256 de coordenadas.csv: {mc['sha256_csv']}."] if mc else []),
                f"SHA-256 do manifesto de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "inep")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "escolas.json")
    args = p.parse_args()
    envelope = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(
        json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
