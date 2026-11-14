"""Cartografía global y UX en el navegador: GLO-01…GLO-18 (orden del 14-nov-2026).

Qué prueba y qué NO prueba este archivo:

- Las teselas de los mapas base se sirven con una imagen neutra (la red está cortada en las
  pruebas): se comprueba qué capa pide el mapa, su atribución y su comportamiento cuando falla,
  no el dibujo del proveedor real. La disponibilidad real de los proveedores se comprueba en
  tests/test_global_red.py (marca `red`, GitHub Actions).
- La búsqueda de lugares usa el catálogo local (geocodificador en línea desactivado).
- El catálogo de ASF es la respuesta real guardada de Chigorodó, rotulada CATÁLOGO SIMULADO: fuera
  de Chigorodó no tiene escenas, lo que sirve para probar el estado «sin escenas compatibles».
- Ríos, lagos y carreteras son los datos reales de Natural Earth incluidos en el repositorio.

`CARTOGRAFÍA GLOBAL` aprobada aquí no significa `PROCESAMIENTO SAR GLOBAL`: el análisis solo se
ha comprobado con RTC auténticos en Chigorodó.
"""
import hashlib
import re

import pytest

from conftest import Servidor, preparar_datos

RIOS, VIAS = "#4FC3F7", "#FFD60A"
CIUDADES = {   # consulta → (etiqueta esperada, zoom, lat, lon) del catálogo local
    "Chigorodó": ("Chigorodó, Antioquia, Colombia", 11, 7.67, -76.68),
    "medellin": ("Medellín, Antioquia, Colombia", 11, 6.25, -75.57),
    "Paris France": ("París, Isla de Francia, Francia", 11, 48.86, 2.35),
    "Nairobi Kenya": ("Nairobi, Nairobi, Kenia", 11, -1.29, 36.82),
    "東京": ("Tokio, Tokio, Japón", 10, 35.68, 139.69),
    "Sydney Australia": ("Sídney, Nueva Gales del Sur, Australia", 10, -33.87, 151.21),
}


@pytest.fixture(scope="module")
def servidor_global(tmp_path_factory):
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("global") / "data"))
    s.huellas = huellas(s.datos)
    yield s
    s.cerrar()


