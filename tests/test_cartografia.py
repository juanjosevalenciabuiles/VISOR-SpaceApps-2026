"""Pruebas del sistema cartográfico multicapa: mapas base, capas de contexto y
la independencia entre la capa SAR y el fondo.  Ejecutar con:  pytest"""
import json
import re
import sys
from pathlib import Path

import folium
import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from components import mapa  # noqa: E402
from components.barra_lateral import Controles  # noqa: E402
from utils import capas_contexto, config  # noqa: E402
from utils.capas_contexto import CAPAS_CONTEXTO, CapaContexto, leer_contexto  # noqa: E402
from utils.config import ANTIOQUIA_BBOX, FENOMENOS  # noqa: E402
from utils.geotiff import leer_geotiff  # noqa: E402
from utils import mapas_base  # noqa: E402
from utils.mapas_base import (  # noqa: E402
    MAPA_BASE_PREDETERMINADO, MAPAS_BASE, obtener, url_teselas,
)

FENOMENO = FENOMENOS["inundacion"]


@pytest.fixture(scope="module")
def capa():
    return leer_geotiff(FENOMENO.ruta)


@pytest.fixture(autouse=True)
def sin_clave_carto(monkeypatch):
    monkeypatch.delenv("CARTO_API_KEY", raising=False)


def controles(**cambios) -> Controles:
    base = dict(clave="inundacion", mostrar_capa=True, opacidad=0.85,
                mostrar_huella=False, mostrar_referencia=False)
    return Controles(**{**base, **cambios})


def html(fenomeno, capa, c) -> str:
    return mapa.construir(fenomeno, capa, c).get_root().render()


def urls_teselas(texto: str) -> list[str]:
    return re.findall(r'L\.tileLayer\(\s*"([^"]+)"', texto)


def imagenes_sar(texto: str) -> list[str]:
    return re.findall(r"data:image/png;base64,[A-Za-z0-9+/=]+", texto)


# ---------------------------------------------------------------------------
# Catálogo de mapas base
# ---------------------------------------------------------------------------

def test_catalogo_de_mapas_base(monkeypatch):
    assert list(MAPAS_BASE) == [
        "osm_oscuro", "calles", "carto_oscuro", "carto_voyager", "carto_positron", "topografico", "satelital",
    ]
    # Sin clave de CARTO, sus fondos no se ofrecen (saldrían con marca de agua) y el oscuro es el de OSM.
    assert mapas_base.ofrecidos() == ["osm_oscuro", "calles", "topografico", "satelital"]
    assert set(mapas_base.no_ofrecidos()) == {"carto_oscuro", "carto_voyager", "carto_positron"}
    assert all("CARTO_API_KEY" in m for m in mapas_base.no_ofrecidos().values())
    assert mapas_base.predeterminado() == "osm_oscuro"
    assert obtener("no_existe").clave == "osm_oscuro" and obtener(None).clave == "osm_oscuro"
    assert obtener("carto_oscuro").clave == "osm_oscuro", "un fondo no disponible nunca se sirve"
    # Con clave válida, CARTO vuelve a ser el predeterminado.
    monkeypatch.setenv("CARTO_API_KEY", "abc123")
    assert MAPA_BASE_PREDETERMINADO == "carto_oscuro" == mapas_base.predeterminado() == obtener(None).clave
    assert mapas_base.no_ofrecidos() == {}
    for clave, m in MAPAS_BASE.items():
        assert m.clave == clave
        assert m.url.startswith("https://") and all(x in m.url for x in ("{z}", "{x}", "{y}"))
        assert "key=" not in m.url and "token" not in m.url      # sin credenciales en el catálogo
        assert m.atribucion and m.proveedor and m.licencia and m.uso
        assert 10 <= (m.max_zoom_nativo or m.max_zoom) <= m.max_zoom <= 20
        assert m.cobertura                                        # alcance declarado


def test_osm_sin_clave_con_politica_y_oscuro_solo_por_css():
    calles, oscuro = MAPAS_BASE["calles"], MAPAS_BASE["osm_oscuro"]
    assert calles.url == oscuro.url == "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    for m in (calles, oscuro):
        assert "OpenStreetMap" in m.atribucion and "policies/tiles" in m.licencia and not m.usa_clave_carto
    assert oscuro.clase_css == "visor-base-oscura" and calles.clase_css is None
    texto = html(FENOMENO, None, controles(mapa_base="osm_oscuro"))
    assert '"className": "visor-base-oscura"' in texto and ".visor-base-oscura { filter: invert(1)" in texto


def test_aviso_de_teselas_caidas_va_en_el_mapa_fijo():
    texto = mapa.mapa_fijo().get_root().render()
    assert "tileerror" in texto and "El mapa base no responde" in texto and "visor-aviso-teselas" in texto


