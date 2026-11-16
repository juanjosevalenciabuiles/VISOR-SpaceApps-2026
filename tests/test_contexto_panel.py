"""Panel derecho «Conozcamos esta zona»: contexto local, adaptadores IDEAM/EONET y la app (sin red).

El IDEAM se simula con el ESQUEMA REAL observado el 14-nov-2026 en la capa 2 (ver
tests/test_contexto_red.py, trabajo manual de la CI). Nada aquí consulta servicios reales.
"""
import json
import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest
from shapely.geometry import box, mapping

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils import contexto_ambiental as ca  # noqa: E402
from utils import contexto_local as cl  # noqa: E402
from utils.config import AOI_CHIGORODO  # noqa: E402

CHIGORODO = mapping(box(*AOI_CHIGORODO))
CAMPOS_REALES = [{"name": n, "type": t} for n, t in (
    ("OBJECTID", "esriFieldTypeOID"), ("Shape", "esriFieldTypeGeometry"), ("ALERTA", "esriFieldTypeDouble"),
    ("AH", "esriFieldTypeInteger"), ("NOMAH", "esriFieldTypeString"), ("ZH", "esriFieldTypeInteger"),
    ("NOMZH", "esriFieldTypeString"), ("SZH", "esriFieldTypeInteger"), ("NOMSZH", "esriFieldTypeString"),
    ("DEP", "esriFieldTypeString"), ("DEP_1", "esriFieldTypeString"), ("DEP_2", "esriFieldTypeString"),
    ("NIVEL_A", "esriFieldTypeString"), ("Shape_Area", "esriFieldTypeDouble"))]
META = {"name": "Alertas_vigentes", "displayField": "NOMAH", "objectIdField": "OBJECTID", "fields": CAMPOS_REALES}


def _anillo(o, s, e, n):
    return [[[o, s], [e, s], [e, n], [o, n], [o, s]]]


def _rasgo(oid, nivel, szh, zh, rings, dep="ANTIOQUIA"):
    return {"attributes": {"OBJECTID": oid, "NIVEL_A": nivel, "NOMSZH": szh, "NOMZH": zh, "NOMAH": "Caribe",
                           "DEP": dep, "DEP_1": "CHOCÓ", "DEP_2": " "}, "geometry": {"rings": rings}}


class _Resp:
    def __init__(self, datos):
        self.datos = datos

    def read(self):
        return json.dumps(self.datos).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ideam(features=None, error=None, meta=META):
    pedidas = []

    def abrir(req, timeout):
        pedidas.append(req.full_url)
        if error:
            raise error
        if req.full_url.endswith("?f=json"):
            return _Resp(meta)
        return _Resp({"features": features or []})
    return abrir, pedidas


@pytest.fixture(autouse=True)
def limpio():
    ca.olvidar()
    yield
    ca.olvidar()


# ---------------------------------------------------------------------------
# Contexto local (DANE + cartografía de referencia)
# ---------------------------------------------------------------------------

def test_contexto_local_chigorodo():
    c = cl.contexto(CHIGORODO)
    assert c.municipios[0].nombre == "Chigorodó" and c.municipios[0].departamento == "Antioquia"
    assert c.lugar.startswith("Chigorodó") and c.lugar.endswith("Antioquia")
    assert abs(sum(m.fraccion for m in c.municipios) - 1) < 0.02, "los municipios cubren la zona"
    assert 700 < c.area_km2 < 800, "superficie en MAGNA-SIRGAS Origen Nacional (EPSG:9377)"
    assert c.rios == [] and c.vias >= 1 and not c.avisos


def test_contexto_local_islas_bogota_y_rios():
    san_andres = cl.contexto(mapping(box(-81.7243, 12.5337, -81.7163, 12.5417)))
    assert san_andres.municipios[0].nombre == "San Andrés"
    assert "Bogotá, D.C." in cl.contexto(mapping(box(-74.25, 4.5, -73.95, 4.8))).lugar
    assert "Cauca" in cl.contexto(mapping(box(-75.2, 8.3, -74.5, 9.0))).rios


def test_contexto_local_con_poligono_usa_la_forma_real():
    triangulo = {"type": "Polygon", "coordinates": [[[-76.75, 7.6], [-76.6, 7.6], [-76.75, 7.75], [-76.75, 7.6]]]}
    rect = cl.contexto(mapping(box(-76.75, 7.6, -76.6, 7.75)))
    tri = cl.contexto(triangulo)
    assert tri.area_km2 < rect.area_km2 * 0.6


# ---------------------------------------------------------------------------
# IDEAM (esquema real, respuestas simuladas)
# ---------------------------------------------------------------------------

