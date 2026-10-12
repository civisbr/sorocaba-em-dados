"""Situação da verificação metrológica dos radares de Sorocaba em data/public/radares_inmetro.json. Puro e offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent


def _data(t) -> str | None:
    try:
        return datetime.strptime(str(t), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    texto = (raw / "medidores_sorocaba.json").read_text(encoding="utf-8")
    if hashlib.sha256(texto.encode("utf-8")).hexdigest() != man["sha256_filtrado"]:
        raise ValueError("medidores_sorocaba.json não confere com o hash do manifesto")
    dados = []
    for m in json.loads(texto):
        faixas = m.get("Faixas") or []
        hist = m.get("Historico") or []
        ultimo = max(hist, key=lambda h: _data(h.get("DataLaudo")) or "") if hist else {}
        dados.append({
            "recorte": "medidor", "local": " ".join(str(m["LocalVerificacao"]).split()), "tipo": m.get("TipoMedidor") or "",
            "ultima_verificacao": _data(m.get("DataUltimaVerificacao")), "validade": _data(m.get("DataValidade")), "resultado": m.get("UltimoResultado") or "",
            "inmetros": "; ".join(sorted({str(f["NumeroInmetro"]) for f in faixas if f.get("NumeroInmetro")})), "series": "; ".join(sorted({str(f["NumeroSerie"]) for f in faixas if f.get("NumeroSerie")})),
            "velocidades": "; ".join(sorted({str(int(f["VelocidadeNominal"])) for f in faixas if str(f.get("VelocidadeNominal", "")).isdigit() and int(f["VelocidadeNominal"]) > 0}, key=int)),
            "n_faixas": len(faixas), "certificado": str(ultimo.get("NumeroCertificado") or ""), "n_verificacoes": len(hist),
        })
    acesso = date.fromisoformat(man["acesso_em"])
    return Envelope(
        painel="radares_inmetro",
        fonte=Fonte(nome="Inmetro — Portal de Serviços nos Estados (PSIE), medidores de velocidade", url="https://dados.gov.br/dados/conjuntos-dados/portal-de-servicos-do-inmetro-nos-estados-psie", licenca=man["licenca"], acesso_em=acesso),
        referencia=Referencia(inicio=acesso, fim=acesso, granularidade=Granularidade.SEMANAL),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(flag=Flag.REAL, n_registros=len(dados), notas=[
            "Situação da verificação metrológica do Inmetro, não da validade jurídica de uma multa: essa depende do auto de infração e da análise do órgão autuador.",
            "Verificação vencida pode significar equipamento retirado ou substituído, e verificação em dia pode estar atrasada na base. Confirme sempre no portal oficial com o número do Inmetro da notificação.",
            "A relação de radares da Semob não traz número do Inmetro; por isso este quadro lista os medidores da base do Inmetro em Sorocaba, sem cruzar com a lista da Semob.",
            f"SHA-256 do arquivo filtrado: {man['sha256_filtrado']}",
        ]),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "inmetro")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "radares_inmetro.json")
    a = p.parse_args()
    e = construir(a.raw)
    a.saida.parent.mkdir(parents=True, exist_ok=True)
    a.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