def test_proveedores_y_atribuciones():
    carto = [m for m in MAPAS_BASE.values() if m.usa_clave_carto]
    assert {m.clave for m in carto} == {"carto_oscuro", "carto_voyager", "carto_positron"}
    for m in carto:
        assert "basemaps.cartocdn.com" in m.url and "CARTO" in m.atribucion and "OpenStreetMap" in m.atribucion
    topo, sat = MAPAS_BASE["topografico"], MAPAS_BASE["satelital"]
    assert "opentopomap.org" in topo.url and "OpenTopoMap" in topo.atribucion and "CC-BY-SA" in topo.atribucion
    assert "s2cloudless_3857" in sat.url and "EOX IT Services GmbH" in sat.atribucion
    assert "Copernicus Sentinel data 2016" in sat.atribucion
    assert "2016" in sat.nombre and "2016" in sat.uso            # no se presenta como imagen actual


def test_clave_carto(monkeypatch):
    oscuro = MAPAS_BASE["carto_oscuro"]
    assert config.carto_estado() == "ausente" and url_teselas(oscuro) == oscuro.url

    monkeypatch.setenv("CARTO_API_KEY", "  abc123_DEF-456  ")
    assert config.carto_estado() == "ok"
    assert url_teselas(oscuro) == oscuro.url + "?key=abc123_DEF-456"

    # Caracteres especiales: se aceptan, pero siempre codificados dentro de la URL.
    monkeypatch.setenv("CARTO_API_KEY", "a&b=c/d+e")
    assert config.carto_estado() == "ok"
    assert url_teselas(oscuro).endswith("?key=a%26b%3Dc%2Fd%2Be")

    for mala in ("con espacio", "línea\npartida", "ñandú", "x" * 600, "tab\tulado"):
        monkeypatch.setenv("CARTO_API_KEY", mala)
        assert config.carto_estado() == "invalida"
        assert config.carto_api_key() == "" and "key=" not in url_teselas(oscuro)


def test_la_clave_de_carto_no_se_envia_a_otros_proveedores(monkeypatch, capa):
    monkeypatch.setenv("CARTO_API_KEY", "CLAVESECRETA123")
    for m in MAPAS_BASE.values():
        assert ("CLAVESECRETA123" in url_teselas(m)) == m.usa_clave_carto
    assert "CLAVESECRETA123" not in html(FENOMENO, capa, controles(mapa_base="topografico"))
    assert "CLAVESECRETA123" not in html(FENOMENO, capa, controles(mapa_base="satelital"))


# ---------------------------------------------------------------------------
# Cambio de mapa base e independencia de la capa SAR
# ---------------------------------------------------------------------------

def test_mapa_fijo_no_lleva_teselas_ni_datos():
    m = mapa.mapa_fijo()
    assert not any(isinstance(h, (folium.TileLayer, folium.raster_layers.ImageOverlay, folium.GeoJson))
                   for h in m._children.values())
    assert tuple(m.location) == tuple(config.MAPA_CENTRO)
    assert m.options["zoom"] == config.MAPA_ZOOM
    texto = m.get_root().render()
    assert not urls_teselas(texto) and not imagenes_sar(texto)


def test_cambiar_mapa_base_no_altera_la_capa_sar(capa, monkeypatch):
    monkeypatch.setenv("CARTO_API_KEY", "abc123")       # todos los fondos disponibles
    imagenes, fondos = set(), set()
    for clave, m in MAPAS_BASE.items():
        texto = html(FENOMENO, capa, controles(mapa_base=clave))
        assert urls_teselas(texto) == [url_teselas(m)]           # un solo fondo, el elegido
        sar = imagenes_sar(texto)
        assert len(sar) == 1
        imagenes.add(sar[0])
        fondos.add(m.url)
    assert len(imagenes) == 1 and len(fondos) == len(MAPAS_BASE) - 1     # calles y oscuro OSM comparten teselas


def test_cada_fondo_lleva_su_atribucion(capa):
    texto = html(FENOMENO, capa, controles(mapa_base="satelital"))
    assert "s2maps.eu" in texto and "cartocdn" not in texto
    texto = html(FENOMENO, capa, controles(mapa_base="topografico"))
    assert "opentopomap.org" in texto and "s2maps.eu" not in texto


def test_orden_e_independencia_de_los_grupos(capa):
    todo = controles(hidrografia=True, vias=True, mostrar_huella=True, mostrar_referencia=True)
    nombres = [g.layer_name for g in mapa.construir_capas(FENOMENO, capa, todo)]
    assert nombres[0].startswith("Mapa base")
    assert nombres[1].startswith("SAR")
    assert nombres[2:] == ["Ríos y lagos (mundo)", "Carreteras principales (mundo)", "Área de referencia",
                           "Cobertura de la capa"]
    # Cada grupo contiene únicamente lo suyo.
    grupos = mapa.construir_capas(FENOMENO, capa, todo)
    tipos = [{type(h).__name__ for h in g._children.values()} for g in grupos]
    assert tipos[0] == {"TileLayer"} and tipos[1] == {"ImageOverlay"} and tipos[2] == {"GeoJson"}


