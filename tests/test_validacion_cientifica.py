"""Validación científica del motor SAR con verdad conocida.

Escenas sintéticas cuyo resultado correcto se conoce de antemano: un parche
que pierde exactamente 6 dB, speckle multiplicativo con estadística gamma,
CRS en pies, huellas SHA-256 y reconstrucción de la máscara desde el GeoTIFF
continuo en dB. No usa datos reales ni red.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine, from_origin

from utils import analisis_sar as sar
from utils.analisis_sar import ErrorSAR, ParametrosCambio, analizar_par, area_pixel_ha
from utils.procedencia import sha256_archivo

X0, Y0, RES = 300_000.0, 850_000.0, 30.0       # UTM 18N, cerca de Urabá
N = 120
PARCHE = (slice(40, 80), slice(40, 80))       # 40×40 px que se oscurecen
CAIDA_DB = -6.0


def _tif(ruta, datos, crs="EPSG:32618", transform=None, nodata=0.0):
    with rasterio.open(ruta, "w", driver="GTiff", height=datos.shape[0], width=datos.shape[1], count=1,
                       dtype="float32", crs=crs, transform=transform or from_origin(X0, Y0, RES, RES),
                       nodata=nodata) as f:
        f.write(datos.astype("float32"), 1)
    return ruta


def _par(tmp_path, speckle_looks=None, semilla=7):
    """Antes: −8 dB uniforme. Después: igual, salvo el parche (−14 dB)."""
    base = np.full((N, N), 10 ** (-8 / 10), dtype="float64")
    despues = base.copy()
    despues[PARCHE] *= 10 ** (CAIDA_DB / 10)
    if speckle_looks:
        rng = np.random.default_rng(semilla)
        ruido = lambda: rng.gamma(speckle_looks, 1 / speckle_looks, size=base.shape)  # noqa: E731
        base, despues = base * ruido(), despues * ruido()
    a = _tif(tmp_path / "S1A_IW_20260924T232218_DVP_RTC30_G_gpuned_AAAA_VV.tif", base)
    d = _tif(tmp_path / "S1A_IW_20261006T232218_DVP_RTC30_G_gpuned_BBBB_VV.tif", despues)
    return a, d


def _leer(ruta):
    with rasterio.open(ruta) as src:
        return src.read(1, masked=True), src.profile


# ---------------------------------------------------------------------------
# Radiometría
# ---------------------------------------------------------------------------

def test_conversiones_ida_y_vuelta():
    db = np.ma.MaskedArray(np.array([[-25.0, -12.5, 0.0, 3.0]], dtype="float32"))
    for escala, valores in (("db", db.data), ("power", 10 ** (db.data / 10)), ("amplitude", 10 ** (db.data / 20))):
        vuelta = sar.potencia_a_db(sar.a_potencia(np.ma.MaskedArray(valores.astype("float32")), escala))
        np.testing.assert_allclose(vuelta.data, db.data, atol=1e-4, err_msg=escala)
        assert not vuelta.mask.any()


def test_la_diferencia_de_db_es_la_razon_de_potencias():
    antes = np.ma.MaskedArray(np.array([[0.1, 0.02]], dtype="float32"))
    despues = np.ma.MaskedArray(np.array([[0.025, 0.02]], dtype="float32"))
    dif = sar.diferencia_db(sar.potencia_a_db(antes), sar.potencia_a_db(despues))
    np.testing.assert_allclose(dif.data, 10 * np.log10(np.array([[0.25, 1.0]])), atol=1e-5)
    assert dif.data[0, 0] < 0          # menos retrodispersión = negativo


def test_filtro_conserva_la_media_y_la_positividad_con_contraste_extremo():
    p = np.full((60, 60), 1e-4, dtype="float32")
    p[:, :30] = 1e3                     # +30 dB junto a −40 dB
    f = sar.filtrar_speckle(np.ma.MaskedArray(p), 7)
    assert float(f.min()) > 0
    np.testing.assert_allclose(f.data[:, 40:], 1e-4, rtol=1e-3)   # lejos del borde no cambia
    np.testing.assert_allclose(f.data[:, :20], 1e3, rtol=1e-6)


def test_el_filtro_reduce_la_varianza_del_speckle_como_predice_la_teoria():
    rng = np.random.default_rng(1)
    looks = 4
    p = rng.gamma(looks, 1 / looks, size=(300, 300)).astype("float32")
    f = sar.filtrar_speckle(np.ma.MaskedArray(p), 5).data[10:-10, 10:-10]
    # Media de 25 muestras independientes: la varianza cae ~25 veces.
    assert abs(float(f.mean()) - 1.0) < 0.01
    razon = float(p.var()) / float(f.var())
    assert 20 < razon < 30


# ---------------------------------------------------------------------------
# Verdad conocida de extremo a extremo
# ---------------------------------------------------------------------------

def test_cambio_exacto_sin_ruido(tmp_path):
    a, d = _par(tmp_path)
    r = analizar_par(a, d, tmp_path / "out", parametros=ParametrosCambio(3.0, 3.0, 1))
    dif, perfil = _leer(r.diferencia)
    np.testing.assert_allclose(dif[PARCHE], CAIDA_DB, atol=1e-4)
    fuera = dif.copy()
    fuera[PARCHE] = np.ma.masked
    np.testing.assert_allclose(fuera.compressed(), 0.0, atol=1e-4)
    assert perfil["dtype"] == "float32" and perfil["nodata"] == sar.NODATA_DB

    masc, _ = _leer(r.mascara)
    assert (masc[PARCHE] == sar.DISMINUCION).all()
    assert int((masc == sar.DISMINUCION).sum()) == 40 * 40
    e = r.estadisticas
    assert e["clases"][str(sar.DISMINUCION)]["area_ha"] == pytest.approx(1600 * 0.09)  # 30 m × 30 m = 0,09 ha
    assert sum(c["pixeles"] for c in e["clases"].values()) == N * N
    assert sum(c["porcentaje_de_validos"] for c in e["clases"].values()) == pytest.approx(100, abs=0.01)


def test_cambio_con_speckle_se_detecta_con_alta_precision(tmp_path):
    a, d = _par(tmp_path, speckle_looks=4.9)    # ENL típico de un RTC a 30 m
    r = analizar_par(a, d, tmp_path / "out", parametros=ParametrosCambio(3.0, 3.0, 5))
    masc = _leer(r.mascara)[0].filled(sar.NODATA_MASCARA)
    interior = (slice(43, 77), slice(43, 77))   # lejos del borde del parche (ventana 5)
    exterior = np.ones_like(masc, bool)
    exterior[36:84, 36:84] = False
    acierto = float((masc[interior] == sar.DISMINUCION).mean())
    falsos = float((masc[exterior] != sar.SIN_CAMBIO).mean())
    assert acierto > 0.97, acierto
    assert falsos < 0.02, falsos


def test_la_mascara_se_reconstruye_desde_el_geotiff_continuo(tmp_path):
    """Las dos salidas son coherentes: aplicar los mismos umbrales al
    `_dif_db.tif` reproduce exactamente `_mascara.tif`."""
    a, d = _par(tmp_path, speckle_looks=4.9)
    parametros = ParametrosCambio(3.0, 2.5, 3)
    r = analizar_par(a, d, tmp_path / "out", parametros=parametros)
    dif, _ = _leer(r.diferencia)
    masc, _ = _leer(r.mascara)
    rehecha = sar.mascara_cambios(dif, parametros)
    np.testing.assert_array_equal(rehecha, masc.filled(sar.NODATA_MASCARA))
    assert json.loads(r.informe.read_text(encoding="utf-8"))["parametros"] == {
        "umbral_disminucion_db": 3.0, "umbral_aumento_db": 2.5, "ventana_speckle": 3, "umbral_oscuro_db": None}


def test_nodata_de_entrada_se_conserva_en_ambas_salidas(tmp_path):
    a, d = _par(tmp_path)
    with rasterio.open(d, "r+") as f:
        datos = f.read(1)
        datos[:10, :] = 0.0                     # sin dato en HyP3
        f.write(datos, 1)
    r = analizar_par(a, d, tmp_path / "out", parametros=ParametrosCambio(3.0, 3.0, 1))
    dif, _ = _leer(r.diferencia)
    masc, _ = _leer(r.mascara)
    assert dif.mask[:10, :].all() and not dif.mask[10:, :].any()
    assert masc.mask[:10, :].all()
    assert r.estadisticas["pixeles_validos"] == (N - 10) * N


# ---------------------------------------------------------------------------
# Cuadrícula y superficies
# ---------------------------------------------------------------------------

def test_area_del_pixel_segun_las_unidades_del_crs():
    t = Affine(30.0, 0, 0, 0, -30.0, 0)
    assert area_pixel_ha(CRS.from_epsg(32618), t) == pytest.approx(0.09)
    # EPSG:2229 está en pies de agrimensor: 30 ft × 30 ft ≈ 0,00836 ha, no 0,09.
    assert area_pixel_ha(CRS.from_epsg(2229), t) == pytest.approx(0.09 * 0.3048006096 ** 2, rel=1e-9)
    assert area_pixel_ha(CRS.from_epsg(4326), Affine(0.0003, 0, 0, 0, -0.0003, 0)) is None
    assert area_pixel_ha(None, t) is None


def test_un_crs_geografico_no_inventa_hectareas(tmp_path):
    t = from_origin(-76.8, 7.9, 0.0003, 0.0003)
    base = np.full((40, 40), 0.1, dtype="float32")
    a = _tif(tmp_path / "S1A_IW_20260924T232218_DVP_RTC30_G_gpuned_AAAA_VV.tif", base, "EPSG:4326", t)
    d = _tif(tmp_path / "S1A_IW_20261006T232218_DVP_RTC30_G_gpuned_BBBB_VV.tif", base * 0.2, "EPSG:4326", t)
    r = analizar_par(a, d, tmp_path / "out", parametros=ParametrosCambio(3.0, 3.0, 1))
    assert all(c["area_ha"] is None for c in r.estadisticas["clases"].values())


# ---------------------------------------------------------------------------
# Procedencia y no sobrescritura
# ---------------------------------------------------------------------------

def test_el_informe_registra_huellas_de_entradas_y_salidas(tmp_path):
    a, d = _par(tmp_path)
    r = analizar_par(a, d, tmp_path / "out", parametros=ParametrosCambio(3.0, 3.0, 1, umbral_oscuro_db=-20.0),
                     guardar_db=True)
    informe = json.loads(r.informe.read_text(encoding="utf-8"))
    assert informe["entradas"]["antes"]["sha256"] == sha256_archivo(a)
    assert informe["entradas"]["despues"]["sha256"] == sha256_archivo(d)
    huellas = informe["huellas_sha256"]
    for ruta in (r.diferencia, r.mascara, *r.extras.values()):
        assert huellas[ruta.name] == sha256_archivo(ruta)
    assert any("Señal baja en ambas fechas" in paso for paso in informe["metodo"])


def test_repetir_un_analisis_no_reemplaza_el_anterior(tmp_path):
    a, d = _par(tmp_path)
    salida = tmp_path / "out"
    primero = analizar_par(a, d, salida, parametros=ParametrosCambio(3.0, 3.0, 1))
    huella = sha256_archivo(primero.mascara)
    segundo = analizar_par(a, d, salida, parametros=ParametrosCambio(5.0, 5.0, 1))
    assert segundo.mascara.name.startswith(primero.mascara.name.removesuffix("_mascara.tif") + "_r2")
    assert sha256_archivo(primero.mascara) == huella


def test_prefijo_explicito_ocupado_se_detiene_salvo_que_se_pida(tmp_path):
    a, d = _par(tmp_path)
    salida = tmp_path / "out"
    analizar_par(a, d, salida, prefijo="caso", parametros=ParametrosCambio(3.0, 3.0, 1))
    huella = sha256_archivo(salida / "caso_mascara.tif")
    with pytest.raises(ErrorSAR, match="Ya existen resultados"):
        analizar_par(a, d, salida, prefijo="caso", parametros=ParametrosCambio(5.0, 5.0, 1))
    assert sha256_archivo(salida / "caso_mascara.tif") == huella
    analizar_par(a, d, salida, prefijo="caso", parametros=ParametrosCambio(5.0, 5.0, 1), sobrescribir=True)
    assert sha256_archivo(salida / "caso_mascara.tif") != huella
