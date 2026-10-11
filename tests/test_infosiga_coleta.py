import json
from datetime import date

import httpx
import pytest

from scripts import fetch_infosiga as f
from scripts.build_infosiga import construir

CAB = "id_sinistro;tipo_registro;data_sinistro;hora_sinistro;dia_da_semana;logradouro;latitude;longitude;cod_ibge;tp_sinistro_primario;qtd_gravidade_fatal;qtd_gravidade_grave"
LINHA = "1;SINISTRO NAO FATAL;01/01/2025;14:30;Terça-feira;AV X;-23,50;-47,45;3552205;COLISAO;0;0"
HOJE = date(2026, 3, 1)
BASE = "https://infosiga.detran.sp.gov.br/dados-abertos/"


def catalogo(meses, duplicar=False, ano=2026):
    urls = [f"{BASE}sinistros_{m:02d}-{ano}.csv?sig=abc" for m in meses]
    if duplicar:
        urls.append(urls[0])
    return {"result": {"resources": [{"url": u} for u in urls]}}


def transporte(meses, falhar_403_uma_vez=False, duplicar=False, ano=2026):
    estado = {"403": falhar_403_uma_vez, "catalogos": 0}

    def tratar(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("package_show"):
            estado["catalogos"] += 1
            return httpx.Response(200, json=catalogo(meses, duplicar, ano))
        if estado["403"]:
            estado["403"] = False
            return httpx.Response(403)
        return httpx.Response(200, content=(CAB + "\n" + LINHA + "\n").encode("latin-1"))

    t = httpx.MockTransport(tratar)
    t.estado = estado
    return t


def coletar(tmp_path, meses, **kw):
    return f.coletar(HOJE, tmp_path, transporte=transporte(meses, **kw))


def test_coleta_grava_manifesto_sem_query_e_com_hash(tmp_path):
    assert coletar(tmp_path, [1, 2]) == [2026]
    man = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))
    o = man["anos"]["2026"]["origem"]["01"]
    assert "?" not in o["url"] and len(o["sha256"]) == 64 and man["anos"]["2026"]["com_coordenada"] == 2
    assert man["anos"]["2026"]["registros"] == 2


def test_aborta_quando_catalogo_perde_mes_ja_coletado_e_nao_altera_arquivos(tmp_path):
    coletar(tmp_path, [1, 2])
    antes = (tmp_path / "2026" / "mensal.csv").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="perdeu os meses"):
        coletar(tmp_path, [1])
    assert (tmp_path / "2026" / "mensal.csv").read_text(encoding="utf-8") == antes


def test_aborta_com_recurso_duplicado(tmp_path):
    with pytest.raises(ValueError, match="duplicado"):
        coletar(tmp_path, [1], duplicar=True)


def test_403_relê_catalogo_uma_vez(tmp_path):
    t = transporte([1], falhar_403_uma_vez=True)
    assert f.coletar(HOJE, tmp_path, transporte=t) == [2026]
    assert t.estado["catalogos"] == 2


def test_poda_anos_fora_da_janela_e_registra(tmp_path):
    (tmp_path / "2019").mkdir()
    (tmp_path / "manifesto.json").write_text(json.dumps({"anos": {"2019": {"meses": [1]}}}), encoding="utf-8")
    coletar(tmp_path, [1])
    man = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))
    assert "2019" not in man["anos"] and man["anos_removidos"]["2019"] == "2026-03-01" and not (tmp_path / "2019").exists()


def test_build_sem_ano_completo_da_erro_claro(tmp_path):
    coletar(tmp_path, [1, 2])
    with pytest.raises(ValueError, match="nenhum ano completo"):
        construir(tmp_path)


def test_build_com_ano_completo_usa_cobertura_do_manifesto(tmp_path):
    t = transporte(list(range(1, 13)), ano=2025)
    f.coletar(HOJE, tmp_path, transporte=t)
    man = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))
    assert man["anos"]["2025"]["com_coordenada"] == 12
    env = construir(tmp_path)
    assert env.qualidade.n_registros > 0


def test_buscar_endereco_rejeita_via_bairro_e_numero_diferente():
    from scripts.geocode_radares import buscar_endereco

    def com(resposta):
        return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[resposta])))

    ok = {"lat": "-23.5", "lon": "-47.4", "addresstype": "house", "osm_type": "node", "osm_id": 1, "address": {"house_number": "660", "road": "Rua Michel Chicri Maluf"}}
    assert buscar_endereco(com(ok), "RUA MICHEL CHICRI MALUF", "660")[2] == "node/1"
    assert buscar_endereco(com({**ok, "addresstype": "suburb"}), "RUA MICHEL CHICRI MALUF", "660") is None
    assert buscar_endereco(com({**ok, "address": {"house_number": "661", "road": "Rua Michel Chicri Maluf"}}), "RUA MICHEL CHICRI MALUF", "660") is None
    assert buscar_endereco(com({**ok, "address": {"house_number": "660", "road": "Rua Outra"}}), "RUA MICHEL CHICRI MALUF", "660") is None


def test_hook_de_hosts_continua_valendo_com_transporte_injetado(tmp_path):
    def tratar(req):
        if req.url.path.endswith("package_show"):
            return httpx.Response(200, json={"result": {"resources": [{"url": "https://exemplo.invalido/sinistros_01-2026.csv"}]}})
        return httpx.Response(200, content=b"")

    with pytest.raises(ValueError, match="fora dos hosts"):
        f.coletar(HOJE, tmp_path, transporte=httpx.MockTransport(tratar))