# ---------------------------------------------------------------------------
# Activación de capas
# ---------------------------------------------------------------------------

def test_desactivar_la_capa_sar_conserva_el_fondo(capa):
    texto = html(FENOMENO, capa, controles(mostrar_capa=False, mapa_base="calles"))
    assert not imagenes_sar(texto)
    assert urls_teselas(texto) == [MAPAS_BASE["calles"].url]


def test_sin_geotiff_el_mapa_sigue_funcionando():
    grupos = mapa.construir_capas(FENOMENO, None, controles(hidrografia=True, mostrar_huella=True))
    assert [g.layer_name for g in grupos] == [f"Mapa base · {MAPAS_BASE['osm_oscuro'].nombre}", "Ríos y lagos (mundo)"]


def test_opacidad_solo_afecta_a_la_capa_sar(capa):
    a = html(FENOMENO, capa, controles(opacidad=0.3))
    b = html(FENOMENO, capa, controles(opacidad=0.9))
    assert imagenes_sar(a) == imagenes_sar(b) and urls_teselas(a) == urls_teselas(b)
    assert '"opacity": 0.3' in a and '"opacity": 0.9' in b


def test_activar_hidrografia_y_vias(capa):
    nada = html(FENOMENO, capa, controles())
    assert "Cauca" not in nada and "geo_json" not in nada

    rios = html(FENOMENO, capa, controles(hidrografia=True))
    assert all(r in rios for r in ("Cauca", "Magdalena", "Atrato"))
    assert CAPAS_CONTEXTO["hidrografia"].color in rios and CAPAS_CONTEXTO["vias"].color not in rios

    ambas = html(FENOMENO, capa, controles(hidrografia=True, vias=True))
    assert CAPAS_CONTEXTO["vias"].color in ambas and len(imagenes_sar(ambas)) == 1


# ---------------------------------------------------------------------------
# Capas de contexto: datos reales y manejo de errores
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("clave", list(CAPAS_CONTEXTO))
def test_capas_de_contexto_son_reales_y_mundiales(clave):
    c = CAPAS_CONTEXTO[clave]
    assert c.fuente.startswith("Natural Earth") and c.licencia == "Dominio público"
    assert "Calles" in c.alcance or "No incluye" in c.alcance        # dice qué NO trae
    for ruta in c.rutas:
        gdf = gpd.read_file(f"/vsigzip/{ruta}")
        assert len(gdf) > 1000 and gdf.crs.to_epsg() == 4326
        oeste, sur, este, norte = gdf.total_bounds
        assert oeste < -150 and este > 150 and sur < -30 and norte > 50, "cubre varios continentes"


REGIONES = {   # (oeste, sur, este, norte) alrededor de cada ciudad, zoom 9
    "Chigorodó": (-77.4, 7.2, -76.0, 8.2), "Medellín": (-76.1, 5.8, -75.0, 6.7), "París": (1.6, 48.4, 3.1, 49.3),
    "Nairobi": (36.3, -1.8, 37.3, -0.8), "Tokio": (139.0, 35.2, 140.4, 36.1), "Sídney": (150.5, -34.4, 151.7, -33.4),
}


@pytest.mark.parametrize("region", list(REGIONES))
def test_carreteras_y_rios_se_recortan_a_la_vista_en_cinco_continentes(region):
    """GLO-02…07/10: datos reales dentro del encuadre; nunca el mundo entero ni geometrías de otra zona."""
    caja = box(*REGIONES[region])
    vias = capas_contexto.recortar("vias", REGIONES[region], 9)
    assert vias is not None and vias.elementos > 0, f"{region}: sin carreteras principales"
    for f in json.loads(vias.geojson)["features"]:
        from shapely.geometry import shape
        assert shape(f["geometry"]).intersects(caja.buffer(0.05))
    rios = capas_contexto.recortar("hidrografia", REGIONES[region], 9)
    assert rios is not None and rios.elementos == len(json.loads(rios.geojson)["features"])


def test_recorte_por_zoom_limites_y_antimeridiano():
    lejos = capas_contexto.recortar("vias", (-180, -85, 180, 85), 3)
    assert lejos.elementos == 0 and "Acércate" in lejos.aviso                  # el mundo entero no se envía
    mundo = capas_contexto.recortar("hidrografia", (-180, -85, 180, 85), 3)
    assert 0 < mundo.elementos <= capas_contexto.MAX_ELEMENTOS
    # Encuadre que cruza ±180°: se usa la franja de latitud en todo el mundo, sin rectángulos invertidos.
    assert capas_contexto.limites_validos((179, -20, -179, -15)) == (-180.0, -20.0, 180.0, -15.0)
    assert capas_contexto.limites_validos((10, 5, 20, 5)) is None
    assert capas_contexto.recortar("vias", None, 9) is None


