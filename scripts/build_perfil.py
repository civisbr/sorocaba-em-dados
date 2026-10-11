"""Transforma as respostas do IBGE em data/public/perfil.json. Puro e offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from schemas.envelope import Cobertura, Envelope, Flag, Fonte, Granularidade, Qualidade, Referencia

RAIZ = Path(__file__).resolve().parent.parent
SETORES = {
    "513": ("agropecuaria", "Agropecuária"),
    "517": ("industria", "Indústria"),
    "6575": ("servicos", "Serviços (exceto administração pública)"),
    "525": ("administracao_publica", "Administração, defesa, educação e saúde públicas"),
}
PARTICIPACOES = {
    "553": "Microrregião de Sorocaba",
    "552": "Macro Metropolitana Paulista",
    "497": "Estado de São Paulo",
    "530": "Região Sudeste",
    "496": "Brasil",
}


def ler(raw: Path, nome: str):
    return json.loads((raw / f"{nome}.json").read_text(encoding="utf-8"))


def series(resposta: list[dict]) -> dict[str, dict[str, float | None]]:
    """variável -> {ano: valor}; '...' e '-' viram None (a fonte não publica)."""
    saida = {}
    for v in resposta:
        serie = v["resultados"][0]["series"][0]["serie"]
        saida[v["id"]] = {ano: (float(x) if x not in ("...", "-", "X", "") else None) for ano, x in serie.items()}
    return saida


def registro(recorte, chave, rotulo, ano=None, valor=None, unidade=None, texto=None, pct=None) -> dict:
    return {"recorte": recorte, "chave": chave, "rotulo": rotulo, "ano": ano, "valor": valor, "unidade": unidade, "texto": texto, "pct": pct}


def construir(raw: Path) -> Envelope:
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    loc = ler(raw, "localidade")
    censo = series(ler(raw, "censo_2022"))
    est = series(ler(raw, "estimativa"))
    pib = series(ler(raw, "pib"))
    vab = series(ler(raw, "vab"))
    dados: list[dict] = []

    micro = loc["microrregiao"]
    meso = micro["mesorregiao"]
    imediata = loc["regiao-imediata"]
    for chave, rotulo, texto in (
        ("microrregiao", "Microrregião", micro["nome"]),
        ("mesorregiao", "Mesorregião", meso["nome"]),
        ("regiao_imediata", "Região geográfica imediata", imediata["nome"]),
        ("regiao_intermediaria", "Região geográfica intermediária", imediata["regiao-intermediaria"]["nome"]),
        ("uf", "Estado", meso["UF"]["nome"]),
    ):
        dados.append(registro("territorio", chave, rotulo, texto=texto))

    ano_est, v_est = next(iter(est["9324"].items()))
    censo_ano = max(censo["93"])
    for chave, rotulo, valor, ano, unidade in (
        ("populacao_censo", "População (Censo)", censo["93"]["2022"], 2022, "pessoas"),
        ("populacao_estimada", "População estimada", v_est, int(ano_est), "pessoas"),
        ("area", "Área", censo["6318"]["2022"], 2022, "km²"),
        ("densidade", "Densidade demográfica", censo["614"]["2022"], 2022, "hab/km²"),
    ):
        dados.append(registro("indicador", chave, rotulo, ano, valor, unidade))

    for ano, valor in sorted(pib["37"].items()):
        if valor is not None:
            dados.append(registro("pib_serie", "pib", "PIB a preços correntes", int(ano), valor, "R$ mil"))
    ano_pib = max(a for a, v in pib["37"].items() if v is not None)
    for vid, rotulo in PARTICIPACOES.items():
        if pib[vid].get(ano_pib) is not None:
            dados.append(registro("pib_participacao", vid, rotulo, int(ano_pib), pib[vid][ano_pib], "%"))

    # Estrutura do valor adicionado: último ano em que o IBGE publicou o total e todos os setores.
    anos_vab = [a for a in sorted(vab["498"]) if vab["498"][a] is not None and all(vab[v].get(a) is not None for v in SETORES)]
    ano_vab = anos_vab[-1] if anos_vab else None
    if ano_vab:
        total = vab["498"][ano_vab]
        for vid, (chave, rotulo) in SETORES.items():
            v = vab[vid][ano_vab]
            # Parcela = valor do setor / VAB total, ambos da mesma tabela do IBGE e do mesmo ano.
            dados.append(registro("vab_setor", chave, rotulo, int(ano_vab), v, "R$ mil", pct=round(v / total * 100, 1)))
        soma = sum(vab[v][ano_vab] for v in SETORES)
        if abs(soma - total) > 1:
            raise ValueError(f"setores ({soma}) não somam o VAB total ({total})")
        dados.append(registro("vab_setor", "total", "Valor adicionado bruto total", int(ano_vab), total, "R$ mil", pct=100.0))

    h = hashlib.sha256((raw / "manifesto.json").read_bytes()).hexdigest()
    return Envelope(
        painel="cidade",
        fonte=Fonte(
            nome="IBGE — Censo 2022, Estimativas de População e PIB dos Municípios",
            url="https://sidra.ibge.gov.br/",
            licenca="Dados abertos do IBGE",
            acesso_em=date.fromisoformat(man["acesso_em"]),
        ),
        referencia=Referencia(
            inicio=date(int(min(a for a, v in pib["37"].items() if v is not None)), 1, 1), fim=date(int(ano_est), 12, 31), granularidade=Granularidade.ANUAL
        ),
        cobertura=Cobertura(municipio="Sorocaba", ibge="3552205", uf="SP"),
        qualidade=Qualidade(
            flag=Flag.REAL,
            n_registros=len(dados),
            notas=[
                f"Cada indicador traz o seu ano: Censo {censo_ano}, estimativa de população de {ano_est} e PIB até {ano_pib}.",
                "PIB a preços correntes (nominal): os valores de anos diferentes não descontam inflação.",
                (f"Estrutura do valor adicionado: {ano_vab}, o último ano em que o IBGE publicou os setores para o município." if ano_vab else "O IBGE ainda não publicou a estrutura do valor adicionado por setor para o município."),
                "O IBGE não publica PIB per capita nessa tabela, e não calculamos por conta própria.",
                f"SHA-256 do manifesto de coleta: {h}",
            ],
        ),
        dados=dados,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAIZ / "data" / "raw" / "ibge" / "perfil")
    p.add_argument("--saida", type=Path, default=RAIZ / "data" / "public" / "perfil.json")
    args = p.parse_args()
    e = construir(args.raw)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
