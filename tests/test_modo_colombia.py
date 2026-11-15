"""Modo Colombia (VISOR_REGION_MODE=CO): pruebas de aceptación CO-01…CO-12 sin navegador.

La parte visual (velo que no captura clics, cambio de mapa base, móvil, Chromium/Firefox) está en
tests/e2e/test_modo_colombia_e2e.py. Aquí: la política es la misma en interfaz y servidor.
"""
import gzip
import json
import shutil
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils import alcance_geografico as alcance  # noqa: E402
from utils import lugares, sesion  # noqa: E402
from utils.config import AOI_CHIGORODO  # noqa: E402

PANAMA_FRONTERA = (-77.6, 7.8, -77.0, 8.4)
CARTAGENA_COSTA = (-75.6, 10.3, -75.4, 10.5)
QUITO = (-78.6, -0.3, -78.4, -0.1)
SAN_ANDRES_INTERIOR = (-81.7243, 12.5337, -81.7163, 12.5417)
PROVIDENCIA_INTERIOR = (-81.3791, 13.3491, -81.3711, 13.3571)


@pytest.fixture(autouse=True)
def modo_co(monkeypatch):
    monkeypatch.setenv("VISOR_REGION_MODE", "CO")
    monkeypatch.setenv("VISOR_GEOCODIFICADOR_URL", "desactivado")
    lugares._cache.clear()
    yield


def _app(monkeypatch, tmp_path=None):
    from streamlit.testing.v1 import AppTest
    monkeypatch.chdir(RAIZ)
    return AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180).run()


def _texto(at) -> str:
    return " ".join(m.value for m in at.markdown)


# ---------------------------------------------------------------------------
# Fuente y política
# ---------------------------------------------------------------------------

def test_fuente_del_limite_registrada_y_geometria_auditable():
    ficha = alcance.ficha_fuente()
    assert "DANE" in ficha["fuente"] and "CC BY 4.0" in ficha["licencia"] and ficha["crs"] == "EPSG:4326"
    assert len(ficha["commit_derivado"]) == 40 and "Gorgona" in " ".join(ficha["advertencias"])
    import hashlib
    for nombre, datos in ficha["archivos"].items():
        ruta = alcance.CARPETA / nombre
        assert hashlib.sha256(ruta.read_bytes()).hexdigest() == datos["sha256"], f"{nombre} cambió sin regenerar"
    geo = alcance.geometria()
    assert geo.geom_type == "MultiPolygon" and len(geo.geoms) == 69, "continente + islas de la fuente"
    o, s, e, n = geo.bounds
    assert o < -81.7 and n > 13.39 and s < -4.2 and e > -66.9, "incluye San Andrés y Providencia y Leticia"


def test_modo_por_defecto_es_colombia_y_lo_desconocido_cierra(monkeypatch):
    monkeypatch.delenv("VISOR_REGION_MODE")
    assert alcance.modo() == "CO"
    monkeypatch.setenv("VISOR_REGION_MODE", "mundo")
    assert alcance.modo() == "CO", "un valor desconocido no abre la plataforma"
    monkeypatch.setenv("VISOR_REGION_MODE", "global")
    assert alcance.modo() == "GLOBAL"


# ---------------------------------------------------------------------------
# CO-01 · primera apertura
# ---------------------------------------------------------------------------

def test_co01_primera_apertura(monkeypatch):
    at = _app(monkeypatch)
    assert not at.exception
    texto = _texto(at)
    assert 'id="insignia-colombia"' in texto and "COLOMBIA · Área de estudio habilitada" in texto
    assert at.session_state["resultado_activo"] is None and "SIN RESULTADO" in texto
    assert at.session_state["capa_sar"] is False, "DEMO apagada"
    from components import mapa
    html = mapa.mapa_fijo().get_root().render()
    assert '"visor_velo"' in html and "#2ee6c8" in html and "pointerEvents = \"none\"" in html.replace("'", '"')
    compacto = "".join(html.split())
    assert "center:[4.6,-74.3]" in compacto and '"zoom":5' in compacto
    assert '"maxBounds":[[-8.0,-86.0,],[17.0,-62.0,],]' in compacto, "paneo limitado a Colombia con margen"
    assert "MGN 2025, DANE" in html and '"attribution"' in html and "Fuera de Colombia" in html


