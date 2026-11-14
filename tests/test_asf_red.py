"""Consulta REAL al catálogo de ASF. No corre en CI ni por defecto.

    VISOR_PRUEBAS_RED=1 .venv/bin/python -m pytest -m red

Solo lee metadatos públicos (sin credenciales, sin descargas). Las demás
pruebas del buscador usan la respuesta guardada en tests/datos/.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import buscador_sar as bus  # noqa: E402

pytestmark = [
    pytest.mark.red,
    pytest.mark.skipif(os.environ.get("VISOR_PRUEBAS_RED") != "1", reason="consulta real: requiere VISOR_PRUEBAS_RED=1"),
]


def test_catalogo_real_de_chigorodo():
    r = bus.buscar(-76.80, 7.55, -76.55, 7.80, "2026-09-20", "2026-10-10")
    assert r.escenas, "ASF no devolvió escenas"
    assert all(e.plataforma.startswith("S1") for e in r.escenas)
    if r.recomendado:
        assert r.recomendado.estado == "Recomendado (sin validar)"
        assert r.recomendado.antes.inicio < r.recomendado.despues.inicio
