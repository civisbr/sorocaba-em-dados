# tests/test_infodengue.py
import json
from datetime import date

import httpx
import pytest

from scripts import fetch_infodengue as f
from scripts.build_infodengue import DIAS_DESATUALIZADO, construir
from scripts.fetch_infodengue import CAMPOS, csv_texto

HOJE = date(2026, 10, 11)


def linha(se, casos=5, nivel=1, ini=1790467200000):
    return {"SE": se, "data_iniSE": ini, "casos": casos, "casos_est": 7.0, "casos_est_min": 3, "casos_est_max": 20,
            "nivel": nivel, "p_inc100k": 1.5, "Rt": 1.1, "versao_modelo": "2026-10-07", "notif_accum_year": 999999}


def transporte(por_doenca):
    def tratar(req: httpx.Request) -> httpx.Response:
        d = req.url.params["disease"]
        return httpx.Response(200, json=por_doenca.get(d, []))
    return httpx.MockTransport(tratar)


def test_normalizar_converte_epoch_e_ignora_notif_accum_year():
    r = f.normalizar(linha(202638))
    assert r == {"se": 202638, "data_inicio": "2026-09-27", "casos": 5, "casos_est": 7.0, "casos_est_min": 3, "casos_est_max": 20,
                 "nivel": 1, "p_inc100k": 1.5, "rt": 1.1}


@pytest.mark.parametrize("ruim", [{"nivel": 0}, {"nivel": 5}, {"SE": 2026}, {"SE": "x"}, {"casos": None}, {"SE": 202699}, {"SE": 202600},
                                  {"casos_est": float("nan")}, {"casos_est": float("inf")}, {"casos_est": "7"}, {"p_inc100k": -1}, {"Rt": float("inf")},
                                  {"casos_est_min": 10, "casos_est": 7.0}, {"data_iniSE": "x"}, {"data_iniSE": 10**20}])
def test_normalizar_rejeita_linha_invalida(ruim):
    with pytest.raises(ValueError):
        f.normalizar({**linha(202638), **ruim})


def test_coleta_grava_csv_e_manifesto_sem_notif_accum_year(tmp_path):
    t = transporte({"dengue": [linha(202637), linha(202638)], "chikungunya": [linha(202638)]})
    assert f.coletar(HOJE, tmp_path, transporte=t) == ["dengue", "chikungunya"]
    assert "notif_accum" not in (tmp_path / "dengue.csv").read_text(encoding="utf-8")
    man = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))
    assert man["doencas"]["dengue"]["ultima_se"] == 202638 and len(man["doencas"]["dengue"]["sha256_csv"]) == 64
    assert "zika" not in man["doencas"]  # sem linhas: não grava


def test_dengue_vazia_aborta_sem_gravar(tmp_path):
    with pytest.raises(ValueError, match="dengue"):
        f.coletar(HOJE, tmp_path, transporte=transporte({}))
    assert not (tmp_path / "dengue.csv").exists()


def test_serie_que_encolhe_aborta_e_preserva_arquivo(tmp_path):
    f.coletar(HOJE, tmp_path, transporte=transporte({"dengue": [linha(202637), linha(202638)]}))
    antes = (tmp_path / "dengue.csv").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="encolheu"):
        f.coletar(HOJE, tmp_path, transporte=transporte({"dengue": [linha(202638)]}))
    assert (tmp_path / "dengue.csv").read_text(encoding="utf-8") == antes


def test_host_fora_da_lista_e_barrado(tmp_path):
    def tratar(req):
        return httpx.Response(302, headers={"location": "https://exemplo.invalido/x"})
    with pytest.raises(ValueError, match="fora"):
        f.coletar(HOJE, tmp_path, transporte=httpx.MockTransport(tratar))




def _raw(tmp_path, series, verificado="2026-10-11"):
    man = {"doencas": {}, "fonte": "x", "verificado_em": verificado}
    for d, linhas in series.items():
        (tmp_path / f"{d}.csv").write_text(csv_texto(linhas), encoding="utf-8")
        man["doencas"][d] = {"n_semanas": len(linhas), "ultima_se": linhas[-1]["se"], "versao_modelo": "2026-10-07", "sha256_csv": __import__("hashlib").sha256(csv_texto(linhas).encode("utf-8")).hexdigest()}
    (tmp_path / "manifesto.json").write_text(json.dumps(man), encoding="utf-8")
    return tmp_path