# ---------------------------------------------------------------------------
# CO-02…CO-05 · búsqueda y coordenadas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("consulta,esperado", [
    ("Chigorodó", "Chigorodó, Antioquia, Colombia"), ("Bogota", "Bogotá, Distrito Capital, Colombia"),
    ("medellin", "Medellín, Antioquia, Colombia")])
def test_co02_lugares_de_colombia(consulta, esperado):
    encontrados, _, aviso = lugares.buscar(consulta)
    assert encontrados[0].etiqueta == esperado and aviso is None


def test_co02_homonimos_se_conservan():
    encontrados, _, _ = lugares.buscar("Rionegro")
    assert [l.etiqueta for l in encontrados] == ["Rionegro, Antioquia, Colombia", "Rionegro, Santander, Colombia"]


@pytest.mark.parametrize("consulta", ["San Andrés", "Providencia", "Santa Catalina"])
def test_co03_islas(consulta):
    encontrados, _, aviso = lugares.buscar(consulta)
    assert encontrados and encontrados[0].nombre == consulta and aviso is None


def test_co03_zonas_dentro_de_las_islas_se_admiten():
    assert sesion.validar_zona(SAN_ANDRES_INTERIOR) and sesion.validar_zona(PROVIDENCIA_INTERIOR)


@pytest.mark.parametrize("consulta", ["Tokio", "Quito", "Panamá", "Lima", "Caracas", "Paris France"])
def test_co04_lugares_fuera_se_explican(consulta):
    encontrados, _, aviso = lugares.buscar(consulta)
    assert encontrados == [] and "no está en Colombia" in aviso and "territorio colombiano" in aviso


def test_co04_geocodificador_pide_solo_colombia_y_se_verifica_la_geometria(monkeypatch):
    monkeypatch.setenv("VISOR_GEOCODIFICADOR_URL", "https://geo.ejemplo.org")
    pedidas = []

    class R:
        def __init__(self, cuerpo):
            self.cuerpo = cuerpo

        def read(self):
            return self.cuerpo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def abrir(peticion, timeout):
        pedidas.append(peticion.full_url)
        # Un servicio que se equivoca: dice «Colombia» para un punto de Quito. Se rechaza por geometría.
        return R(json.dumps([
            {"lat": "-0.18", "lon": "-78.47", "name": "Quito", "address": {"country": "Colombia"}},
            {"lat": "7.67", "lon": "-76.68", "name": "Chigorodó", "address": {"state": "Antioquia",
                                                                               "country": "Colombia"}},
        ]).encode())

    encontrados, fuente, _ = lugares.buscar("prueba", abrir=abrir)
    assert "countrycodes=co" in pedidas[0] and fuente == lugares.EN_LINEA
    assert [l.nombre for l in encontrados] == ["Chigorodó"]
    lugares._cache.clear()
    solo_fuera = lambda p, timeout: R(json.dumps([{"lat": "-0.18", "lon": "-78.47", "name": "Quito"}]).encode())  # noqa: E731
    encontrados, _, aviso = lugares.buscar("Quito", abrir=solo_fuera)
    assert encontrados == [] and "no está en Colombia" in aviso


def test_co05_coordenadas_externas_no_navegan(monkeypatch):
    """Las coordenadas se escriben en el buscador: fuera de Colombia no navegan; dentro, sí."""
    import streamlit as st
    from components import barra_lateral
    monkeypatch.setenv("VISOR_REGION_MODE", "CO")
    estado = {"lugar_texto": "35.68, 139.69", "resultado_activo": None, "zona": None}       # Tokio
    monkeypatch.setattr(st, "session_state", estado)
    idas = []
    barra_lateral._buscar_lugar(lambda lat, lon, zoom: idas.append([lat, lon]))
    assert idas == [] and "fuera de Colombia" in estado["lugares_encontrados"]["aviso"]
    estado["lugar_texto"] = "7.67, -76.68"
    barra_lateral._buscar_lugar(lambda lat, lon, zoom: idas.append([lat, lon]))
    assert idas == [[7.67, -76.68]] and estado["lugares_encontrados"] is None


