"""Modo Colombia en el navegador (servidor con VISOR_REGION_MODE=CO): CO-01…CO-09 y CO-12.

Teselas simuladas (sin red); catálogo ASF guardado y RTC sintéticos para el análisis de Chigorodó.
"""
import pytest

from conftest import Servidor, preparar_datos
from test_global_e2e import capa_contexto, elegir_fondo, fondos


@pytest.fixture(scope="module")
def servidor_co(tmp_path_factory):
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("co") / "data"), {"VISOR_REGION_MODE": "CO"})
    yield s
    s.cerrar()


def velo(p) -> dict:
    """Velo y contorno: trazos del panel propio, su color y si capturan el puntero."""
    return p.mapa.evaluate("""()=>{const pane=map.getPane('visor_velo'); if(!pane) return null;
        const t=[...pane.querySelectorAll('path')];
        return {trazos:t.length, contorno:t.filter(x=>(x.getAttribute('stroke')||'').toLowerCase()==='#2ee6c8').length,
                interactivos:t.filter(x=>x.classList.contains('leaflet-interactive')).length,
                puntero:getComputedStyle(pane).pointerEvents, z:+getComputedStyle(pane).zIndex}}""")


def buscar(p, consulta):
    if not p.page.locator(".st-key-lugar_texto input").first.is_visible():
        p.clic("btn_explorador")
    p.escribir("lugar_texto", consulta)
    p.clic("lugar_buscar")


def test_co01_co09_apertura_velo_y_cambio_de_fondo(abrir, servidor_co):
    p = abrir(url=servidor_co.url)
    assert "COLOMBIA · ÁREA DE ESTUDIO HABILITADA" in p.texto("barra_superior").upper()
    zoom, lat, lon = p.vista()
    assert zoom == 5 and abs(lat - 4.6) < 0.5 and abs(lon + 74.2) < 0.5, "centrado en Colombia"
    o, s, e, n = p.mapa.evaluate("()=>{const b=map.getBounds();return [b.getWest(),b.getSouth(),b.getEast(),b.getNorth()]}")
    assert o <= -81.74 and e >= -66.85 and s <= -4.23 and n >= 13.4, "se ve todo el país, San Andrés incluido"
    v = velo(p)
    assert v["trazos"] == 2 and v["contorno"] == 1 and v["interactivos"] == 0 and v["puntero"] == "none"
    assert v["z"] > 400, "por encima de ríos, vías y resultados"
    assert p.mapa.locator("#rotulo-fuera").inner_text().startswith("Fuera de Colombia")
    assert "MGN 2025, DANE" in p.mapa.locator(".visor-atribucion-limite").inner_text()
    assert p.capas_resultado() == [] and "SIN RESULTADO" in p.texto("barra_superior")
    # No se puede llevar el mapa lejos de Colombia: Leaflet recoloca la vista dentro de la extensión.
    p.mapa.evaluate("()=>map.setView([35.68,139.69],5,{animate:false})")
    p.page.wait_for_timeout(600)
    lat, lon = p.mapa.evaluate("()=>[map.getCenter().lat, map.getCenter().lng]")
    assert -8 <= lat <= 17 and -86 <= lon <= -62
    assert p.mapa.evaluate("()=>map.getMinZoom()") == 4
    # CO-09: cambiar fondo y activar ríos no quita el velo ni el zoom.
    p.mapa.evaluate("()=>map.setView([7.67,-76.68],9,{animate:false})")
    p.page.wait_for_timeout(800)
    zoom = p.vista()[0]
    for nombre in ("Calles", "Satélite", "Relieve"):
        elegir_fondo(p, nombre)
        assert len(fondos(p)) == 1 and velo(p)["contorno"] == 1 and p.vista()[0] == zoom
    capa_contexto(p, "hidrografia")
    assert velo(p)["trazos"] == 2 and "OpenStreetMap" in p.mapa.locator(".leaflet-control-attribution").inner_text() \
        or "Esri" in p.mapa.locator(".leaflet-control-attribution").inner_text()
    assert not p.errores