def test_ideam_alertas_que_tocan_la_zona_ordenadas_por_gravedad():
    o, s, e, n = AOI_CHIGORODO
    features = [
        _rasgo(1, "ALERTA AMARILLA", "Río León", "Caribe - Litoral", _anillo(o - 0.1, s, o + 0.1, n)),
        _rasgo(2, "ALERTA NARANJA", "Río Atrato bajo", "Atrato - Darién", _anillo(o - 1, s - 1, e + 1, n + 1)),
        # en el rectángulo de búsqueda del servidor, pero sin tocar la zona real
        _rasgo(3, "ALERTA ROJA", "Lejos", "Otra", _anillo(e + 0.5, s, e + 0.6, n)),
    ]
    abrir, pedidas = _ideam(features)
    res = ca.consultar_ideam(CHIGORODO, abrir=abrir)
    assert res["estado"] == "CON_RESULTADOS" and [i["title"] for i in res["items"]] == ["Río Atrato bajo", "Río León"]
    primero = res["items"][0]
    assert primero["value"] == "ALERTA NARANJA" and primero["gravedad"] == 2
    assert primero["zona_hidrografica"] == "Atrato - Darién" and primero["departamentos"] == ["Antioquia", "Chocó"]
    assert primero["spatial_relation"] == "la zona está dentro del área de alerta"
    assert res["items"][1]["spatial_relation"] == "el área de alerta cruza la zona"
    assert primero["published_at"] is None, "la capa no declara fechas: no se inventa"
    assert "outSR=4326" in pedidas[1] and "esriGeometryEnvelope" in pedidas[1]
    assert all(set(ca.CAMPOS_COMUNES) <= set(i) for i in res["items"])


def test_ideam_sin_coincidencias_y_errores():
    abrir, _ = _ideam([])
    assert ca.consultar_ideam(CHIGORODO, abrir=abrir)["estado"] == "SIN_COINCIDENCIAS"
    abrir, _ = _ideam(error=urllib.error.URLError(TimeoutError()))
    assert ca.consultar_ideam(CHIGORODO, abrir=abrir)["estado"] == "ERROR_FUENTE"
    abrir, _ = _ideam(meta={"error": {"code": 500, "message": "caído"}})
    res = ca.consultar_ideam(CHIGORODO, abrir=abrir)
    assert res["estado"] == "ERROR_FUENTE" and res["error"] == "ErrorContexto"


def test_gravedad():
    assert [ca.gravedad(x) for x in ("ALERTA ROJA", "alerta naranja", "ALERTA AMARILLA", "NORMAL", None)] == [3, 2, 1, 0, 0]


# ---------------------------------------------------------------------------
# Consultas en segundo plano
# ---------------------------------------------------------------------------

def test_pedir_por_clave_sin_mezclar_zonas_y_fallo_controlado():
    llamadas = []
    a = ca.pedir("ideam", "zona-a", lambda: (llamadas.append("a"), {"estado": "SIN_COINCIDENCIAS", "items": []})[1],
                 sincrono=True)
    b = ca.pedir("ideam", "zona-b", lambda: (_ for _ in ()).throw(RuntimeError("boom")), sincrono=True)
    again = ca.pedir("ideam", "zona-a", lambda: pytest.fail("no se repite dentro del TTL"), sincrono=True)
    assert a["estado"] == again["estado"] == "SIN_COINCIDENCIAS" and llamadas == ["a"]
    assert b["estado"] == "ERROR_FUENTE" and b["error"] == "RuntimeError"


def test_pedir_en_segundo_plano_no_bloquea():
    import threading
    soltar = threading.Event()
    estado = ca.pedir("eonet", "x", lambda: (soltar.wait(5), {"estado": "SIN_COINCIDENCIAS", "items": []})[1])
    assert estado["estado"] == "CONSULTANDO"
    soltar.set()
    import time
    for _ in range(50):
        if ca.estado("eonet", "x")["estado"] != "CONSULTANDO":
            break
        time.sleep(0.05)
    assert ca.estado("eonet", "x")["estado"] == "SIN_COINCIDENCIAS"


# ---------------------------------------------------------------------------
# Frases
# ---------------------------------------------------------------------------

