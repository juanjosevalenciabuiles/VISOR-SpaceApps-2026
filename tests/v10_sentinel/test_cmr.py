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


def test_pagina_cmr_llena_rechazada_sin_paginacion():
    entradas = [{"id": f"g-{i}", "time_start": "2026-10-01T00:00:00Z"} for i in range(100)]
    with pytest.raises(ValueError, match="CMR_PAGINACION_PENDIENTE"):
        extraer_granulos({"feed": {"entry": entradas}})


def test_pagina_cmr_incompleta_permite_metadatos_sin_qa():
    entradas = [{"id": f"g-{i}", "time_start": "2026-10-01T00:00:00Z"} for i in range(99)]
    resultado = extraer_granulos({"feed": {"entry": entradas}})
    assert len(resultado) == 99
    assert all(g["qa_metadata"] == "NO_VERIFICADO" for g in resultado)


def test_consulta_paginada_no_confunde_catalogo_con_qa(monkeypatch):
    import json
    from urllib.parse import parse_qs, urlsplit
    from utils.v10_sentinel import cmr

    paginas = []
    class Respuesta:
        status = 200
        def __init__(self, payload):
            self.payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self, n):
            return json.dumps(self.payload).encode()

    def abrir(request, timeout):
        pagina = int(parse_qs(urlsplit(request.full_url).query)["page_num"][0])
        paginas.append(pagina)
        count = 100 if pagina == 1 else 1
        return Respuesta({"feed": {"entry": [
            {"id": f"{pagina}-{i}", "time_start": "2026-10-01T00:00:00Z"}
            for i in range(count)]}})

    monkeypatch.setattr(cmr, "urlopen", abrir)
    result = cmr.consultar_cmr((-77, 5, -76, 6),
                              "2026-10-01T00:00:00Z", "2026-10-10T00:00:00Z")
    assert paginas == [1, 2]
    assert len(result["granulos"]) == 101
    assert result["estado"] == "METADATOS_SIN_QA"
    assert all(g["qa_metadata"] == "NO_VERIFICADO" for g in result["granulos"])


def test_consulta_rechaza_paginas_repetidas(monkeypatch):
    import json
    from utils.v10_sentinel import cmr

    class Respuesta:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self, n):
            return json.dumps({"feed": {"entry": [
                {"id": str(i), "time_start": "2026-10-01T00:00:00Z"}
                for i in range(100)]}}).encode()

    monkeypatch.setattr(cmr, "urlopen", lambda request, timeout: Respuesta())
    result = cmr.consultar_cmr((-77, 5, -76, 6),
                              "2026-10-01T00:00:00Z", "2026-10-10T00:00:00Z")
    assert result["estado"] == "SIN_DATOS"
    assert result["granulos"] == []
