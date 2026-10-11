"""Gráficos SVG gerados no build, sem biblioteca client-side."""

from __future__ import annotations

LARGURA = 480
ALTURA = 260
TOPO = 24
BASE_ROTULOS = 28


def barras_mensais(pontos: list[tuple[str, int]], rotulos: dict[int, str]) -> dict:
    """Retorna barras já posicionadas para o template.

    `pontos` é (rótulo curto, valor); `rotulos` mapeia índice -> texto do eixo X.
    """
    valores = [v for _, v in pontos]
    vmax, vmin = max(max(valores), 0), min(min(valores), 0)
    area = ALTURA - TOPO - BASE_ROTULOS
    escala = area / ((vmax - vmin) or 1)
    zero = TOPO + vmax * escala
    largura = LARGURA / len(pontos)
    barras = []
    for i, (rotulo, valor) in enumerate(pontos):
        altura = abs(valor) * escala
        y = zero - altura if valor >= 0 else zero
        barras.append(
            {
                "x": round(i * largura + largura * 0.12, 2),
                "y": round(y, 2),
                "w": round(largura * 0.76, 2),
                "h": round(max(altura, 1), 2),
                "positivo": valor >= 0,
                "rotulo": rotulo,
                "valor": valor,
            }
        )
    eixo = [
        {
            "x": round(i * largura + (largura * 0.88 if i == len(pontos) - 1 else largura / 2), 2),
            "texto": t,
            "ancora": "end" if i == len(pontos) - 1 else "middle",
        }
        for i, t in sorted(rotulos.items())
    ]
    return {
        "largura": LARGURA,
        "altura": ALTURA,
        "zero": round(zero, 2),
        "barras": barras,
        "eixo_x": eixo,
        "y_rotulos": ALTURA - 8,
    }


def linhas(series: dict[str, list[int]], rotulos: dict[int, str]) -> dict:
    """Duas ou mais séries com a mesma escala vertical, começando em zero."""
    n = len(next(iter(series.values())))
    bruto = max(v for serie in series.values() for v in serie) or 1
    vmax = -(-bruto // 2000) * 2000
    area = ALTURA - TOPO - BASE_ROTULOS
    passo = LARGURA / n

    def y(v: int) -> float:
        return TOPO + area * (1 - v / vmax)

    saida = {}
    for nome, serie in series.items():
        pts = [(round(i * passo + passo / 2, 1), round(y(v), 1)) for i, v in enumerate(serie)]
        saida[nome] = {"pontos": " ".join(f"{x},{yy}" for x, yy in pts), "fim": pts[-1], "ultimo": serie[-1]}
    return {
        "largura": LARGURA,
        "altura": ALTURA,
        "series": saida,
        "grade": [{"y": round(y(vmax * f), 1), "valor": round(vmax * f)} for f in (0, 0.5, 1)],
        "eixo_x": [
            {
                "x": round(i * passo + (passo * 0.9 if i == n - 1 else passo / 2), 1),
                "texto": t,
                "ancora": "end" if i == n - 1 else "middle",
            }
            for i, t in sorted(rotulos.items())
        ],
        "y_rotulos": ALTURA - 8,
    }
