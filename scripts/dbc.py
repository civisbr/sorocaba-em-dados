"""Leitor de arquivos .dbc do DATASUS (DBF com payload comprimido em PKWare DCL).

O .dbc guarda o cabeçalho DBF em claro, 4 bytes de CRC e, depois, os registros
comprimidos com o formato "implode" do PKWare (o mesmo que zlib/contrib/blast
descomprime). Esta é uma porta direta do blast.c, sem dependência de C.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator

MAX_BITS = 13
MAX_SAIDA = 512 * 1024 * 1024

_LITERAIS = (
    11, 124, 8, 7, 28, 7, 188, 13, 76, 4, 10, 8, 12, 10, 12, 10, 8, 23, 8,
    9, 7, 6, 7, 8, 7, 6, 55, 8, 23, 24, 12, 11, 7, 9, 11, 12, 6, 7, 22, 5,
    7, 24, 6, 11, 9, 6, 7, 22, 7, 11, 38, 7, 9, 8, 25, 11, 8, 11, 9, 12,
    8, 12, 5, 38, 5, 38, 5, 11, 7, 5, 6, 21, 6, 10, 53, 8, 7, 24, 10, 27,
    44, 253, 253, 253, 252, 252, 252, 13, 12, 45, 12, 45, 12, 61, 12, 45,
    44, 173,
)
_COMPRIMENTOS = (2, 35, 36, 53, 38, 23)
_DISTANCIAS = (2, 20, 53, 230, 247, 151, 248)
_BASE = (3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264)
_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8)


class DbcInvalido(ValueError):
    pass


class _Huffman:
    def __init__(self, repeticoes: tuple[int, ...]):
        comprimentos: list[int] = []
        for r in repeticoes:
            comprimentos.extend([r & 15] * ((r >> 4) + 1))
        self.contagem = [0] * (MAX_BITS + 1)
        for c in comprimentos:
            self.contagem[c] += 1
        deslocamento = [0, 0] + [0] * (MAX_BITS - 1)
        for i in range(1, MAX_BITS):
            deslocamento[i + 1] = deslocamento[i] + self.contagem[i]
        self.simbolo = [0] * len(comprimentos)
        for s, c in enumerate(comprimentos):
            if c:
                self.simbolo[deslocamento[c]] = s
                deslocamento[c] += 1


_TAB_LIT = _Huffman(_LITERAIS)
_TAB_LEN = _Huffman(_COMPRIMENTOS)
_TAB_DIST = _Huffman(_DISTANCIAS)


class _Bits:
    def __init__(self, dados: bytes, pos: int):
        self.dados = dados
        self.pos = pos
        self.buf = 0
        self.n = 0

    def bits(self, precisa: int) -> int:
        val = self.buf
        while self.n < precisa:
            if self.pos >= len(self.dados):
                raise DbcInvalido("fluxo comprimido truncado")
            val |= self.dados[self.pos] << self.n
            self.pos += 1
            self.n += 8
        self.buf = val >> precisa
        self.n -= precisa
        return val & ((1 << precisa) - 1)

    def decodificar(self, h: _Huffman) -> int:
        codigo = primeiro = indice = 0
        for comp in range(1, MAX_BITS + 1):
            codigo |= self.bits(1) ^ 1
            cont = h.contagem[comp]
            if codigo - cont < primeiro:
                return h.simbolo[indice + (codigo - primeiro)]
            indice += cont
            primeiro = (primeiro + cont) << 1
            codigo <<= 1
        raise DbcInvalido("código Huffman inválido")


def descomprimir(dados: bytes, inicio: int = 0, limite: int = MAX_SAIDA) -> bytes:
    """Descomprime um fluxo PKWare DCL a partir de `inicio`."""
    b = _Bits(dados, inicio)
    codificado = b.bits(8)
    dicionario = b.bits(8)
    if codificado > 1:
        raise DbcInvalido("cabeçalho DCL inválido")
    if not 4 <= dicionario <= 6:
        raise DbcInvalido("tamanho de dicionário DCL inválido")
    saida = bytearray()
    while True:
        if b.bits(1):
            s = b.decodificar(_TAB_LEN)
            comp = _BASE[s] + b.bits(_EXTRA[s])
            if comp == 519:
                break
            extra = 2 if comp == 2 else dicionario
            dist = (b.decodificar(_TAB_DIST) << extra) + b.bits(extra) + 1
            if dist > len(saida):
                raise DbcInvalido("distância além do início da saída")
            if len(saida) + comp > limite:
                raise DbcInvalido("saída excede o limite")
            ini = len(saida) - dist
            if dist >= comp:
                saida += saida[ini : ini + comp]
            else:
                for _ in range(comp):
                    saida.append(saida[ini])
                    ini += 1
        else:
            if len(saida) >= limite:
                raise DbcInvalido("saída excede o limite")
            saida.append(b.decodificar(_TAB_LIT) if codificado else b.bits(8))
    return bytes(saida)


def dbc_para_dbf(dados: bytes) -> bytes:
    if len(dados) < 32:
        raise DbcInvalido("arquivo curto demais")
    tam_cab = struct.unpack_from("<H", dados, 8)[0]
    if tam_cab < 33 or tam_cab + 4 > len(dados):
        raise DbcInvalido("tamanho de cabeçalho DBF inválido")
    return dados[:tam_cab] + descomprimir(dados, tam_cab + 4)


def ler_dbf(dbf: bytes, filtro: tuple[str, str] | None = None) -> Iterator[dict[str, str]]:
    """Gera registros como dict de texto (latin-1), sem os marcados como apagados.

    `filtro=(campo, valor)` compara os bytes do campo antes de montar o dict,
    o que torna a leitura de arquivos estaduais inteiros muito mais rápida.
    """
    n_reg, tam_cab, tam_reg = struct.unpack_from("<IHH", dbf, 4)
    campos: list[tuple[str, int]] = []
    pos = 32
    while pos + 32 < tam_cab and dbf[pos] != 0x0D:
        nome = dbf[pos : pos + 11].split(b"\0")[0].decode("latin-1")
        campos.append((nome, dbf[pos + 16]))
        pos += 32
    if sum(t for _, t in campos) + 1 > tam_reg:
        raise DbcInvalido("campos maiores que o registro")
    alvo = None
    if filtro is not None:
        off = 1
        for nome, tam in campos:
            if nome == filtro[0]:
                alvo = (off, tam, filtro[1].encode("latin-1"))
                break
            off += tam
        if alvo is None:
            raise DbcInvalido(f"campo {filtro[0]} ausente")
    for i in range(n_reg):
        ini = tam_cab + i * tam_reg
        reg = dbf[ini : ini + tam_reg]
        if len(reg) < tam_reg:
            raise DbcInvalido("registros truncados")
        if reg[0:1] == b"*":
            continue
        if alvo is not None and reg[alvo[0] : alvo[0] + alvo[1]].strip() != alvo[2]:
            continue
        off = 1
        linha: dict[str, str] = {}
        for nome, tam in campos:
            linha[nome] = reg[off : off + tam].decode("latin-1").strip()
            off += tam
        yield linha


def ler_dbc(dados: bytes, filtro: tuple[str, str] | None = None) -> Iterator[dict[str, str]]:
    return ler_dbf(dbc_para_dbf(dados), filtro)
