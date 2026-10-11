import json
import re
from pathlib import Path

import pytest

from scripts.charts import barras_mensais, linhas, linhas_preco
from scripts.mapa import gerar
from scripts.render import RAIZ, renderizar, sinal

PUBLIC = RAIZ / "data" / "public"
MALHA = RAIZ / "data" / "raw" / "ibge" / "malha_3552205.geojson"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    saida = tmp_path_factory.mktemp("dist")
    renderizar(PUBLIC, saida)
    return saida


def test_renderizacao_deterministica(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    renderizar(PUBLIC, a)
    renderizar(PUBLIC, b)
    for p in a.rglob("*"):
        if p.is_file():
            assert p.read_bytes() == (b / p.relative_to(a)).read_bytes(), p


def test_paginas_esperadas(site):
    for rel in ("index.html", "emprego/index.html", "combustivel/index.html", "escolas/index.html", "sobre/index.html", "data/emprego.json"):
        assert (site / rel).exists(), rel


def test_titulos_com_topônimo(site):
    t = (site / "emprego/index.html").read_text(encoding="utf-8")
    assert "<title>Emprego em Sorocaba | Sorocaba em Dados</title>" in t


def test_numero_publicado_vem_do_json(site):
    env = json.loads((PUBLIC / "emprego.json").read_text(encoding="utf-8"))
    ultimo = [r for r in env["dados"] if r["recorte"] == "mensal"][-1]
    html = (site / "emprego/index.html").read_text(encoding="utf-8")
    assert sinal(ultimo["saldo"]) in html


def test_proveniencia_no_rodape_do_painel(site):
    html = (site / "emprego/index.html").read_text(encoding="utf-8")
    for trecho in ("Fonte", "Período de referência", "Coletado em", "emprego.json", "scripts/build_emprego.py"):
        assert trecho in html


def test_escolas_sem_ranking_e_com_ano_de_referencia(site):
    html = (site / "escolas/index.html").read_text(encoding="utf-8")
    env = json.loads((PUBLIC / "escolas.json").read_text(encoding="utf-8"))
    assert "Não há ranking" in html and f"Censo Escolar {env['dados'][0]['ano_censo']}" in html
    assert "municipals" not in html and "estaduals" not in html
    assert html.count('<li data-rede=') == len(env["dados"])
    for e in env["dados"][:3]:
        assert (site / "escolas" / e["co_inep"] / "index.html").exists()


def test_pagina_de_escola_mostra_traco_quando_sem_ideb(site):
    env = json.loads((PUBLIC / "escolas.json").read_text(encoding="utf-8"))
    sem = next(e for e in env["dados"] if all(v is None for k, v in e.items() if k.startswith("ideb_")))
    html = (site / "escolas" / sem["co_inep"] / "index.html").read_text(encoding="utf-8")
    assert "não tem IDEB publicado" in html


def test_filtro_de_escolas_fica_oculto_sem_js(site):
    assert 'id="escolas-filtro"' in (site / "escolas/index.html").read_text(encoding="utf-8")
    assert "[hidden]{display:none!important}" in (site / "style.css").read_text(encoding="utf-8")


def test_combustivel_usa_linguagem_de_amostra(site):
    html = (site / "combustivel/index.html").read_text(encoding="utf-8")
    assert "postos pesquisados" in html
    assert "mais barato de Sorocaba" not in html
    assert "combustivel.json" in html and (site / "data/combustivel.json").exists()


def test_sem_js_o_conteudo_existe(site):
    html = (site / "index.html").read_text(encoding="utf-8")
    assert 'id="busca-form" hidden' in html
    assert 'href="emprego/"' in html


def test_orcamento_de_peso_por_pagina(site):
    css, js = (site / "style.css").stat().st_size, (site / "app.js").stat().st_size
    for pagina in site.rglob("index.html"):
        assert pagina.stat().st_size + css + js < 150_000, pagina


def test_links_internos_resolvem(site):
    for pagina in site.rglob("index.html"):
        html = pagina.read_text(encoding="utf-8")
        for href in re.findall(r'href="([^"#:]+)"', html):
            if href.startswith(("http", "mailto")):
                continue
            alvo = (pagina.parent / href).resolve()
            assert alvo.exists() or (alvo / "index.html").exists(), f"{pagina}: {href}"


def test_mapa_usa_malha_oficial_e_centro_dentro_do_quadro():
    m = gerar(MALHA)
    assert m["caminho"].startswith("M") and m["caminho"].endswith("Z")
    assert 0 < m["centro_x"] < m["largura"] and 0 < m["centro_y"] < m["altura"]


def test_barras_com_saldos_mistos():
    g = barras_mensais([("a", 10), ("b", -5), ("c", 0)], {0: "a"})
    pos, neg = g["barras"][0], g["barras"][1]
    assert pos["positivo"] and not neg["positivo"]
    assert pos["y"] + pos["h"] == pytest.approx(g["zero"], abs=0.1)
    assert neg["y"] == pytest.approx(g["zero"], abs=0.1)


def test_linhas_escala_comeca_em_zero():
    g = linhas({"x": [100, 300], "y": [200, 50]}, {0: "a"})
    assert g["grade"][0]["valor"] == 0 and g["grade"][-1]["valor"] >= 300


def test_render_recusa_apagar_diretorio_alheio(tmp_path):
    alheio = tmp_path / "meus-arquivos"
    alheio.mkdir()
    (alheio / "importante.txt").write_text("não apague")
    with pytest.raises(SystemExit):
        renderizar(PUBLIC, alheio)
    assert (alheio / "importante.txt").exists()


def test_linhas_preco_eixo_cobre_os_dados():
    g = linhas_preco({"a": [5.74, 6.0], "b": [6.69, 6.5]}, {0: "x"})
    assert g["grade"][0]["valor"] <= 5.74 and g["grade"][-1]["valor"] >= 6.69


def test_orcamento_dos_recursos_do_mapa_de_saude(site):
    assert (site / "mapa-base.svg").stat().st_size < 260_000
    assert (site / "mapa-saude.js").stat().st_size < 20_000
    assert (site / "data" / "mapa-bairros.json").stat().st_size < 80_000


def test_identidade_visual_favicon_logo_e_fonte_propria(site):
    html = (site / "index.html").read_text(encoding="utf-8")
    for alvo in ("favicon.svg", "favicon-32.png", "apple-touch-icon.png", "logo-icone.svg", "fonts/orbitron-subset.woff2"):
        assert alvo in html and (site / alvo).exists(), alvo
    assert "font-src 'self'" in html and "fonts.googleapis" not in html and "fonts.gstatic" not in html
    assert (site / "fonts" / "OFL-Orbitron.txt").exists()
    for svg in ("favicon.svg", "logo-icone.svg"):
        assert "<script" not in (site / svg).read_text(encoding="utf-8")


def test_todo_asset_estatico_vai_para_a_saida(site):
    raiz = Path(__file__).resolve().parent.parent / "static"
    for arq in raiz.rglob("*"):
        if arq.is_file() and not arq.name.startswith("."):
            assert (site / arq.relative_to(raiz)).exists(), f"static/{arq.relative_to(raiz)} não é copiado para a saída"


def test_identidade_em_pagina_aninhada_e_csp_sem_terceiros(site):
    escola = next((site / "escolas").glob("*/index.html")).read_text(encoding="utf-8")
    for alvo in ("../../favicon.svg", "../../logo-icone.svg", "../../fonts/orbitron-subset.woff2"):
        assert alvo in escola, alvo
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', escola).group(1)
    assert not re.search(r"https?:|\*", csp)
