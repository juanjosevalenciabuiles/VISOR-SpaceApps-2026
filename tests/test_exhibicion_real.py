"""La muestra exige preparación local REAL y no invoca búsquedas ni descargas."""

from components import exhibicion_real as muestra


def test_muestra_sin_trabajos_no_inventa_pares(tmp_path):
    assert muestra.preparaciones_locales(tmp_path / "sin_datos") == []


def test_normalizacion_compartida_preserva_valores_observados():
    import numpy as np
    a = np.ma.array([[-18.0, -12.0], [-9.0, -6.0]])
    b = np.ma.array([[-16.0, -11.0], [-5.0, -2.0]])
    low, high = muestra._normalizacion(a, b)
    assert low < high and low <= -17 and high >= -3


def test_no_preparaciones_si_falta_manifiesto(tmp_path):
    import json
    d = tmp_path / "trabajos"
    d.mkdir()
    (d / "uno.json").write_text(json.dumps({
        "job_id": "1111111111111111", "estado": "APTO",
        "tipo": "adquisicion_nisar_gcov", "procesador": "harmony_cog",
    }))
    assert muestra.preparaciones_locales(d) == []
