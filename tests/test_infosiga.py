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