def huellas(carpeta):
    return {str(p.relative_to(carpeta)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(carpeta.rglob("*")) if p.is_file()}


def fondos(p) -> list[str]:
    return p.mapa.evaluate("()=>{const o=[];map.eachLayer(l=>{if(l instanceof L.TileLayer)o.push(l._url)});return o}")


def trazos_color(p, color: str) -> int:
    return p.mapa.evaluate(f"()=>document.querySelectorAll('path[stroke=\"{color}\" i]').length")


def atribucion(p) -> str:
    return p.mapa.evaluate("()=>document.querySelector('.leaflet-control-attribution').innerText")


def buscar(p, consulta: str):
    p.escribir("lugar_texto", consulta)
    p.clic("lugar_buscar")


def elegir_fondo(p, nombre: str):
    caja = p.page.locator(".st-key-mapa_base [role=combobox]").first
    caja.scroll_into_view_if_needed()
    caja.click()
    p.page.locator("[role=option]").filter(has_text=nombre).first.click()
    p.esperar()


def capa_contexto(p, clave: str):
    p.alternar(f"ctx_{clave}")
    p.esperar(1500)


@pytest.mark.parametrize("consulta", list(CIUDADES))
def test_glo_02_07_buscar_dibujar_y_contexto_en_cinco_continentes(abrir, servidor_global, consulta):
    """GLO-02…07 (+GLO-01, GLO-14): por nombre, sin coordenadas; zona válida en ambos hemisferios; ríos y
    carreteras reales del lugar; sin escenas → «sin escenas compatibles», nunca Chigorodó ni DEMO."""
    etiqueta, zoom, lat, lon = CIUDADES[consulta]
    p = abrir(url=servidor_global.url)
    p.marcar_mapa()
    assert p.capas_resultado() == [] and "SIN RESULTADO" in p.texto("barra_superior")      # GLO-01
    buscar(p, consulta)
    assert p.vista() == [zoom, lat, lon], "el mapa va al lugar"
    assert etiqueta in p.texto("panel_explorador") and "UBICADO" in p.texto("panel_explorador")

    capa_contexto(p, "vias")
    capa_contexto(p, "hidrografia")
    assert trazos_color(p, VIAS) > 0, f"{consulta}: carreteras principales reales en la vista"
    assert p.capas_resultado() == []

    p.clic("lugar_definir_zona")
    p.dibujar_rectangulo()
    p.clic("zona_usar_dibujo")
    panel = p.texto("panel_sar")
    assert "ZONA CONFIRMADA" in panel and "dibujo en el mapa" in panel
    norte = float(re.search(r"norte (-?\d+\.\d+)", panel).group(1))
    assert (norte > 0) == (lat > 0), "hemisferio correcto: nada fijado al norte ni a EPSG:32618"

    p.pestana_sar(1)
    p.clic("sar_buscar")
    panel = p.texto("panel_sar")
    if consulta == "Chigorodó":
        assert "pares compatibles" in panel and "No se encontraron escenas" not in panel
    else:
        assert "No se encontraron escenas compatibles para esta zona" in panel                # GLO-14
        assert "Ampliar el rango" in panel
        p.pestana_sar(2)
        assert p.page.locator(".st-key-sar_analizar").count() == 0, "sin escenas no se puede analizar"
    assert p.capas_resultado() == [] and "SIN RESULTADO" in p.texto("barra_superior")
    assert p.mapa_intacto() and not p.errores


def test_glo_08_antimeridiano(abrir, servidor_global):
    p = abrir(url=servidor_global.url)
    buscar(p, "Suva")
    assert p.vista()[1:] == [-18.14, 178.44]
    p.confirmar_zona("179.5", "-17", "-179.5", "-16")              # cruza ±180°
    panel = p.texto("panel_sar")
    assert "meridiano 180" in panel and "ZONA CONFIRMADA" not in panel
    p.confirmar_zona("178.2", "-18.3", "178.6", "-17.9")           # a un lado: válida
    assert "ZONA CONFIRMADA" in p.texto("panel_sar")
    p.clic("btn_explorador")
    capa_contexto(p, "vias")
    # Natural Earth no trae carreteras principales junto a Suva: se dice, no se inventan.
    assert trazos_color(p, VIAS) == 0 and "nada en esta vista" in p.texto("panel_explorador")
    assert p.capas_resultado() == [] and not p.errores


def test_glo_09_12_fondos_y_capas_sin_perder_mapa_ni_zona(abrir, servidor_global):
    """GLO-09 un fondo activo a la vez con su atribución; GLO-12 alternar 10 veces sin duplicar ni mover."""
    p = abrir(url=servidor_global.url)
    p.marcar_mapa()
    p.confirmar_zona()
    p.clic("sar_centrar")
    p.clic("btn_explorador")
    v, zona = p.vista(), p.trazos()
    assert fondos(p) == ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"]          # oscuro OSM sin clave
    assert "OpenStreetMap" in atribucion(p)
    oscuro = p.mapa.evaluate("()=>document.querySelector('.visor-base-oscura')!==null")
    assert oscuro, "el oscuro sin clave es OSM con filtro de color"
    for nombre, url, credito in (("Calles", "tile.openstreetmap.org", "OpenStreetMap"),
                                 ("Relieve", "opentopomap.org", "OpenTopoMap"),
                                 ("Satélite", "s2cloudless", "EOX"),
                                 ("Oscuro", "tile.openstreetmap.org", "OpenStreetMap")):
        elegir_fondo(p, nombre)
        activos = fondos(p)
        assert len(activos) == 1 and url in activos[0], (nombre, activos)
        assert credito in atribucion(p) and p.vista() == v and p.trazos() >= zona
    texto = p.texto("panel_explorador")
    assert "No disponibles aquí" in texto and "CARTO_API_KEY" in texto, "CARTO sin clave no se ofrece"

    capas = p.mapa.evaluate("()=>Object.keys(map._layers).length")
    for i in range(10):
        capa_contexto(p, "hidrografia")
        capa_contexto(p, "vias")
        elegir_fondo(p, "Calles" if i % 2 else "Oscuro")
    assert p.mapa.evaluate("()=>Object.keys(map._layers).length") == capas, "sin capas acumuladas"
    assert len(fondos(p)) == 1 and p.capas_resultado() == [] and p.vista() == v
    assert p.mapa_intacto() and not p.errores


def test_glo_10_16_rios_carreteras_y_resultado_no_se_confunden(abrir, servidor_global):
    p = abrir(url=servidor_global.url)
    buscar(p, "Chigorodó")
    capa_contexto(p, "hidrografia")
    assert trazos_color(p, RIOS) > 0 and trazos_color(p, VIAS) == 0
    capa_contexto(p, "vias")
    assert trazos_color(p, VIAS) > 0
    p.ver_historico("coincidencia_vv_vh_20260924_20261006")
    info = p.texto("panel_info")
    # Leyendas separadas: cartografía (Natural Earth) ≠ resultado SAR. JRC no está en esta versión.
    assert "Ríos y lagos (mundo)" in info and "no agua actual ni inundación" in info
    assert "Coincidencia VV/VH" in info and "No es una inundación confirmada" in info
    assert "JRC" not in p.texto("panel_explorador")
    capa_contexto(p, "hidrografia")
    capa_contexto(p, "vias")
    assert trazos_color(p, RIOS) == 0 and trazos_color(p, VIAS) == 0 and len(p.capas_resultado()) == 1


def test_glo_11_proveedor_caido(abrir, servidor_global):
    """403/429/caída del proveedor: aviso en el mapa, sin bloquear la app ni sustituir el fondo en silencio."""
    p = abrir(url=servidor_global.url)
    p.page.route(re.compile(r"https://[a-c]\.tile\.opentopomap\.org/.*"),
                 lambda r: r.fulfill(status=403, body="Forbidden"))
    assert not p.mapa.evaluate("()=>document.querySelector('#visor-aviso-teselas').classList.contains('visible')")
    elegir_fondo(p, "Relieve")
    p.page.wait_for_timeout(2500)
    aviso = p.mapa.evaluate("()=>{const e=document.querySelector('#visor-aviso-teselas');"
                            "return e.classList.contains('visible')?e.innerText:''}")
    assert "El mapa base no responde" in aviso and "Elige otro mapa base" in aviso
    assert len(fondos(p)) == 1 and "opentopomap" in fondos(p)[0], "no se cambia el fondo a escondidas"
    buscar(p, "Nairobi")                                          # la app sigue funcionando
    assert p.vista()[1:] == [-1.29, 36.82] and p.capas_resultado() == []
    elegir_fondo(p, "Satélite")
    p.page.wait_for_timeout(1500)
    assert not p.mapa.evaluate("()=>document.querySelector('#visor-aviso-teselas').classList.contains('visible')")


def test_glo_13_15_nueva_zona_tras_analizar_y_reanalisis(abrir, servidor_global):
    analisis = servidor_global.datos / "analisis"
    p = abrir(url=servidor_global.url)
    p.confirmar_zona()
    p.pestana_sar(1)
    p.clic("sar_buscar")
    p.pestana_sar(2)
    antes = set(x.name for x in analisis.iterdir())
    p.clic("sar_analizar")
    p.esperar(3000)
    primeros = set(x.name for x in analisis.iterdir()) - antes
    assert len(p.capas_resultado()) == 1 and primeros
    # GLO-15: la misma configuración solo se repite si se pide expresamente.
    assert p.page.locator(".st-key-sar_analizar button").first.is_disabled()
    p.alternar("sar_reanalizar")
    p.clic("sar_analizar")
    p.esperar(3000)
    segundos = set(x.name for x in analisis.iterdir()) - antes - primeros
    assert segundos and all("_r" in n for n in segundos), "archivos nuevos, sin sobrescribir"
    assert len(p.capas_resultado()) == 1, "un solo resultado tras reanalizar"
    # GLO-13: otra zona (Medellín) retira el raster y sus cifras; el historial conserva ambos.
    p.clic("btn_explorador")
    buscar(p, "medellin")
    p.confirmar_zona("-75.65", "6.2", "-75.5", "6.3")
    assert p.capas_resultado() == [] and "SIN RESULTADO" in p.texto("barra_superior")
    p.clic("btn_explorador")
    p.expandir("historial")
    historial = p.texto("panel_explorador")
    for n in primeros | segundos:
        if n.startswith("coincidencia_") and n.endswith(".tif"):
            assert n in historial
    assert not p.errores


def test_glo_17_movil(abrir, servidor_global):
    """Pantalla de teléfono: buscar, cambiar fondo y fijar la zona con el área visible, sin coordenadas."""
    p = abrir(390, 844, movil=True, url=servidor_global.url)
    buscar(p, "Tokyo Japan")
    assert p.vista() == [10, 35.68, 139.69]
    elegir_fondo(p, "Calles")
    assert len(fondos(p)) == 1
    p.clic("btn_sar")                            # en el teléfono, el botón de la barra superior
    p.alternar("zona_por_vista")
    assert "Mueve o acerca el mapa" in p.texto("panel_sar")
    p.clic("minimizar_sar")                      # se aparta el panel y se arrastra el mapa con el dedo
    p.page.mouse.move(120, 150)
    p.page.mouse.down()
    p.page.mouse.move(170, 165, steps=6)
    p.page.mouse.up()
    p.esperar(1500)
    p.clic("restaurar_sar")
    panel = p.texto("panel_sar")
    assert "Área visible" in panel, panel[-400:]
    p.clic("zona_usar_vista")
    assert "ZONA CONFIRMADA" in p.texto("panel_sar") and "área visible del mapa" in p.texto("panel_sar")
    botones = p.page.evaluate("""()=>[...document.querySelectorAll('.st-key-barra_superior button')].filter(b=>b.offsetWidth)
        .map(b=>b.getBoundingClientRect().right<=innerWidth)""")
    assert botones and all(botones) and not p.errores


def test_glo_18_atribucion_y_datos_intactos(abrir, servidor_global):
    p = abrir(url=servidor_global.url)
    assert p.mapa.evaluate("()=>document.querySelector('.leaflet-control-attribution').offsetHeight>0")
    assert "OpenStreetMap" in atribucion(p)
    buscar(p, "Chigorodó")
    capa_contexto(p, "vias")
    p.clic("btn_info")
    assert "Natural Earth" in p.texto("panel_info")
    texto = p.page.evaluate("()=>document.body.innerText")
    assert "CARTO_API_KEY=" not in texto and "EARTHDATA" not in texto
    actuales = huellas(servidor_global.datos)
    cambiados = [n for n, h in servidor_global.huellas.items() if actuales.get(n) != h]
    assert cambiados == [], f"archivos fuente modificados: {cambiados}"
