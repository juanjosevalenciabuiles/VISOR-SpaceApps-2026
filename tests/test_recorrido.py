"""Recorrido del usuario: zona, búsqueda de lugares, identidad de las ejecuciones y ausencia de
resultados antes de analizar (orden del 13-nov-2026, P0-01…P0-24).

Las pruebas de navegador del mismo recorrido están en tests/e2e/test_recorrido_e2e.py.

`test_reproduccion_real_chigorodo_desde_la_app` recorre la app completa con los cuatro RTC
auténticos de Chigorodó (24-sep y 6-oct-2026) y exige los conteos de referencia. Se ejecuta solo
si VISOR_RTC_REALES apunta a la carpeta que los contiene; si no, queda OMITIDA (nunca aprobada).
"""
import json
import math
import os
import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import lugares, sesion  # noqa: E402
from utils.analisis_sar import MAX_PIXELES  # noqa: E402

AOI = (-76.80, 7.55, -76.55, 7.80)


# ---------------------------------------------------------------------------
# Zona: validación antes de tocar datos pesados (P0-03, P0-21)
# ---------------------------------------------------------------------------

def test_zona_valida_y_canonica():
    assert sesion.validar_zona(AOI) == AOI
    assert sesion.validar_zona(("-76.800001", 7.55, -76.55, 7.8)) == AOI       # misma zona ⇒ misma clave
    assert 0.8e6 < sesion.pixeles_estimados(AOI) < 0.9e6                      # ≈ 924 × 926 del recorte real


@pytest.mark.parametrize("zona,mensaje", [
    ((-75, 6, -76, 7), "oeste debe ser menor"),
    ((-76, 7, -75, 6), "sur debe ser menor"),
    ((-200, 0, 1, 1), "fuera del mundo"),
    ((19.43, -99.13, 19.6, -98.9), "fuera del mundo"),           # lat/lon intercambiadas (Ciudad de México)
    ((-76.8, 7.55, -76.7999, 7.5501), "demasiado pequeña"),
    ((-77, 5, -74, 9), "millones de píxeles"),                    # cabe en 5° pero supera el motor
    ((-80, 0, -70, 4), "demasiado amplia"),
    ((179.5, 0, -179.5, 1), "meridiano 180"),
    ((float("nan"), 0, 1, 1), "no son números"),
    (("a", 0, 1, 1), "cuatro números"),
])
def test_zona_invalida_se_rechaza_con_explicacion(zona, mensaje):
    with pytest.raises(sesion.ErrorZona, match=mensaje):
        sesion.validar_zona(zona)


def test_limite_de_pixeles_coincide_con_el_motor():
    lado = math.sqrt(MAX_PIXELES) * sesion.RESOLUCION_ESTIMADA_M / 1000 / 111.32   # grados, en el ecuador
    sesion.validar_zona((0, 0, lado * 0.95, lado * 0.95))
    with pytest.raises(sesion.ErrorZona):
        sesion.validar_zona((0, 0, lado * 1.05, lado * 1.05))


def test_zona_desde_geojson():
    poligono = {"type": "Polygon", "coordinates": [[[-76.8, 7.55], [-76.55, 7.55], [-76.6, 7.8], [-76.8, 7.55]]]}
    limites, geom = sesion.zona_de_geojson({"type": "Feature", "geometry": poligono, "properties": {}})
    assert limites == AOI and geom["type"] == "Polygon"
    coleccion = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": poligono}]}
    assert sesion.zona_de_geojson(json.dumps(coleccion))[0] == AOI
    for malo, mensaje in (
        ({"type": "Point", "coordinates": [-76.6, 7.6]}, "ningún polígono"),
        ("{no es json", "no es un GeoJSON válido"),
        ({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}, "se cruza a sí mismo"),
        ({"type": "Polygon", "coordinates": [[[19.4, -99.1], [19.6, -99.1], [19.6, -98.9], [19.4, -99.1]]]},
         "fuera del mundo"),                                        # [lat, lon] en vez de [lon, lat]
    ):
        with pytest.raises(sesion.ErrorZona, match=mensaje):
            sesion.zona_de_geojson(malo)


# ---------------------------------------------------------------------------
# Identidad de la ejecución y pares ya analizados (P0-05, P0-13)
# ---------------------------------------------------------------------------

PARAM = {"VV": {"umbral_disminucion_db": 7.5, "ventana_speckle": 3},
         "VH": {"umbral_disminucion_db": 3.0, "ventana_speckle": 5}}


