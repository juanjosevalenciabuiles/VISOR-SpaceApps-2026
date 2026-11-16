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


def test_rechaza_cobertura_parcial_sin_red(tmp_path, monkeypatch):
    """Una tesela intersectada no equivale a cobertura completa del AOI."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from utils.v10_sentinel import cog

    tif = tmp_path / "tesela.tif"
    with rasterio.open(
        tif, "w", driver="GTiff", width=10, height=10, count=1,
        dtype="uint8", crs="EPSG:4326", transform=from_origin(-76, 8, 0.1, 0.1)
    ) as ds:
        ds.write(np.ones((10, 10), dtype=np.uint8), 1)
    monkeypatch.setattr(cog, "_url_cog_confiable", lambda url: url)
    with pytest.raises(ValueError, match="AOI_COBERTURA_INCOMPLETA"):
        cog.leer_ventana_cog(str(tif), (-76.2, 7.2, -75.2, 7.8))
