"""Regresiones de catálogo CMR incompleto, sin acceso a red."""
import pytest

from utils.v10_sentinel.cmr import extraer_granulos


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "G1"},
        {"time_start": "2026-11-01T00:00:00Z"},
        None,
        {"id": "", "time_start": "2026-11-01T00:00:00Z"},
    ],
)
def test_granulo_incompleto_rechazado(entry):
    with pytest.raises(ValueError, match="CMR granulo incompleto"):
        extraer_granulos({"feed": {"entry": [entry]}})
