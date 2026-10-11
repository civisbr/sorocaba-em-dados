import json
from datetime import date

import httpx
import pytest

from scripts import build_hospitais, fetch_cnes, fetch_sih
from scripts.contexto_hospitais import contexto_hospitais, nome_unidade
from scripts.saude_codigos import capitulo_cid, natureza

HOJE = date(2026, 10, 11)


def _nome_br(n):
    return " ".join(w.capitalize() for w in n.lower().split())


def _st(cnes, tipo="05", nat="2062", sus="1", pf="3"):
    return {"CNES": cnes, "TP_UNID": tipo, "PF_PJ": pf, "NAT_JUR": nat, "VINC_SUS": sus, "URGEMERG": "1", "CENTRCIR": "1", "CENTROBS": "0", "CENTRNEO": "0"}


def _lt(cnes, cod="03", n="100", sus="40", tp="1"):
    return {"CNES": cnes, "TP_LEITO": tp, "CODLEITO": cod, "QT_EXIST": n, "QT_SUS": sus}


def _api(transporte_tipos):
    def tratar(req):
        tipo = int(req.url.params["codigo_tipo_unidade"])
        return httpx.Response(200, json={"estabelecimentos": transporte_tipos.get(tipo, [])})
    return httpx.MockTransport(tratar)


def _estab_api(cnes, nome="HOSPITAL TESTE SOROCABA"):
    return {"codigo_cnes": int(cnes), "nome_fantasia": nome, "endereco_estabelecimento": "RUA A", "numero_estabelecimento": "10", "bairro_estabelecimento": "CENTRO",
            "numero_telefone_estabelecimento": "(15) 3000-0000", "latitude_estabelecimento_decimo_grau": -23.5, "longitude_estabelecimento_decimo_grau": -47.4}


def _coletar_cnes(tmp_path, n_hosp=6, comp="2608", **kw):
    cnes = [f"{2000000 + i:07d}" for i in range(n_hosp)]
    st = [_st(c) for c in cnes] + [_st("8016429", tipo="01", nat="1023"), _st("9999999", tipo="22", pf="1"), _st("7777777", tipo="73", sus="0", nat="2143")]
    lt = [_lt(c) for c in cnes]

    def baixar(caminho):
        return (b"ST" if "/ST/" in caminho else b"LT"), "hash"

    def ler(dados, filtro):
        assert filtro == ("CODUFMUN", "355220")
        return iter(st if dados == b"ST" else lt)

    def listar(pasta):
        return [f"{pasta.rsplit('/', 1)[-1]}SP{comp}.dbc", f"{pasta.rsplit('/', 1)[-1]}SP2501.dbc"]

    api = _api({5: [_estab_api(c) for c in cnes]})
    return fetch_cnes.coletar(HOJE, tmp_path, listar=listar, baixar=baixar, ler=ler, transporte=api, **kw), cnes


def test_cnes_coleta_filtra_tipos_e_grava_manifesto(tmp_path):
    comp, cnes = _coletar_cnes(tmp_path)
    assert comp == "202608"
    linhas = (tmp_path / "estabelecimentos.csv").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 1 + 6  # sem presídio (tipo 01 estadual), sem pessoa física, sem UPA privada
    man = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))
    assert man["n_hospitais"] == 6 and man["competencia"] == "202608"
    assert "HOSPITAL TESTE" in linhas[1]


def test_cnes_competencia_antiga_aborta(tmp_path):
    with pytest.raises(ValueError, match="parada"):
        _coletar_cnes(tmp_path, comp="2601")


def test_cnes_poucos_hospitais_aborta_sem_gravar(tmp_path):
    with pytest.raises(ValueError, match="implausível"):
        _coletar_cnes(tmp_path, n_hosp=2)
    assert not (tmp_path / "estabelecimentos.csv").exists()


def test_cnes_host_fora_do_ministerio_e_recusado():
    req = httpx.Request("GET", "https://outro.exemplo/cnes")
    with pytest.raises(ValueError):
        fetch_cnes.so_host_confiavel(req)


def test_cnes_futuro_e_recusado(tmp_path):
    with pytest.raises(ValueError):
        fetch_cnes.coletar(date(2999, 1, 1), tmp_path)


def _rd(cnes, espec="01", diag="S720", res="355220", dias="5", uti="0"):
    return {"CNES": cnes, "ESPEC": espec, "DIAG_PRINC": diag, "MUNIC_RES": res, "DIAS_PERM": dias, "UTI_MES_TO": uti}


