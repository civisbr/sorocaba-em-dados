from scripts.geo_aprox import OSM, Via, aproximar, interpretar, montar, palavras

DENTRO = lambda la, lo: True


def _rua(nome, lat0, lon0, lat1, lon1):
    return {"tags": {"name": nome}, "geometry": [{"lat": lat0, "lon": lon0}, {"lat": lat1, "lon": lon1}]}


def _osm(vias, enderecos=(), marcos=(), rodovias=()):
    return montar({"vias": list(vias), "enderecos": list(enderecos), "marcos": list(marcos), "rodovias": list(rodovias)})


def test_interpretar_endereco_cruzamento_referencia_e_rodovia():
    assert interpretar("AV. DOM AGUIRRE, Nº 3303").numero == 3303
    c = interpretar("AV. ANTONIO CARLOS COMITRE X RUA ASSUNÇÃO")
    assert (c.via, c.outra) == ("AVENIDA ANTONIO CARLOS COMITRE", "RUA ASSUNÇÃO")
    r = interpretar("AV. DOM AGUIRRE, PRÓX. À RUA COM. HÉLIO MONZONI")
    assert r.outra and "HÉLIO MONZONI" in r.outra
    k = interpretar("RODOVIA SP-270 KM 094 + 017M (EXPRESSA)")
    assert k.rodovia == ("SP", 270) and k.km == 94.017
    assert interpretar("SP 097 KM 001,100").km == 1.1


def test_nome_da_via_tolera_numero_por_extenso_e_hifen():
    assert palavras("QUINZE DE AGOSTO") <= palavras("Avenida 15 de Agosto", juntar=True)
    assert palavras("EDWARD FRUFRU MARCIANO") <= palavras("Avenida Edward Fru-Fru Marciano da Silva", juntar=True)


def test_cruzamento_de_duas_vias():
    osm = _osm([_rua("Rua Alfa", -23.50, -47.40, -23.50, -47.39), _rua("Rua Beta", -23.51, -47.395, -23.49, -47.395)])
    p = aproximar("RUA ALFA X RUA BETA", osm, DENTRO)
    assert p and p.nivel == "cruzamento" and abs(p.lat + 23.50) < 0.0005 and abs(p.lon + 47.395) < 0.0005


def test_numero_interpolado_entre_enderecos_vizinhos():
    rua = _rua("Rua Alfa", -23.50, -47.40, -23.50, -47.39)
    end = lambda n, lon: {"lat": -23.50, "lon": lon, "tags": {"addr:housenumber": str(n), "addr:street": "Rua Alfa"}}
    osm = _osm([rua], [end(100, -47.40), end(200, -47.39)])
    p = aproximar("RUA ALFA, Nº 150", osm, DENTRO)
    assert p and p.nivel == "número" and abs(p.lon + 47.395) < 0.001


def test_sem_endereco_cai_no_meio_da_via_e_sem_via_nao_inventa():
    osm = _osm([_rua("Rua Alfa", -23.50, -47.40, -23.50, -47.38)])
    assert aproximar("RUA ALFA, Nº 150", osm, DENTRO).nivel == "via"
    assert aproximar("RUA INEXISTENTE, Nº 1", osm, DENTRO) is None


def test_fora_do_municipio_e_descartado():
    osm = _osm([_rua("Rua Alfa", -23.50, -47.40, -23.50, -47.38)])
    assert aproximar("RUA ALFA, Nº 1", osm, lambda la, lo: False) is None


def test_ruas_homonimas_distantes_so_se_desempatam_por_numero():
    osm = _osm([_rua("Rua Alfa", -23.50, -47.40, -23.50, -47.39), _rua("Rua Alfa", -23.60, -47.30, -23.60, -47.29)])
    assert aproximar("RUA ALFA, Nº 5", osm, DENTRO) is None


def test_rodovia_por_km_anda_a_partir_do_marco():
    marco = lambda km, lon: {"lat": -23.5, "lon": lon, "tags": {"highway": "milestone", "distance": str(km), "ref": "SP-270"}}
    pontos = [{"lat": -23.5, "lon": -47.5 + i * 0.001} for i in range(200)]
    rodovia = {"tags": {"ref": "SP-270", "highway": "motorway", "name": "Rodovia Teste"}, "geometry": pontos}
    osm = _osm([], marcos=[marco(10, -47.5), marco(11, -47.389)], rodovias=[rodovia])
    p = aproximar("RODOVIA SP-270 KM 010 + 500M", osm, DENTRO)
    assert p and p.nivel == "km" and abs(p.lon + 47.5) < 0.01 + 0.0001


def test_apos_a_avenida_extrai_a_via_de_referencia():
    assert interpretar("AV. COM. CAMILLO JULIO APROX. 150M APÓS A AV. TADAO YOSHIDA").outra == "AVENIDA TADAO YOSHIDA"


