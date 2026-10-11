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
    ultimo = len(pontos) - 1
    eixo = [
        {
            "x": round(i * largura + (largura * 0.88 if i == ultimo else largura * 0.12 if i == 0 else largura / 2), 2),
            "texto": t,
            "ancora": "end" if i == ultimo else "start" if i == 0 else "middle",
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


def linhas_preco(series: dict[str, list[float]], rotulos: dict[int, str]) -> dict:
    """Séries de preço com eixo vertical ajustado aos dados (preço não começa em zero)."""
    n = len(next(iter(series.values())))
    todos = [v for serie in series.values() for v in serie]
    vmin = int(min(todos) * 2) / 2 - 0.5
    vmax = -(-max(todos) * 2 // 1) / 2 + 0.5
    area = ALTURA - TOPO - BASE_ROTULOS
    passo = LARGURA / n

    def y(v: float) -> float:
        return TOPO + area * (1 - (v - vmin) / (vmax - vmin))

    saida = {}
    for nome, serie in series.items():
        pts = [(round(i * passo + passo / 2, 1), round(y(v), 1)) for i, v in enumerate(serie)]
        saida[nome] = {"pontos": " ".join(f"{x},{yy}" for x, yy in pts), "marcas": pts}
    return {
        "largura": LARGURA,
        "altura": ALTURA,
        "series": saida,
        "grade": [{"y": round(y(v), 1), "valor": v} for v in (vmin, (vmin + vmax) / 2, vmax)],
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


def linhas_posicao(pontos: list[tuple[int, int]], max_rotulos: int = 5) -> dict:
    """Posição em ranking ao longo dos anos: eixo vertical invertido (posição 1 no topo), anos proporcionais."""
    anos = [a for a, _ in pontos]
    pos = [p for _, p in pontos]
    a0, a1 = min(anos), max(anos)
    topo = max(1, min(pos) - max(1, (max(pos) - min(pos)) // 5))
    base = max(pos) + max(1, (max(pos) - min(pos)) // 5)
    area = ALTURA - TOPO - BASE_ROTULOS
    margem = 36

    def x(a: int) -> float:
        return round(margem + (LARGURA - 2 * margem) * ((a - a0) / ((a1 - a0) or 1)), 1)

    def y(p: int) -> float:
        return round(TOPO + area * ((p - topo) / ((base - topo) or 1)), 1)

    marcas = [{"x": x(a), "y": y(p), "ano": a, "pos": p} for a, p in pontos]
    passo = max(1, -(-len(pontos) // max_rotulos))
    rotulos = [
        {"x": m["x"], "texto": str(m["ano"]), "ancora": "start" if i == 0 else "end" if i == len(marcas) - 1 else "middle"}
        for i, m in enumerate(marcas) if i % passo == 0 or i == len(marcas) - 1
    ]
    if len(rotulos) >= 2 and rotulos[-2]["x"] > rotulos[-1]["x"] - 40:  # evita rótulos colados no fim
        rotulos.pop(-2)
    grade = sorted({topo, round((topo + base) / 2), base})
    return {
        "largura": LARGURA,
        "altura": ALTURA,
        "pontos": " ".join(f"{m['x']},{m['y']}" for m in marcas),
        "marcas": marcas,
        "grade": [{"y": y(g), "valor": g} for g in grade],
        "rotulos": rotulos,
        "y_rotulos": ALTURA - 8,
    }