def _l(se, ini, casos=3, nivel=1):
    return {"se": se, "data_inicio": ini, "casos": casos, "casos_est": 5.0, "casos_est_min": 1, "casos_est_max": 9, "nivel": nivel, "p_inc100k": 0.4, "rt": 1.0}


def test_build_deterministico_e_marca_estimativa(tmp_path):
    raw = _raw(tmp_path, {"dengue": [_l(202638, "2026-09-20"), _l(202639, "2026-09-27")]})
    a, b = construir(raw), construir(raw)
    assert a.model_dump_json() == b.model_dump_json()
    assert a.qualidade.flag.value == "estimativa"
    semanal = [r for r in a.dados if r["recorte"] == "semanal"]
    assert [(r["ano"], r["semana"]) for r in semanal] == [(2026, 38), (2026, 39)]


def test_zika_parado_vira_desatualizado_e_dengue_recente_e_atual(tmp_path):
    raw = _raw(tmp_path, {"dengue": [_l(202639, "2026-09-27")], "zika": [_l(202407, "2024-02-11")]})
    sit = {r["grupo"]: r for r in construir(raw).dados if r["recorte"] == "situacao"}
    assert sit["dengue"]["categoria"] == "atual" and sit["zika"]["categoria"] == "desatualizado"
    assert sit["zika"]["n"] > DIAS_DESATUALIZADO


def test_build_sem_dengue_da_erro(tmp_path):
    raw = _raw(tmp_path, {"zika": [_l(202407, "2024-02-11")]})
    with pytest.raises(ValueError, match="dengue"):
        construir(raw)


def _env(semanas, doenca="dengue", categoria="atual"):
    dados = [{"recorte": "semanal", "grupo": doenca, "se": se, "ano": se // 100, "semana": se % 100, "data_inicio": ini, "casos": c, "casos_est": c * 2.0,
              "est_min": c, "est_max": c * 3, "nivel": n, "inc100k": 1.0, "rt": 1.0} for se, ini, c, n in semanas]
    dados.append({"recorte": "situacao", "grupo": doenca, "se": semanas[-1][0], "categoria": categoria, "n": 10})
    return {"dados": dados}


def test_contexto_soma_8_semanas_e_compara_com_ano_anterior():
    from scripts.render import contexto_saude_doencas
    sem = [(202500 + w, f"2025-{(w - 1) // 5 + 1:02d}-01", 10, 1) for w in range(20, 41)] + [(202600 + w, f"2026-{(w - 1) // 5 + 1:02d}-01", 20, 2) for w in range(20, 41)]
    d = contexto_saude_doencas(_env(sem))["doencas"][0]
    assert d["casos_8s"] == 160 and d["nivel"] == 2 and d["nivel_rotulo"].startswith("Amarelo")
    assert d["comparacao"][0] == {"ano": 2026, "casos": 160} and {"ano": 2025, "casos": 80} in d["comparacao"]


def test_comparacao_omitida_quando_janela_cruza_a_virada_do_ano():
    from scripts.render import contexto_saude_doencas
    sem = [(202600 + w, "2026-01-05", 4, 1) for w in range(1, 6)]
    assert contexto_saude_doencas(_env(sem))["doencas"][0]["comparacao"] is None


def test_desatualizada_vai_para_sem_dado_recente():
    from scripts.render import contexto_saude_doencas
    ctx = contexto_saude_doencas(_env([(202407, "2024-02-11", 0, 1)], doenca="zika", categoria="desatualizado"))
    assert ctx["doencas"] == [] and ctx["sem_dado_recente"][0]["nome"] == "zika"


def test_render_gera_pagina_de_saude_com_nivel_em_texto(tmp_path):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "scripts.render", "--saida", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    html = (tmp_path / "saude" / "index.html").read_text(encoding="utf-8")
    assert "Como estão a dengue e a chikungunya" in html and "Ver os valores por semana" in html
    assert any(n in html for n in ("Verde", "Amarelo", "Laranja", "Vermelho"))
    assert (tmp_path / "data" / "saude_doencas.json").exists()
    assert "Saúde" in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_resposta_com_nan_no_json_e_rejeitada(tmp_path):
    def tratar(req):
        return httpx.Response(200, content=b'[{"SE": 202638, "data_iniSE": 1790467200000, "casos": 1, "casos_est": NaN, "casos_est_min": 1, "casos_est_max": 2, "nivel": 1, "p_inc100k": 1.0, "Rt": 1.0}]')
    with pytest.raises(ValueError):
        f.coletar(HOJE, tmp_path, transporte=httpx.MockTransport(tratar))
    assert not (tmp_path / "dengue.csv").exists()


