"""Calendário de vacinação e campanhas em data/public/saude_vacinas.json. Curadoria manual em data/raw/vacinas; puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent
PUBLICOS = ("Crianças", "Adolescentes e jovens (10 a 24 anos)", "Adultos (25 a 59 anos)", "Idosos (60 anos ou mais)", "Gestantes")


def _csv(raw: Path, nome: str, campos: list[str]) -> list[dict]:
    with (raw / nome).open(encoding="utf-8", newline="") as f:
        leitor = csv.DictReader(f, delimiter=";")
        if leitor.fieldnames != campos:
            raise ValueError(f"{nome}: colunas esperadas {campos}")
        return list(leitor)


def _https(url: str, onde: str) -> str:
    if not url.startswith("https://"):
        raise ValueError(f"{onde}: URL precisa ser https")
    return url


def construir(raw: Path) -> Envelope:
    fonte = json.loads((raw / "fonte.json").read_text(encoding="utf-8"))
    cal = _csv(raw, "calendario.csv", ["publico", "idade", "vacina", "protege", "nota"])
    camp = _csv(raw, "campanhas.csv", ["nome", "inicio", "fim", "publico", "resumo", "fonte_url"])
    if not cal:
        raise ValueError("calendário vazio")
    vistos = set()
    dados: list[dict] = []
    for r in cal:
        if r["publico"] not in PUBLICOS:
            raise ValueError(f"público desconhecido: {r['publico']!r}")
        if not (r["idade"] and r["vacina"] and r["protege"]):
            raise ValueError(f"linha incompleta do calendário: {r}")
        chave = (r["publico"], r["idade"], r["vacina"], r["nota"])
        if chave in vistos:
            raise ValueError(f"linha repetida no calendário: {chave}")
        vistos.add(chave)
        dados.append({"recorte": "calendario", **r})
    for r in camp:
        ini, fim = date.fromisoformat(r["inicio"]), date.fromisoformat(r["fim"])
        if fim < ini:
            raise ValueError(f"campanha com fim antes do início: {r['nome']}")
        dados.append({"recorte": "campanha", "nome": r["nome"], "inicio": ini.isoformat(), "fim": fim.isoformat(), "publico": r["publico"], "resumo": r["resumo"], "fonte_url": _https(r["fonte_url"], r["nome"])})
    conferido = max(date.fromisoformat(fonte["calendario"]["conferido_em"]), date.fromisoformat(fonte["campanhas"]["conferido_em"]))
    h = hashlib.sha256((raw / "calendario.csv").read_bytes() + (raw / "campanhas.csv").read_bytes()).hexdigest()
    return Envelope(
        painel="saude_vacinas",
        fonte=Fonte(nome=fonte["calendario"]["fonte"], url=_https(fonte["calendario"]["url"], "calendário"), licenca="Informação pública do Ministério da Saúde; transcrita e conferida manualmente", acesso_em=conferido),
        referencia=Referencia(inicio=conferido, fim=conferido, granularidade=Granularidade.MENSAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL, n_registros=len(dados),
            notas=[
                f"Calendário Nacional de Vacinação do Ministério da Saúde, transcrito e conferido em {fonte['calendario']['conferido_em']}. {fonte['calendario']['observacao']}",
                f"Campanhas conferidas em {fonte['campanhas']['conferido_em']} por busca nas páginas da Prefeitura e da imprensa. {fonte['campanhas']['observacao']}",
                "O esquema de cada vacina pode mudar por orientação do Ministério ou do estado; na dúvida, vale a orientação da UBS e a caderneta de vacinação.",
                "Não há dado aberto confiável de cobertura vacinal por município que dispense registros individuais, por isso o painel não mostra cobertura.",
                f"SHA-256 dos arquivos de curadoria: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "vacinas")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "saude_vacinas.json")
    a = p.parse_args()
    e = construir(a.raw)
    a.saida.parent.mkdir(parents=True, exist_ok=True)
    a.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
