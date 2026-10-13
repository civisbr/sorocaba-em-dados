import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from scripts import build_artesp, fetch_artesp
from scripts.fetch_artesp import coletar

CHAVE = "chave_de_teste_0123456789abcdef_fedcba9876543210"
SORO = [{"cod_ibge": "3552205", "nome": "Sorocaba"}]


def oc(slug, data, classe="Acidente", via="SP 270", km=95.3, tipo="Colisão", fim=None, municipios=SORO):
    return {"slug": slug, "classe": classe, "subclasse_ac": tipo, "rodovia": {"slug": "sp-270", "nome": via}, "municipios": municipios, "km_inicial": km,
            "dt_hr_oc": f"{data}T10:00:00", "dinamica_oc": "relato livre com placa ABC1D23", "lat": -23.4, "lng": -47.4, "fim": fim or []}


def transporte(itens_por_ano, vistos=None):
    def h(req: httpx.Request) -> httpx.Response:
        if vistos is not None:
            vistos.append(req)
        ini = req.url.params["filtro_data_inicio"]
        itens = itens_por_ano.get(ini[:4], [])
        off = int(req.url.params["offset"])
        pg = itens[off:off + 100]
        return httpx.Response(200, json={"meta": {"count": len(itens), "next": "x" if off + 100 < len(itens) else None}, "results": pg})
    return httpx.MockTransport(h)


def dados(n=4):
    return {a: [oc(f"oc{a}{i}", f"{a}-03-1{i}", fim=[{"tipo": "FATAL", "qtd": 1}, {"tipo": "LEVE", "qtd": 2}, {"tipo": "ILESA", "qtd": 5}]) for i in range(n)] for a in ("2022", "2023", "2024", "2025", "2026")}


def test_agrega_sem_texto_livre_nem_ponto(tmp_path):
    vistos = []
    coletar(CHAVE, date.today(), tmp_path, transporte(dados(), vistos))
    tudo = "".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file())
    assert "ABC1D23" not in tudo and "-23.4" not in tudo and CHAVE not in tudo
    assert all(r.headers["authorization"] == f"Api-Key {CHAVE}" for r in vistos)
    assert (tmp_path / "2024" / "mensal.csv").read_text(encoding="utf-8").splitlines()[1] == "2024;3;Acidente;4;4;8"


def test_suprime_rodovia_e_trecho_raros(tmp_path):
    d = dados(2)
    coletar(CHAVE, date.today(), tmp_path, transporte(d))
    assert (tmp_path / "2024" / "rodovia.csv").read_text(encoding="utf-8").strip().splitlines() == ["ano;rodovia;acidentes"]
    assert (tmp_path / "2024" / "trecho.csv").read_text(encoding="utf-8").strip().splitlines() == ["ano;rodovia;km_ini;acidentes"]


def test_descarta_fora_do_municipio_e_nome_estranho(tmp_path):
    d = dados(4)
    d["2024"].append(oc("x1", "2024-04-01", municipios=[{"cod_ibge": "3509502"}]))
    d["2024"].append(oc("x2", "2024-04-02", via="=HYPERLINK(1)"))
    coletar(CHAVE, date.today(), tmp_path, transporte(d))
    man = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))
    assert man["anos"]["2024"]["descartadas"] == {"fora_do_municipio": 1, "rodovia_fora_do_padrao": 1}
    assert "HYPERLINK" not in (tmp_path / "2024" / "rodovia.csv").read_text(encoding="utf-8")


def test_contagem_divergente_aborta_sem_gravar(tmp_path):
    def h(req):
        return httpx.Response(200, json={"meta": {"count": 5, "next": None}, "results": [oc("a", "2025-01-01")]})
    with pytest.raises(ValueError, match="anunciou 5"):
        coletar(CHAVE, date.today(), tmp_path, httpx.MockTransport(h))
    assert not (tmp_path / "manifesto.json").exists()


def test_cota_esgotada_nao_repete(tmp_path):
    chamadas = []
    def h(req):
        chamadas.append(1)
        return httpx.Response(429)
    with pytest.raises(fetch_artesp.LimiteExcedido):
        coletar(CHAVE, date.today(), tmp_path, httpx.MockTransport(h))
    assert len(chamadas) == 1


def test_chave_invalida_nao_chega_a_rede(tmp_path):
    with pytest.raises(ValueError, match="ARTESP_API_KEY"):
        coletar("curta", date.today(), tmp_path, httpx.MockTransport(lambda r: httpx.Response(500)))


