from collections import Counter

from scripts.build_infosiga import RAIZ, construir
from scripts.fetch_infosiga import TABELAS, agregar_mes

CAB = "id_sinistro;tipo_registro;data_sinistro;hora_sinistro;dia_da_semana;logradouro;latitude;longitude;cod_ibge;tp_sinistro_primario;qtd_gravidade_fatal;qtd_gravidade_grave"


def test_agrega_so_sorocaba_separa_notificacao_e_converte_decimal():
    linhas = [CAB,
        "1;SINISTRO FATAL;01/01/2025;14:30;Segunda-feira;AV X;-23,50;-47,45;3552205;COLISAO;1;0",
        "2;NOTIFICACAO;02/01/2025;;Terça-feira;AV Y;;;3552205;COLISAO;0;0",
        "3;SINISTRO NAO FATAL;03/01/2025;09:00;Quarta-feira;AV X;-23,51;-47,46;3550308;COLISAO;0;1"]
    cont = {t: Counter() for t in TABELAS}
    assert agregar_mes("\n".join(linhas), 2025, 1, cont) == 2
    assert cont["mensal"][(2025, 1, "NOTIFICACAO", "sinistros")] == 1
    assert cont["mensal"][(2025, 1, "SINISTRO FATAL", "vitimas_fatais")] == 1
    assert sum(cont["hora"].values()) == 1 and sum(cont["via"].values()) == 1  # notificação fica fora do detalhe
    assert list(cont["grade"]) == [(2025, -23.4975, -47.4475)]  # centro da célula [-23,500; -23,495) x [-47,450; -47,445)


def test_build_deterministico_sem_ponto_individual_nem_data():
    a, b = construir(RAIZ / "data/raw/infosiga"), construir(RAIZ / "data/raw/infosiga")
    assert a.model_dump_json() == b.model_dump_json()
    for r in a.dados:
        assert r["recorte"] != "grade" or r["n"] >= 5
        assert r["recorte"] != "via" or r["n"] >= 10


def test_raw_sem_id_de_sinistro_ou_data_exata():
    for arq in (RAIZ / "data/raw/infosiga").rglob("*.csv"):
        cab = arq.read_text(encoding="utf-8").splitlines()[0]
        for proibido in ("id_sinistro", "data_sinistro", "numero", "placa"):
            assert proibido not in cab, arq


def test_logradouro_descarta_plus_code_e_neutraliza_formula():
    from scripts.fetch_infosiga import logradouro
    assert logradouro("58VJ+3M Sorocaba") is None
    assert logradouro("  av   x ") == "AV X"
    assert logradouro("=CMD()") == "'=CMD()"


def test_contorno_aceita_centro_e_rejeita_cidade_vizinha():
    from scripts.fetch_infosiga import carregar_contorno, dentro
    c = carregar_contorno()
    assert dentro(c, -23.50, -47.46) and not dentro(c, -23.30, -47.00)


def test_suprime_celula_e_via_raras_e_conta_valor_invalido():
    from scripts.fetch_infosiga import inteiro, suprimir
    cont = {t: Counter() for t in TABELAS}
    cont["grade"].update({(2025, 1.0, 1.0): 4, (2025, 2.0, 2.0): 5})
    cont["via"].update({(2025, "A"): 9, (2025, "B"): 10})
    assert suprimir(cont) == 1 and list(cont["grade"]) == [(2025, 2.0, 2.0)] and list(cont["via"]) == [(2025, "B")]
    inv = Counter()
    assert inteiro("NAO DISPONIVEL", inv) == 0 and inteiro("2,0", inv) == 2 and inv["contagem"] == 1


def _mes(a, m, n, nt=0, f=0):
    return {"ano": a, "mes": m, "n": n, "n2": f, "categoria": f"{nt}|0"}


def test_janelas_usam_meses_do_calendario_e_suprimem_comparacao_enganosa():
    from scripts.render import comparacao_anterior, janelas_12_meses
    serie = {(a, m): _mes(a, m, 100, nt=10) for a in (2024, 2025) for m in range(1, 13)}
    ult, ant = janelas_12_meses(serie)
    assert (ult[0]["ano"], ult[0]["mes"]) == (2025, 1) and (ant[0]["ano"], ant[0]["mes"]) == (2024, 1)
    assert comparacao_anterior(ult, ant) == 1200
    del serie[(2024, 6)]
    assert janelas_12_meses(serie)[1] == []
    muda = {(a, m): _mes(a, m, 100, nt=10 if a == 2025 else 150) for a in (2024, 2025) for m in range(1, 13)}
    assert comparacao_anterior(*janelas_12_meses(muda)) is None


def test_logradouro_plus_code_em_qualquer_posicao_e_coordenada_em_texto():
    from scripts.fetch_infosiga import logradouro, url_segura
    assert logradouro("RUA X 8XQ2+J5") is None and logradouro("PONTO -23.50123 -47.4") is None
    assert logradouro("AVENIDA DOM AGUIRRE") == "AVENIDA DOM AGUIRRE"
    assert url_segura("https://u:p@h.gov.br:8443/a/b.csv?sig=1#f") == "https://h.gov.br:8443/a/b.csv"


def test_raw_commitado_respeita_supressao_e_nao_tem_plus_code():
    from scripts.fetch_infosiga import COORD_TEXTO, PLUS_CODE
    from scripts.infosiga_regras import CELULA_MINIMA, DETALHE_MINIMO, VIA_MINIMA
    import csv
    for arq in (RAIZ / "data/raw/infosiga").rglob("grade.csv"):
        assert all(int(r["n"]) >= CELULA_MINIMA for r in csv.DictReader(arq.open(encoding="utf-8"), delimiter=";")), arq
    for nome in ("hora.csv", "tipo.csv"):
        for arq in (RAIZ / "data/raw/infosiga").rglob(nome):
            assert all(int(r["n"]) >= DETALHE_MINIMO for r in csv.DictReader(arq.open(encoding="utf-8"), delimiter=";")), arq
    for arq in (RAIZ / "data/raw/infosiga").rglob("via.csv"):
        for r in csv.DictReader(arq.open(encoding="utf-8"), delimiter=";"):
            assert int(r["n"]) >= VIA_MINIMA and not PLUS_CODE.search(r["logradouro"]) and not COORD_TEXTO.search(r["logradouro"]), arq
