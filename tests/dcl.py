"""Codificador PKWare DCL mínimo, só para testes: gera fluxos que o leitor de scripts/dbc.py precisa descomprimir (ida e volta)."""

from __future__ import annotations

from scripts.dbc import _BASE, _COMPRIMENTOS, _DISTANCIAS, _EXTRA, _LITERAIS


def _codigos(rep: tuple[int, ...]) -> dict[int, tuple[int, int]]:
    comprimentos: list[int] = []
    for r in rep:
        comprimentos += [r & 15] * ((r >> 4) + 1)
    saida, codigo = {}, 0
    for tam in range(1, 14):
        for simbolo, c in enumerate(comprimentos):
            if c == tam:
                saida[simbolo] = (codigo, tam)
                codigo += 1
        codigo <<= 1
    return saida


LIT, LEN, DIST = _codigos(_LITERAIS), _codigos(_COMPRIMENTOS), _codigos(_DISTANCIAS)


class _Bits:
    def __init__(self) -> None:
        self.buf = self.n = 0
        self.saida = bytearray()

    def pôr(self, valor: int, k: int) -> None:
        self.buf |= valor << self.n
        self.n += k
        while self.n >= 8:
            self.saida.append(self.buf & 255)
            self.buf >>= 8
            self.n -= 8

    def huff(self, cl: tuple[int, int]) -> None:
        codigo, tam = cl
        for i in range(tam - 1, -1, -1):
            self.pôr(((codigo >> i) & 1) ^ 1, 1)

    def fim(self) -> bytes:
        if self.n:
            self.saida.append(self.buf & 255)
        return bytes(self.saida)


def _simbolo_comprimento(n: int) -> int:
    return next(s for s in range(15, -1, -1) if _BASE[s] <= n < _BASE[s] + (1 << _EXTRA[s]))


def comprimir(dados: bytes, dicionario: int = 6, codificado: bool = True, janela: int = 1000) -> bytes:
    w = _Bits()
    w.pôr(1 if codificado else 0, 8)
    w.pôr(dicionario, 8)
    i = 0
    while i < len(dados):
        melhor, dist = 0, 0
        for d in range(1, min(i, janela, (64 << dicionario)) + 1):
            n = 0
            while i + n < len(dados) and dados[i + n] == dados[i + n - d] and n < 516:
                n += 1
            if n > melhor:
                melhor, dist = n, d
        if melhor >= 2 and not (melhor == 2 and dist > 255) and dist <= (64 << dicionario):
            s = _simbolo_comprimento(melhor)
            w.pôr(1, 1)
            w.huff(LEN[s])
            w.pôr(melhor - _BASE[s], _EXTRA[s])
            extra = 2 if melhor == 2 else dicionario
            d1 = dist - 1
            w.huff(DIST[d1 >> extra])
            w.pôr(d1 & ((1 << extra) - 1), extra)
            i += melhor
        else:
            w.pôr(0, 1)
            if codificado:
                w.huff(LIT[dados[i]])
            else:
                w.pôr(dados[i], 8)
            i += 1
    s = _simbolo_comprimento(519)
    w.pôr(1, 1)
    w.huff(LEN[s])
    w.pôr(519 - _BASE[s], _EXTRA[s])
    w.pôr(0, 8)
    return w.fim()
