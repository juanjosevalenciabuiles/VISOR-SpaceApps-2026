"""Puente V9 con COG sintéticos SOLO de test (sin descargas ni inundaciones)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from utils import v9_nisar_puente as puente
from utils.v9_datos.cambio_cog import QAInsuficiente


def _capa(path, valor, dtype, nodata):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", count=1, width=8, height=8,
                       dtype=dtype, crs="EPSG:32618",
                       transform=from_origin(500000, 900000, 30, 30), nodata=nodata) as dst:
        dst.write(np.full((8, 8), valor, dtype=dtype), 1)


def _preparacion(tmp_path, monkeypatch, qa_pre=2, qa_post=2, otra_orbita=False):
    catalogo = tmp_path / "catalogo"
    catalogo.mkdir()
    harmony = tmp_path / "harmony"
    harmony.mkdir()
    destino = tmp_path / "analisis"
    destino.mkdir()
    monkeypatch.setattr(puente, "CATALOGO", catalogo)
    monkeypatch.setattr(puente, "HARMONY", harmony)
    monkeypatch.setattr(puente, "DESTINO", destino)
    granules = ["n1", "n2"]
    for granule, valor, qa in (("n1", 1.0, qa_pre), ("n2", 10.0, qa_post)):
        directorio = harmony / granule
        _capa(directorio / "HHHH.tif", valor, "float32", -9999.0)
        _capa(directorio / "mask.tif", qa, "uint8", 255)
        _capa(directorio / "numberOfLooks.tif", 3.0, "float32", -9999.0)
    primera = SimpleNamespace(granule="n1", geometria=(42, "ASC", 1), crid="A", pol_a=("HH",),
                              track=42, direccion="ASCENDING", frame=1, modo_a="20", modo_b="00",
                              inicio=datetime(2026, 10, 22, tzinfo=timezone.utc))
    segunda = SimpleNamespace(granule="n2", geometria=(43 if otra_orbita else 42, "ASC", 1),
                              crid="A", pol_a=("HH",), track=43 if otra_orbita else 42,
                              direccion="ASCENDING", frame=1, modo_a="20", modo_b="00",
                              inicio=datetime(2026, 11, 3, tzinfo=timezone.utc))
    monkeypatch.setattr(puente.nisar_catalogo, "leer_nombre",
                        lambda granule: {"n1": primera, "n2": segunda}.get(granule))
    manifest = {
        "estado": "NISAR_COG_PREPARADO_SIN_CLASIFICAR", "metodo": "NASA_HARMONY",
        "madurez": "VALIDATED", "plan": {"tipo": "PAR", "granules": granules, "termino": "HHHH"},
        "escenas": [{"granule": name, "carpeta_relativa": name,
                     "archivos": ["HHHH.tif", "mask.tif", "numberOfLooks.tif"]}
                    for name in granules],
    }
    job = "1234567890abcdef"
    (catalogo / f"resultado_{job}.json").write_text(json.dumps(manifest), encoding="utf-8")
    return job, manifest, destino


def test_publica_cambio_10_db_con_sha_y_qa_subfranja_2(tmp_path, monkeypatch):
    job, _, destino = _preparacion(tmp_path, monkeypatch)
    resultado = puente.procesar_preparacion(job)
    assert resultado["estado"] == "CAMBIO_DB_EXPLORATORIO"
    assert "inundación" in resultado["advertencia"]
    with rasterio.open(resultado["raster"]) as src:
        assert np.allclose(src.read(1), 10)
    ficha = json.loads(next(destino.glob("*.json")).read_text())
    assert ficha["procedencia"]["estado"] == "real_sin_validar"
    assert ficha["qa"]["pixeles_validos"] == 64
    assert puente.procesar_preparacion(job)["reutilizado"] is True


def test_sin_qa_real_no_publica_geotiff(tmp_path, monkeypatch):
    job, _, destino = _preparacion(tmp_path, monkeypatch, qa_pre=0, qa_post=2)
    with pytest.raises(QAInsuficiente, match="SIN_QA"):
        puente.procesar_preparacion(job)
    assert list(destino.glob("*.tif")) == []


def test_orbitas_incompatibles_bloquean(tmp_path, monkeypatch):
    job, _, destino = _preparacion(tmp_path, monkeypatch, otra_orbita=True)
    with pytest.raises(QAInsuficiente, match="SIN_PAR"):
        puente.procesar_preparacion(job)
    assert not list(destino.glob("*.tif"))


def test_no_reinterpretar_manifest_de_otra_fuente(tmp_path, monkeypatch):
    job, manifest, _ = _preparacion(tmp_path, monkeypatch)
    manifest["metodo"] = "HDF5_COMPLETO"
    (puente.CATALOGO / f"resultado_{job}.json").write_text(json.dumps(manifest))
    with pytest.raises(QAInsuficiente, match="Harmony"):
        puente.procesar_preparacion(job)


def test_rutas_inseguras_no_se_aceptan():
    with pytest.raises(QAInsuficiente, match="no seguro"):
        puente._ruta_segura(puente.HARMONY, "../archivo.tif")
