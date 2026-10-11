# tests/test_infodengue.py
import json
from datetime import date

import httpx
import pytest

from scripts import fetch_infodengue as f

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


@pytest.mark.parametrize("ruim", [{"nivel": 0}, {"nivel": 5}, {"SE": 2026}, {"SE": "x"}, {"casos": None}])
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