def test_erro_nao_vaza_a_chave(tmp_path):
    with pytest.raises(fetch_artesp.ErroHTTP) as e:
        coletar(CHAVE, date.today(), tmp_path, httpx.MockTransport(lambda r: httpx.Response(401)))
    assert CHAVE not in str(e.value)


def test_pagina_varias_vezes(tmp_path):
    d = dados(0)
    d["2025"] = [oc(f"p{i}", "2025-05-05") for i in range(150)]
    coletar(CHAVE, date.today(), tmp_path, transporte(d))
    assert (tmp_path / "2025" / "mensal.csv").read_text(encoding="utf-8").splitlines()[1] == "2025;5;Acidente;150;0;0"


def test_build_completa_meses_sem_registro_e_ignora_mes_aberto(tmp_path):
    coletar(CHAVE, date.today(), tmp_path / "raw", transporte(dados()))
    man = tmp_path / "raw" / "manifesto.json"
    m = json.loads(man.read_text(encoding="utf-8"))
    m["verificado_em"] = "2026-10-13"
    man.write_text(json.dumps(m), encoding="utf-8")
    env = build_artesp.construir(tmp_path / "raw")
    mensal = [r for r in env.dados if r["recorte"] == "mensal"]
    assert (mensal[0]["ano"], mensal[0]["mes"]) == (2021, 12) and (mensal[-1]["ano"], mensal[-1]["mes"]) == (2026, 9)
    assert len(mensal) == 58 and any(r["n"] == 0 for r in mensal)
    assert any(r["recorte"] == "trecho" and r["km"] == 95 for r in env.dados)


def test_host_fora_da_lista_e_http_sao_recusados():
    for url in ("https://outro.exemplo/rodovias/api/ocorrencias/", "http://ccm.artesp.sp.gov.br/rodovias/api/ocorrencias/"):
        with pytest.raises(ValueError, match="fora do host"):
            fetch_artesp.so_host_confiavel(httpx.Request("GET", url))
    fetch_artesp.so_host_confiavel(httpx.Request("GET", fetch_artesp.URL))


def test_403_por_ip_vira_erro_sem_a_chave(tmp_path):
    with pytest.raises(fetch_artesp.ErroHTTP) as e:
        coletar(CHAVE, date.today(), tmp_path, httpx.MockTransport(lambda r: httpx.Response(403)))
    assert e.value.status == 403 and CHAVE not in str(e.value)


def test_ano_corrente_sem_rodovia_tipo_trecho_e_tipo_livre_vira_outros(tmp_path):
    d = dados(4)
    d["2024"] += [oc(f"t{i}", "2024-06-01", tipo="relato com dado pessoal") for i in range(3)]
    d["2026"] = [oc(f"c{i}", "2026-02-02") for i in range(5)]
    coletar(CHAVE, date.today(), tmp_path, transporte(d))
    assert "Outros" in (tmp_path / "2024" / "tipo.csv").read_text(encoding="utf-8")
    assert "pessoal" not in (tmp_path / "2024" / "tipo.csv").read_text(encoding="utf-8")
    for t in ("rodovia", "tipo", "trecho"):
        assert len((tmp_path / "2026" / f"{t}.csv").read_text(encoding="utf-8").splitlines()) == 1


def test_resposta_com_formato_errado_e_pagina_gigante_sao_recusadas(tmp_path):
    with pytest.raises(ValueError):
        coletar(CHAVE, date.today(), tmp_path, httpx.MockTransport(lambda r: httpx.Response(200, json=[1])))
    grande = {"meta": {"count": 101, "next": None}, "results": [oc(f"g{i}", "2025-01-01") for i in range(101)]}
    with pytest.raises(ValueError):
        coletar(CHAVE, date.today(), tmp_path, httpx.MockTransport(lambda r: httpx.Response(200, json=grande)))


def test_hifen_na_rodovia_e_tipos_de_vitima_novos_sao_contados(tmp_path):
    d = dados(4)
    d["2024"].append(oc("h1", "2024-04-01", via="SP-270", fim=[{"tipo": "OBITO", "qtd": 1}]))
    d["2024"].append(oc("h2", "2024-04-02", via="SP 27O!"))
    coletar(CHAVE, date.today(), tmp_path, transporte(d))
    desc = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))["anos"]["2024"]["descartadas"]
    assert desc == {"vitima_tipo_desconhecido": 1, "rodovia_fora_do_padrao": 1}


def test_evento_de_outro_ano_nao_conta_duas_vezes(tmp_path):
    d = dados(4)
    d["2025"].append(oc("e1", "2024-12-31"))
    coletar(CHAVE, date.today(), tmp_path, transporte(d))
    assert json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))["anos"]["2025"]["descartadas"] == {"fora_da_janela": 1}
