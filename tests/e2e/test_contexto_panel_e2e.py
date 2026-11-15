"""Panel derecho «Conozcamos esta zona» en el navegador (Modo Colombia, sin red: consultas externas
desactivadas y declaradas como tales; las reales están en test_capturas_red.py)."""
import pytest

from conftest import Servidor, preparar_datos


@pytest.fixture(scope="module")
def servidor_ctx(tmp_path_factory):
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("ctx") / "data"), {"VISOR_REGION_MODE": "CO"})
    yield s
    s.cerrar()


def test_contexto_aparece_al_confirmar_y_cambia_tras_analizar(abrir, servidor_ctx):
    p = abrir(url=servidor_ctx.url)
    assert "Selecciona una zona para conocer qué sucede allí" in p.texto("panel_info")
    p.clic("cerrar_info")                                 # aunque el panel esté cerrado…
    assert not p.page.locator(".st-key-panel_info").first.is_visible()
    p.confirmar_zona()                                    # …al confirmar la zona se abre solo
    panel = p.page.locator(".st-key-panel_info").first
    assert panel.is_visible()
    texto = p.texto("panel_info")
    assert "Conozcamos esta zona" in texto and "Está en Chigorodó" in texto and "km²" in texto
    assert "Aún no has realizado un análisis" in texto and "Consulta externa desactivada" in texto
    assert p.page.locator("#ctx-ideam").count() == 1 and p.page.locator("#ctx-eonet").count() == 1
    p.pestana_sar(1)
    p.clic("sar_buscar")
    assert "fechas de las dos imágenes elegidas" in p.texto("panel_info")
    p.pestana_sar(2)
    assert p.analizar() == "APTO"
    texto = p.texto("panel_info")
    assert "Aún no has realizado un análisis" not in texto and "El resultado está abajo" in texto
    assert not p.errores


def test_contexto_en_el_celular(abrir, servidor_ctx):
    p = abrir(390, 844, movil=True, url=servidor_ctx.url)
    p.confirmar_zona()
    panel = p.page.locator(".st-key-panel_info").first
    caja = panel.bounding_box()
    assert panel.is_visible() and caja["y"] > 844 * 0.3, "hoja inferior: el mapa sigue siendo protagonista"
    assert "Conozcamos esta zona" in p.texto("panel_info")
    assert not p.errores
