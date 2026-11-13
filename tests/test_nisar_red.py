"""Consulta REAL al catálogo NISAR (CMR de NASA). No corre por defecto.

    VISOR_PRUEBAS_RED=1 .venv/bin/python -m pytest -m red

Solo metadatos públicos: sin credenciales y sin descargas. No exige que haya
escenas ni pares: comprueba que la respuesta real se interpreta sin errores.
"""
import os
from datetime import datetime, timezone

import pytest

from utils import nisar_catalogo as cat

pytestmark = [
    pytest.mark.red,
    pytest.mark.skipif(os.environ.get("VISOR_PRUEBAS_RED") != "1", reason="consulta real: requiere VISOR_PRUEBAS_RED=1"),
]


def test_catalogo_nisar_real_de_chigorodo():
    r = cat.buscar(-76.80, 7.55, -76.55, 7.80, "2026-10-21", f"{datetime.now(timezone.utc):%Y-%m-%d}")
    assert r.madurez == "VALIDATED"
    for c in r.candidatos:
        assert c.nombre.granule.startswith("NISAR_L2_") and 0 < c.cobertura <= 1
    assert all(p.estado == "CANDIDATO NO VALIDADO" for p in r.pares)
    assert r.pares or not r.candidatos or r.bloqueos            # si no hay par, se explica por qué
