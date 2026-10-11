"""Agrupamento das naturezas da SSP-SP, compartilhado entre a coleta e o build.

A coleta já grava só o grupo: categorias raras e sensíveis (estupro, latrocínio, extorsão
mediante sequestro) nunca chegam ao repositório em nível mais fino que o mês da cidade inteira.
"""

import re
import unicodedata

# Só categorias presentes com o mesmo nome em todos os anos da série.
GRUPOS = {
    "roubos": ("Roubos", {"ROUBO - OUTROS", "ROUBO DE VEICULO", "ROUBO DE CARGA"}),
    "furtos": ("Furtos", {"FURTO - OUTROS", "FURTO DE VEICULO", "FURTO DE CARGA"}),
    "mortes_dolosas": ("Mortes por crime doloso", {"HOMICIDIO DOLOSO", "LATROCINIO", "LESAO CORPORAL SEGUIDA DE MORTE"}),
    "lesao_dolosa": ("Lesão corporal dolosa", {"LESAO CORPORAL DOLOSA"}),
    "estupros": ("Estupros", {"ESTUPRO", "ESTUPRO DE VULNERAVEL"}),
    "trafico": ("Tráfico de entorpecentes", {"TRAFICO DE ENTORPECENTES"}),
}
DE_PARA = {n: g for g, (_, ns) in GRUPOS.items() for n in ns}
# Únicos grupos com recorte por hora, bairro e tipo: crimes patrimoniais, sem vítima identificável.
GRUPOS_DETALHADOS = ("roubos", "furtos")


def chave(natureza: str) -> str:
    sem = unicodedata.normalize("NFKD", natureza.replace("–", "-").replace("—", "-")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s*[-–]\s*", " - ", " ".join(sem.split()))


def grupo_de(natureza: str) -> str | None:
    return DE_PARA.get(chave(natureza))


def sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper().strip()
