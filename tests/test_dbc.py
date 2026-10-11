import struct

import pytest

from scripts.dbc import DbcInvalido, dbc_para_dbf, descomprimir, ler_dbc, ler_dbf

# Vetor de teste do blast.c (zlib/contrib): descomprime para "AIAIAIAIAIAIA".
VETOR_BLAST = bytes.fromhex("00 04 82 24 25 8f 80 7f".replace(" ", ""))


def _dbf(registros, campos=(("CNES", 7), ("CODUFMUN", 6), ("QT", 3))):
    tam_cab = 32 + 32 * len(campos) + 1
    tam_reg = 1 + sum(t for _, t in campos)
    cab = bytearray(32)
    cab[0] = 3
    struct.pack_into("<IHH", cab, 4, len(registros), tam_cab, tam_reg)
    for nome, tam in campos:
        d = bytearray(32)
        d[: len(nome)] = nome.encode()
        d[11] = ord("C")
        d[16] = tam
        cab += d
    cab += b"\r"
    corpo = b""
    for r in registros:
        corpo += (b"*" if r[0] == "*" else b" ") + b"".join(v.ljust(t).encode("latin-1") for v, (_, t) in zip(r[1:] if r[0] == "*" else r, campos))
    return bytes(cab) + corpo


def test_blast_vetor_conhecido():
    assert descomprimir(VETOR_BLAST) == b"AIAIAIAIAIAIA"


def test_blast_truncado_e_cabecalho_invalido():
    with pytest.raises(DbcInvalido):
        descomprimir(VETOR_BLAST[:5])
    with pytest.raises(DbcInvalido):
        descomprimir(bytes([2, 4, 0]))
    with pytest.raises(DbcInvalido):
        descomprimir(bytes([0, 9, 0]))


def test_blast_respeita_limite_de_saida():
    with pytest.raises(DbcInvalido):
        descomprimir(VETOR_BLAST, limite=5)


def test_ler_dbf_campos_apagados_e_filtro():
    dbf = _dbf([("0001", "355220", "12"), ("*", "0002", "355220", "7"), ("0003", "350000", "5")])
    assert list(ler_dbf(dbf)) == [
        {"CNES": "0001", "CODUFMUN": "355220", "QT": "12"},
        {"CNES": "0003", "CODUFMUN": "350000", "QT": "5"},
    ]
    assert [r["CNES"] for r in ler_dbf(dbf, ("CODUFMUN", "355220"))] == ["0001"]
    with pytest.raises(DbcInvalido):
        list(ler_dbf(dbf, ("NAO_EXISTE", "x")))


def test_ler_dbf_registros_truncados():
    dbf = _dbf([("0001", "355220", "12")])
    with pytest.raises(DbcInvalido):
        list(ler_dbf(dbf[:-3]))


def test_dbc_para_dbf_junta_cabecalho_e_payload():
    cab = bytearray(40)
    struct.pack_into("<H", cab, 8, 40)
    dbc = bytes(cab) + b"\0\0\0\0" + VETOR_BLAST
    assert dbc_para_dbf(dbc) == bytes(cab) + b"AIAIAIAIAIAIA"
    with pytest.raises(DbcInvalido):
        dbc_para_dbf(b"curto")
    struct.pack_into("<H", cab, 8, 5000)
    with pytest.raises(DbcInvalido):
        dbc_para_dbc = dbc_para_dbf(bytes(cab) + b"\0" * 8)


def test_ler_dbc_nao_aceita_arquivo_sem_payload():
    with pytest.raises(DbcInvalido):
        list(ler_dbc(b"\0" * 20))


def test_blast_distancia_alem_do_inicio_e_codigo_invalido():
    # bits manipulados à mão: marcador de cópia logo no início, sem nada na saída
    with pytest.raises(DbcInvalido):
        descomprimir(bytes([0, 4, 0xFF, 0xFF, 0xFF, 0xFF]))


def test_ler_dbf_campos_maiores_que_o_registro():
    dbf = bytearray(_dbf([("0001", "355220", "12")]))
    struct.pack_into("<H", dbf, 10, 5)
    with pytest.raises(DbcInvalido):
        list(ler_dbf(bytes(dbf)))