def test_run_id_estable_y_sensible_a_cada_entrada():
    base = sesion.run_id(AOI, "A", "B", PARAM)
    assert base == sesion.run_id((-76.800001, 7.55, -76.55, 7.8), "A", "B", json.loads(json.dumps(PARAM)))
    otros = {
        sesion.run_id((-76.81, 7.55, -76.55, 7.8), "A", "B", PARAM),
        sesion.run_id(AOI, "A", "C", PARAM),
        sesion.run_id(AOI, "A", "B", {**PARAM, "VV": {"umbral_disminucion_db": 7.0, "ventana_speckle": 3}}),
        sesion.run_id(AOI, "A", "B", {**PARAM, "VH": {"umbral_disminucion_db": 3.0, "ventana_speckle": 3}}),
    }
    assert base not in otros and len(otros) == 4


def test_contexto_cambia_con_zona_par_y_parametros():
    c = sesion.contexto(AOI, "A|B", PARAM)
    assert c == sesion.contexto(AOI, "A|B", PARAM)
    assert c != sesion.contexto(None, "A|B", PARAM) != sesion.contexto(AOI, None, PARAM)
    assert c != sesion.contexto(AOI, "A|B", {"VV": {"umbral_disminucion_db": 5, "ventana_speckle": 3}})


def _registro(carpeta, nombre, aoi, antes, despues, salidas, generado, run="r1"):
    for s in salidas:
        (carpeta / s).write_text("x")
    (carpeta / nombre).write_text(json.dumps({
        "generado_utc": generado, "run_id": run, "par": sesion.clave_par(antes, despues),
        "par_catalogo_asf": {"antes": {"nombre": antes}, "despues": {"nombre": despues}},
        "aoi_lonlat": list(aoi), "salidas": salidas}), encoding="utf-8")


def test_pares_ya_analizados_por_zona_sin_ocultar_escenas(tmp_path):
    _registro(tmp_path, "flujo_1_registro.json", AOI, "A", "B", ["coincidencia_1.tif", "cambio_VV_1_mascara.tif"],
              "2026-11-13T10:00:00+00:00", "r1")
    _registro(tmp_path, "flujo_2_registro.json", AOI, "A", "B", ["cambio_VV_2_mascara.tif"],
              "2026-11-13T11:00:00+00:00", "r2")
    (tmp_path / "roto_registro.json").write_text("{no es json")
    previas = sesion.ejecuciones_del_par(tmp_path, AOI, "A", "B")
    assert [r["run_id"] for r in previas] == ["r2", "r1"]                    # la más reciente primero
    assert sesion.resultado_principal(previas[1]) == "coincidencia_1.tif"
    # La misma escena en otro par o en otra zona NO cuenta como usada.
    assert sesion.ejecuciones_del_par(tmp_path, AOI, "A", "C") == []
    assert sesion.ejecuciones_del_par(tmp_path, (-75.45, 6.1, -75.3, 6.22), "A", "B") == []
    # Si sus archivos ya no existen, no se ofrece como «ver resultado anterior».
    (tmp_path / "cambio_VV_2_mascara.tif").unlink()
    assert [r["run_id"] for r in sesion.ejecuciones_del_par(tmp_path, AOI, "A", "B")] == ["r1"]
    assert sesion.ejecucion_con_id(tmp_path, "r2") is None and sesion.ejecucion_con_id(tmp_path, "r1")


# ---------------------------------------------------------------------------
# Búsqueda de lugares (P0-02, P0-24)
# ---------------------------------------------------------------------------

def test_catalogo_local_desambigua_y_tolera_tildes(monkeypatch):
    monkeypatch.setenv("VISOR_GEOCODIFICADOR_URL", "desactivado")
    assert [l.etiqueta for l in lugares.buscar_local("rionegro")] == [
        "Rionegro, Antioquia, Colombia", "Rionegro, Santander, Colombia"]
    assert [l.etiqueta for l in lugares.buscar_local("CHIGORODO")] == ["Chigorodó, Antioquia, Colombia"]
    assert [l.etiqueta for l in lugares.buscar_local("bogota")] == ["Bogotá, Distrito Capital, Colombia"]
    encontrados, fuente, aviso = lugares.buscar("Atlantis")
    assert encontrados == [] and fuente == lugares.LOCAL and aviso is None          # nunca inventa
    assert lugares.buscar("a")[2] and lugares.buscar("")[0] == []


class _Resp:
    def __init__(self, datos):
        self.datos = json.dumps(datos).encode()

    def read(self):
        return self.datos

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_geocodificador_en_linea_configurado(monkeypatch):
    monkeypatch.setenv("VISOR_GEOCODIFICADOR_URL", "https://geo.ejemplo.org")
    lugares._cache.clear()
    pedidas = []

    def abrir(peticion, timeout):
        pedidas.append(peticion)
        return _Resp([{"lat": "48.8588", "lon": "2.3200", "name": "Paris", "display_name": "Paris, Île-de-France, France",
                       "address": {"state": "Île-de-France", "country": "France"},
                       "boundingbox": ["48.81", "48.90", "2.22", "2.47"]},
                      {"lat": "no", "lon": "0", "name": "malo"}])
    encontrados, fuente, aviso = lugares.buscar("Paris France", abrir=abrir)
    assert fuente == lugares.EN_LINEA and aviso is None
    assert [l.etiqueta for l in encontrados] == ["Paris, Île-de-France, France"] and encontrados[0].zoom >= 10
    assert "format=jsonv2" in pedidas[0].full_url and pedidas[0].get_header("User-agent").startswith("VISOR")
    lugares.buscar("paris  france", abrir=abrir)                     # caché: no se repite la consulta
    assert len(pedidas) == 1


