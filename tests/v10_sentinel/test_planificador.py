from utils.v10_sentinel.planificador import COLLECTION, MAX_BYTES, planificar


def escena(fecha, **extra):
    value = {"collection": COLLECTION, "observed_at": fecha,
             "granule_id": fecha, "source_s1_granule": "S1_" + fecha,
             "bbox": [-77, 5, -75, 7],
             "wtr_url": "https://example.org/test_WTR.tif",
             "estimated_window_bytes": 1024, "qa_metadata": "APTO"}
    value.update(extra)
    return value


def test_par_fechas_estrictas_y_presupuesto():
    r = planificar([-76.5, 5.5, -75.5, 6.5], "2026-10-05", "2026-10-07",
                   [escena("2026-10-04"), escena("2026-10-06"),
                    escena("2026-10-08")])
    assert r["estado"] == "APTA_METADATA"
    assert r["fechas_reales"] == ["2026-10-04", "2026-10-08"]


def test_cobertura_parcial_no_se_publica():
    r = planificar([-76.5, 5.5, -75.5, 6.5], "2026-10-05", "2026-10-07",
                   [escena("2026-10-04", bbox=[-76, 5, -75, 7]),
                    escena("2026-10-08")])
    assert r["estado"] == "NO_APTA"
    assert r["rechazos"]["COBERTURA"] == 1


def test_sin_par_ni_descarga_si_presupuesto_insuficiente():
    r = planificar([-76.5, 5.5, -75.5, 6.5], "2026-10-05", "2026-10-07",
                   [escena("2026-10-04", estimated_window_bytes=MAX_BYTES),
                    escena("2026-10-08")])
    assert r["estado"] == "NO_APTA"


def test_catalogo_no_es_evidencia_y_qa_faltante_se_rechaza():
    r = planificar([-76.5, 5.5, -75.5, 6.5], "2026-10-05", "2026-10-07",
                   [escena("2026-10-04", qa_metadata=None), escena("2026-10-08")])
    assert r["estado"] == "NO_APTA"
    assert r["rechazos"]["QA"] == 1


def test_urls_no_confiables_se_rechazan():
    r = planificar([-76.5, 5.5, -75.5, 6.5], "2026-10-05", "2026-10-07",
                   [escena("2026-10-04", wtr_url="http://example.org/a"),
                    escena("2026-10-08")])
    assert r["rechazos"]["URL"] == 1
