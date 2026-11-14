"""ECO (esquina inferior derecha) y la ficha del lugar en el navegador, sin red externa."""
import pytest

from conftest import Servidor, preparar_datos


@pytest.fixture(scope="module")
def servidor_eco(tmp_path_factory):
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("eco") / "data"), {"VISOR_REGION_MODE": "CO"})
    yield s
    s.cerrar()


def _se_cruzan(a, b) -> bool:
    return not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])


def _reproduce(p) -> bool:
    p.page.wait_for_function("()=>{const v=document.querySelector('#eco-avatar video');"
                             "return v && v.readyState>=2 && !v.paused && v.currentTime>0}", timeout=15000)
    return True


def test_eco_saluda_y_reproduce_su_clip(abrir, servidor_eco):
    p = abrir(url=servidor_eco.url)
    avatar = p.page.locator("#eco-avatar").first
    assert avatar.get_attribute("data-clip") == "saludo" and _reproduce(p)
    v = p.page.evaluate("()=>{const v=document.querySelector('#eco-avatar video');"
                        "return {src:v.currentSrc, muted:v.muted, loop:v.loop}}")
    assert v["muted"] and v["loop"] and "/app/static/eco/eco_01_saludo." in v["src"]
    assert p.page.request.get(servidor_eco.url + "/app/static/eco/eco_04_listo.webm").status == 200
    caja = avatar.bounding_box()
    vista = p.page.viewport_size
    assert caja["x"] > vista["width"] * 0.75 and caja["y"] > vista["height"] * 0.6, "esquina inferior derecha"
    assert not _se_cruzan(p.page.locator("#eco-mensaje").first.bounding_box(),
                          p.page.locator(".st-key-panel_info").first.bounding_box())
    assert "Busca un lugar de Colombia" in p.page.locator("#eco-mensaje").first.inner_text()
    assert "Cómo empezar" in p.texto("panel_info")
    assert not p.errores


def test_ficha_del_lugar_y_eco_siguen_la_zona(abrir, servidor_eco):
    p = abrir(url=servidor_eco.url)
    p.confirmar_zona()
    p.page.wait_for_selector('#eco-avatar[data-clip="enfoque"]', timeout=15000)
    assert "Chigorodó" in p.page.locator("#eco-mensaje").first.inner_text()
    ficha = p.page.locator("#ctx-ficha").first
    assert ficha.is_visible() and "Chigorodó" in ficha.inner_text() and "Municipio · Antioquia, Colombia" in ficha.inner_text()
    assert p.page.locator("#ctx-foto").first.get_attribute("data-origen") == "satelite"   # sin red: vista satelital
    assert "km²" in p.page.locator("#ctx-chips").first.inner_text()
    p.clic("cerrar_sar")
    assert not p.visible("panel_sar")
    p.clic("ctx_analizar")                                 # el botón de la ficha abre el análisis
    assert p.visible("panel_sar")
    p.pestana_sar(1)
    p.clic("sar_buscar")
    p.pestana_sar(2)
    assert p.analizar() == "APTO"
    p.page.wait_for_selector('#eco-avatar[data-clip="listo"]', timeout=20000)
    assert "no una inundación confirmada" in p.page.locator("#eco-mensaje").first.inner_text()
    assert not p.errores


def test_eco_se_oculta_y_vuelve(abrir, servidor_eco):
    p = abrir(url=servidor_eco.url)
    p.clic("eco_ocultar")
    assert p.page.locator("#eco-avatar").count() == 0
    p.clic("eco_mostrar")
    assert p.page.locator("#eco-avatar").count() == 1
    assert not p.errores


def test_eco_en_el_celular_no_tapa_el_panel(abrir, servidor_eco):
    p = abrir(390, 844, movil=True, url=servidor_eco.url)
    p.confirmar_zona()
    p.page.wait_for_selector('#eco-avatar[data-clip="enfoque"]', timeout=15000)
    eco = p.page.locator(".st-key-eco").first.bounding_box()
    panel = p.page.locator(".st-key-panel_info").first
    if panel.is_visible():
        assert not _se_cruzan(eco, panel.bounding_box())
    assert eco["x"] + eco["width"] <= 391
    assert not p.errores