def test_versao_do_modelo_fora_do_formato_e_ignorada(tmp_path):
    ruim = {**linha(202638), "versao_modelo": "<script>"}
    f.coletar(HOJE, tmp_path, transporte=transporte({"dengue": [ruim]}))
    assert json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))["doencas"]["dengue"]["versao_modelo"] is None


def test_virada_de_ano_nao_encolhe_a_janela_de_coleta(tmp_path):
    pedidos = []

    def tratar(req):
        pedidos.append(req.url.params["ey_start"])
        return httpx.Response(200, json=[linha(202639, ini=1790467200000)] if req.url.params["disease"] != "zika" else [])
    f.coletar(date.today(), tmp_path, transporte=httpx.MockTransport(tratar))
    assert set(pedidos) == {str(f.ANO_INICIAL)}


def test_fonte_parada_aborta_a_coleta(tmp_path):
    antiga = linha(202401, ini=1704067200000)
    with pytest.raises(ValueError, match="parada"):
        f.coletar(HOJE, tmp_path, transporte=transporte({"dengue": [antiga]}))
    assert not (tmp_path / "dengue.csv").exists()


def test_build_recusa_csv_alterado_a_mao(tmp_path):
    raw = _raw(tmp_path, {"dengue": [_l(202639, "2026-09-27")]})
    (raw / "dengue.csv").write_text((raw / "dengue.csv").read_text(encoding="utf-8").replace(";3;", ";9;"), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        construir(raw)


def test_janela_de_8_semanas_em_janeiro_pega_as_ultimas_8_linhas():
    from scripts.render import contexto_saude_doencas
    sem = [(202552 + 0, "2025-12-21", 3, 1)] + [(202600 + w, "2026-01-05", 3, 1) for w in range(1, 6)] + [(202545, "2025-11-02", 3, 1), (202546, "2025-11-09", 3, 1), (202547, "2025-11-16", 3, 1)]
    sem.sort()
    assert contexto_saude_doencas(_env(sem))["doencas"][0]["casos_8s"] == 24


def test_aviso_quando_a_coleta_esta_velha():
    from scripts.render import contexto_saude_doencas
    env = _env([(202639, "2026-09-27", 3, 1)])
    env["fonte"] = {"acesso_em": "2026-08-01"}
    assert contexto_saude_doencas(env, date(2026, 10, 11))["dias_sem_coleta"] == 71
    assert contexto_saude_doencas(env, date(2026, 8, 5))["dias_sem_coleta"] is None


def test_comparacao_na_semana_53_usa_a_52_nos_anos_sem_ela():
    from scripts.render import contexto_saude_doencas
    sem = [(202400 + w, "2024-06-01", 5, 1) for w in range(40, 53)] + [(202500 + w, "2025-06-01", 7, 1) for w in range(40, 54)]
    comp = contexto_saude_doencas(_env(sem))["doencas"][0]["comparacao"]
    assert {"ano": 2025, "casos": 56} in comp and {"ano": 2024, "casos": 40} in comp


def test_build_recusa_csv_so_com_cabecalho(tmp_path):
    raw = _raw(tmp_path, {"dengue": [_l(202639, "2026-09-27")]})
    cab = "se;data_inicio;casos;casos_est;casos_est_min;casos_est_max;nivel;p_inc100k;rt\n"
    (raw / "dengue.csv").write_text(cab, encoding="utf-8")
    man = json.loads((raw / "manifesto.json").read_text(encoding="utf-8"))
    man["doencas"]["dengue"]["sha256_csv"] = __import__("hashlib").sha256(cab.encode("utf-8")).hexdigest()
    (raw / "manifesto.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(ValueError, match="sem semanas"):
        construir(raw)


def test_item_que_nao_e_objeto_e_rejeitado():
    with pytest.raises(ValueError):
        f.normalizar([1, 2])
