"""Pruebas sin red para límites de adquisición COG."""
import pytest
from utils.v10_sentinel.cog import _url_cog_confiable, leer_ventana_cog


@pytest.mark.parametrize("url", [
    "http://archive.podaac.earthdata.nasa.gov/file.tif",
    "https://evil.example/file.tif",
    "https://nasa.gov.evil.example/file.tif",
    "https://user:password@archive.podaac.earthdata.nasa.gov/file.tif",
])
def test_rechaza_url_no_confiable(url):
    with pytest.raises(ValueError):
        _url_cog_confiable(url)


def test_acepta_host_oficial():
    assert _url_cog_confiable(
        "https://archive.podaac.earthdata.nasa.gov/file.tif"
    ).startswith("https://")


def test_rechaza_presupuesto_antes_de_red():
    with pytest.raises(ValueError, match="PRESUPUESTO_INVALIDO"):
        leer_ventana_cog("https://archive.podaac.earthdata.nasa.gov/file.tif",
                         (-76, 7, -75, 8), presupuesto_bytes=385*1024*1024)


def test_rechaza_aoi_antes_de_red():
    with pytest.raises(ValueError, match="AOI_INVALIDA"):
        leer_ventana_cog("https://archive.podaac.earthdata.nasa.gov/file.tif",
                         (-75, 8, -76, 7))
