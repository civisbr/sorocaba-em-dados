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
