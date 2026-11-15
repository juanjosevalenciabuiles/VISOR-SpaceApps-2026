"""Fixtures sintéticos sin red: no son observaciones reales."""
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from utils.procedencia import REAL_SIN_VALIDAR, evaluar, sha256_archivo
from utils.v9_datos.cambio_cog import QAInsuficiente, procesar_par


def escena(tmp_path, nombre, gamma=1.0, qa=1, looks=4.0):
    def guardar(tipo, valor, dtype, nodata):
        ruta = tmp_path / f"{nombre}_{tipo}.tif"
        with rasterio.open(ruta, "w", driver="GTiff", width=4, height=4,
                           count=1, dtype=dtype, crs="EPSG:32618",
                           transform=from_origin(450000, 800000, 30, 30),
                           nodata=nodata) as ds:
            ds.write(np.full((4, 4), valor, dtype=dtype), 1)
        return str(ruta)
    return {
        "sensor": "NISAR", "banda": "L", "orbita": 42, "stack": "A",
        "madurez": "VALIDATED", "polarizacion": "HHHH",
        "observed_at": "2026-10-22" if nombre == "pre" else "2026-11-03",
        "granule": nombre, "cog": guardar("gamma", gamma, "float32", -9999),
        "qa_mask": guardar("qa", qa, "uint8", 255),
        "looks": guardar("looks", looks, "float32", -9999),
    }


def test_delta_ficha_y_no_sobrescritura(tmp_path):
    a, b = escena(tmp_path, "pre"), escena(tmp_path, "post", gamma=10)
    destino = tmp_path / "delta.tif"
    resultado = procesar_par(a, b, destino)
    assert resultado["estado"] == "CAMBIO_DB_EXPLORATORIO"
    with rasterio.open(destino) as ds:
        assert np.allclose(ds.read(1), 10)
    ficha = json.loads(destino.with_suffix(".json").read_text())
    assert ficha["tipo_producto"] == "diferencia_db"
    assert evaluar(False, ficha, sha256_archivo(destino)).estado == REAL_SIN_VALIDAR
    with pytest.raises(FileExistsError):
        procesar_par(a, b, destino)


def test_qa_cero_no_publica(tmp_path):
    a, b = escena(tmp_path, "pre"), escena(tmp_path, "post", qa=0)
    with pytest.raises(QAInsuficiente, match="SIN_QA"):
        procesar_par(a, b, tmp_path / "delta.tif")
    assert not (tmp_path / "delta.tif").exists()


def test_madurez_distinta_bloquea(tmp_path):
    a, b = escena(tmp_path, "pre"), escena(tmp_path, "post")
    b["madurez"] = "PROVISIONAL"
    with pytest.raises(QAInsuficiente, match="SIN_PAR"):
        procesar_par(a, b, tmp_path / "delta.tif")


def test_sin_looks_y_banda_c_bloquean(tmp_path):
    a, b = escena(tmp_path, "pre"), escena(tmp_path, "post")
    b.pop("looks")
    with pytest.raises(QAInsuficiente, match="SIN_QA"):
        procesar_par(a, b, tmp_path / "delta.tif")
    b = escena(tmp_path, "post")
    b["banda"] = "C"
    with pytest.raises(QAInsuficiente, match="SIN_PAR"):
        procesar_par(a, b, tmp_path / "delta.tif")