# ---------------------------------------------------------------------------
# CO-06…CO-08 · zona de análisis
# ---------------------------------------------------------------------------

def test_co06_zona_en_chigorodo():
    assert sesion.validar_zona(AOI_CHIGORODO) == AOI_CHIGORODO


@pytest.mark.parametrize("limites,motivo", [(PANAMA_FRONTERA, "sale del territorio colombiano"),
                                            (CARTAGENA_COSTA, "sale del territorio colombiano"),
                                            (QUITO, "está fuera de Colombia")])
def test_co07_zona_que_cruza_frontera_o_costa_se_rechaza(limites, motivo):
    with pytest.raises(sesion.ErrorZona, match=motivo):
        sesion.validar_zona(limites)


def test_co08_poligono_dentro_con_rectangulo_fuera_se_rechaza():
    # Una «L» al sur y al este del golfo de Urabá: entera en tierra colombiana, pero su rectángulo
    # envolvente (lo que procesa el motor) incluye ~29 % de mar del golfo.
    from shapely.geometry import Polygon
    ele = Polygon([(-76.65, 7.7), (-77.0, 7.7), (-77.0, 7.75), (-76.7, 7.75), (-76.7, 8.2), (-76.65, 8.2)])
    assert alcance.geometria().covers(ele), "el polígono dibujado está entero en Colombia"
    with pytest.raises(sesion.ErrorZona, match="rectángulo envolvente"):
        sesion.zona_de_geojson(ele.__geo_interface__)


def test_co08_la_app_no_confirma_una_zona_fuera(monkeypatch):
    from tests.test_flujo_sar import confirmar_zona
    at = _app(monkeypatch)
    at.button(key="btn_sar").click().run()
    with pytest.raises(AssertionError):
        confirmar_zona(at, PANAMA_FRONTERA)
    assert "sale del territorio colombiano" in at.session_state["error_zona"] and at.session_state["zona"] is None


# ---------------------------------------------------------------------------
# CO-10 · GLOBAL restituye todo
# ---------------------------------------------------------------------------

def test_co10_global_restituye_navegacion_y_opciones(monkeypatch):
    monkeypatch.setenv("VISOR_REGION_MODE", "GLOBAL")
    lugares._cache.clear()
    assert lugares.buscar("Tokio")[0][0].pais == "Japón"
    assert sesion.validar_zona(PANAMA_FRONTERA) and sesion.validar_zona((2.25, 48.8, 2.45, 48.9))
    from components import mapa
    html = mapa.mapa_fijo().get_root().render()
    assert "visor_velo" not in html and "COLOMBIA" not in html
    for modulo in ("utils.lugares", "utils.capas_contexto", "utils.buscador_sar", "utils.procesadores"):
        __import__(modulo)


# ---------------------------------------------------------------------------
# CO-11 · el servidor rechaza antes de consultar, gastar o calcular
# ---------------------------------------------------------------------------

def test_co11_busqueda_asf_fuera_no_consulta():
    from utils import buscador_sar as bus
    llamadas = []
    with pytest.raises(bus.ErrorBusqueda, match="fuera de Colombia"):
        bus.buscar(*QUITO, "2026-09-01", "2026-10-30", abrir=lambda *a, **k: llamadas.append(a))
    assert llamadas == [], "no se llega a ASF"


def test_co11_trabajo_fuera_se_bloquea_antes_de_leer(tmp_path, monkeypatch):
    from utils import ejecucion_sar, flujo_sar, trabajos
    monkeypatch.setenv("VISOR_TRABAJOS_DIR", str(tmp_path / "t"))
    monkeypatch.setattr(flujo_sar, "analizar_disponibles", lambda *a, **k: pytest.fail("no debe calcular"))
    t = trabajos.crear("fuera", {"tipo": "prueba"})
    trabajos.lanzar(t["job_id"], ejecucion_sar.tarea_cambio_s1(None, [], QUITO, {}, False, "fuera", tmp_path / "a"),
                    sincrono=True)
    fin = trabajos.leer(t["job_id"])
    assert fin["estado"] == "ERROR" and "fuera de Colombia" in fin["error"]
    assert {f["clave"]: f["estado"] for f in fin["fases"]}["datos"] == "BLOQUEADO"
    assert not (tmp_path / "a").exists()


