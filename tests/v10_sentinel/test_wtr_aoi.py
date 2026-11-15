"""Regresiones de máscara AOI para comparación WTR sintética sin red."""
import pytest

from utils.v10_sentinel.wtr import comparar_wtr

GEO = {"crs": "EPSG:32618", "transform": (30.0, 0.0, 500000.0, 0.0, -30.0, 900000.0)}



def _comparar(mask, qa_post=None):
    return comparar_wtr(
        [[1, 99], [0, 99]],
        [[1, 99], [1, 99]],
        [[True, False], [True, False]],
        qa_post or [[True, False], [True, False]],
        codigos={"agua": 1, "no_agua": 0},
        version_verificada=True, georef_anterior=GEO, georef_posterior=GEO,
        mascara_aoi=mask,
    )


def test_fuera_aoi_no_bloquea_cobertura():
    r = _comparar([[True, False], [True, False]])
    assert r["estado"] == "APTA"
    assert r["clases"] == [[1, 255], [2, 255]]
    assert r["pixeles_totales"] == 2
    assert r["pixeles_fuera_aoi"] == 2


def test_qa_faltante_dentro_aoi_rechaza():
    r = _comparar([[True, False], [True, False]], [[True, False], [False, False]])
    assert r["estado"] == "NO_APTA"
    assert r["clases"] is None
    assert r["pixeles_validos"] == 1


@pytest.mark.parametrize("mask", [
    [[False, False], [False, False]],
    [[True]],
    [[1, False], [True, False]],
])
def test_mascara_invalida_rechazada(mask):
    with pytest.raises(ValueError):
        _comparar(mask)