def test_co02_co04_co05_busqueda_y_coordenadas(abrir, servidor_co):
    p = abrir(url=servidor_co.url)
    assert "en Colombia" in p.page.locator(".st-key-lugar_texto input").first.get_attribute("placeholder")
    buscar(p, "Chigorodó")
    assert p.vista() == [11, 7.67, -76.68]
    buscar(p, "Providencia")
    p.page.locator(".st-key-lugar_ir_0 button").first.click()
    p.esperar()
    assert p.vista()[1:] == [13.35, -81.37]
    antes = p.vista()
    buscar(p, "Tokio")
    assert "no está en Colombia" in p.texto("panel_explorador") and p.vista() == antes
    # «Ir a…» con coordenadas de Quito: no navega y lo explica.
    p.page.locator(".st-key-popover_ir button").first.click()
    p.page.wait_for_timeout(400)
    p.escribir("ir_lat", "-0.18")
    p.escribir("ir_lon", "-78.47")
    p.clic("btn_ir")
    assert "fuera de Colombia" in p.page.locator("[data-testid=stPopoverBody]").inner_text()
    assert p.vista() == antes
    assert not p.errores


def test_co06_co07_co08_zona(abrir, servidor_co):
    p = abrir(url=servidor_co.url)
    p.mapa.evaluate("()=>map.setView([7.67,-76.68],11,{animate:false})")
    p.page.wait_for_timeout(800)
    p.clic("btn_sar")
    p.pestana_sar(0)
    # CO-06: un rectángulo dibujado en Chigorodó se confirma.
    p.dibujar_rectangulo(700, 380, 90, 80)
    p.clic("zona_usar_dibujo")
    assert "ZONA CONFIRMADA" in p.texto("panel_sar")
    # CO-07: por coordenadas cruzando la frontera con Panamá → rechazo explicado, la zona anterior se mantiene.
    p.confirmar_zona("-77.6", "7.8", "-77.0", "8.4")
    assert "sale del territorio colombiano" in p.texto("panel_sar")
    # CO-08 (vía de dibujo): un rectángulo que empieza SOBRE el velo se puede dibujar (el velo no captura
    # el puntero) pero no se confirma.
    p.mapa.evaluate("()=>map.setView([8.4,-77.6],9,{animate:false})")
    p.page.wait_for_timeout(800)
    p.dibujar_rectangulo(760, 330, 160, 140)
    assert p.mapa.evaluate("()=>{let n=0;map.eachLayer(l=>{if(l instanceof L.Rectangle)n++});return n}") >= 1
    texto = p.texto("panel_sar")
    assert "sale del territorio colombiano" in texto, "se rechaza al dibujar, con el motivo"
    assert p.page.locator(".st-key-zona_usar_dibujo button:visible").count() == 0, "no se ofrece confirmarla"
    assert not p.errores


def test_co12_chigorodo_completo_en_modo_colombia(abrir, servidor_co):
    p = abrir(url=servidor_co.url)
    p.confirmar_zona()
    p.pestana_sar(1)
    p.clic("sar_buscar")
    p.pestana_sar(2)
    assert p.analizar() == "APTO"
    assert len(p.capas_resultado()) == 1 and "ANÁLISIS DE ESTA SESIÓN" in p.texto("barra_superior")
    assert velo(p)["contorno"] == 1, "el resultado queda bajo el mismo velo/contorno"
    assert not p.errores


def test_co12_movil(abrir, servidor_co):
    p = abrir(390, 844, movil=True, url=servidor_co.url)
    insignia = p.page.locator("#insignia-colombia").first
    assert insignia.is_visible() and insignia.inner_text().strip().upper() == "COLOMBIA"
    caja = insignia.bounding_box()
    assert caja["x"] >= 0 and caja["x"] + caja["width"] <= 390, "la insignia cabe en el teléfono"
    assert velo(p)["contorno"] == 1 and p.mapa.locator("#rotulo-fuera").is_visible()
    assert not p.errores
