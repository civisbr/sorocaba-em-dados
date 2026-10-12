"""Tabelas de códigos do CNES e do SIH/SUS usadas nos painéis de saúde.

Fonte: tabelas auxiliares do DATASUS (TAB_CNES.zip e TAB_SIH.zip em ftp.datasus.gov.br/dissemin/publicos).
"""

from __future__ import annotations

TIPOS_UNIDADE = {
    "01": "Posto de saúde", "02": "Unidade básica de saúde", "04": "Policlínica", "05": "Hospital geral",
    "07": "Hospital especializado", "15": "Unidade mista", "20": "Pronto-socorro geral", "21": "Pronto-socorro especializado",
    "62": "Hospital-dia", "70": "Centro de atenção psicossocial (CAPS)", "73": "Unidade de pronto atendimento (UPA)",
    "36": "Clínica ou centro de especialidade", "45": "Unidade de saúde da família", "85": "Centro de imunização",
}
HOSPITALAR = ("05", "07", "15")
URGENCIA = ("20", "21", "73")
ATENCAO_BASICA = ("01", "02", "45")

GRUPO_LEITO = {"1": "Cirúrgicos", "2": "Clínicos", "3": "Complementares (UTI e intermediários)", "4": "Obstétricos", "5": "Pediátricos", "6": "Outras especialidades", "7": "Hospital-dia"}

LEITOS = {
    "01": "Buco-maxilo-facial", "02": "Cardiologia", "03": "Cirurgia geral", "04": "Endocrinologia", "05": "Gastroenterologia",
    "06": "Ginecologia", "07": "Cirúrgico, diagnóstico ou terapêutico", "08": "Nefrologia e urologia", "09": "Neurocirurgia",
    "10": "Obstetrícia cirúrgica", "11": "Oftalmologia", "12": "Oncologia", "13": "Ortopedia e traumatologia", "14": "Otorrinolaringologia",
    "15": "Plástica", "16": "Torácica", "31": "Aids", "32": "Cardiologia clínica", "33": "Clínica geral", "34": "Crônicos",
    "35": "Dermatologia", "36": "Geriatria", "37": "Hansenologia", "38": "Hematologia", "39": "Leito-dia", "40": "Nefrourologia",
    "41": "Neonatologia", "42": "Neurologia", "43": "Obstetrícia clínica", "44": "Oncologia clínica", "45": "Pediatria clínica",
    "46": "Pneumologia", "47": "Psiquiatria", "48": "Reabilitação", "49": "Pneumologia sanitária", "61": "UTI adulto",
    "62": "UTI infantil", "63": "UTI neonatal", "64": "Unidade intermediária", "65": "Unidade intermediária neonatal",
    "66": "Unidade de isolamento", "67": "Transplante", "68": "Pediatria cirúrgica", "69": "Aids", "70": "Fibrose cística",
    "71": "Intercorrência pós-transplante", "72": "Geriatria", "73": "Saúde mental", "74": "UTI adulto tipo I", "75": "UTI adulto tipo II",
    "76": "UTI adulto tipo III", "77": "UTI pediátrica tipo I", "78": "UTI pediátrica tipo II", "79": "UTI pediátrica tipo III",
    "80": "UTI neonatal tipo I", "81": "UTI neonatal tipo II", "82": "UTI neonatal tipo III", "83": "UTI de queimados",
    "84": "Acolhimento noturno", "85": "UTI coronariana tipo II", "86": "UTI coronariana tipo III", "87": "Saúde mental",
    "88": "Queimado adulto", "89": "Queimado pediátrico", "90": "Queimado adulto", "91": "Queimado pediátrico",
    "92": "Cuidados intermediários neonatal convencional", "93": "Cuidados intermediários neonatal canguru", "94": "Cuidados intermediários pediátrico", "95": "Cuidados intermediários adulto",
}
UTI = {"61", "62", "63", "74", "75", "76", "77", "78", "79", "80", "81", "82", "83", "85", "86"}

