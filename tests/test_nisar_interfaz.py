"""Panel NISAR en Mission Control (AppTest) y perfil de escena única. Datos SINTÉTICOS."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio

from tests import nisar_sintetico as sint
from tests.test_nisar_catalogo import granule, item
from utils import nisar_catalogo as cat
from utils import nisar_flujo, nisar_gcov, qgis, resultados
from utils.diferencia_db import ESCALA_DIFERENCIA, ESCALA_GAMMA0, colorizar_diferencia, escala_de

RAIZ = Path(__file__).resolve().parent.parent
CHIGORODO = (-76.80, 7.55, -76.55, 7.80)
NISAR = "NISAR · banda L"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    from components import nisar as ui
    nisar, analisis = tmp_path / "nisar", tmp_path / "analisis"
    (nisar / "crudos").mkdir(parents=True)
    monkeypatch.setattr(nisar_gcov, "CARPETA_NISAR", nisar)
    monkeypatch.setattr(ui, "CARPETA_CRUDOS", nisar / "crudos")
    monkeypatch.setattr(nisar_flujo, "CARPETA_NISAR", nisar)
    monkeypatch.setattr(nisar_flujo, "CARPETA_ANALISIS", analisis)
    monkeypatch.setattr(resultados, "CARPETA_ANALISIS", analisis)
    monkeypatch.chdir(RAIZ)
    return nisar, analisis


def app():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180).run()
    at.button(key="btn_sar").click().run()
    at.button_group(key="sar_sensor").select(NISAR).run()
    assert not at.exception, at.exception
    return at


def texto(at) -> str:
    return " ".join(m.value for m in at.markdown)


def test_sentinel1_sigue_siendo_el_flujo_por_defecto(entorno):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180).run()
    at.button(key="btn_sar").click().run()
    assert any(b.key == "sar_buscar" for b in at.button)
    assert not any(b.key == "nisar_buscar" for b in at.button)


def test_catalogo_muestra_candidatos_y_par_no_validado(entorno, monkeypatch):
    items = [item(granule("20261024T231500")), item(granule("20261105T231500"))]
    monkeypatch.setattr(cat, "consultar_cmr", lambda parametros, **k: {"items": items})
    at = app()
    at.button(key="nisar_buscar").click().run()
    assert not at.exception, at.exception
    t = texto(at)
    assert "CANDIDATO NO VALIDADO" in t and granule("20261024T231500") in t
    assert "banda L" in t and "no se descarga nada" in t


def test_catalogo_sin_par_explica_el_bloqueo(entorno, monkeypatch):
    items = [item(granule("20261024T231500")), item(granule("20261105T231500", track=49))]
    monkeypatch.setattr(cat, "consultar_cmr", lambda parametros, **k: {"items": items})
    at = app()
    at.button(key="nisar_buscar").click().run()
    t = texto(at)
    assert "Sin par temporal compatible" in t and "track distinto" in t and "CANDIDATO NO VALIDADO" not in t


def test_error_de_red_en_catalogo_no_rompe(entorno, monkeypatch):
    from utils.buscador_sar import ErrorConexion

    def falla(*a, **k):
        raise ErrorConexion("No se pudo conectar con el catálogo de NASA (CMR). Revisa la conexión.")
    monkeypatch.setattr(cat, "consultar_cmr", falla)
    at = app()
    at.button(key="nisar_buscar").click().run()
    assert not at.exception and "No se pudo conectar" in texto(at)


def test_recorte_y_analisis_exigen_umbrales_escritos(entorno):
    nisar, analisis = entorno
    for nombre, fecha, semilla in (("a", "2026-10-24T23:15:00", 1), ("b", "2026-11-05T23:15:00", 2)):
        sint.gcov(nisar / "crudos" / f"{nombre}.h5", fecha=fecha, semilla=semilla)
    at = app()
    for nombre in ("a.h5", "b.h5"):
        at.selectbox(key="nisar_h5").set_value(nombre).run()
        at.button(key="nisar_recortar").click().run()
        assert not at.exception, at.exception
    assert len(list(nisar.glob("nisar_gcov_*.tif"))) == 2
    assert at.button(key="nisar_analizar").disabled                    # sin umbrales no se analiza
    at.number_input(key="nisar_umbral_dis").set_value(3.0)
    at.number_input(key="nisar_umbral_aum").set_value(3.0).run()
    assert not at.button(key="nisar_analizar").disabled
    at.button(key="nisar_analizar").click().run()
    assert not at.exception, at.exception
    assert (analisis / "nisar_cambio_AHHHH_20261024_20261105_mascara.tif").is_file()
    at.button(key="nisar_ver_unica").click().run()
    assert not at.exception, at.exception
    unica = next(analisis.glob("nisar_gamma0_*_db.tif"))
    # Los tres productos se reconocen y, al venir de un GCOV sintético, son DEMO.
    for res in resultados.cargar_resultados():
        assert res.dibujable, (res.ruta.name, res.error)
        assert res.capa.procedencia.estado == "demo"
    assert resultados.leer_resultado(unica).perfil.clave == "retrodispersion_db"


def test_escena_unica_se_ve_y_se_exporta_con_su_propia_escala(entorno, tmp_path):
    nisar, analisis = entorno
    h5 = sint.gcov(nisar / "crudos" / "a.h5", mision="NISAR")
    recorte = nisar_gcov.exportar_recorte(h5, CHIGORODO)
    ruta = nisar_flujo.escena_unica(nisar_flujo.recortes_locales()[0][0])
    res = resultados.leer_resultado(ruta)
    assert res.perfil.clave == "retrodispersion_db" and res.perfil.continuo
    assert escala_de(res.perfil.clave) is ESCALA_GAMMA0 and escala_de("diferencia_db") is ESCALA_DIFERENCIA
    e = res.estadisticas
    assert e["mediana"] == pytest.approx(-7.0, abs=0.5) and e["pixeles_validos"] > 0
    rgba = colorizar_diferencia(np.ma.MaskedArray([[-30.0, 0.0, -12.0]], mask=[[False, False, True]]), ESCALA_GAMMA0)
    assert rgba[0, 0, :3].tolist() == [0x1C, 0x1C, 0x1E] and rgba[0, 1, :3].tolist() == [255, 255, 255]
    assert rgba[0, 0, 3] == rgba[0, 1, 3] == round(0.85 * 255) and rgba[0, 2, 3] == 0
    sha = qgis.hashlib.sha256(ruta.read_bytes()).hexdigest()
    _, paquete = qgis.exportar(ruta, (), res.nombre, continuo=True, escala=ESCALA_GAMMA0)
    assert qgis.verificar_paquete(paquete, ruta, (), continuo=True, escala=ESCALA_GAMMA0) == []
    assert qgis.verificar_paquete(paquete, ruta, (), continuo=True, escala=ESCALA_DIFERENCIA) != []
    assert 'classificationMin="-30"' in qgis.estilo_qml_continuo(ESCALA_GAMMA0)
    assert qgis.hashlib.sha256(ruta.read_bytes()).hexdigest() == sha
    with rasterio.open(recorte) as src:
        assert src.tags()["ESCALA"] == "power"                           # el recorte sigue en potencia


def test_la_diferencia_en_db_conserva_su_estilo():
    assert 'classificationMin="-10"' in qgis.estilo_qml_continuo()
    assert qgis.estilo_qml_continuo() == qgis.estilo_qml_continuo(ESCALA_DIFERENCIA)
