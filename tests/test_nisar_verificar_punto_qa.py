"""Verificación de un punto de interés frente a un raster QA NISAR local."""
from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform

from scripts.nisar_verificar_punto_qa import verificar


def _crear(tmp_path, *, declarar=True):
    ruta = tmp_path / "cobertura.tif"
    with rasterio.open(ruta, "w", driver="GTiff", count=1, width=4, height=4,
                       crs="EPSG:32618", dtype="uint8", nodata=0,
                       transform=from_origin(310000, 850000, 10, 10)) as out:
        x = np.zeros((4, 4), dtype="uint8")
        x[1, 2] = 3
        x[2, 2] = 1
        out.write(x, 1)
        if declarar:
            out.update_tags(AREA="COBERTURA_QA_NISAR_NO_INUNDACION")
    return ruta


def _lonlat(x, y):
    lon, lat = transform("EPSG:32618", "EPSG:4326", [x], [y])
    return lon[0], lat[0]


def test_punto_con_par_valido(tmp_path):
    ruta = _crear(tmp_path)
    lon, lat = _lonlat(310025, 849985)
    r = verificar(ruta, lon, lat)
    assert r["clase_qa"] == 3
    assert r["puede_comparar_ambas_fechas"] is True
    assert "NO_INUNDACION" in r["estado"]


def test_punto_solo_una_fecha_o_sin_cobertura(tmp_path):
    ruta = _crear(tmp_path)
    lon1, lat1 = _lonlat(310025, 849975)
    solo = verificar(ruta, lon1, lat1)
    assert solo["clase_qa"] == 1
    assert not solo["puede_comparar_ambas_fechas"]
    lon0, lat0 = _lonlat(310005, 849995)
    sin = verificar(ruta, lon0, lat0)
    assert sin["clase_qa"] == 0 and not sin["puede_comparar_ambas_fechas"]


def test_fuera_raster_no_se_confunde_con_qa_cero(tmp_path):
    ruta = _crear(tmp_path)
    lon, lat = _lonlat(311000, 850000)
    r = verificar(ruta, lon, lat)
    assert r["en_cuadricula"] is False
    assert r["clase_qa"] is None
    assert not r["puede_comparar_ambas_fechas"]


def test_rechaza_geotiff_que_no_declara_qa(tmp_path):
    ruta = _crear(tmp_path, declarar=False)
    lon, lat = _lonlat(310005, 849995)
    with pytest.raises(ValueError, match="no declara ser cobertura QA"):
        verificar(ruta, lon, lat)
