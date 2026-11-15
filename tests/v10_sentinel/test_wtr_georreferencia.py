"""Regresiones críticas de alineación WTR: metadatos de GeoTIFF, no solo matrices."""
import pytest

from utils.v10_sentinel.wtr import comparar_wtr

GRID = {"crs": "EPSG:32618", "transform": (30, 0, 500000, 0, -30, 900000)}


def _comparar(anterior, posterior):
    return comparar_wtr(
        [[0, 1]], [[1, 1]], [[True, True]], [[True, True]],
        codigos={"agua": 1, "no_agua": 0}, version_verificada=True,
        georef_anterior=anterior, georef_posterior=posterior,
    )


def test_grillas_iguales_producen_agua_observada():
    r = _comparar(GRID, dict(GRID))
    assert r["estado"] == "APTA"
    assert r["clases"] == [[2, 1]]


@pytest.mark.parametrize("post", [
    {"crs": "EPSG:32618", "transform": (30, 0, 500030, 0, -30, 900000)},
    {"crs": "EPSG:32619", "transform": (30, 0, 500000, 0, -30, 900000)},
    {"crs": "EPSG:32618", "transform": (20, 0, 500000, 0, -20, 900000)},
])
def test_mismas_dimensiones_distinta_geografia_rechazadas(post):
    with pytest.raises(ValueError, match="desalineadas|CRS distintos"):
        _comparar(GRID, post)


def test_sin_crs_o_transform_no_genera_mapa():
    with pytest.raises(ValueError, match="SIN_GEOREFERENCIA"):
        _comparar(GRID, None)
    with pytest.raises(ValueError, match="SIN_GEOREFERENCIA"):
        _comparar({"crs": "EPSG:32618"}, GRID)


def test_transform_nan_inf_o_degenerado_rechazado():
    for transform in ((30, 0, float("nan"), 0, -30, 900000),
                      (0, 0, 500000, 0, 0, 900000)):
        with pytest.raises(ValueError, match="inválida|degenerada"):
            _comparar(GRID, {**GRID, "transform": transform})


def test_epsg_equivalente_reconocido():
    r = _comparar(GRID, {"crs": 32618, "transform": GRID["transform"]})
    assert r["clases"] == [[2, 1]]
