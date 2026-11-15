"""Pruebas sintéticas sin red de la puerta de publicación."""
import hashlib
import json

import numpy as np
import rasterio

from utils.v10_sentinel.publicacion import publicar_comparacion


GEOREF = {"crs": "EPSG:32618", "transform": (30, 0, 500000, 0, -30, 800000)}


def _publicar(tmp_path, resultado, **kwargs):
    return publicar_comparacion(
        resultado, GEOREF, "2026-10-01T00:00:00Z",
        "2026-10-12T00:00:00Z", "granulo_pre", "granulo_post",
        tmp_path / "salida.tif", **kwargs
    )


def test_no_publicar_sin_fuente_y_qa(tmp_path):
    resultado = {"estado": "APTA", "cobertura_qa_completa": True,
                 "clases": [[2]], "pixeles_totales": 1}
    assert _publicar(tmp_path, resultado)["estado"] == "NO_APTA"
    assert list(tmp_path.iterdir()) == []


def test_no_publicar_cobertura_parcial(tmp_path):
    resultado = {"estado": "NO_APTA", "cobertura_qa_completa": False,
                 "clases": None, "pixeles_totales": 2}
    salida = _publicar(tmp_path, resultado, qa_verificada=True,
                      fuente_verificada=True)
    assert salida["estado"] == "NO_APTA"
    assert not (tmp_path / "salida.tif").exists()


def test_geotiff_ficha_y_hash(tmp_path):
    resultado = {"estado": "APTA", "cobertura_qa_completa": True,
                 "clases": [[0, 1], [2, 255]], "pixeles_totales": 3}
    salida = _publicar(tmp_path, resultado, qa_verificada=True,
                      fuente_verificada=True)
    assert salida["estado"] == "APTA"
    with rasterio.open(salida["geotiff"]) as ds:
        assert ds.crs.to_epsg() == 32618
        assert tuple(ds.transform)[:6] == GEOREF["transform"]
        assert ds.nodata == 255
        assert np.array_equal(ds.read(1), np.array([[0, 1], [2, 255]]))
    ficha = json.loads((tmp_path / "salida.visor.ficha.v1.json").read_text())
    assert ficha["schema"] == "visor.ficha.v1"
    assert ficha["sha256"] == hashlib.sha256(
        (tmp_path / "salida.tif").read_bytes()
    ).hexdigest()
    assert "no inundacion confirmada" in ficha["advertencia"]


def test_no_publicar_conteos_inconsistentes(tmp_path):
    resultado = {"estado": "APTA", "cobertura_qa_completa": True,
                 "clases": [[2, 255]], "pixeles_totales": 2}
    assert _publicar(tmp_path, resultado, qa_verificada=True,
                    fuente_verificada=True)["estado"] == "NO_APTA"
    assert not (tmp_path / "salida.tif").exists()
