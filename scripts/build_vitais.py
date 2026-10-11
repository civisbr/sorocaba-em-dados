"""Mortes e nascimentos de moradores em data/public/saude_panorama.json. Puro e offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    texto = (raw / "indicadores.csv").read_text(encoding="utf-8")
    if hashlib.sha256(texto.encode("utf-8")).hexdigest() != man["sha256_csv"]:
        raise ValueError("indicadores.csv não confere com o hash do manifesto")
    linhas = list(csv.DictReader(io.StringIO(texto), delimiter=";"))
    if not linhas:
        raise ValueError("indicadores vazios")
    dados = [{"recorte": "indicador", "ano": int(r["ano"]), "bloco": r["bloco"], "categoria": r["categoria"], "n": int(r["n"])} for r in linhas]
    anos = sorted({r["ano"] for r in dados})
    for a in anos:
        blocos = {r["bloco"] for r in dados if r["ano"] == a}
        if not {"obito_total", "nasc_total"} <= blocos:
            raise ValueError(f"ano {a} sem total de óbitos ou de nascimentos")
    return Envelope(
        painel="saude_panorama",
        fonte=Fonte(nome="SIM e SINASC — DATASUS, Ministério da Saúde", url="https://datasus.saude.gov.br/", licenca="Dados abertos do Ministério da Saúde (DATASUS); citar a fonte", acesso_em=date.fromisoformat(man["verificado_em"])),
        referencia=Referencia(inicio=date(anos[0], 1, 1), fim=date(anos[-1], 12, 31), granularidade=Granularidade.ANUAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL, n_registros=len(dados),
            notas=[
                "Óbitos e nascidos vivos de moradores de Sorocaba, pelo local de residência da mãe ou do falecido, mesmo que o fato tenha ocorrido em outra cidade.",
                f"O ano mais recente ({anos[-1]}) pode ser revisado pelo Ministério da Saúde; os anteriores são mais estáveis.",
                "Óbitos fetais (natimortos) ficam fora. A causa é a causa básica da declaração de óbito, agrupada em capítulos do CID-10.",
                "Contagens com menos de 5 ocorrências são omitidas, exceto os totais.",
                "A taxa de mortalidade infantil usa poucos casos por ano (cerca de 90): varia de um ano para outro sem que isso signifique melhora ou piora real.",
                f"SHA-256 do recorte de coleta: {man['sha256_csv']}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "vitais")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "saude_panorama.json")
    a = p.parse_args()
    e = construir(a.raw)
    a.saida.parent.mkdir(parents=True, exist_ok=True)
    a.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