def test_hidrografia_no_se_confunde_con_precipitacion():
    assert "precipitacion" not in CAPAS_CONTEXTO and "lluvia" not in CAPAS_CONTEXTO
    assert "no agua actual ni inundación" in CAPAS_CONTEXTO["hidrografia"].alcance


@pytest.mark.parametrize("contenido", [
    None,                                                # archivo inexistente
    "esto no es geojson",
    '{"type": "FeatureCollection", "features": []}',     # vacío
    '{"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": null}]}',
])
def test_contexto_inexistente_danado_o_vacio_no_se_ofrece(tmp_path, contenido):
    ruta = tmp_path / "capa.geojson"
    if contenido is not None:
        ruta.write_text(contenido, encoding="utf-8")
    assert leer_contexto(ruta) is None


def test_contexto_en_otro_crs_se_reproyecta(tmp_path):
    linea = gpd.GeoDataFrame({"name": ["x"]}, geometry=[LineString([(-75.6, 6.2), (-75.5, 6.3)])], crs=4326)
    ruta = tmp_path / "utm.gpkg"
    linea.to_crs(32618).to_file(ruta, driver="GPKG")
    x, y = json.loads(leer_contexto(ruta).geojson)["features"][0]["geometry"]["coordinates"][0]
    assert x == pytest.approx(-75.6, abs=1e-5) and y == pytest.approx(6.2, abs=1e-5)


def test_capa_de_contexto_sin_datos_no_agrega_nada(monkeypatch, capa):
    falsa = CapaContexto("hidrografia", "Ríos y lagos (mundo)", "no_existe.geojson", "#fff", 1, "f", "l", "a")
    monkeypatch.setitem(CAPAS_CONTEXTO, "hidrografia", falsa)
    assert capas_contexto.leer_contexto(falsa.ruta) is None
    assert mapa.grupo_contexto("hidrografia") is None
    nombres = [g.layer_name for g in mapa.construir_capas(FENOMENO, capa, controles(hidrografia=True))]
    assert "Ríos y lagos (mundo)" not in nombres and len(nombres) == 2     # fondo + SAR intactos
    assert capas_contexto.cargar_contexto("inventada") is None


# ---------------------------------------------------------------------------
# La app completa
# ---------------------------------------------------------------------------

def test_app_cambia_de_fondo_y_de_capas_sin_errores(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(RAIZ)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60).run()
    assert not at.exception

    def textos():
        return " ".join(m.value for m in at.markdown)

    # Sin clave, CARTO no se ofrece y se dice por qué; el fondo inicial es el oscuro de OSM.
    assert at.selectbox(key="mapa_base").value == "osm_oscuro"
    assert at.selectbox(key="mapa_base").options == [MAPAS_BASE[k].nombre for k in mapas_base.ofrecidos()]
    assert "No disponibles aquí" in textos() and "CARTO_API_KEY" in textos()
    for clave in mapas_base.ofrecidos():
        at.selectbox(key="mapa_base").set_value(clave).run()
        assert not at.exception and len(at.error) == 0
        assert MAPAS_BASE[clave].proveedor.split(" ")[0] in textos()   # créditos del fondo activo

    at.toggle(key="ctx_hidrografia").set_value(True).run()
    at.toggle(key="ctx_vias").set_value(True).run()
    assert not at.exception and all(CAPAS_CONTEXTO[k].nombre in textos() for k in CAPAS_CONTEXTO)
    assert textos().count("Natural Earth 1:10m") >= 2                 # créditos de las dos capas

    for fenomeno in FENOMENOS:                         # el fondo elegido se conserva
        at.radio(key="fenomeno").set_value(fenomeno).run()
        assert not at.exception and at.selectbox(key="mapa_base").value == "satelital"
    at.toggle(key="capa_sar").set_value(True).run()    # DEMO encendida a propósito
    assert not at.exception and at.selectbox(key="mapa_base").value == "satelital"
    assert at.session_state["resultado_activo"] is None


def test_app_con_clave_carto_ofrece_carto_y_lo_usa_por_defecto(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("CARTO_API_KEY", "abc123")
    monkeypatch.chdir(RAIZ)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60).run()
    assert at.selectbox(key="mapa_base").value == "carto_oscuro"
    assert len(at.selectbox(key="mapa_base").options) == len(MAPAS_BASE)
    assert "No disponibles aquí" not in " ".join(m.value for m in at.markdown)
