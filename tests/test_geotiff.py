"""Pruebas básicas del cargador GeoTIFF.  Ejecutar con:  pytest"""
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.config import FENOMENOS  # noqa: E402
from utils.geotiff import ErrorCapa, a_web_mercator, colorizar, leer_geotiff  # noqa: E402

NODATA = -9999.0


def crear_tif(ruta, crs="EPSG:4326", limites=(-76.0, 6.0, -75.0, 7.0), lado=50, tags=None, datos=None):
    if datos is None:
        datos = np.linspace(0, 1, lado * lado, dtype="float32").reshape(lado, lado)
        datos[:5, :] = NODATA
    with rasterio.open(
        ruta, "w", driver="GTiff", height=datos.shape[0], width=datos.shape[1], count=1,
        dtype="float32", crs=crs, nodata=NODATA,
        transform=from_bounds(*limites, datos.shape[1], datos.shape[0]),
    ) as dst:
        dst.write(datos, 1)
        if tags:
            dst.update_tags(**tags)
    return ruta


def test_lee_wgs84_y_enmascara_nodata(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "a.tif"))
    assert not capa.reproyectada
    assert capa.limites == pytest.approx((-76.0, 6.0, -75.0, 7.0))
    assert capa.datos.mask[:5, :].all()
    assert not capa.datos.mask[10:, :].any()
    assert capa.rango[0] >= 0  # el NoData no contamina el rango


def test_reproyecta_utm_a_wgs84(tmp_path):
    # UTM 18N: rectángulo cerca de Medellín
    ruta = crear_tif(tmp_path / "utm.tif", crs="EPSG:32618", limites=(420000, 670000, 470000, 720000))
    capa = leer_geotiff(ruta)
    assert capa.reproyectada and capa.crs_original == "EPSG:32618"
    oeste, sur, este, norte = capa.limites
    assert -76.0 < oeste < este < -75.0 and 6.0 < sur < norte < 7.0
    assert not capa.avisos


def test_nan_se_trata_como_sin_dato(tmp_path):
    datos = np.ones((20, 20), dtype="float32")
    datos[0, 0] = np.nan
    capa = leer_geotiff(crear_tif(tmp_path / "nan.tif", datos=datos))
    assert capa.datos.mask[0, 0]


def test_reduce_rasters_grandes(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "g.tif", lado=400), max_lado=100)
    assert max(capa.datos.shape) == 100
    assert capa.forma_original == (400, 400)


def test_avisa_si_queda_fuera_de_antioquia(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "f.tif", limites=(10.0, 40.0, 11.0, 41.0)))
    assert any("fuera" in a for a in capa.avisos)


def test_etiqueta_demo(tmp_path):
    assert leer_geotiff(crear_tif(tmp_path / "d.tif", tags={"VISOR_DEMO": "1"})).es_demo
    assert not leer_geotiff(crear_tif(tmp_path / "r.tif")).es_demo


def test_json_lateral_aporta_metadatos(tmp_path):
    crear_tif(tmp_path / "m.tif")
    (tmp_path / "m.json").write_text('{"fecha": "2026-05-01", "fuente": "Sentinel-1"}', encoding="utf-8")
    capa = leer_geotiff(tmp_path / "m.tif")
    assert capa.metadatos["FECHA"] == "2026-05-01"


def test_errores_legibles(tmp_path):
    with pytest.raises(ErrorCapa, match="No se encontró"):
        leer_geotiff(tmp_path / "no_existe.tif")

    (tmp_path / "roto.tif").write_bytes(b"esto no es un tif")
    with pytest.raises(ErrorCapa, match="no es un GeoTIFF"):
        leer_geotiff(tmp_path / "roto.tif")

    with rasterio.open(tmp_path / "sin_crs.tif", "w", driver="GTiff", height=5, width=5, count=1, dtype="float32") as d:
        d.write(np.ones((5, 5), dtype="float32"), 1)
    with pytest.raises(ErrorCapa, match="CRS"):
        leer_geotiff(tmp_path / "sin_crs.tif")

    todo_nodata = np.full((10, 10), NODATA, dtype="float32")
    with pytest.raises(ErrorCapa, match="píxeles válidos"):
        leer_geotiff(crear_tif(tmp_path / "vacio.tif", datos=todo_nodata))


def test_colorizar_transparencia(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "c.tif"))
    rgba = colorizar(capa.datos, ("#000000", "#00F0FF"))
    assert rgba.shape == capa.datos.shape + (4,) and rgba.dtype == np.uint8
    assert (rgba[:5, :, 3] == 0).all()   # NoData transparente
    assert rgba[-1, -1, 3] == 255        # máximo indicio, opaco
    assert tuple(rgba[-1, -1, :3]) == (0, 240, 255)


def test_colorizar_invertido(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "i.tif"))
    rgba = colorizar(capa.datos, ("#000000", "#FFFFFF"), invertir=True)
    assert rgba[5, 0, 3] > rgba[-1, -1, 3]


def test_configuracion_de_fenomenos():
    assert set(FENOMENOS) == {"inundacion", "deslizamiento", "deforestacion"}
    for f in FENOMENOS.values():
        assert f.archivo.endswith(".tif") and len(f.colores) >= 2 and f.advertencias


def test_a_web_mercator_conserva_colores_y_forma():
    rgba = np.zeros((40, 10, 4), dtype="uint8")
    rgba[:20] = (255, 45, 85, 255)  # mitad norte de color
    salida = a_web_mercator(rgba, sur=5.0, norte=9.0)
    assert salida.shape == rgba.shape and salida.dtype == np.uint8
    assert tuple(salida[0, 0]) == (255, 45, 85, 255) and salida[-1, 0, 3] == 0
    assert set(map(tuple, salida.reshape(-1, 4))) == {(255, 45, 85, 255), (0, 0, 0, 0)}
    assert abs(int((salida[:, 0, 3] > 0).sum()) - 20) <= 1  # casi sin distorsión a esta latitud