@pytest.mark.parametrize("fallo,frase", [
    (urllib.error.HTTPError("u", 429, "x", {}, None), "demasiadas consultas"),
    (urllib.error.HTTPError("u", 403, "x", {}, None), "rechazó la clave"),
    (urllib.error.URLError("sin red"), "No se pudo conectar"),
    (TimeoutError(), "No se pudo conectar"),
])
def test_geocodificador_caido_usa_el_catalogo_local_y_lo_dice(monkeypatch, fallo, frase):
    monkeypatch.setenv("VISOR_GEOCODIFICADOR_URL", "https://geo.ejemplo.org")
    lugares._cache.clear()

    def abrir(peticion, timeout):
        raise fallo
    encontrados, fuente, aviso = lugares.buscar("Chigorodó", abrir=abrir)
    assert fuente == lugares.LOCAL and frase in aviso and "catálogo local" in aviso
    assert [l.nombre for l in encontrados] == ["Chigorodó"]


def test_proveedor_solo_https_y_nominatim_por_defecto(monkeypatch):
    for url, esperado in (("https://a.org", "https://a.org"), ("http://a.org", None),
                          ("http://localhost:8080", "http://localhost:8080"), ("desactivado", None),
                          ("", lugares.NOMINATIM)):
        monkeypatch.setenv("VISOR_GEOCODIFICADOR_URL", url)
        assert lugares.proveedor() == esperado


@pytest.mark.parametrize("consulta,esperado", [
    ("Chigorodó", "Chigorodó, Antioquia, Colombia"), ("Paris France", "París, Isla de Francia, Francia"),
    ("Nairobi Kenya", "Nairobi, Nairobi, Kenia"), ("Tokyo Japan", "Tokio, Tokio, Japón"), ("東京", "Tokio, Tokio, Japón"),
    ("Sydney Australia", "Sídney, Nueva Gales del Sur, Australia"), ("medellin", "Medellín, Antioquia, Colombia"),
])
def test_catalogo_local_mundial_y_multilingue(monkeypatch, consulta, esperado):
    """GLO-02…07 sin red: el catálogo local encuentra ciudades de cinco continentes por nombre."""
    monkeypatch.setenv("VISOR_GEOCODIFICADOR_URL", "desactivado")
    encontrados, fuente, aviso = lugares.buscar(consulta)
    assert [l.etiqueta for l in encontrados][:1] == [esperado] and fuente == lugares.LOCAL and aviso is None
    l = encontrados[0]
    assert -90 <= l.latitud <= 90 and -180 <= l.longitud <= 180


# ---------------------------------------------------------------------------
# La app: nada en pantalla antes de analizar (P0-01, P0-12, P0-14, P0-20)
# ---------------------------------------------------------------------------

def test_app_arranca_vacia_aunque_haya_resultados_en_disco(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from test_resultados import exploratorio, reproducible

    from utils import resultados
    exploratorio(tmp_path / "coincidencia_VV_VH_Chigorodo.tif")
    reproducible(tmp_path)
    monkeypatch.setattr(resultados, "CARPETA_ANALISIS", tmp_path)
    monkeypatch.setenv("VISOR_GEOCODIFICADOR_URL", "desactivado")
    monkeypatch.chdir(RAIZ)
    for _ in range(2):                                               # dos sesiones nuevas e independientes
        at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120).run()
        assert not at.exception
        assert at.session_state["resultado_activo"] is None and at.session_state["zona"] is None
        assert at.toggle(key="capa_sar").value is False
        texto = " ".join(m.value for m in at.markdown)
        assert "SIN RESULTADO" in texto and "Cómo empezar" in texto and "No es una inundación confirmada" not in texto
        assert not any(k.startswith("qgis_") for k in (b.key or "" for b in at.get("download_button")))
        # Ni el mapa base ni la búsqueda de un lugar ponen nada en el mapa.
        at.selectbox(key="mapa_base").set_value("calles").run()
        at.text_input(key="lugar_texto").input("Chigorodó")
        at.button(key="lugar_buscar").click().run()
        assert at.session_state["lugar"]["etiqueta"].startswith("Chigorodó")
        assert at.session_state["zona"] is None and at.session_state["resultado_activo"] is None
        at.button(key="hist_ver_coincidencia_vv_vh_20260924_20261006").click().run()
        assert at.session_state["resultado_activo"]["origen"] == sesion.HISTORICO