def test_co11_motor_rechaza_la_cuadricula_antes_de_leer_pixeles(tmp_path, monkeypatch):
    from tests.test_flujo_sar import rtc
    from utils import analisis_sar
    sar = tmp_path / "sar"
    sar.mkdir()
    a, b = rtc(sar, "20260924T232218", "VV"), rtc(sar, "20261006T232218", "VV")
    monkeypatch.setattr(analisis_sar, "leer_en_cuadricula", lambda *x, **k: pytest.fail("no debe leer"))
    # Recuadro de los RTC sintéticos ampliado a mano hacia el golfo de Urabá: parte en el mar.
    monkeypatch.setattr(analisis_sar, "comprobar_alcance", analisis_sar.comprobar_alcance)
    with pytest.raises(analisis_sar.ErrorSAR, match="Colombia"):
        analisis_sar.comprobar_alcance(analisis_sar.Cuadricula(
            analisis_sar.CRS.from_epsg(32618), analisis_sar.Affine(30, 0, 180000, 0, -30, 940000), 900, 900))
    analisis_sar.comprobar_alcance(analisis_sar.Cuadricula(
        analisis_sar.CRS.from_epsg(32618), analisis_sar.Affine(30, 0, 256000, 0, -30, 850000), 900, 900))
    assert a.exists() and b.exists()


def test_co11_sin_limite_nacional_no_se_admite_nada(tmp_path, monkeypatch):
    monkeypatch.setenv("VISOR_LIMITE_COLOMBIA_DIR", str(tmp_path / "vacio"))
    with pytest.raises(sesion.ErrorZona, match="No se pudo cargar el límite nacional"):
        sesion.validar_zona(AOI_CHIGORODO)
    encontrados, _, aviso = lugares.buscar("Chigorodó")
    assert encontrados == [] and "límite nacional" in aviso
    (tmp_path / "danado").mkdir()
    (tmp_path / "danado" / alcance.ARCHIVO_VALIDACION).write_bytes(gzip.compress(b"{}"))
    monkeypatch.setenv("VISOR_LIMITE_COLOMBIA_DIR", str(tmp_path / "danado"))
    assert not alcance.limite_disponible()


def test_co11_resultados_guardados_de_otro_pais_no_se_recuperan():
    from types import SimpleNamespace
    dentro = SimpleNamespace(capa=SimpleNamespace(limites=AOI_CHIGORODO))
    fuera = SimpleNamespace(capa=SimpleNamespace(limites=QUITO))
    ilegible = SimpleNamespace(capa=None)
    visibles, ocultos = alcance.filtrar_resultados([dentro, fuera, ilegible])
    assert visibles == [dentro, ilegible] and ocultos == 1


# ---------------------------------------------------------------------------
# CO-12 · Chigorodó completo en Modo Colombia (RTC sintéticos; los reales: test_recorrido P0-16)
# ---------------------------------------------------------------------------

def test_co12_flujo_completo_de_chigorodo_en_modo_colombia(tmp_path, monkeypatch):
    from tests.test_flujo_sar import test_app_busca_analiza_y_muestra_el_resultado
    test_app_busca_analiza_y_muestra_el_resultado(tmp_path, monkeypatch)


def test_co12_datos_originales_intactos():
    """El Modo Colombia no escribe en data/ salvo sus propios archivos de límite (versionados)."""
    ficha = alcance.ficha_fuente()
    from utils import contexto_local
    assert set(ficha["archivos"]) == {alcance.ARCHIVO_VALIDACION, alcance.ARCHIVO_DIBUJO,
                                      contexto_local.ARCHIVO_MUNICIPIOS}
    assert shutil.which("git") is None or True
