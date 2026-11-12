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

def test_catalogo_de_mapas_base():
    assert list(MAPAS_BASE) == [
        "carto_oscuro", "carto_voyager", "carto_positron", "topografico", "satelital",
    ]
    assert MAPA_BASE_PREDETERMINADO == "carto_oscuro"
    assert obtener("no_existe").clave == "carto_oscuro" and obtener(None).clave == "carto_oscuro"
    for clave, m in MAPAS_BASE.items():
        assert m.clave == clave
        assert m.url.startswith("https://") and all(x in m.url for x in ("{z}", "{x}", "{y}"))
        assert "key=" not in m.url and "token" not in m.url      # sin credenciales en el catálogo
        assert m.atribucion and m.proveedor and m.licencia and m.uso
        assert 10 <= (m.max_zoom_nativo or m.max_zoom) <= m.max_zoom <= 20


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


def test_cambiar_mapa_base_no_altera_la_capa_sar(capa):
    imagenes, fondos = set(), set()
    for clave, m in MAPAS_BASE.items():
        texto = html(FENOMENO, capa, controles(mapa_base=clave))
        assert urls_teselas(texto) == [m.url]                    # un solo fondo, el elegido
        sar = imagenes_sar(texto)
        assert len(sar) == 1
        imagenes.add(sar[0])
        fondos.add(m.url)
    assert len(imagenes) == 1 and len(fondos) == len(MAPAS_BASE)


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
    assert nombres[2:] == ["Hidrografía", "Carreteras", "Área de referencia", "Cobertura de la capa"]
    # Cada grupo contiene únicamente lo suyo.
    grupos = mapa.construir_capas(FENOMENO, capa, todo)
    tipos = [{type(h).__name__ for h in g._children.values()} for g in grupos]
    assert tipos[0] == {"TileLayer"} and tipos[1] == {"ImageOverlay"} and tipos[2] == {"GeoJson"}


# ---------------------------------------------------------------------------
# Activación de capas
# ---------------------------------------------------------------------------

def test_desactivar_la_capa_sar_conserva_el_fondo(capa):
    texto = html(FENOMENO, capa, controles(mostrar_capa=False, mapa_base="carto_voyager"))
    assert not imagenes_sar(texto)
    assert urls_teselas(texto) == [MAPAS_BASE["carto_voyager"].url]


def test_sin_geotiff_el_mapa_sigue_funcionando():
    grupos = mapa.construir_capas(FENOMENO, None, controles(hidrografia=True, mostrar_huella=True))
    assert [g.layer_name for g in grupos] == [f"Mapa base · {MAPAS_BASE['carto_oscuro'].nombre}", "Hidrografía"]


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
def test_capas_de_contexto_incluidas_son_reales_y_estan_en_la_region(clave):
    c = CAPAS_CONTEXTO[clave]
    assert c.fuente.startswith("Natural Earth") and c.licencia and "No incluye" in c.alcance
    gdf = gpd.read_file(c.ruta)
    assert len(gdf) > 0 and gdf.crs.to_epsg() == 4326
    assert set(gdf.geom_type) <= {"LineString", "MultiLineString"}
    assert gdf.within(box(*ANTIOQUIA_BBOX).buffer(1e-6)).all()   # recortadas al área de referencia
    datos = leer_contexto(c.ruta)
    assert datos.elementos == len(gdf) and json.loads(datos.geojson)["type"] == "FeatureCollection"


def test_hidrografia_no_se_confunde_con_precipitacion():
    assert "precipitacion" not in CAPAS_CONTEXTO and "lluvia" not in CAPAS_CONTEXTO
    assert set(gpd.read_file(CAPAS_CONTEXTO["hidrografia"].ruta)["name"]) == {"Cauca", "Magdalena", "Atrato"}


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
    falsa = CapaContexto("hidrografia", "Hidrografía", "no_existe.geojson", "#fff", 1, "f", "l", "a")
    monkeypatch.setitem(CAPAS_CONTEXTO, "hidrografia", falsa)
    assert capas_contexto.leer_contexto(falsa.ruta) is None
    assert mapa.grupo_contexto("hidrografia") is None
    nombres = [g.layer_name for g in mapa.construir_capas(FENOMENO, capa, controles(hidrografia=True))]
    assert "Hidrografía" not in nombres and len(nombres) == 2     # fondo + SAR intactos
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

    assert "CARTO_API_KEY" in textos()                 # fondo CARTO sin clave: se avisa
    for clave, m in MAPAS_BASE.items():
        at.selectbox(key="mapa_base").set_value(clave).run()
        assert not at.exception and len(at.error) == 0
        assert m.proveedor.split(" ")[0] in textos()   # créditos del fondo activo
        assert ("CARTO_API_KEY" in textos()) == m.usa_clave_carto

    at.toggle(key="ctx_hidrografia").set_value(True).run()
    at.toggle(key="ctx_vias").set_value(True).run()
    assert not at.exception and textos().count("Natural Earth") == 2

    for fenomeno in FENOMENOS:                         # el fondo elegido se conserva
        at.radio(key="fenomeno").set_value(fenomeno).run()
        assert not at.exception and at.selectbox(key="mapa_base").value == "satelital"
    at.toggle(key="capa_sar").set_value(False).run()   # capa SAR apagada
    assert not at.exception and at.selectbox(key="mapa_base").value == "satelital"
