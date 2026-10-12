"""Texto de exibição dos locais de radar e rótulos de posição. A fonte vem em caixa alta; os dados guardados não mudam, só o que o site mostra."""

from __future__ import annotations

import re

MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "a", "à", "ao", "aos", "na", "no", "nas", "nos", "em", "com", "x", "por", "para"}
ABREVIATURAS = {
    "AV": "Av.", "R": "R.", "DR": "Dr.", "DRA": "Dra.", "PROF": "Prof.", "PROFA": "Profa.", "ENG": "Eng.", "COM": "Com.", "CDOR": "Cdor.", "CEL": "Cel.",
    "PE": "Pe.", "CAP": "Cap.", "GAL": "Gal.", "MAL": "Mal.", "PROX": "Próx.", "PRÓX": "Próx.", "APROX": "Aprox.", "ROD": "Rod.", "AL": "Al.", "TRAV": "Trav.",
    "PROXIMO": "Próximo", "PRÓXIMO": "Próximo", "KM": "km", "NUM": "nº", "STA": "Sta.", "STO": "Sto.", "SEN": "Sen.", "DEP": "Dep.", "PÇA": "Pça.", "PC": "Pç.",
}
ROTULOS = {
    "cruzamento": "aproximada, perto do cruzamento das duas vias",
    "número": "aproximada, pelo número do endereço",
    "km": "aproximada, pelo km da rodovia",
    "numeração": "aproximada, estimada pela numeração ao longo da via",
    "via": "aproximada, no meio da via (sem endereço no mapa)",
}


def rotulo_posicao(precisao: str, detalhe: str = "") -> str:
    base = ROTULOS.get(precisao)
    if base is None:
        return {"porta": "endereço exato no OpenStreetMap", "endereço": "endereço exato no OpenStreetMap", "câmera no OSM": "câmera de velocidade mapeada no OpenStreetMap"}.get(precisao, precisao)
    return f"{base} ({detalhe})" if detalhe else base


PALAVRA = re.compile(r"[\wÀ-ÿ°ºª]+(?:[-/][\wÀ-ÿ]+)*")
RODOVIA = re.compile(r"(?:SP|SPM|SPA|BR)(?:-?\d+)?")
SO_MEIO = MINUSCULAS | {"oposto", "próx", "aprox", "próximo", "após", "nº"}
MINUSCULAR_ABREV = {"próx", "aprox", "próximo"}
SEM_PONTO = {"KM", "PROXIMO", "PRÓXIMO"}


def _palavra(m: re.Match[str], texto: str, primeira: bool, todas: bool) -> str:
    w = m.group()
    if not todas and not (len(w) > 1 and w.isupper()):
        return w
    chave = w.upper().replace("°", "").replace("º", "").replace("ª", "")
    if RODOVIA.fullmatch(chave) or re.fullmatch(r"[CB]/[CB]|CB|BC", chave):
        return chave
    ponto = texto[m.end() : m.end() + 1] == "."
    if chave in ABREVIATURAS and not (chave == "COM" and not ponto):  # "COM" sem ponto é a preposição ("Av. X com Rua Y")
        s = ABREVIATURAS[chave]
        if not primeira and s.rstrip(".").lower() in MINUSCULAR_ABREV:
            s = s.lower()
        if w.endswith("ª"):
            return s.rstrip(".") + "ª"
        return s[:-1] if s.endswith(".") and ponto else s
    if re.fullmatch(r"\d+M", chave):
        return chave[:-1] + "m"
    baixa = w.lower()
    if not primeira and baixa in SO_MEIO and not (len(baixa) == 1 and texto[m.end() : m.end() + 1] == "."):
        return baixa
    return "-".join(p[:1].upper() + p[1:].lower() for p in w.split("-"))


def legivel(texto: str) -> str:
    """"AV. DOM AGUIRRE, PROX. À RUA COM. HÉLIO MONZONI" -> "Av. Dom Aguirre, próx. à Rua Com. Hélio Monzoni". Texto que já está em caixa mista só ganha espaços arrumados; em caixa mista parcial, só as palavras em caixa alta são ajustadas."""
    t = re.sub(r"\s+,", ",", " ".join(str(texto).split()))
    t = re.sub(r"\(\s*([CBcb])\s*/\s*([CBcb])\s*\)", lambda m: f"({m.group(1)}/{m.group(2)})".upper(), t)
    letras = [c for c in re.sub(r"\bn\s*[º°]", "", t) if c.isalpha() and c not in "ºª"]
    if not letras or sum(c.isupper() for c in letras) / len(letras) < 0.2:  # já está em caixa mista
        return t
    todas = sum(c.isupper() for c in letras) / len(letras) >= 0.6  # só caixa alta; senão, só as palavras em caixa alta são ajustadas
    t = re.sub(r"\b[Nn]\s*[º°]\s*\.?\s*(?=\d)|\b[Nn]\.\s*(?=\d)", "nº ", t)
    partes, ultimo, primeira = [], 0, True
    for m in PALAVRA.finditer(t):
        partes += [t[ultimo : m.start()], _palavra(m, t, primeira, todas)]
        ultimo, primeira = m.end(), False
    return "".join(partes) + t[ultimo:]
