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
    if not p.visible("panel_explorador"):       # el buscador flota aparte: se mira el panel
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


@pytest.fixture(scope="module")
def servidor_real_co(tmp_path_factory):
    # Modo Colombia con servicios reales: Nominatim con countrycodes=co y teselas reales.
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("reales_co") / "data"),
                 {"VISOR_GEOCODIFICADOR_URL": None, "VISOR_ASF_SIMULADO": None, "VISOR_DIAGNOSTICO": None,
                  "VISOR_REGION_MODE": "CO"})
    yield s
    s.cerrar()


def test_capturas_modo_colombia_con_servicios_reales(navegador, servidor_real_co):
    ctx = navegador.new_context(viewport={"width": 1440, "height": 900})
    p = Pagina(ctx.new_page(), servidor_real_co.url, red_real=True)
    try:
        capturar(p, "CO01_inicio_modo_colombia")
        assert teselas_reales(p) > 0 and "COLOMBIA" in p.texto("barra_superior").upper()
        abrir_explorador(p)
        ir(p, "Chigorodó, Antioquia")
        assert "Nominatim" in p.texto("panel_explorador")
        p.mapa.evaluate("()=>map.setView([7.9,-77.0],9,{animate:false})")   # frontera con Panamá y golfo
        capturar(p, "CO02_uraba_frontera_panama_oscurecida")
        ir(p, "San Andrés isla")
        capturar(p, "CO03_san_andres")
        # «Tokio» SÍ existe en Colombia (veredas con ese nombre): Nominatim con countrycodes=co las devuelve.
        ir(p, "Nairobi, Kenya")
        assert "no está en Colombia" in p.texto("panel_explorador")
        capturar(p, "CO04_nairobi_rechazado")
        assert not p.errores
    finally:
        ctx.close()


@pytest.fixture(scope="module")
def servidor_real_ctx(tmp_path_factory):
    # Modo Colombia con IDEAM y NASA EONET reales en el panel derecho.
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("reales_ctx") / "data"),
                 {"VISOR_GEOCODIFICADOR_URL": None, "VISOR_ASF_SIMULADO": None, "VISOR_REGION_MODE": "CO",
                  "VISOR_CONTEXTO_EXTERNO": None})
    yield s
    s.cerrar()


def _esperar_fuentes(p, segundos=60):
    p.page.wait_for_function(
        "()=>{const e=[...document.querySelectorAll('#ctx-ideam [data-estado], #ctx-eonet [data-estado]')]"
        ".map(x=>x.dataset.estado); return document.querySelector('#ctx-zona') && !e.includes('CONSULTANDO')}",
        timeout=segundos * 1000)
    p.esperar(1500)


def test_capturas_contexto_ambiental_real(navegador, servidor_real_ctx):
    ctx = navegador.new_context(viewport={"width": 1440, "height": 900})
    pagina_ctx = ctx.new_page()
    pagina_ctx.on("response", lambda r: "upload.wikimedia.org" in r.url and print("CTX_WIKIMEDIA", r.status, r.url))
    p = Pagina(pagina_ctx, servidor_real_ctx.url, red_real=True)
    try:
        for nombre, coords in (("CTX01_chigorodo", ("-76.8", "7.55", "-76.55", "7.8")),
                               ("CTX02_la_mojana", ("-75.2", "8.3", "-74.5", "9.0"))):
            p.confirmar_zona(*coords)
            _esperar_fuentes(p)
            try:   # foto de Wikimedia Commons (si la página del municipio tiene una con licencia)
                p.page.wait_for_selector('#ctx-foto[data-origen="wikimedia"]', timeout=30000)
                p.page.wait_for_function("()=>{const f=document.querySelector('#ctx-foto');"
                                         "const i=f&&f.querySelector('img'); return i && i.complete && i.naturalWidth>0}",
                                         timeout=10000)
                p.esperar(2500)
            except Exception:  # noqa: BLE001 — se informa abajo: la ficha cae a la vista satelital
                pass
            foto = p.page.locator("#ctx-foto").first
            print("CTX_FOTO", nombre, foto.get_attribute("data-origen"), foto.inner_text(),
                  "| imagen cargada:", p.page.evaluate("()=>{const i=document.querySelector('#ctx-foto img');"
                                                       "return i ? i.naturalWidth : -1}"),
                  "| ECO:", p.page.locator("#eco-avatar").first.get_attribute("data-clip"),
                  p.page.locator("#eco-mensaje").first.inner_text().replace("\n", " "))
            texto = p.texto("panel_info")
            print("CTX_PANEL", nombre, " | ".join(texto.split("\n")[:40]))
            assert "Conozcamos esta zona" in texto and "Fuente no disponible" not in texto, texto[:1500]
            p.page.locator(".st-key-panel_info").first.screenshot(path=str(DESTINO / f"{nombre}_{NAVEGADOR}.png"))
            capturar(p, nombre + "_pantalla")
        assert not p.errores
    finally:
        ctx.close()
