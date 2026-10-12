import pytest

from scripts.texto_local import legivel, rotulo_posicao


@pytest.mark.parametrize("bruto,esperado", [
    ("AV. DOM AGUIRRE, PROX. À RUA COM. HÉLIO MONZONI", "Av. Dom Aguirre, próx. à Rua Com. Hélio Monzoni"),
    ("AV. ANTONIO CARLOS CÔMITRE PROX. AO Nº 1315", "Av. Antonio Carlos Cômitre próx. ao nº 1315"),
    ("RODOVIA SP-270 KM 094 + 017M (EXPRESSA)", "Rodovia SP-270 km 094 + 017m (Expressa)"),
    ("RUA PROFª GUIDA MARES, N° 246", "Rua Profª Guida Mares, nº 246"),
    ("AV. DOM AGUIRRE (B/C ) PRÓX RUA CDOR. HELIO MONZONI", "Av. Dom Aguirre (B/C) próx. Rua Cdor. Helio Monzoni"),
    ("AV. QUINZE DE AGOSTO COM A PONTE LUIZ F. DAMIAN LUIZITO", "Av. Quinze de Agosto com a Ponte Luiz F. Damian Luizito"),
    ("RUA ANA M. DE CARVALHO , N º 15 (C/B)", "Rua Ana M. de Carvalho, nº 15 (C/B)"),
])
def test_legivel_em_caixa_alta(bruto, esperado):
    assert legivel(bruto) == esperado


def test_texto_ja_com_minusculas_so_ganha_espacos_arrumados():
    assert legivel("Av.  Tadao Yoshida, próx. ponte") == "Av. Tadao Yoshida, próx. ponte"


def test_rotulo_de_posicao_diz_quando_e_aproximada():
    assert rotulo_posicao("via").startswith("aproximada")
    assert "entre os nº 10 e 20" in rotulo_posicao("número", "entre os nº 10 e 20")
    assert rotulo_posicao("porta") == "endereço exato no OpenStreetMap"


@pytest.mark.parametrize("bruto,esperado", [
    ("RUA ANTÔNIO SILVA SALADINO, n° 565", "Rua Antônio Silva Saladino, nº 565"),
    ("AV. SANTA CRUZ , N° 290 (CB)", "Av. Santa Cruz, nº 290 (CB)"),
    ("SP-270 KM:084 Metros:900 OESTE", "SP-270 km:084 Metros:900 Oeste"),
])
def test_legivel_casos_de_borda(bruto, esperado):
    assert legivel(bruto) == esperado
