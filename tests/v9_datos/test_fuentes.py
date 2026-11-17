"""Pruebas offline de los adaptadores, sin observaciones reales."""
import pytest

from utils.v9_datos.fuentes import adaptar_observacion

URL = "https://example.org/producto"


def _base(**cambios):
    r = dict(observed_at="2026-10-05", url=URL, granule_origen="S1A_123",
             qa="APTO", relacion_espacial="aoi", agua_observada=True)
    r.update(cambios)
    return r


def test_catalogo_no_se_convierte_en_observacion():
    r = adaptar_observacion("DSWx-S1", _base())
    assert r["valid"] is False
    assert r["tipo"] == "agua_satelital"


def test_dswx_verificado_conserva_linaje_sentinel():
    r = adaptar_observacion("DSWx-S1", _base(), pixeles_verificados=True)
    assert r["valid"] is True
    assert r["origen"] == "S1:S1A_123"
    assert "no demuestra inundación" in r["limitaciones"]


@pytest.mark.parametrize("cambios", [
    {"qa": "NO_APTO"}, {"relacion_espacial": "municipio"},
    {"granule_origen": ""}, {"agua_observada": False},
])
def test_dswx_no_apto_no_es_evidencia(cambios):
    assert not adaptar_observacion(
        "DSWx-S1", _base(**cambios), pixeles_verificados=True)["valid"]


def test_imerg_nunca_se_etiqueta_agua():
    r = adaptar_observacion("IMERG", _base(precipitacion_mm=22.5),
                           pixeles_verificados=True)
    assert r["valid"] is True
    assert r["tipo"] == "lluvia"
    assert r["origen"] == "GPM:S1A_123"
    assert "no demuestra" in r["limitaciones"]


@pytest.mark.parametrize("valor", [None, -1, float("nan"), float("inf"), "22"])
def test_imerg_sin_medicion_valida(valor):
    assert not adaptar_observacion(
        "IMERG", _base(precipitacion_mm=valor), pixeles_verificados=True)["valid"]


@pytest.mark.parametrize("url", [
    "http://example.org", "https://user:pass@example.org", "file:///tmp/x",
])
def test_url_insegura_rechazada(url):
    with pytest.raises(ValueError):
        adaptar_observacion("IMERG", _base(url=url))


def test_fecha_y_producto_invalidos():
    with pytest.raises(ValueError):
        adaptar_observacion("IMERG", _base(observed_at="2026-99-99"))
    with pytest.raises(ValueError):
        adaptar_observacion("NISAR", _base())