def test_frases_deterministas():
    from components import contexto_zona as cz
    local = cl.contexto(CHIGORODO)
    fuentes = {"ideam": {"estado": "CON_RESULTADOS", "items": [{"gravedad": 2}, {"gravedad": 1}]},
               "eonet": {"estado": "SIN_COINCIDENCIAS", "items": []}}
    frases = cz.frases_principales(local, date(2026, 9, 24), date(2026, 10, 6), "fechas de las dos imágenes elegidas",
                                   fuentes)
    assert frases[0].startswith("Está en Chigorodó") and "km²" in frases[1]
    assert "24/09/2026 a 06/10/2026" in frases[2]
    assert any("2 alerta(s)" in f and "naranja" in f for f in frases)
    assert any("no registra eventos" in f for f in frases)
    caidas = {"ideam": {"estado": "ERROR_FUENTE", "items": []}, "eonet": {"estado": "ERROR_FUENTE", "items": []}}
    sin = cz.frases_principales(local, date(2026, 9, 24), date(2026, 10, 6), "x", caidas)
    assert not any("IDEAM" in f or "EONET" in f for f in sin), "una fuente caída no genera afirmaciones"


# ---------------------------------------------------------------------------
# En la app
# ---------------------------------------------------------------------------

def _app(monkeypatch, tmp_path, ideam=None, eonet=None):
    from streamlit.testing.v1 import AppTest

    from components import contexto_zona
    from utils import wikipedia_lugar
    contexto_zona._local.cache_clear()
    monkeypatch.setenv("VISOR_REGION_MODE", "CO")
    monkeypatch.setenv("VISOR_CONTEXTO_EXTERNO", "activo")
    monkeypatch.setenv("VISOR_CONTEXTO_SINCRONO", "1")  # pruebas deterministas, nunca llamadas a Wikipedia
    monkeypatch.setattr(wikipedia_lugar, "consultar", lambda municipio, depto: {
        "estado": "CON_RESULTADOS", "items": [{
            "title": municipio, "extract": "Municipio de Colombia, descripción histórica de prueba.",
            "url": "https://es.wikipedia.org/wiki/Ejemplo", "imagen": None, "credito": None,
        }],
    })
    monkeypatch.setattr(ca, "consultar_ideam", ideam or (lambda g, abrir=None: {"estado": "SIN_COINCIDENCIAS",
                                                                              "items": [], "retrieved_at": None}))
    monkeypatch.setattr(ca, "consultar_eonet", eonet or (lambda g, a, b, abrir=None: {"estado": "SIN_COINCIDENCIAS",
                                                                                   "items": []}))
    monkeypatch.chdir(RAIZ)
    return AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180).run()


def _texto(at):
    return " ".join(m.value for m in at.markdown)


