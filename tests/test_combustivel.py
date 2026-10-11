import json
from datetime import date

import pytest

from scripts import fetch_anp
from scripts.build_combustivel import centavos, construir, inicio_da_semana

CAB = ";".join(fetch_anp.COLUNAS)


def linha(cnpj, produto, coleta, valor, rua="R X", unidade="R$ / litro", municipio="SOROCABA", uf="SP"):
    return f"SE;{uf};{municipio};POSTO {cnpj} LTDA; {cnpj};{rua};1;;CENTRO;18000-000;{produto};{coleta};{valor};;{unidade};BRANCA"


def snapshot(raiz, nome, linhas, acesso="2026-10-11", ultima="2026-10-08"):
    pasta = raiz / nome
    pasta.mkdir(parents=True)
    (pasta / "a.csv").write_text("\n".join([CAB, *linhas]) + "\n", encoding="utf-8")
    (pasta / "manifesto.json").write_text(json.dumps({"acesso_em": acesso, "ultima_coleta": ultima}), encoding="utf-8")


def test_centavos_arredonda_sem_float():
    assert centavos("5,99") == 599 and centavos("6,095") == 610


def test_semana_comeca_no_domingo():
    assert inicio_da_semana(date(2026, 10, 8)) == date(2026, 10, 4)
    assert inicio_da_semana(date(2026, 10, 4)) == date(2026, 10, 4)


def test_mediana_e_amostra(tmp_path):
    snapshot(tmp_path, "20261008", [linha("1", "GASOLINA", "05/10/2026", "5,00"), linha("2", "GASOLINA", "06/10/2026", "6,00"), linha("3", "GASOLINA", "07/10/2026", "9,00")])
    env = construir(tmp_path)
    sem = [r for r in env.dados if r["recorte"] == "semanal"]
    assert len(sem) == 1 and sem[0]["n_postos"] == 3 and sem[0]["mediana"] == 6.0
    assert sem[0]["minimo"] == 5.0 and sem[0]["maximo"] == 9.0 and sem[0]["amostra_pequena"] is True


def test_semana_aberta_nao_entra(tmp_path):
    snapshot(tmp_path, "20261008", [linha("1", "GASOLINA", "05/10/2026", "5,00")], acesso="2026-10-08")
    with pytest.raises(ValueError, match="nenhuma semana fechada"):
        construir(tmp_path)


def test_instantaneo_novo_vence_na_mesma_coleta(tmp_path):
    snapshot(tmp_path, "20261001", [linha("1", "ETANOL", "05/10/2026", "3,00")], acesso="2026-10-06")
    snapshot(tmp_path, "20261008", [linha("1", "ETANOL", "05/10/2026", "4,00")])
    env = construir(tmp_path)
    assert [r for r in env.dados if r["recorte"] == "semanal"][0]["mediana"] == 4.0


def test_unidade_inesperada_quebra(tmp_path):
    snapshot(tmp_path, "20261008", [linha("1", "GASOLINA", "05/10/2026", "5,00", unidade="R$ / m3")])
    with pytest.raises(ValueError, match="unidade"):
        construir(tmp_path)


def test_posto_sem_historico_nao_exibe_contagem_de_semanas_acima(tmp_path):
    snapshot(tmp_path, "20261008", [linha("1", "GASOLINA", "05/10/2026", "5,00"), linha("2", "GASOLINA", "05/10/2026", "6,00")])
    posto = [r for r in construir(tmp_path).dados if r["recorte"] == "posto"][0]
    assert posto["semanas_observadas"] == 1 and posto["semanas_acima_mediana"] is None


def test_filtro_mantem_so_sorocaba_sp_e_valida_cabecalho():
    corpo = "\n".join([CAB, linha("1", "GASOLINA", "05/10/2026", "5,00"), linha("2", "GASOLINA", "05/10/2026", "5,00", municipio="SOROCABA", uf="RS"),
                        linha("3", "GASOLINA", "05/10/2026", "5,00", municipio="VOTORANTIM")]).encode("utf-8-sig")
    saida = fetch_anp.filtrar(corpo)
    assert saida.count("\n") == 2
    with pytest.raises(ValueError, match="colunas inesperadas"):
        fetch_anp.filtrar(b"a;b\n1;2\n")


def test_dado_real_publicado_e_coerente():
    from scripts.build_combustivel import RAIZ

    env = json.loads((RAIZ / "data" / "public" / "combustivel.json").read_text(encoding="utf-8"))
    assert env["qualidade"]["n_registros"] == len(env["dados"])
    for r in (r for r in env["dados"] if r["recorte"] == "semanal"):
        assert r["minimo"] <= r["mediana"] <= r["maximo"]
