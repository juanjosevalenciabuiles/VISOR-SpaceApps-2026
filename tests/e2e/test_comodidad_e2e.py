"""Comodidad visual en el navegador: sugerencias al escribir, coordenadas, y lo técnico plegado."""
import pytest

from conftest import Servidor, preparar_datos


@pytest.fixture(scope="module")
def servidor_com(tmp_path_factory):
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("com") / "data"), {"VISOR_REGION_MODE": "CO"})
    yield s
    s.cerrar()


def _campo(p):
    return p.page.locator(".st-key-lugar_texto input").first


def test_sugerencias_mientras_se_escribe(abrir, servidor_com):
    p = abrir(url=servidor_com.url)
    assert not p.visible("linea_temporal"), "sin resultado, la línea temporal no ocupa sitio"
    campo = _campo(p)
    campo.click()
    campo.type("chigo", delay=40)
    p.page.wait_for_selector('[role="option"]:has-text("Chigorodó, Antioquia, Colombia")', timeout=8000)
    opciones = p.page.locator('[role="option"]').all_inner_texts()
    assert not any("Tokio" in o or "Nairobi" in o for o in opciones)
    v = p.vista()
    p.page.locator('[role="option"]:has-text("Chigorodó, Antioquia, Colombia")').first.click()
    p.page.wait_for_selector(".mc-resultado:has-text('Chigorodó, Antioquia, Colombia')", timeout=10000)
    p.esperar(1200)
    assert p.vista() != v, "elegir la sugerencia lleva el mapa allí"
    assert p.capas_resultado() == [], "buscar no dibuja ni analiza nada"
    # Coordenadas escritas: Enter las busca tal cual.
    campo = _campo(p)
    campo.click()
    campo.fill("6.25, -75.57")
    p.esperar(500)
    campo.press("Enter")
    p.page.wait_for_selector(".mc-resultado:has-text('6.2500, -75.5700')", timeout=10000)
    assert not p.errores


def test_lo_tecnico_queda_plegado_y_analizar_a_la_vista(abrir, servidor_com):
    p = abrir(url=servidor_com.url)
    p.confirmar_zona()
    etiquetas = p.page.locator('.st-key-panel_sar [role="tab"]').all_inner_texts()
    assert etiquetas == ["1 · Zona", "2 · Imágenes", "3 · Análisis", "4 · Resultado"]
    p.pestana_sar(1)
    p.clic("sar_buscar")
    p.pestana_sar(2)
    boton = p.page.locator(".st-key-sar_analizar button").first
    boton.wait_for(state="visible", timeout=15000)
    assert p.page.locator(".st-key-sar_avanzado details").first.get_attribute("open") is None, "ajustes plegados"
    panel = p.page.locator(".st-key-panel_sar").first.bounding_box()
    caja = boton.bounding_box()
    assert caja["y"] + caja["height"] <= panel["y"] + panel["height"], "«Analizar» se ve sin desplazarse"
    assert p.analizar() == "APTO"
    detalles = p.page.locator("#res-detalles-tecnicos").first
    assert detalles.get_attribute("open") is None
    info = p.page.locator(".st-key-panel_info").first.inner_text()
    assert "data/analisis" not in info and p.page.locator(".st-key-panel_info .mc-leyenda-res").first.is_visible()
    assert p.visible("linea_temporal"), "con dos fechas declaradas la línea temporal aparece"
    assert not p.errores