def test_app_sin_zona_invita_a_elegirla(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    texto = _texto(at)
    # Sin AOI no hay ficha territorial repetida sobre el mapa.
    assert 'id="ctx-zona"' not in texto and not at.session_state["ui_info"]
    assert "Welcome to V.I.S.O.R." in texto or "Bienvenido a V.I.S.O.R." in texto


def test_app_al_confirmar_la_zona_aparece_el_contexto_sin_pulsar_nada(monkeypatch, tmp_path):
    from tests.test_flujo_sar import confirmar_zona
    o, s, e, n = AOI_CHIGORODO
    alerta = {"estado": "CON_RESULTADOS", "retrieved_at": "2026-11-14T19:00:00+00:00", "items": [{
        "title": "Río León", "zona_hidrografica": "Caribe - Litoral", "value": "ALERTA NARANJA", "gravedad": 2,
        "spatial_relation": "el área de alerta cruza la zona", "departamentos": ["Antioquia"]}]}
    llamadas = []
    at = _app(monkeypatch, tmp_path, ideam=lambda g, abrir=None: (llamadas.append(g), alerta)[1])
    at.session_state["ui_info"] = False
    at.button(key="btn_sar").click().run()
    datos_antes = sorted(p.name for p in (RAIZ / "data").rglob("*"))
    confirmar_zona(at)
    assert at.session_state["ui_info"] is True, "la información debe abrirse al confirmar el área"
    texto = _texto(at)
    # La ficha breve muestra fotografía atribuida o satelital, y Wikipedia sin repetir alertas ni SAR.
    assert 'id="ctx-foto"' in texto and 'id="ctx-ficha"' in texto
    assert "Chigorodó" in texto and "Wikipedia (ES)" in texto
    assert 'id="ctx-zona"' not in texto and 'id="ctx-ideam"' not in texto
    assert 'id="ctx-eonet"' not in texto and 'id="ctx-radar"' not in texto
    # El adaptador de contexto conserva su caché: nunca multiplicar consultas.
    assert len(llamadas) <= 1
    for _ in range(3):                                # reruns: no se vuelve a consultar
        at.run()
    assert len(llamadas) <= 1
    assert sorted(p.name for p in (RAIZ / "data").rglob("*")) == datos_antes, "no escribe en data/"
    # Nada del contexto bloquea el flujo SAR.
    at.button(key="sar_buscar").click().run()
    assert not at.exception


def test_app_fuente_caida_y_cambio_de_zona(monkeypatch, tmp_path):
    from tests.test_flujo_sar import confirmar_zona
    at = _app(monkeypatch, tmp_path, ideam=lambda g, abrir=None: {"estado": "ERROR_FUENTE", "items": [],
                                                                  "error": "URLError"})
    at.button(key="btn_sar").click().run()
    confirmar_zona(at)
    texto = _texto(at)
    assert at.session_state["ui_info"] and 'id="ctx-foto"' in texto and not at.exception
    zona_a = at.session_state["zona"]["limites"]
    confirmar_zona(at, (-74.10, 4.68, -74.05, 4.72))      # Bogotá
    texto = _texto(at)
    assert at.session_state["zona"]["limites"] != zona_a
    assert at.session_state["ui_info"] and 'id="ctx-foto"' in texto and not at.exception
    assert "Bogotá" in texto  # la nueva área reemplaza los datos visibles de la anterior


def test_app_contexto_desactivado_lo_dice(monkeypatch, tmp_path):
    from tests.test_flujo_sar import confirmar_zona
    at = _app(monkeypatch, tmp_path)
    monkeypatch.setenv("VISOR_CONTEXTO_EXTERNO", "desactivado")
    at.button(key="btn_sar").click().run()
    confirmar_zona(at)
    texto = _texto(at)
    assert at.session_state["ui_info"] and 'id="ctx-foto"' in texto and not at.exception
    assert "No verified Wikipedia summary" in texto or "No hay una descripción" in texto


def test_busqueda_rionegro_no_se_renombra_san_carlos_por_fraccion():
    from components import contexto_zona as cz
    from utils import lugares
    from utils.contexto_local import ContextoLocal, Municipio
    rionegro = next(x for x in lugares.sugerencias().values()
                    if x.nombre == "Rionegro" and x.region == "Antioquia")
    encontrado = cl.municipio_en_punto(rionegro.longitud, rionegro.latitud)
    assert encontrado is not None and encontrado.nombre == "Rionegro"
    local = ContextoLocal(municipios=[
        Municipio("San Carlos", "Antioquia", "05649", .67),
        Municipio(encontrado.nombre, encontrado.departamento, encontrado.divipola, .33)], area_km2=20)
    zona = {"clave": "ejemplo", "geometria": mapping(box(rionegro.longitud - .02, rionegro.latitud - .02,
                                                     rionegro.longitud + .02, rionegro.latitud + .02)),
            "limites": (rionegro.longitud - .02, rionegro.latitud - .02,
                       rionegro.longitud + .02, rionegro.latitud + .02)}
    lugar = {"etiqueta": rionegro.etiqueta, "latitud": rionegro.latitud, "longitud": rionegro.longitud}
    ref = cz.municipio_de_busqueda(zona, local, lugar)
    assert ref is not None and ref.nombre == "Rionegro"
    fuentes = {"wiki": {"estado": "DESACTIVADO"}, "ideam": {"estado": "DESACTIVADO"},
               "eonet": {"estado": "DESACTIVADO"}}
    html = cz.cabecera_html(zona, local, fuentes, referencia=ref)
    assert '<h2 class="mc-ficha-nombre">Rionegro</h2>' in html
    assert "Buscaste Rionegro" in html and "San Carlos" in html and "67 %" in html
    assert "33 %" in cz.barra_municipios(local)
    frases = cz.frases_principales(local, date(2026, 10, 1), date(2026, 11, 1),
                                   "periodo", fuentes, referencia=ref)
    assert "Rionegro" in frases[0] and "San Carlos" in frases[1]


def test_busqueda_fuera_de_zona_no_se_atribuye_al_area():
    from components import contexto_zona as cz
    from utils.contexto_local import ContextoLocal, Municipio
    local = ContextoLocal(municipios=[Municipio("San Carlos", "Antioquia", "05649", 1.0)])
    zona = {"geometria": mapping(box(-75.2, 6.0, -75.1, 6.1))}
    assert cz.municipio_de_busqueda(zona, local, {
        "etiqueta": "Rionegro, Antioquia, Colombia", "latitud": 6.15, "longitud": -75.38}) is None
    assert cz.municipio_de_busqueda(zona, local, {
        "etiqueta": "Rionegro, Antioquia, Colombia", "latitud": None, "longitud": None}) is None


def test_ficha_breve_muestra_wikipedia_foto_acreditada_y_no_duplica_capas():
    """La ficha de zona contiene una imagen y un resumen, no paneles ambientales repetidos."""
    from types import SimpleNamespace as NS
    from components import contexto_zona as cz
    zona = {"clave": "prueba", "limites": AOI_CHIGORODO}
    local = NS(municipios=[NS(nombre="Chigorodó", departamento="Antioquia")], area_km2=42.2)
    wiki = {"estado": "CON_RESULTADOS", "items": [{
        "title": "Chigorodó", "extract": "Municipio de Antioquia.", "url": "https://es.wikipedia.org/wiki/Chigorod%C3%B3",
        "imagen": "https://upload.wikimedia.org/wikipedia/commons/thumb/test.jpg",
        "credito": {"pagina": "https://commons.wikimedia.org/wiki/File:Test.jpg",
                    "autor": "Autora de prueba", "licencia": "CC BY-SA 4.0"},
    }]}
    html = cz.ficha_breve_html(zona, local, wiki)
    assert 'id="ctx-foto"' in html and 'data-origen="wikimedia"' in html
    assert "Autora de prueba" in html and "CC BY-SA 4.0" in html
    assert "Wikipedia (ES)" in html and "Municipio de Antioquia" in html
    assert "42.2 km²" in html and "Chigorodó" in html
    assert 'id="ctx-ideam"' not in html and 'id="ctx-eonet"' not in html
    assert 'id="ctx-radar"' not in html and 'id="ctx-zona"' not in html


def test_ficha_breve_sin_wikipedia_usa_imagen_satelital_sin_inventar_descripcion():
    from types import SimpleNamespace as NS
    from components import contexto_zona as cz
    local = NS(municipios=[], area_km2=None)
    html = cz.ficha_breve_html({"clave": "sin", "limites": AOI_CHIGORODO},
                               local, {"estado": "SIN_COINCIDENCIAS", "items": []})
    assert 'data-origen="satelite"' in html
    assert "EOX" in html and "Wikipedia" in html
    assert "No verified Wikipedia summary" in html or "No hay una descripción" in html


def test_abrir_info_al_confirmar_y_respetar_cierre_manual_en_reruns(monkeypatch, tmp_path):
    """Se abre en cada AOI nueva; zoom y reruns no deshacen el cierre voluntario."""
    from tests.test_flujo_sar import confirmar_zona
    at = _app(monkeypatch, tmp_path)
    at.button(key="btn_sar").click().run()
    confirmar_zona(at)
    assert at.session_state["ui_info"] is True
    assert 'id="ctx-ficha"' in _texto(at)
    at.button(key="cerrar_info").click().run()
    assert at.session_state["ui_info"] is False
    for _ in range(2):
        at.run()
    assert at.session_state["ui_info"] is False, "ningún rerun reabre la ficha"
    confirmar_zona(at, (-74.10, 4.68, -74.05, 4.72))
    assert at.session_state["ui_info"] is True, "otro AOI siempre muestra su propia información"
    assert "Bogotá" in _texto(at)


def test_recomendaciones_fluviales_son_aoi_validas_y_no_pretenden_cobertura_nisar():
    from components import barra_lateral
    from utils import lugares, sesion
    casos = barra_lateral.RECOMENDACIONES_AOI
    assert set(casos) == {
        "chigorodo", "choco_atrato", "carepa", "apartado", "caucasia", "choco_cabi",
    }
    for caso in casos.values():
        assert sesion.validar_zona(caso["limites"]) == caso["limites"]
        ciudades = lugares.buscar_local(caso["municipio"])
        assert any(
            x.nombre == caso["municipio"]
            and caso["limites"][0] < x.longitud < caso["limites"][2]
            and caso["limites"][1] < x.latitud < caso["limites"][3]
            for x in ciudades
        ), "La AOI recomendada debe incluir el municipio identificado"
    assert "Chigorodó" in casos["chigorodo"]["nombre_es"]
    # La recomendación visible reproduce la EXTENSIÓN aproximada de la captura
    # que incluye el sector Turbo/Chigorodó, no el AOI de ensayo histórico.
    assert casos["chigorodo"]["limites"] == (-76.825, 7.568, -76.648, 7.676)
    assert casos["chigorodo"]["limites"] != AOI_CHIGORODO
    assert "Atrato" in casos["choco_atrato"]["nombre_en"]
    assert "Cauca River" in casos["caucasia"]["nombre_en"]
    assert "Cabí" in casos["choco_cabi"]["nombre_es"]
    assert len({tuple(caso["limites"]) for caso in casos.values()}) == len(casos)


def test_recomendacion_un_click_confirma_zona_muestra_ficha_y_no_lanza_sar(monkeypatch):
    from components import barra_lateral
    from utils import sesion
    estado = {
        "visor_idioma": "en", "zona": {"limites": [-76.1, 7.2, -76, 7.3]},
        "resultado_activo": {"id": "anterior", "origen": sesion.ANALISIS},
        "v9_preparacion": "cog_preparado_para_otra_zona",
        "v9_mapa_job": "mapa_viejo", "v9_publicado": "mapa_viejo",
        "trabajo_activo": "analisis_anterior", "trabajo_publicado": "analisis_anterior",
        "mapa_dibujo": {"type": "Feature"}, "ui_info": False,
    }
    monkeypatch.setattr(barra_lateral.st, "session_state", estado)
    vistas = []
    barra_lateral._seleccionar_recomendacion("chigorodo", lambda zona: vistas.append(zona))
    aoi = barra_lateral.RECOMENDACIONES_AOI["chigorodo"]["limites"]
    extendida = tuple(estado["zona"]["limites"])
    assert vistas == [extendida]
    assert estado["recomendacion_aoi_limites"] == extendida
    assert extendida[0] <= aoi[0] and extendida[1] <= aoi[1]
    assert extendida[2] >= aoi[2] and extendida[3] >= aoi[3]
    assert estado["resultado_activo"] is None
    assert "v9_preparacion" not in estado
    assert "v9_mapa_job" not in estado and "v9_publicado" not in estado
    assert estado["trabajo_activo"] is None and estado["trabajo_publicado"] is None
    assert estado["mapa_dibujo"] is None
    assert estado["ui_info"] is True and estado["ui_sar"] == "abierto"
    assert estado["ui_explorador"] is False
    assert estado["ui_explorador_previo"] is True
    assert "nisar_auto_job" not in estado, "seleccionar zona no inicia la descarga"
    assert estado["lugar"]["etiqueta"].startswith("Chigorodó")
    assert estado["visor_aoi_recomendacion_seq"] == 1
    assert estado["recomendacion_aoi_actual"] == "chigorodo"
    # Cambiar a Chocó usa la misma operación, sin intentar preparar ni analizar.
    barra_lateral._seleccionar_recomendacion("choco_atrato", lambda zona: vistas.append(zona))
    nueva = tuple(estado["zona"]["limites"])
    original = barra_lateral.RECOMENDACIONES_AOI["choco_atrato"]["limites"]
    assert nueva[0] <= original[0] and nueva[1] <= original[1]
    assert nueva[2] >= original[2] and nueva[3] >= original[3]
    assert estado["lugar"]["etiqueta"].startswith("Quibdó")
    assert estado["visor_aoi_recomendacion_seq"] == 2
    assert estado["ui_info"] is True and estado["ui_sar"] == "abierto"
    assert estado["ui_explorador"] is False
    assert "nisar_auto_job" not in estado


def test_recomendacion_invalida_no_borra_zona_ni_resultado(monkeypatch):
    from components import barra_lateral
    from utils import sesion
    estado = {"resultado_activo": {"id": "validado"}, "zona": {"limites": [-76.1, 7.2, -76, 7.3]},
              "visor_aoi_recomendacion_seq": 4}
    monkeypatch.setattr(barra_lateral.st, "session_state", estado)

    def no_valida(_):
        raise sesion.ErrorZona("AOI fuera de alcance")

    monkeypatch.setattr(barra_lateral.sesion, "validar_zona", no_valida)
    vistas = []
    barra_lateral._seleccionar_recomendacion("chigorodo", lambda zona: vistas.append(zona))
    assert estado["error_recomendacion"] == "AOI fuera de alcance"
    assert estado["resultado_activo"]["id"] == "validado"
    assert estado["zona"]["limites"] == [-76.1, 7.2, -76, 7.3]
    assert estado["visor_aoi_recomendacion_seq"] == 4 and not vistas



def test_todas_las_recomendaciones_abren_sar_sin_descargar(monkeypatch):
    """Los seis presets conservan el flujo de un clic y el resultado anterior no reaparece."""
    from components import barra_lateral
    estado = {
        "visor_idioma": "en", "ui_info": False,
        "ui_sar": "cerrado", "ui_explorador": True,
    }
    monkeypatch.setattr(barra_lateral.st, "session_state", estado)
    visitas = []
    for numero, (clave, caso) in enumerate(barra_lateral.RECOMENDACIONES_AOI.items(), 1):
        barra_lateral._seleccionar_recomendacion(clave, lambda limites: visitas.append(limites))
        expandida = tuple(estado["zona"]["limites"])
        o, sur, e, norte = caso["limites"]
        assert expandida[0] <= o and expandida[1] <= sur
        assert expandida[2] >= e and expandida[3] >= norte
        assert estado["recomendacion_aoi_limites"] == expandida
        assert estado["lugar"]["etiqueta"].startswith(caso["municipio"])
        assert estado["ui_info"] is True
        assert estado["ui_sar"] == "abierto"
        assert estado["ui_explorador"] is False
        assert estado["ui_explorador_previo"] is True
        assert estado["visor_aoi_recomendacion_seq"] == numero
        assert estado["recomendacion_aoi_actual"] == clave
        assert "nisar_auto_job" not in estado
        assert "v9_preparacion" not in estado
    assert len(visitas) == len(barra_lateral.RECOMENDACIONES_AOI)


def test_recomendaciones_principales_visibles_y_otras_plegables():
    from components import barra_lateral
    from pathlib import Path
    source = (Path(barra_lateral.__file__)).read_text(encoding="utf-8")
    assert 'principales = ("chigorodo", "choco_atrato")' in source
    assert "with st.expander(" in source
    assert "More suggested areas" in source
    assert "recom_{clave}" in source


def test_zonas_recomendadas_son_compactas_y_cuadradas_en_km_dentro_de_colombia():
    """Cada preset conserva el río, pero ya no produce grandes rectángulos al 87 %."""
    from components import barra_lateral
    from utils import sesion
    from utils.analisis_sar import MAX_PIXELES

    casos = barra_lateral.RECOMENDACIONES_AOI
    for clave, caso in casos.items():
        base = caso["limites"]
        ampliada = barra_lateral._ampliar_area_recomendada(base)
        assert sesion.validar_zona(ampliada) == ampliada
        assert ampliada[0] <= base[0] and ampliada[1] <= base[1]
        assert ampliada[2] >= base[2] and ampliada[3] >= base[3]
        ancho_km, alto_km = sesion.dimensiones_km(ampliada)
        assert 0.97 <= ancho_km / alto_km <= 1.03, (
            f"{clave}: lado oeste-este {ancho_km:.2f} km, "
            f"norte-sur {alto_km:.2f} km; la zona debe ser cuadrada en km"
        )
        pix = sesion.pixeles_estimados(ampliada)
        assert pix <= int(MAX_PIXELES * 0.40), (
            f"{clave}: el área no debe volver al máximo de la versión anterior"
        )
        assert pix > sesion.pixeles_estimados(base), (
            f"{clave}: conservar extensión mayor que el corredor base"
        )
    assert casos["chigorodo"]["limites"] == (-76.825, 7.568, -76.648, 7.676)


def test_cuadrados_recomendados_son_deterministas_y_no_modifican_preset():
    """Repetir la elección no desplaza la zona ni altera coordenadas científicas."""
    from components import barra_lateral

    originales = {k: tuple(x["limites"]) for k, x in
                  barra_lateral.RECOMENDACIONES_AOI.items()}
    for clave, original in originales.items():
        uno = barra_lateral._ampliar_area_recomendada(original)
        dos = barra_lateral._ampliar_area_recomendada(original)
        assert uno == dos, f"{clave}: la selección debe ser reproducible"
        assert barra_lateral.RECOMENDACIONES_AOI[clave]["limites"] == original



def test_wikipedia_sigue_visible_a_la_derecha_despues_del_analisis(monkeypatch):
    """Information: la foto y Wikipedia siguen visibles aun con resultado SAR."""
    from contextlib import nullcontext
    from types import SimpleNamespace as NS
    from components import interfaz

    estado = {"ui_info": True, "visor_idioma": "es"}
    eventos = []
    llamadas_wiki = []
    monkeypatch.setattr(interfaz.st, "session_state", estado)
    monkeypatch.setattr(interfaz.st, "container", lambda **kw: nullcontext())
    monkeypatch.setattr(interfaz.st, "expander", lambda *args, **kw: nullcontext())
    monkeypatch.setattr(interfaz.st, "markdown",
                        lambda texto, **kw: eventos.append(("html", texto)))
    monkeypatch.setattr(interfaz.st, "caption",
                        lambda texto, **kw: eventos.append(("caption", texto)))
    monkeypatch.setattr(interfaz.st, "button", lambda *args, **kw: False)
    monkeypatch.setattr(interfaz.flujo, "es_historico", lambda: False)
    monkeypatch.setattr(interfaz.ui_resultados, "ficha_html",
                        lambda _: '<div id="resultado-sar">SAR QA</div>')
    monkeypatch.setattr(interfaz.ui_resultados, "boton_qgis", lambda _: None)
    monkeypatch.setattr(interfaz.barra_lateral, "render_leyenda",
                        lambda *args, **kw: None)
    monkeypatch.setattr(interfaz.contexto_zona, "zona_actual",
                        lambda: {"clave": "municipio_prueba"})
    monkeypatch.setattr(interfaz.contexto_zona, "local_de",
                        lambda zona: NS())
    monkeypatch.setattr(interfaz.contexto_zona, "municipio_de_busqueda",
                        lambda *args: None)
    monkeypatch.setattr(interfaz.contexto_zona, "wikipedia_zona",
                        lambda *args: llamadas_wiki.append(True) or
                        {"estado": "CON_RESULTADOS", "items": []})
    monkeypatch.setattr(interfaz.contexto_zona, "ficha_breve_html",
                        lambda *args: '<div id="ctx-ficha">Wikipedia complementaria</div>')
    controles = NS(mostrar_capa=False, resultados={"res_sar": 1.0})
    res = NS(id="res_sar", dibujable=True)

    interfaz.panel_informacion(None, None, None, controles, [res])
    html = " ".join(texto for tipo, texto in eventos if tipo == "html")
    assert llamadas_wiki == [True], "Wikipedia debe seguir consultándose a la derecha"
    assert 'id="ctx-ficha"' in html
    assert 'id="resultado-sar"' in html
    assert html.index('id="ctx-ficha"') < html.index('id="resultado-sar"')
    assert not any(tipo == "toggle" for tipo, _ in eventos)

    eventos.clear()
    controles.resultados.clear()
    interfaz.panel_informacion(None, None, None, controles, [])
    html = " ".join(texto for tipo, texto in eventos if tipo == "html")
    assert 'id="ctx-ficha"' in html and 'id="resultado-sar"' not in html


def test_ubicacion_izquierda_no_reaparece_con_sar_o_resultado(monkeypatch):
    """Evita la ficha LOCATED que asomaba debajo de SAR Tools tras analizar."""
    from contextlib import nullcontext
    from components import barra_lateral

    estado = {
        "ui_explorador": True, "ui_sar": "cerrado",
        "lugar": {"etiqueta": "Quibdó, Chocó, Colombia"},
    }
    eventos = []
    monkeypatch.setenv("VISOR_MOSTRAR_DEMO", "0")
    monkeypatch.setattr(barra_lateral.st, "session_state", estado)
    monkeypatch.setattr(barra_lateral.st, "expander",
                        lambda *args, **kw: nullcontext())
    monkeypatch.setattr(barra_lateral, "lugar_ubicado",
                        lambda _: eventos.append("ubicacion"))
    monkeypatch.setattr(barra_lateral, "recomendaciones_analisis",
                        lambda _: None)
    monkeypatch.setattr(barra_lateral, "_controles_resultados",
                        lambda *args: {})
    from components import sistema
    monkeypatch.setattr(sistema, "render", lambda: None)

    def pintar(activo):
        barra_lateral.render(
            contenedor=nullcontext(), titulo=False, resultados=[],
            centrar=lambda *_: None, activo=activo,
            abrir_zona=lambda: None,
        )

    pintar(None)
    assert eventos == ["ubicacion"], "mantener lugar mientras se explora"
    estado["ui_sar"] = "abierto"
    pintar(None)
    assert eventos == ["ubicacion"], "no mostrar LOCATED detrás de SAR Tools"
    estado["ui_sar"] = "cerrado"
    pintar(object())
    assert eventos == ["ubicacion"], "no mostrar LOCATED tras publicar SAR"
    estado["ui_explorador"] = False
    pintar(None)
    assert eventos == ["ubicacion"], "panel no visible no debe pintar lugar"



def test_wikipedia_no_se_renderiza_en_panel_sar_ni_explorador():
    """La ficha de Wikipedia debe pertenecer exclusivamente al panel Information."""
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "components" / "interfaz.py"
              ).read_text(encoding="utf-8")
    informacion = source.split("def panel_informacion(", 1)[1].split(
        "def guia_eco(", 1
    )[0]
    assert "contexto_zona.ficha_breve_html(" in informacion
    assert "contexto_zona.ficha_breve_html(" not in source.split(
        "def herramientas_sar(", 1
    )[1].split("def linea_temporal(", 1)[0]
    assert "contexto_zona.ficha_breve_html(" not in source.split(
        "def panel_explorador(", 1
    )[1].split("def panel_informacion(", 1)[0]