def test_sih_agrega_sem_registro_individual_e_funde_celulas_pequenas():
    rd = [_rd("1", diag="S720")] * 6 + [_rd("1", diag="J189")] * 2 + [_rd("1", diag="J189", res="351000")]
    linhas = fetch_sih.agregar(rd, "202607")
    por = {(l["capitulo"], l["residente"]): l for l in linhas}
    assert por[("Lesões, envenenamentos e outras causas externas", 1)]["internacoes"] == 6
    assert por[("Outros capítulos", 1)]["internacoes"] == 2  # 2 < 5: capítulo some, total permanece
    assert por[("Outros capítulos", 0)]["internacoes"] == 1
    assert sum(l["internacoes"] for l in linhas) == 9
    assert all(set(l) == set(fetch_sih.CAMPOS) for l in linhas)


def test_sih_rejeita_muitos_registros_invalidos():
    with pytest.raises(ValueError, match="inválidos"):
        fetch_sih.agregar([_rd("1", dias="x")] * 10, "202607")


def test_sih_janela_exige_meses_consecutivos():
    todos = [f"2025{m:02d}" for m in range(8, 13)] + [f"2026{m:02d}" for m in range(1, 8)]
    assert fetch_sih.janela(todos)[0] == "202508" and len(fetch_sih.janela(todos)) == 12
    with pytest.raises(ValueError, match="ausentes"):
        fetch_sih.janela([m for m in todos if m != "202512"])
    with pytest.raises(ValueError):
        fetch_sih.janela([])


def test_sih_incremental_so_refaz_meses_recentes(tmp_path):
    meses = [f"2025{m:02d}" for m in range(8, 13)] + [f"2026{m:02d}" for m in range(1, 8)]
    chamadas = []

    def baixar(caminho):
        chamadas.append(caminho)
        return b"x", "h"

    def ler(dados, filtro):
        assert filtro == ("MUNIC_MOV", "355220")
        return iter([_rd("1")] * 6)

    listar = lambda pasta: [f"RDSP{m[2:]}.dbc" for m in meses]
    assert len(fetch_sih.coletar(HOJE, tmp_path, listar, baixar, ler)) == 12
    chamadas.clear()
    assert fetch_sih.coletar(HOJE, tmp_path, listar, baixar, ler) == meses[-3:]
    assert len(chamadas) == 3
    assert (tmp_path / "internacoes.csv").read_text(encoding="utf-8").count("\n") == 1 + 12


def test_sih_fonte_parada_aborta(tmp_path):
    antigos = [f"RDSP25{m:02d}.dbc" for m in range(1, 13)]
    with pytest.raises(ValueError, match="parada"):
        fetch_sih.coletar(HOJE, tmp_path, lambda p: antigos, lambda c: (b"", ""), lambda d, f: iter([]))


def test_codigos():
    assert capitulo_cid("J189") == "Doenças respiratórias"
    assert capitulo_cid("V892") == "Causas externas (acidentes e violência)"
    assert capitulo_cid("") is None and capitulo_cid("123") is None
    assert natureza("1023") == "Público" and natureza("3999") == "Sem fins lucrativos" and natureza("") == "Outro"


def test_nome_unidade_mantem_cidade_quando_ficaria_ambiguo():
    assert nome_unidade("SANTA CASA DE SOROCABA", _nome_br) == "Santa Casa De Sorocaba"
    assert nome_unidade("HOSPITAL SANTA LUCINDA SOROCABA", _nome_br) == "Hospital Santa Lucinda"


@pytest.fixture
def raw(tmp_path):
    cnes, sih = tmp_path / "cnes", tmp_path / "sih"
    _coletar_cnes(cnes)
    meses = [f"2025{m:02d}" for m in range(8, 13)] + [f"2026{m:02d}" for m in range(1, 8)]
    fetch_sih.coletar(HOJE, sih, lambda p: [f"RDSP{m[2:]}.dbc" for m in meses], lambda c: (b"x", "h"), lambda d, f: iter([_rd("2000000", dias="30")] * 8 + [_rd("2000001")] * 7))
    return cnes, sih


