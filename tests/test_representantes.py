import re

from scripts.build_representantes import RAIZ, construir, em_exercicio, tokens

RAW = RAIZ / "data/raw/representantes"


def test_nome_de_urna_com_titulo_casa_com_nome_oficial():
    assert em_exercicio("AGENTE FEDERAL DANILO BALAS", ["Danilo Balas", "Outro Nome"]) is True


def test_nome_de_uma_palavra_so_casa_por_igualdade():
    assert em_exercicio("DANILO", ["Danilo Balas"]) is None
    assert em_exercicio("VITOR LIPPI", ["Vitor Lippi"]) is True


def test_sem_correspondencia_ou_ambiguo_fica_sem_confirmacao():
    assert em_exercicio("CARLA ZAMBELLI", ["Vitor Lippi"]) is None
    assert em_exercicio("JOAO SILVA", ["João Silva", "Silva João"]) is None


def test_tokens_ignoram_acento_e_caixa():
    assert tokens("Vitão do Cachorrão") == tokens("VITAO DO CACHORRAO")


def test_build_deterministico_e_composicao():
    a, b = construir(RAW), construir(RAW)
    assert a.model_dump_json() == b.model_dump_json()
    grupos = [r["grupo"] for r in a.dados]
    assert grupos.count("prefeito") == 1 and grupos.count("vice_prefeito") == 1 and grupos.count("vereador") == 25
    assert grupos.count("deputado_federal") == 10 and grupos.count("deputado_estadual") == 10


def test_exercicio_so_para_legislatura_em_curso():
    for r in construir(RAW).dados:
        if r["grupo"].startswith("deputado") and r["eleicao"] != 2022:
            assert r["em_exercicio"] is None


def test_percentuais_plausiveis_e_ordenados():
    por = {}
    for r in construir(RAW).dados:
        if r["grupo"].startswith("deputado"):
            por.setdefault((r["grupo"], r["eleicao"]), []).append(r)
    for lista in por.values():
        votos = [r["votos_na_cidade"] for r in lista]
        assert votos == sorted(votos, reverse=True)
        assert 0 < sum(r["pct_votos_na_cidade"] for r in lista) < 100


def test_raw_sem_dado_pessoal():
    for arq in RAW.glob("*.csv"):
        texto = arq.read_text(encoding="utf-8")
        assert not re.search(r"\d{11}", texto), arq
        assert "@" not in texto, arq


def _zip(nome, cabecalho, linhas):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(nome, "\n".join([";".join(cabecalho), *[";".join(l) for l in linhas]]).encode("latin-1"))
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_eleitos_municipais_filtra_municipio_ano_e_situacao():
    from scripts.fetch_representantes import eleitos_municipais

    cab = ["SG_UE", "ANO_ELEICAO", "DS_CARGO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "DS_SIT_TOT_TURNO", "NR_TURNO"]
    z = _zip("consulta_cand_2024_SP.csv", cab, [
        ["71455", "2024", "PREFEITO", "A  B", "X", "ELEITO", "1"],
        ["71455", "2024", "VEREADOR", "C", "Y", "SUPLENTE", "1"],
        ["71455", "2024", "VEREADOR", "D", "Y", "ELEITO POR QP", "1"],
        ["99999", "2024", "PREFEITO", "OUTRO", "X", "ELEITO", "1"],
        ["71455", "2020", "PREFEITO", "ANTIGO", "X", "ELEITO", "1"],
    ])
    r = eleitos_municipais(z, 2024)
    assert [(x["cargo"], x["nome_urna"]) for x in r] == [("PREFEITO", "A B"), ("VEREADOR", "D")]


def test_votos_somam_zonas_e_ignoram_segundo_turno_e_outros_municipios():
    from scripts.fetch_representantes import votos_deputados

    cab = ["CD_MUNICIPIO", "DS_CARGO", "NR_TURNO", "SQ_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "QT_VOTOS_NOMINAIS_VALIDOS", "DS_SIT_TOT_TURNO"]
    z = _zip("votacao_candidato_munzona_2022_SP.csv", cab, [
        ["71455", "Deputado Federal", "1", "1", "ANA", "P", "10", "ELEITO POR QP"],
        ["71455", "Deputado Federal", "1", "1", "ANA", "P", "5", "ELEITO POR QP"],
        ["71455", "Deputado Federal", "1", "2", "BIA", "P", "7", "SUPLENTE"],
        ["71455", "Deputado Federal", "2", "1", "ANA", "P", "99", "ELEITO POR QP"],
        ["11111", "Deputado Federal", "1", "1", "ANA", "P", "99", "ELEITO POR QP"],
        ["71455", "Senador", "1", "3", "CAIO", "P", "50", "ELEITO"],
    ])
    eleitos, totais = votos_deputados(z, 2022)
    assert [(e["nome_urna"], e["votos"]) for e in eleitos] == [("ANA", 15)]
    assert totais == [{"ano": 2022, "cargo": "Deputado Federal", "votos_nominais_validos": 22}]


def test_raw_json_so_com_chaves_esperadas():
    import json
    for nome, chaves in (("camara_deputados_sp.json", {"id", "nome", "partido", "uf"}), ("alesp_deputados.json", {"id", "nome", "partido", "situacao"})):
        for item in json.loads((RAW / nome).read_text(encoding="utf-8")):
            assert set(item) == chaves


def test_csv_raw_com_cabecalho_exato():
    from scripts.fetch_representantes import CAMPOS_ELEITOS, CAMPOS_TOTAIS, CAMPOS_VOTOS

    esperado = {"eleitos_municipais_2024.csv": CAMPOS_ELEITOS, "votos_deputados_2022.csv": CAMPOS_VOTOS, "votos_deputados_2026.csv": CAMPOS_VOTOS, "totais_votos_2022.csv": CAMPOS_TOTAIS}
    for nome, campos in esperado.items():
        assert (RAW / nome).read_text(encoding="utf-8").splitlines()[0] == ";".join(campos)


def test_cpf_formatado_tambem_barrado():
    for arq in list(RAW.glob("*.csv")) + list(RAW.glob("*.json")):
        assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", arq.read_text(encoding="utf-8")), arq
