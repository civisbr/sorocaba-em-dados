"""Comportamento do mapa interativo em navegadores reais (Chromium, Firefox, WebKit). Pulado se o Playwright ou o navegador não estiver instalado.

Para rodar: uv run --no-project --with playwright --with pytest --with-requirements ... ou, mais simples,
`uv run --with playwright pytest tests/test_mapa_navegador.py` depois de `playwright install chromium firefox webkit`.
"""

import functools
import http.server
import subprocess
import sys
import threading

import pytest

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def url(tmp_path_factory):
    saida = tmp_path_factory.mktemp("site")
    r = subprocess.run([sys.executable, "-m", "scripts.render", "--saida", str(saida)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(saida))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


@pytest.fixture(scope="module", params=["chromium", "firefox", "webkit"])
def navegador(request):
    with sync_api.sync_playwright() as p:
        try:
            nav = getattr(p, request.param).launch()
        except Exception as e:  # navegador não instalado
            pytest.skip(f"{request.param} indisponível: {str(e)[:60]}")
        yield nav
        nav.close()


@pytest.fixture(scope="module")
def pagina_nova(navegador):
    ctx = navegador.new_context(viewport={"width": 1280, "height": 900})
    return lambda: ctx.new_page()


def _abrir(pagina_nova, url, caminho):
    pg = pagina_nova()
    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(url + caminho)
    pg.wait_for_selector(".ms-svg")
    return pg, erros


def test_saude_marcadores_selecao_filtro_e_bairro(pagina_nova, url):
    pg, erros = _abrir(pagina_nova, url, "hospitais/")
    assert pg.locator(".ms-u").count() >= 40
    pg.locator(".ms-u[data-grupo=hospital]").first.dispatch_event("click")
    assert pg.locator(".ms-selecionada h3").inner_text() != "Ponto selecionado"
    pg.locator('.ms-filtro input[value="ubs"]').uncheck()
    assert pg.locator(".ms-u.g-ubs.ms-off").count() == pg.locator(".ms-u.g-ubs").count() > 0
    pg.fill(".ms-bairro", "Vila Hortência")
    pg.click(".ms-bairro-form button")
    pg.wait_for_function("document.querySelector('.ms-msg').textContent.includes('Posição marcada')")
    assert pg.locator(".ms-prox-b").count() >= 1
    assert not erros


def test_teclado_uma_parada_de_tab_e_setas(pagina_nova, url):
    pg, _ = _abrir(pagina_nova, url, "hospitais/")
    tabs = pg.evaluate("Array.from(document.querySelectorAll('.ms-u')).filter(u => u.getAttribute('tabindex') === '0').length")
    assert tabs == 1
    pg.locator(".ms-u").first.focus()
    pg.keyboard.press("ArrowRight")
    assert pg.evaluate("document.activeElement !== document.querySelector('.ms-u')")


def test_celulas_de_calor_tem_tamanho(pagina_nova, url):
    pg, erros = _abrir(pagina_nova, url, "seguranca/")
    caixa = pg.evaluate("(() => { const b = document.querySelector('.ms-c:not(.ms-off)').getBBox(); return [b.width, b.height]; })()")
    assert caixa[0] > 5 and caixa[1] > 5
    assert not erros


def test_escolas_pontos_do_json_filtro_de_etapa_e_sem_unidades_restritas(pagina_nova, url):
    pg, erros = _abrir(pagina_nova, url, "escolas/")
    pg.wait_for_function("document.querySelectorAll('.ms-u').length > 100")
    total = pg.locator(".ms-u").count()
    assert not pg.evaluate("Array.from(document.querySelectorAll('.ms-u')).some(u => /penitenci|socioeduc/i.test(u.dataset.nome))")
    for etapa in ("infantil", "iniciais", "finais", "eja", "outras"):
        pg.locator(f'.ms-filtro input[value="{etapa}"]').uncheck()
    visiveis = pg.evaluate("Array.from(document.querySelectorAll('.ms-u')).filter(u => !u.classList.contains('ms-off')).length")
    assert 0 < visiveis < total  # só ensino médio
    assert not erros


def test_mapa_sem_js_mostra_conteudo_e_esconde_controles(navegador, url):
    pg = navegador.new_context(java_script_enabled=False).new_page()
    pg.goto(url + "hospitais/")
    assert pg.locator(".ms-u").count() >= 40 and not pg.locator(".ms-filtro").is_visible() and not pg.locator(".ms-local").is_visible()


def test_seguranca_tipo_de_ocorrencia_e_registros_perto_do_bairro(pagina_nova, url):
    pg, erros = _abrir(pagina_nova, url, "seguranca/")
    visiveis = lambda: pg.evaluate("[...new Set([...document.querySelectorAll('.ms-c')].filter(c => !c.classList.contains('ms-off')).map(c => c.dataset.grupo))]")
    assert visiveis() == ["roubos"]
    pg.fill(".ms-bairro", "Vila Hortência")
    pg.click(".ms-bairro-form button")
    pg.wait_for_function("document.querySelector('.ms-proximas') && !document.querySelector('.ms-proximas').hidden")
    assert "Roubos:" in pg.locator(".ms-proximas").inner_text()
    pg.locator('.ms-filtro input[value="furtos"]').check()
    assert visiveis() == ["furtos"] and "Furtos:" in pg.locator(".ms-proximas").inner_text()
    assert not erros
