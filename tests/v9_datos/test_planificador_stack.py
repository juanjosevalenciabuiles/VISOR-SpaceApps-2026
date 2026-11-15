from utils.v9_datos.planificador_stack import planificar_stack

AOI = (-77, 7, -76, 8)


def escena(nombre, fecha, **kw):
    e = dict(granule=nombre, observed_at=fecha, sensor="NISAR", banda="L",
             orbita=42, stack="ascendente-42", madurez="VALIDATED",
             polarizaciones=["HH", "HV"], bbox=AOI, tamano_bytes=100,
             qa_apto=True)
    e.update(kw)
    return e


def test_par_misma_orbita_y_pre_post():
    p = planificar_stack([escena("a", "2026-10-22"),
                          escena("b", "2026-11-03")], AOI, "2026-10-28")
    assert p["estado"] == "PLAN_METADATOS"
    assert p["fechas"] == ["2026-10-22", "2026-11-03"]


def test_qa_desconocida_no_genera_plan():
    p = planificar_stack([escena("a", "2026-10-22", qa_apto=None),
                          escena("b", "2026-11-03")], AOI, "2026-10-28")
    assert p["estado"] == "SIN_QA" and not p["escenas"]


def test_orbita_madurez_y_polarizacion_incompatibles():
    a = escena("a", "2026-10-22")
    for cambio in ({"orbita": 43}, {"madurez": "PROVISIONAL"},
                   {"polarizaciones": ["VV"]}, {"banda": "C"}):
        p = planificar_stack([a, escena("b", "2026-11-03", **cambio)],
                             AOI, "2026-10-28")
        assert p["estado"] == "SIN_PAR"


def test_fecha_fuera_de_ventana_y_presupuesto():
    a, b = escena("a", "2026-10-22"), escena("b", "2026-11-03")
    assert planificar_stack([a, b], AOI, "2026-10-28", dias_antes=2)["estado"] == "SIN_PAR"
    assert planificar_stack([a, b], AOI, "2026-10-28", presupuesto_bytes=150)["estado"] == "SIN_PAR"


def test_cero_escenas_y_qa_rechazada():
    assert planificar_stack([], AOI, "2026-10-28")["estado"] == "SIN_DATOS"
    assert planificar_stack([escena("a", "2026-10-22", qa_apto=False)],
                            AOI, "2026-10-28")["estado"] == "SIN_DATOS"
