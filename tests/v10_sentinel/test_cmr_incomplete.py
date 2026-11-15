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

@pytest.mark.parametrize("fecha", ["not-a-date", "2026-11-01", "", "2026-99-01T00:00:00Z"])
def test_fecha_observacion_no_verificable(fecha):
    with pytest.raises(ValueError, match="CMR fecha"):
        extraer_granulos({"feed": {"entry": [{"id": "G1", "time_start": fecha}]}})


def test_fecha_utc_valida():
    granulos = extraer_granulos({
        "feed": {"entry": [{"id": "G1", "time_start": "2026-11-01T00:00:00Z"}]}
    })
    assert granulos[0]["observed_at"] == "2026-11-01T00:00:00Z"
