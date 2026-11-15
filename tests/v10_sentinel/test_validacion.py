"""Pruebas puras de validación previa; no acceden a la red."""
import pytest

from utils.v10_sentinel.validacion import bbox_valida, fecha_observacion, url_candidata


@pytest.mark.parametrize("bbox", [
    [float("nan"), 0, 1, 1],
    [0, 0, float("inf"), 1],
    [-181, 0, 1, 1],
    [170, 0, -170, 1],
])
def test_bbox_invalida(bbox):
    with pytest.raises(ValueError):
        bbox_valida(bbox)


def test_bbox_valida():
    assert bbox_valida([-77, 5, -76, 6]) == (-77, 5, -76, 6)


@pytest.mark.parametrize("valor", ["2026-11-15", "2026-11-15T10:00:00", "invalida"])
def test_fecha_no_verificable(valor):
    with pytest.raises(ValueError):
        fecha_observacion(valor)


def test_fecha_utc():
    assert fecha_observacion("2026-11-15T10:00:00Z").utcoffset().total_seconds() == 0


@pytest.mark.parametrize("url", [
    "http://example.org/file.tif", "https://localhost/file.tif",
    "https://127.0.0.1/file.tif", "https://user:pass@example.org/a",
    "https://example.org:8080/a", "https://example.org/a#frag",
    "https://[::1]/a", "https://example.org:bad/a",
])
def test_urls_rechazadas(url):
    assert not url_candidata(url)


def test_https_candidata_no_autorizada():
    assert url_candidata("https://archive.podaac.earthdata.nasa.gov/a.tif")