ESPEC_SIH = {  # LEITOS.CNV de TAB_SIH.zip (DATASUS); "99" é nosso, para código fora da tabela
    "01": "Cirúrgico", "02": "Obstétrico", "03": "Clínico", "04": "Crônicos", "05": "Psiquiatria", "06": "Pneumologia sanitária (tisiologia)",
    "07": "Pediátrico", "08": "Reabilitação", "09": "Leito-dia cirúrgico", "10": "Leito-dia Aids", "11": "Leito-dia fibrose cística",
    "12": "Leito-dia intercorrência pós-transplante", "13": "Leito-dia geriatria", "14": "Leito-dia saúde mental", "51": "UTI adulto II Covid-19",
    "52": "UTI pediátrica II Covid-19", "64": "Unidade intermediária", "65": "Unidade intermediária neonatal", "74": "UTI I", "75": "UTI adulto II",
    "76": "UTI adulto III", "77": "UTI infantil I", "78": "UTI infantil II", "79": "UTI infantil III", "80": "UTI neonatal I", "81": "UTI neonatal II",
    "82": "UTI neonatal III", "83": "UTI de queimados", "84": "Acolhimento noturno", "85": "UTI coronariana II", "86": "UTI coronariana III",
    "87": "Saúde mental (clínico)", "88": "Queimado adulto (clínico)", "89": "Queimado pediátrico (clínico)", "90": "Queimado adulto (cirúrgico)",
    "91": "Queimado pediátrico (cirúrgico)", "92": "Cuidados intermediários neonatal convencional", "93": "Cuidados intermediários neonatal canguru",
    "94": "Cuidados intermediários pediátrico", "95": "Cuidados intermediários adulto", "96": "Suporte ventilatório pulmonar Covid-19", "99": "Outras especialidades",
}

CAPITULOS_CID = (
    ("A00", "B99", "Doenças infecciosas e parasitárias"), ("C00", "D48", "Tumores (neoplasias)"),
    ("D50", "D89", "Doenças do sangue e do sistema imunológico"), ("E00", "E90", "Doenças endócrinas e metabólicas"),
    ("F00", "F99", "Transtornos mentais e comportamentais"), ("G00", "G99", "Doenças do sistema nervoso"),
    ("H00", "H59", "Doenças do olho"), ("H60", "H95", "Doenças do ouvido"), ("I00", "I99", "Doenças do coração e da circulação"),
    ("J00", "J99", "Doenças respiratórias"), ("K00", "K93", "Doenças do aparelho digestivo"), ("L00", "L99", "Doenças da pele"),
    ("M00", "M99", "Doenças dos ossos, músculos e articulações"), ("N00", "N99", "Doenças do aparelho urinário e genital"),
    ("O00", "O99", "Gravidez, parto e puerpério"), ("P00", "P96", "Afecções do período perinatal"),
    ("Q00", "Q99", "Malformações congênitas"), ("R00", "R99", "Sintomas e sinais não classificados"),
    ("S00", "T98", "Lesões, envenenamentos e outras causas externas"), ("V01", "Y98", "Causas externas (acidentes e violência)"),
    ("Z00", "Z99", "Contatos com serviços de saúde"),
)


def capitulo_cid(codigo: str) -> str | None:
    c = (codigo or "").strip().upper()[:3]
    if len(c) < 3 or not c[0].isalpha() or not c[1:].isdigit():
        return None
    for ini, fim, nome in CAPITULOS_CID:
        if ini <= c <= fim:
            return nome
    return None


def natureza(nat_jur: str) -> str:
    """Classe da natureza jurídica do CNES: 1 pública, 2 empresarial, 3 sem fins lucrativos."""
    return {"1": "Público", "2": "Privado", "3": "Sem fins lucrativos"}.get((nat_jur or "")[:1], "Outro")
