"""Pruebas sin red del diagnóstico NASA PO.DAAC DSWx-S1."""
import json
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

RUTA = Path(__file__).resolve().parents[1] / "scripts" / "verificar_dswx_cmr.py"
SPEC = spec_from_file_location("verificar_dswx_cmr", RUTA)
MOD = module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_cmr_usa_coleccion_y_bbox_correctos():
    url = MOD.crear_url(date(2026, 10, 6))
    q = parse_qs(urlparse(url).query)
    assert q["short_name"] == ["OPERA_L3_DSWX-S1_V1"]
    assert q["bounding_box"] == ["-76.80000,7.55000,-76.55000,7.80000"]
    assert q["temporal"] == ["2026-10-06T00:00:00Z,2026-10-07T00:00:00Z"]


def test_rechazo_aoi_invalida_y_limites():
    with pytest.raises(ValueError):
        MOD.crear_url(date(2026, 10, 6), limites=(1, 1, -1, -1))
    with pytest.raises(ValueError):
        MOD.crear_url(date(2026, 10, 6), max_resultados=0)


def test_normalizacion_no_fabrica_geo_tiffs():
    payload = {"feed": {"entry": [{"granule_ur": "G1", "time_start": "2026-10-06T12:00:00Z",
                                   "links": [{"href": "https://example.org/OPERA_L3_DSWX-S1_test_BWTR.tif"},
                                             {"href": "https://example.org/OPERA_L3_DSWX-S1_test.xml"}]}]}}
    resultado = MOD.normalizar(payload)
    assert resultado[0]["granule_ur"] == "G1"
    assert resultado[0]["archivos_tif_listados"] == ["OPERA_L3_DSWX-S1_test_BWTR.tif"]
    with pytest.raises(ValueError):
        MOD.normalizar({"error": "no encontrado"})


def test_consulta_simulada_sin_descargar_ningun_archivo():
    llamadas = []
    class Respuesta:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return json.dumps({"feed": {"entry": []}}).encode()

    def abrir(req, timeout):
        llamadas.append((req.full_url, timeout))
        return Respuesta()

    resultado = MOD.ejecutar(fechas=(date(2026, 9, 24),), opener=abrir)
    assert len(llamadas) == 1
    assert resultado["por_fecha"]["2026-09-24"]["total_en_pagina"] == 0
    assert resultado["estado"] == "METADATOS_ONLY_NO_DESCARGADOS"
