"""Pruebas sin red: huellas aproximadas no se confunden con QA real."""
from datetime import date

import pytest

from utils.v9_datos import planificar_par


INICIO, FIN = date(2026, 10, 1), date(2026, 11, 30)
AOI = (-76.8, 7.55, -76.55, 7.8)


def escena(nombre, dia, sensor="NISAR", tam=100, bbox=AOI, banda=None):
    return {"granule": nombre, "observed_at": dia, "sensor": sensor,
            "banda": banda or ("L" if sensor == "NISAR" else "C"),
            "tamano_bytes": tam, "bbox": bbox}


def plan(items, budget=300):
    return planificar_par(items, AOI, INICIO, FIN, budget)


def test_plan_nisar_prioritario_y_solo_metadatos():
    items = [escena("n1", "2026-10-22"), escena("n2", "2026-11-03"),
             escena("s1", "2026-10-06", "Sentinel-1", 10),
             escena("s2", "2026-10-18", "Sentinel-1", 10)]
    p = plan(items)
    assert p["estado"] == "PLAN_METADATOS" and p["sensor"] == "NISAR"
    assert p["banda"] == "L" and p["transferencia_estimada_bytes"] == 200
    assert "NO QA" in p["advertencia"]


def test_no_mezclar_banda_l_y_c():
    p = plan([escena("n", "2026-10-22"), escena("s", "2026-10-06", "Sentinel-1")])
    assert p["estado"] == "SIN_PAR_COMPATIBLE" and not p["escenas"]


def test_cuando_nisar_incompatible_usar_respaldo_c():
    p = plan([escena("n1", "2026-10-22", bbox=(-77.1, 7.5, -76.8, 7.8)),
              escena("s1", "2026-10-06", "Sentinel-1", 60),
              escena("s2", "2026-10-18", "Sentinel-1", 60)])
    assert p["sensor"] == "Sentinel-1" and p["banda"] == "C"


def test_sin_cobertura_no_descarga_y_sin_evidencia():
    p = plan([escena("n", "2026-10-22", bbox=(-78, 7, -77, 8))])
    assert p["estado"] == "SIN_COBERTURA_DE_CATALOGO" and p["transferencia_estimada_bytes"] == 0


def test_limite_bytes_y_fechas():
    p = plan([escena("n1", "2026-10-22", tam=200), escena("n2", "2026-11-03", tam=200)], 300)
    assert p["estado"] == "SIN_PAR_COMPATIBLE"
    p = plan([escena("n1", "2026-09-01"), escena("n2", "2026-11-03")])
    assert p["estado"] == "SIN_PAR_COMPATIBLE" and p["descartados"] == 1


def test_banda_incompatible_y_qa_no_se_infiere():
    p = plan([escena("n1", "2026-10-22", banda="C"), escena("n2", "2026-11-03")])
    assert p["estado"] == "SIN_PAR_COMPATIBLE" and p["descartados"] == 1
    assert p["sensor"] is None


def test_fechas_invertidas_y_caja_invalida():
    with pytest.raises(ValueError):
        planificar_par([], AOI, FIN, INICIO, 300)
    with pytest.raises(ValueError):
        planificar_par([], (-76.7, 7.5, -76.8, 7.8), INICIO, FIN, 300)