def test_numero_que_existe_no_osm_usa_o_proprio_endereco():
    rua = _rua("Rua Alfa", -23.50, -47.40, -23.50, -47.39)
    end = lambda n, lon: {"lat": -23.50, "lon": lon, "tags": {"addr:housenumber": str(n), "addr:street": "Rua Alfa"}}
    osm = _osm([rua], [end(100, -47.40), end(150, -47.397), end(200, -47.39)])
    p = aproximar("RUA ALFA, Nº 150", osm, DENTRO)
    assert p and p.nivel == "número" and abs(p.lon + 47.397) < 1e-6


def test_vias_proximas_mas_desligadas_dao_posicao_com_aviso():
    osm = _osm([_rua("Rua Alfa", -23.50, -47.40, -23.50, -47.39), _rua("Rua Beta", -23.5008, -47.395, -23.502, -47.395)])
    p = aproximar("RUA ALFA, PRÓX. À RUA BETA", osm, DENTRO)
    assert p and p.nivel == "cruzamento" and "m uma da outra" in p.detalhe


def test_numeracao_estimada_ao_longo_da_via_sem_endereco_vizinho():
    rua = {"tags": {"name": "Avenida Longa"}, "geometry": [{"lat": -23.50, "lon": -47.50 + i * 0.001} for i in range(61)]}  # ~6,1 km
    end = lambda n, lon: {"lat": -23.50, "lon": lon, "tags": {"addr:housenumber": str(n), "addr:street": "Avenida Longa"}}
    # a numeração cresce 300 por ~1 km nos 3 primeiros km; o nº 1500 fica a ~4,7 km, além do último endereço (1000)
    osm = _osm([rua], [end(100 + i * 150, -47.50 + i * 0.005) for i in range(7)])
    p = aproximar("AVENIDA LONGA, Nº 1500", osm, DENTRO)
    assert p and p.nivel == "numeração" and "além dos endereços" in p.detalhe and abs(p.lon + 47.4533) < 0.01


def test_numeracao_nao_inventa_com_poucos_ou_desencontrados_enderecos():
    rua = {"tags": {"name": "Avenida Longa"}, "geometry": [{"lat": -23.50, "lon": -47.50 + i * 0.001} for i in range(61)]}
    end = lambda n, lon: {"lat": -23.50, "lon": lon, "tags": {"addr:housenumber": str(n), "addr:street": "Avenida Longa"}}
    assert aproximar("AVENIDA LONGA, Nº 900", _osm([rua], [end(100, -47.50), end(200, -47.49)]), DENTRO).nivel == "via"
    embaralhado = _osm([rua], [end(100, -47.45), end(200, -47.50), end(300, -47.44), end(400, -47.49), end(450, -47.47)])
    assert aproximar("AVENIDA LONGA, Nº 900", embaralhado, DENTRO).nivel == "via"


def _ends(rua, pares):
    return [{"lat": -23.50, "lon": lon, "tags": {"addr:housenumber": str(n), "addr:street": rua}} for n, lon in pares]


def test_numeracao_com_via_cortada_em_duas_pistas_desconexas():
    # a mesma avenida em dois pedaços sem nó em comum, a 60 m um do outro
    a = {"tags": {"name": "Avenida Longa"}, "geometry": [{"lat": -23.50, "lon": -47.50 + i * 0.001} for i in range(31)]}
    b = {"tags": {"name": "Avenida Longa"}, "geometry": [{"lat": -23.50, "lon": -47.4695 + i * 0.001} for i in range(31)]}
    osm = _osm([a, b], _ends("Avenida Longa", [(100 + i * 150, -47.50 + i * 0.005) for i in range(10)]))  # endereços nos dois pedaços
    p = aproximar("AVENIDA LONGA, Nº 1900", osm, DENTRO)
    assert p and p.nivel == "numeração" and abs(p.lon + 47.44) < 0.01


def test_numeracao_ignora_ramo_mais_curto_com_o_mesmo_nome():
    tronco = {"tags": {"name": "Avenida Longa"}, "geometry": [{"lat": -23.50, "lon": -47.50 + i * 0.001} for i in range(61)]}
    ramo = {"tags": {"name": "Avenida Longa"}, "geometry": [{"lat": -23.50 - i * 0.001, "lon": -47.47} for i in range(12)]}
    osm = _osm([tronco, ramo], _ends("Avenida Longa", [(100 + i * 100, -47.50 + i * 0.005) for i in range(10)]))
    p = aproximar("AVENIDA LONGA, Nº 1200", osm, DENTRO)
    assert p and abs(p.lat + 23.50) < 0.0005  # no tronco, não no ramo


def test_numeracao_descarta_endereco_digitado_errado_mesmo_com_poucos_pontos():
    rua = {"tags": {"name": "Avenida Longa"}, "geometry": [{"lat": -23.50, "lon": -47.50 + i * 0.001} for i in range(61)]}
    certos = [(100 + i * 100, -47.50 + i * 0.005) for i in range(8)]
    osm = _osm([rua], _ends("Avenida Longa", certos + [(250, -47.44)]))  # o 250 está a 6 km de onde deveria
    p = aproximar("AVENIDA LONGA, Nº 1150", osm, DENTRO)
    assert p and p.nivel == "numeração" and abs(p.lon + 47.4475) < 0.01