def test_pagina_analisis_sar_no_abre_resultados_guardados(tmp_path, monkeypatch):
    """La página secundaria tampoco muestra el último resultado guardado por existir."""
    from streamlit.testing.v1 import AppTest
    from test_analisis_sar import ANTES, DESPUES, campo, crear_rtc

    from utils.analisis_sar import ParametrosCambio, analizar_par
    entrada, salida = tmp_path / "sar", tmp_path / "out"
    entrada.mkdir()
    a, d = crear_rtc(entrada / ANTES, campo()), crear_rtc(entrada / DESPUES, campo())
    analizar_par(a, d, salida, parametros=ParametrosCambio(ventana_speckle=1))
    monkeypatch.setenv("VISOR_SAR_DIR", str(entrada))
    monkeypatch.setenv("VISOR_ANALISIS_DIR", str(salida))
    monkeypatch.chdir(RAIZ)
    at = AppTest.from_file(str(RAIZ / "pages" / "1_Analisis_SAR.py"), default_timeout=120).run()
    assert not at.exception
    texto = " ".join(m.value for m in at.markdown)
    assert "Ningún resultado en pantalla" in texto and len(at.get("dataframe")) == 0
    at.selectbox(key="sar_informe_elegido").set_value(0).run()
    texto = " ".join(m.value for m in at.markdown)
    assert "HISTÓRICO" in texto and len(at.get("dataframe")) == 1


# ---------------------------------------------------------------------------
# P0-16: la app reproduce Chigorodó desde los RTC auténticos
# ---------------------------------------------------------------------------

REALES = os.environ.get("VISOR_RTC_REALES")
REFERENCIA = {"0": 815237, "1": 11, "2": 27992, "3": 12293}


@pytest.mark.skipif(not REALES or not Path(REALES).is_dir(),
                    reason="Sin los 4 RTC auténticos de Chigorodó (VISOR_RTC_REALES): reproducción NO VERIFICADA aquí")
def test_reproduccion_real_chigorodo_desde_la_app(tmp_path, monkeypatch):
    import hashlib

    import numpy as np
    import rasterio
    from streamlit.testing.v1 import AppTest
    from test_flujo_sar import REAL, confirmar_zona

    from utils import buscador_sar as bus
    from utils import flujo_sar as flujo
    from utils import resultados
    rtcs = sorted(Path(REALES).glob("S1C_IW_2026*_RTC30_*.tif"))
    assert len(rtcs) == 4, [p.name for p in rtcs]
    huellas = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in rtcs}
    salida = tmp_path / "analisis"
    monkeypatch.setattr(bus, "consultar_asf", lambda parametros, **k: REAL)     # catálogo real guardado
    monkeypatch.setattr(flujo, "CARPETA_SAR", Path(REALES))
    monkeypatch.setattr(flujo, "CARPETA_ANALISIS", salida)
    monkeypatch.setattr(resultados, "CARPETA_ANALISIS", salida)
    monkeypatch.chdir(RAIZ)

    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=900).run()
    assert at.session_state["resultado_activo"] is None
    at.button(key="btn_sar").click().run()
    confirmar_zona(at, AOI, date(2026, 9, 20), date(2026, 10, 10))
    at.button(key="sar_buscar").click().run()
    assert at.selectbox(key="sar_par").options[0].startswith("★ 2026-09-24 → 2026-10-06 · S1C")
    at.slider(key="sar_umbral_VV").set_value(7.5)
    at.select_slider(key="sar_ventana_VV").set_value(3)
    at.slider(key="sar_umbral_VH").set_value(3.0)
    at.select_slider(key="sar_ventana_VH").set_value(5)
    at.run()
    assert at.session_state["resultado_activo"] is None and not salida.exists()
    at.button(key="sar_analizar").click().run()
    assert not at.exception, at.exception
    activo = at.session_state["resultado_activo"]
    assert activo and activo["origen"] == sesion.ANALISIS
    with rasterio.open(salida / "coincidencia_VV_VH_20260924_20261006.tif") as s:
        datos = s.read(1)
        assert (s.crs.to_epsg(), s.width, s.height, s.res, s.nodata) == (32618, 924, 926, (30.0, 30.0), 255)
    valores, cuentas = np.unique(datos, return_counts=True)
    obtenido = dict(zip((str(v) for v in valores.tolist()), cuentas.tolist(), strict=True))
    assert obtenido == {**REFERENCIA, "255": 91}, obtenido
    detecciones = sum(obtenido[k] for k in ("1", "2", "3"))
    assert detecciones == 40296 and round(detecciones * 0.09, 2) == 3626.64
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in rtcs} == huellas, "RTC fuente intactos"
