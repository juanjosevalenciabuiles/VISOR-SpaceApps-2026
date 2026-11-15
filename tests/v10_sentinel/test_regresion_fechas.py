"""Regresión del parseo temporal y selección de un par sintético sin red."""
from utils.v10_sentinel.planificador import planificar


def _escena(fecha, identificador):
    return {
        "collection": "OPERA_L3_DSWX-S1_V1",
        "observed_at": fecha,
        "granule_id": identificador,
        "source_s1_granule": "S1_" + identificador,
        "bbox": [-78, 4, -75, 7],
        "wtr_url": "https://archive.podaac.earthdata.nasa.gov/example.tif",
        "estimated_window_bytes": 1024,
        "qa_metadata": "APTO",
    }


def test_fecha_diaria_v9_y_par_con_timestamp_utc():
    resultado = planificar(
        [-77, 5, -76, 6], "2026-10-05", "2026-10-07",
        [_escena("2026-10-04T12:00:00Z", "pre"),
         _escena("2026-10-08T12:00:00Z", "post")],
    )
    assert resultado["estado"] == "APTA_METADATA"
    assert resultado["fechas_reales"] == ["2026-10-04", "2026-10-08"]


def test_no_publica_par_si_falta_post():
    resultado = planificar(
        [-77, 5, -76, 6], "2026-10-05", "2026-10-07",
        [_escena("2026-10-04T12:00:00Z", "pre")],
    )
    assert resultado["estado"] == "NO_APTA"
    assert "pre" not in resultado
