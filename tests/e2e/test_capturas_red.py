"""Capturas con servicios REALES: teselas de los mapas base, Nominatim, catálogo ASF y diagnóstico.

Solo en el trabajo manual «capturas» de GitHub Actions (o con VISOR_PRUEBAS_RED=1): el navegador
no simula nada de la red. Las capturas quedan en informes/capturas_reales/.

Respeta las políticas: unas pocas búsquedas espaciadas (la app ya impone ≤1 consulta/s a Nominatim),
solo las teselas de la vista que se captura y una consulta de metadatos a ASF.

El análisis de la captura 04 usa RTC SINTÉTICOS (no hay RTC reales en GitHub): demuestra el flujo y
la cartografía real, no un resultado científico. Su nombre de archivo lo dice.
"""
import os

import pytest

from conftest import NAVEGADOR, RAIZ, Pagina, Servidor, preparar_datos
from test_global_e2e import buscar, capa_contexto, elegir_fondo

pytestmark = [pytest.mark.red,
              pytest.mark.skipif(os.environ.get("VISOR_PRUEBAS_RED") != "1",
                                 reason="servicios reales: requiere VISOR_PRUEBAS_RED=1")]

DESTINO = RAIZ / "informes" / "capturas_reales"


@pytest.fixture(scope="module")
def servidor_real(tmp_path_factory):
    # Sin simulaciones: Nominatim, ASF y la comprobación de servicios son los reales.
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("reales") / "data"),
                 {"VISOR_GEOCODIFICADOR_URL": None, "VISOR_ASF_SIMULADO": None, "VISOR_DIAGNOSTICO": None})
    yield s
    s.cerrar()


@pytest.fixture
def pagina(navegador, servidor_real):
    ctx = navegador.new_context(viewport={"width": 1440, "height": 900})
    yield Pagina(ctx.new_page(), servidor_real.url, red_real=True)
    ctx.close()


def capturar(p, nombre: str):
    DESTINO.mkdir(parents=True, exist_ok=True)
    p.page.wait_for_timeout(2500)          # teselas reales: dar tiempo a que lleguen
    p.page.screenshot(path=str(DESTINO / f"{nombre}_{NAVEGADOR}.png"))


def teselas_reales(p) -> int:
    return p.mapa.evaluate("""()=>[...document.querySelectorAll('img.leaflet-tile')]
        .filter(i=>i.complete && i.naturalWidth===256 && !i.src.startsWith('data:')).length""")


def abrir_explorador(p):
    if not p.page.locator(".st-key-lugar_texto input").first.is_visible():
        p.clic("btn_explorador")


def ir(p, consulta: str):
    buscar(p, consulta)
    p.esperar(1500)
    if p.page.locator(".st-key-lugar_ir_0 button").count():
        p.clic("lugar_ir_0")
    p.page.wait_for_timeout(1200)          # ≥1 s entre búsquedas, además del límite de la app


def test_capturas_con_servicios_reales(pagina):
    p = pagina
    capturar(p, "01_inicio_sin_resultados_osm_oscuro")
    assert teselas_reales(p) > 0, "teselas reales de OpenStreetMap"
    assert p.capas_resultado() == [] and "SIN RESULTADO" in p.texto("barra_superior")

    abrir_explorador(p)
    ir(p, "Chigorodó, Antioquia")
    assert "Nominatim" in p.texto("panel_explorador") and "UBICADO" in p.texto("panel_explorador")
    capa_contexto(p, "hidrografia")
    capturar(p, "02_chigorodo_busqueda_real_y_rios")

    # Estado del sistema con la comprobación real.
    p.expandir("sistema")
    p.clic("sistema_comprobar")
    tabla = p.texto("sistema")
    assert "Oscuro · OpenStreetMap" in tabla and "APTO" in tabla and "SNAP" in tabla
    capturar(p, "03_estado_del_sistema_real")
    p.page.locator(".st-key-sistema").first.screenshot(path=str(DESTINO / f"03b_estado_del_sistema_detalle_{NAVEGADOR}.png"))
    p.expandir("sistema")

    # Zona por el área visible (sin coordenadas) → catálogo ASF real → par 24-sep/06-oct → Analizar.
    p.clic("lugar_definir_zona")
    p.alternar("zona_por_vista")
    p.clic("zona_usar_vista")
    assert "ZONA CONFIRMADA" in p.texto("panel_sar")
    p.pestana_sar(1)
    p.clic("sar_buscar")
    assert "CATÁLOGO SIMULADO" not in p.texto("panel_sar") and "pares compatibles" in p.texto("panel_sar")
    p.page.locator(".st-key-sar_filtro_pares label").filter(has_text="Todas").first.click()
    p.esperar()
    p.page.locator(".st-key-sar_par [role=combobox]").first.click()
    p.page.locator("[role=option]").filter(has_text="2026-09-24 → 2026-10-06").first.click()
    p.esperar()
    p.pestana_sar(2)
    assert p.analizar() == "APTO"
    assert len(p.capas_resultado()) == 1
    capturar(p, "04_analisis_tras_pulsar_analizar_RTC_SINTETICOS")

    for consulta, fondo, nombre in (("Paris, France", "Calles", "05_paris_calles"),
                                    ("Nairobi, Kenya", "Relieve", "06_nairobi_relieve"),
                                    ("Tokyo, Japan", "Oscuro", "07_tokio_oscuro_rios_carreteras"),
                                    ("Sydney, Australia", "Satélite", "08_sidney_satelite")):
        abrir_explorador(p)
        ir(p, consulta)
        elegir_fondo(p, fondo)
        if "tokio" in nombre:
            capa_contexto(p, "vias")
        assert teselas_reales(p) > 0, f"{consulta}: teselas reales de {fondo}"
        assert p.capas_resultado() == [], "el resultado de Chigorodó no viaja a otra ciudad"
        capturar(p, nombre)

    p.mapa.locator(".leaflet-control-zoom-fullscreen").click()
    capturar(p, "09_pantalla_completa")
    assert not p.errores
