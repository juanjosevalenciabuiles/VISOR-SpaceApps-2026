"""Diferencia de retrodispersión en dB (`…_dif_db.tif`) como producto continuo visualizable.

El archivo se genera con el motor real sobre RTC sintéticos; nunca se modifica.
"""
import hashlib
import io
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))

from test_combinacion_sar import rtc  # noqa: E402
from components import mapa  # noqa: E402
from components import resultados as ui  # noqa: E402
from components.barra_lateral import Controles  # noqa: E402
from utils import procedencia, qgis  # noqa: E402
from utils import resultados as r  # noqa: E402
from utils import verificacion as v  # noqa: E402
from utils.analisis_sar import ParametrosCambio, analizar_par  # noqa: E402
from utils.config import FENOMENOS  # noqa: E402
from utils.diferencia_db import ALFA_MIN, colorizar_diferencia  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def motor(tmp_path):
    """Δ conocido: filas 0–9 −10 dB, 10–19 +10 dB, 20–24 −20 dB (satura), resto 0; fila 59 sin dato."""
    antes = np.full((60, 60), 0.1, "float32")
    despues = antes.copy()
    despues[0:10] = 0.01
    despues[10:20] = 1.0
    despues[20:25] = 0.001
    antes[59] = 0.0
    a = rtc(tmp_path / "S1C_IW_20260924T231502_DVP_RTC30_G_gpuned_1A2B_VV.tif", antes)
    d = rtc(tmp_path / "S1C_IW_20261006T231503_DVP_RTC30_G_gpuned_3C4D_VV.tif", despues)
    return analizar_par(a, d, tmp_path / "analisis", parametros=ParametrosCambio(ventana_speckle=1), guardar_db=True)


def test_se_identifica_solo_la_diferencia(motor):
    assert r.leer_resultado(motor.diferencia).perfil.clave == "diferencia_db"
    assert r.leer_resultado(motor.mascara).perfil.clave == "mascara_cambios"
    for extra in motor.extras.values():                           # retrodispersión de cada fecha: no es Δ
        assert not r.leer_resultado(extra).dibujable


def test_carga_y_estadisticas_sin_modificar_el_archivo(motor):
    antes = sha(motor.diferencia)
    res = r.leer_resultado(motor.diferencia)
    assert res.dibujable and res.perfil.continuo and res.perfil.unidades == "dB"
    e = res.estadisticas
    assert e["pixeles_totales"] == 3600 and e["pixeles_sin_dato"] == 60 and e["nodata"] == -9999.0
    assert e["minimo"] == pytest.approx(-20.0, abs=1e-3) and e["maximo"] == pytest.approx(10.0, abs=1e-3)
    assert e["mediana"] == pytest.approx(0.0, abs=1e-3) and e["fuera_de_rango"] == 300
    assert res.capa.procedencia.estado == procedencia.NO_DECLARADA          # el motor no escribe ficha
    assert sha(motor.diferencia) == antes


def test_rampa_divergente_y_transparencias():
    datos = np.ma.MaskedArray(np.array([[-10.0, 0.0, 10.0, -30.0, 25.0, 3.0]]),
                              mask=[[False, False, False, False, False, True]])
    copia = datos.copy()
    rgba = colorizar_diferencia(datos)
    assert tuple(rgba[0, 0]) == (10, 132, 255, 255)                  # −10 dB: azul intenso, opaco
    assert tuple(rgba[0, 2]) == (255, 69, 58, 255)                   # +10 dB: rojo, opaco
    assert tuple(rgba[0, 1, :3]) == (199, 199, 204) and rgba[0, 1, 3] == round(ALFA_MIN * 255)
    assert tuple(rgba[0, 3]) == tuple(rgba[0, 0]) and tuple(rgba[0, 4]) == tuple(rgba[0, 2])   # satura
    assert rgba[0, 5, 3] == 0                                         # NoData transparente
    assert (rgba[0, :5, 3] > 0).all()                                 # ningún válido se oculta
    assert np.array_equal(datos.data, copia.data)


