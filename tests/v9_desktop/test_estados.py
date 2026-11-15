"""Fixtures de escritorio sintéticos: no son resultados de satélite."""
import pytest
from components.v9_desktop.estados import ESTADOS, describir_estado


@pytest.mark.parametrize("estado", list(ESTADOS))
def test_estados_sin_raster_no_publican_mapa(estado):
    resultado = describir_estado(estado)
    assert resultado["mostrar_mapa"] is False


def test_cog_preparado_no_es_capa_publicada():
    ficha = {"schema": "visor.ficha.v1", "estado": "real_sin_validar",
             "sha256": "ficticio", "fecha_inicio": "2026-10-01",
             "fecha_fin": "2026-11-01", "raster_validado": False}
    assert describir_estado("apto", ficha=ficha)["estado"] == "qa_insuficiente"


def test_ficha_validada_exige_procedencia_y_qa():
    ficha = {"schema": "visor.ficha.v1", "estado": "validado",
             "sha256": "sha-de-fixture-no-real", "fecha_inicio": "2026-10-01",
             "fecha_fin": "2026-11-01", "raster_validado": True, "qa_apto": True,\n             "tipo_producto": "diferencia_db", "unidad": "dB"}
    assert describir_estado("apto", ficha=ficha)["mostrar_mapa"]
    ficha.pop("sha256")
    assert not describir_estado("apto", ficha=ficha)["mostrar_mapa"]


def test_estado_desconocido_se_rechaza():
    with pytest.raises(ValueError):
        describir_estado("prediccion_ml")


def test_apto_no_elude_compuerta_temporal_ni_qa():
    ficha = {"schema": "visor.ficha.v1", "estado": "validado",
             "sha256": "solo-fixture", "fecha_inicio": "2026-11-02",
             "fecha_fin": "2026-11-01", "raster_validado": True,
             "qa_apto": True, "tipo_producto": "diferencia_db", "unidad": "dB"}
    assert describir_estado("apto", ficha=ficha)["mostrar_mapa"] is False
    ficha["fecha_fin"] = "2026-11-03"
    ficha["qa_apto"] = False
    assert describir_estado("apto", ficha=ficha)["mostrar_mapa"] is False
    ficha["qa_apto"] = True
    assert describir_estado("apto", ficha=ficha)["mostrar_mapa"] is True
