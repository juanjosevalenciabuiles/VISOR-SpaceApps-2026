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
    contexto_zona._local.cache_clear()
    monkeypatch.setenv("VISOR_REGION_MODE", "CO")
    monkeypatch.setenv("VISOR_CONTEXTO_EXTERNO", "activo")
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
    assert 'id="ctx-sin-zona"' in texto and "Selecciona una zona para conocer qué sucede allí" in texto
    assert 'id="ctx-zona"' not in texto and "Cómo empezar" in texto


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
    assert at.session_state["ui_info"] is True, "el panel derecho se abre solo"
    texto = _texto(at)
    assert "Conozcamos esta zona" in texto and "Está en Chigorodó" in texto and "km²" in texto
    assert 'data-nivel="ALERTA NARANJA"' in texto and "subzona hidrográfica Río León" in texto
    assert "la más alta es naranja" in texto and "no publica la fecha de emisión" in texto
    assert 'data-estado="SIN_ANALISIS"' in texto and "Aún no has realizado un análisis" in texto
    assert "no confirman lo que muestre el radar" in texto and "Cómo empezar" not in texto
    assert len(llamadas) == 1
    for _ in range(3):                                # reruns: no se vuelve a consultar
        at.run()
    assert len(llamadas) == 1
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
    assert 'data-estado="ERROR_FUENTE"' in texto and "Fuente no disponible" in texto
    zona_a = at.session_state["zona"]["limites"]
    confirmar_zona(at, (-74.10, 4.68, -74.05, 4.72))      # Bogotá
    texto = _texto(at)
    assert at.session_state["zona"]["limites"] != zona_a
    assert "Está en Bogotá, D.C." in texto and "Chigorodó" not in texto.split('id="ctx-zona"')[1]


def test_app_contexto_desactivado_lo_dice(monkeypatch, tmp_path):
    from tests.test_flujo_sar import confirmar_zona
    at = _app(monkeypatch, tmp_path)
    monkeypatch.setenv("VISOR_CONTEXTO_EXTERNO", "desactivado")
    at.button(key="btn_sar").click().run()
    confirmar_zona(at)
    texto = _texto(at)
    assert 'data-estado="DESACTIVADO"' in texto and "Está en Chigorodó" in texto