def test_build_calcula_uso_estimado_e_contexto(raw):
    env = build_hospitais.construir(*raw)
    tot = {r["cnes"]: r for r in env.dados if r["recorte"] == "internacao_total"}
    assert tot["2000000"]["internacoes"] == 96 and tot["2000000"]["dias"] == 96 * 30
    assert tot["2000000"]["uso_estimado_pct"] == round(100 * 2880 / (40 * 365), 1)
    assert env.qualidade.flag.value == "estimativa"
    ctx = contexto_hospitais(env.model_dump(mode="json"), _nome_br)
    assert ctx["resumo"]["n_hospitais"] == 6 and ctx["resumo"]["leitos"] == 600
    assert ctx["hospitais"][0]["cnes"] == "2000000"  # mais internações primeiro
    assert ctx["ref_hosp"] == "leitos em 08/2026; internações até 07/2026"


def test_build_hash_adulterado_e_recusado(raw):
    cnes, sih = raw
    (cnes / "leitos.csv").write_text("cnes;tp_leito;cod_leito;existentes;sus\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        build_hospitais.construir(cnes, sih)


def test_pagina_de_hospitais_renderizada():
    import subprocess
    import sys
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, "-m", "scripts.render", "--saida", d], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        html = (Path(d) / "hospitais" / "index.html").read_text(encoding="utf-8")
        assert "Uso estimado dos leitos SUS" in html and "Leitos por especialidade" in html
        assert "lotação do dia" in html


def test_sih_nenhuma_celula_publicada_descreve_uma_internacao():
    rd = [_rd("1", diag="S720")] * 7 + [_rd("1", espec="03", diag="J189", dias="40", uti="12")] + [_rd("1", espec="02", diag="O800", dias="9")] * 2
    linhas = fetch_sih.agregar(rd, "202607")
    assert sum(l["internacoes"] for l in linhas) == 10
    for l in linhas:
        if l["internacoes"] < fetch_sih.CELULA_MINIMA:
            assert l["dias"] == 0 and l["dias_uti"] == 0
    assert not any(l["espec"] == "03" for l in linhas)  # fundida em "outras especialidades"
    assert any(l["espec"] == fetch_sih.ESPEC_OUTRAS and l["internacoes"] == 3 for l in linhas)


def test_cnes_texto_da_api_e_sanitizado():
    assert fetch_cnes._texto("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert fetch_cnes._texto("  A\nB  ") == "A B" and fetch_cnes._texto(123) == "" and len(fetch_cnes._texto("x" * 500)) == fetch_cnes.TAM_TEXTO


def test_cnes_variacao_grande_de_leitos_entre_coletas_aborta(tmp_path):
    _coletar_cnes(tmp_path)
    man = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))
    man["leitos_total"] = man["leitos_total"] * 3
    (tmp_path / "manifesto.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(ValueError, match="entre coletas"):
        _coletar_cnes(tmp_path)


def test_sih_variacao_grande_entre_coletas_aborta(tmp_path):
    meses = [f"2025{m:02d}" for m in range(8, 13)] + [f"2026{m:02d}" for m in range(1, 8)]
    listar = lambda p: [f"RDSP{m[2:]}.dbc" for m in meses]
    fetch_sih.coletar(HOJE, tmp_path, listar, lambda c: (b"x", "h"), lambda d, f: iter([_rd("1")] * 10))
    with pytest.raises(ValueError, match="entre coletas"):
        fetch_sih.coletar(HOJE, tmp_path, listar, lambda c: (b"x", "h"), lambda d, f: iter([_rd("1")] * 40))


def test_sih_especialidade_desconhecida_vira_outras_e_continuacao_de_aih_nao_conta():
    rd = [_rd("1", espec="87")] * 6 + [{**_rd("1"), "IDENT": "5"}] * 6 + [{**_rd("1"), "IDENT": "1"}] * 6
    linhas = fetch_sih.agregar(rd, "202607")
    assert sum(l["internacoes"] for l in linhas) == 12
    assert {l["espec"] for l in linhas} == {fetch_sih.ESPEC_OUTRAS, "01"}


def test_sih_raw_adulterado_e_recusado_na_coleta_incremental(tmp_path):
    meses = [f"2025{m:02d}" for m in range(8, 13)] + [f"2026{m:02d}" for m in range(1, 8)]
    listar = lambda p: [f"RDSP{m[2:]}.dbc" for m in meses]
    args = (lambda c: (b"x", "h"), lambda d, f: iter([_rd("1")] * 6))
    fetch_sih.coletar(HOJE, tmp_path, listar, *args)
    arq = tmp_path / "internacoes.csv"
    arq.write_text(arq.read_text(encoding="utf-8").replace(";6;", ";7;", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        fetch_sih.coletar(HOJE, tmp_path, listar, *args)
