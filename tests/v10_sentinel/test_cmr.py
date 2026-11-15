"""Fixtures sintéticos: ninguna llamada de red."""
import pytest

from utils.v10_sentinel.cmr import extraer_granulos, parametros_cmr


def test_url_cmr_restringe_coleccion_y_aoi():
    url = parametros_cmr((-77, 5, -76, 6), "2026-10-01T00:00:00Z", "2026-10-10T00:00:00Z")
    assert "OPERA_L3_DSWX-S1_V1" in url
    assert "bounding_box=-77.0%2C5.0%2C-76.0%2C6.0" in url
    assert "page_size=100" in url


def test_no_acepta_fecha_sin_zona():
    with pytest.raises(ValueError):
        parametros_cmr((-77, 5, -76, 6), "2026-10-01T00:00:00", "2026-10-10T00:00:00Z")


def test_metadatos_no_se_convierten_en_qa_ni_wtr():
    data = {"feed": {"entry": [{
        "id": "synthetic", "time_start": "2026-10-01T00:00:00Z",
        "links": [{"href": "https://example.org/product.tif"},
                  {"href": "http://unsafe.example/wtr.tif"},
                  {"href": "https://example.org/inherited", "inherited": True}],
    }]}}
    scene, = extraer_granulos(data)
    assert scene["qa_metadata"] == "NO_VERIFICADO"
    assert scene["links_candidatos"] == ["https://example.org/product.tif"]
    assert "wtr_url" not in scene
    assert "source_s1_granule" not in scene


def test_respuesta_invalida_rechazada():
    with pytest.raises(ValueError):
        extraer_granulos({"feed": {"entry": "invalid"}})
