"""Regresiones de seguridad del lector COG sin acceso a red."""
import pytest
from utils.v10_sentinel.cog import leer_ventana_cog


@pytest.mark.parametrize("bbox", [
    None, "0,0,1,1", (0, 0, "1", 1), (False, 0, 1, 1),
    (0, 0, float("nan"), 1), (0, 0, 1),
])
def test_aoi_malformada_falla_antes_de_red(bbox):
    with pytest.raises(ValueError, match="AOI_INVALIDA"):
        leer_ventana_cog("https://example.earthdata.nasa.gov/a.tif", bbox)
