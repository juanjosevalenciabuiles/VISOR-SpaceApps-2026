"""Invariantes del motor SAR sobre casos con resultado conocido de antemano.

Cada prueba fija la entrada (potencia, NoData, umbral) y comprueba números
exactos: CRS y cuadrícula de salida, NoData, dB, clases, superficies y
estadísticas. Datos sintéticos; no validan nada científicamente.
"""
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))

from test_combinacion_sar import RES, X0, Y0, rtc  # noqa: E402
from utils.analisis_sar import (  # noqa: E402
    AUMENTO, BAJA_EN_AMBAS, DISMINUCION, NODATA_MASCARA, SIN_CAMBIO, ParametrosCambio, analizar_par,
)

AREA_PIXEL_HA = RES * RES / 10_000           # 30 m → 0,09 ha


def par(tmp_path, antes, despues, umbral=3.0, nombre="VV", oscuro=None):
    a = rtc(tmp_path / f"S1C_IW_20260924T231502_DVP_RTC30_G_gpuned_1A2B_{nombre}.tif", antes)
    d = rtc(tmp_path / f"S1C_IW_20261006T231503_DVP_RTC30_G_gpuned_3C4D_{nombre}.tif", despues)
    return analizar_par(a, d, tmp_path / "salida",
                        parametros=ParametrosCambio(umbral_disminucion_db=umbral, ventana_speckle=1,
                                                    umbral_oscuro_db=oscuro))


def leer(ruta):
    with rasterio.open(ruta) as src:
        return src.read(1), src.profile


@pytest.fixture
def caso(tmp_path):
    """60×60 px a −10 dB. Filas 0–9 bajan a −20 dB, 10–19 suben a 0 dB, 20–24 bajan solo 2 dB,
    30–34 en −25 dB en ambas fechas; fila 59 sin dato antes, fila 58 sin dato después.
    Umbral oscuro −20 dB (la clase «baja en ambas fechas» solo existe si se fija)."""
    antes = np.full((60, 60), 0.1, "float32")
    despues = antes.copy()
    despues[0:10] = 0.01
    despues[10:20] = 1.0
    despues[20:25] = 0.1 * 10 ** (-0.2)
    antes[30:35] = despues[30:35] = 10 ** -2.5
    antes[59] = 0.0
    despues[58] = 0.0
    return par(tmp_path, antes, despues, oscuro=-20.0)


def test_sin_umbral_oscuro_no_hay_clase_baja_en_ambas(tmp_path):
    antes = np.full((60, 60), 10 ** -2.5, "float32")
    r = par(tmp_path, antes, antes.copy())
    assert r.estadisticas["clases"][str(BAJA_EN_AMBAS)]["pixeles"] == 0


def test_cuadricula_crs_y_nodata_de_salida(caso):
    for ruta, nodata_esperado in ((caso.mascara, NODATA_MASCARA), (caso.diferencia, None)):
        datos, perfil = leer(ruta)
        assert perfil["crs"].to_epsg() == 32618 and (perfil["width"], perfil["height"]) == (60, 60)
        assert perfil["transform"].a == RES and perfil["transform"].c == X0 and perfil["transform"].f == Y0
        if nodata_esperado is not None:
            assert perfil["nodata"] == nodata_esperado and perfil["dtype"] == "uint8"
    mascara, _ = leer(caso.mascara)
    assert (mascara[58:60] == NODATA_MASCARA).all(), "NoData en cualquiera de las dos fechas → NoData"
    assert (mascara[:58] != NODATA_MASCARA).all()


def test_diferencia_en_db_exacta(caso):
    dif, perfil = leer(caso.diferencia)
    assert np.allclose(dif[0:10], -10.0, atol=1e-4)
    assert np.allclose(dif[10:20], 10.0, atol=1e-4)
    assert np.allclose(dif[20:25], -2.0, atol=1e-4)
    assert np.allclose(dif[40:50], 0.0, atol=1e-4)
    nodata = perfil["nodata"]
    sin = np.isnan(dif[58:60]) if nodata is None or np.isnan(nodata) else dif[58:60] == nodata
    assert sin.all()


def test_clases_con_umbral(caso):
    m, _ = leer(caso.mascara)
    assert (m[0:10] == DISMINUCION).all()
    assert (m[10:20] == AUMENTO).all()
    assert (m[20:25] == SIN_CAMBIO).all(), "−2 dB no supera el umbral de 3 dB"
    assert (m[30:35] == BAJA_EN_AMBAS).all()
    assert (m[40:50] == SIN_CAMBIO).all()


def test_estadisticas_y_superficies(caso):
    e = caso.estadisticas
    assert e["pixeles_totales"] == 3600 and e["pixeles_validos"] == 3600 - 120
    assert sum(c["pixeles"] for c in e["clases"].values()) == e["pixeles_validos"]
    assert e["clases"][str(DISMINUCION)]["pixeles"] == 600
    assert e["clases"][str(AUMENTO)]["pixeles"] == 600
    assert e["clases"][str(BAJA_EN_AMBAS)]["pixeles"] == 300
    for c in e["clases"].values():
        assert c["area_ha"] == pytest.approx(c["pixeles"] * AREA_PIXEL_HA, abs=0.01)
        assert c["porcentaje_de_validos"] == pytest.approx(100 * c["pixeles"] / e["pixeles_validos"], abs=0.001)
    assert e["diferencia_db"]["minimo"] == pytest.approx(-10.0, abs=1e-3)
    assert e["diferencia_db"]["maximo"] == pytest.approx(10.0, abs=1e-3)


def test_el_umbral_cambia_la_clasificacion_de_forma_monotona(tmp_path):
    """Con un umbral más estricto nunca hay MÁS píxeles de disminución (como VV −7,5 dB frente a −3 dB)."""
    antes = np.full((60, 60), 0.1, "float32")
    despues = antes * (10 ** (-np.linspace(0, 1.2, 60, dtype="float32")))[None, :]   # 0 a −12 dB por columna
    conteos = []
    for umbral in (3.0, 5.0, 7.5, 10.0):
        (tmp_path / str(umbral)).mkdir()
        r = par(tmp_path / str(umbral), antes, despues.astype("float32"), umbral=umbral)
        conteos.append(r.estadisticas["clases"][str(DISMINUCION)]["pixeles"])
    assert conteos == sorted(conteos, reverse=True) and conteos[0] > conteos[-1] > 0


def test_las_entradas_no_se_modifican(tmp_path):
    import hashlib
    antes = np.full((60, 60), 0.1, "float32")
    a = rtc(tmp_path / "S1C_IW_20260924T231502_DVP_RTC30_G_gpuned_1A2B_VH.tif", antes)
    d = rtc(tmp_path / "S1C_IW_20261006T231503_DVP_RTC30_G_gpuned_3C4D_VH.tif", antes * 0.5)
    huellas = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (a, d)]
    analizar_par(a, d, tmp_path / "o", parametros=ParametrosCambio(ventana_speckle=3))
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (a, d)] == huellas