def test_mapa_ficha_y_leyenda(motor):
    res = r.leer_resultado(motor.diferencia)
    c = Controles("inundacion", True, 0.85, False, False, resultados={res.id: 0.7})
    grupos = mapa.construir_capas(FENOMENOS["inundacion"], None, c, [res])
    assert grupos[-1].layer_name == "Resultado · Diferencia de retrodispersión (dB)"
    html = ui.ficha_html(res)
    for frase in ("Estadísticas de Δ", "No aplica: dato continuo sin umbral", "No es una inundación confirmada",
                  "PROCEDENCIA NO DECLARADA", "−20,00 dB", "sin filtro de speckle"):
        assert frase in html, frase
    assert "<th>Clase</th>" not in html
    leyenda = ui.leyenda_html(res)
    assert "linear-gradient" in leyenda and "#0A84FF" in leyenda and "−10" in leyenda and "(transparente)" in leyenda


def test_exportacion_qgis_pseudocolor(motor):
    antes = sha(motor.diferencia)
    nombre, datos = qgis.exportar(motor.diferencia, (), "Diferencia", continuo=True)
    assert qgis.verificar_paquete(datos, motor.diferencia, (), continuo=True) == []
    assert qgis.verificar_paquete(datos, motor.diferencia, (), continuo=False) != []   # no se confunde con paleta
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        qml = next(z.read(n) for n in z.namelist() if n.endswith(".qml")).decode()
        leeme = next(z.read(n) for n in z.namelist() if n.endswith("LEEME_QGIS.txt")).decode()
    render = ET.fromstring(qml.split("\n", 1)[1]).find("pipe/rasterrenderer")
    assert render.get("type") == "singlebandpseudocolor"
    assert (render.get("classificationMin"), render.get("classificationMax")) == ("-10", "10")
    assert [i.get("value") for i in render.iter("item")] == ["-10", "-5", "0", "5", "10"]
    assert "sin umbral" in leeme
    assert sha(motor.diferencia) == antes


def test_verificador_lo_aprueba_sin_advertencia_de_perfil(motor):
    inf = v.Informe()
    v.auditar_resultados(inf, motor.diferencia.parent, None)
    dif = [c for c in inf.comprobaciones if "dif_db" in c.descripcion]
    assert dif and all(c.estado == v.APROBADA for c in dif), [(c.id, c.estado, c.detalle) for c in dif]
    assert not any("no reconocido" in c.detalle for c in inf.comprobaciones if "dif_db" in c.descripcion)


def test_estadisticas_grandes_se_marcan_aproximadas(motor, monkeypatch):
    from utils import diferencia_db
    exacto = diferencia_db.describir_continuo(motor.diferencia)
    assert exacto["aproximado"] is False
    monkeypatch.setattr(diferencia_db, "MAX_PIXELES_EXACTOS", 900)     # fuerza la lectura reducida
    aprox = diferencia_db.describir_continuo(motor.diferencia)
    assert aprox["aproximado"] is True and aprox["pixeles_totales"] == 3600
    assert abs(aprox["pixeles_validos"] - exacto["pixeles_validos"]) <= 120
    assert aprox["minimo"] == pytest.approx(-20.0, abs=0.5) and aprox["maximo"] == pytest.approx(10.0, abs=0.5)
    res = r.leer_resultado(motor.diferencia)
    res.estadisticas = aprox
    assert "APROXIMADO" in ui.ficha_html(res)


def test_el_raster_se_lee_una_sola_vez(motor, monkeypatch):
    llamadas = []
    original = r.leer_geotiff
    monkeypatch.setattr(r, "leer_geotiff", lambda ruta, **k: llamadas.append(k) or original(ruta, **k))
    r.leer_resultado(motor.diferencia)
    r.leer_resultado(motor.mascara)
    assert llamadas == [{"categorico": False}, {"categorico": True}]


def test_la_imagen_del_mapa_se_reutiliza_y_respeta_la_opacidad(motor):
    from streamlit.runtime.caching import cache_data_api  # noqa: F401  (caché en memoria fuera de la app)
    res = r.leer_resultado(motor.diferencia)
    mapa.imagen_resultado.clear()
    a = mapa.grupo_resultado(res, 0.3)
    b = mapa.grupo_resultado(res, 0.9)
    ia, ib = (next(iter(g._children.values())) for g in (a, b))
    assert ia.url == ib.url and ia.url.startswith("data:image/png;base64,")
    assert (ia.options["opacity"], ib.options["opacity"]) == (0.3, 0.9)
