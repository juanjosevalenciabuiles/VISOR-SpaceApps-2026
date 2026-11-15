"""Fechas sintéticas; nunca se interpreta un catálogo como inundación."""
import pytest

from utils.v9_datos.ventanas import planificar_periodo


AOI = (-77, 7, -76, 8)


def escena(nombre, fecha, qa=True):
    return dict(granule=nombre, observed_at=fecha, sensor="NISAR",
                banda="L", orbita=7, stack="T07", madurez="PROVISIONAL",
                polarizaciones=["HH"], bbox=AOI, tamano_bytes=10,
                qa_apto=qa)


def test_intervalo_descarta_observacion_dentro_del_evento():
    escenas = [escena("pre", "2026-07-01"), escena("evento", "2026-07-15"),
               escena("post", "2026-08-02")]
    plan = planificar_periodo(escenas, AOI, "2026-07-10", "2026-07-25",
                             margen_dias=20)
    assert plan["estado"] == "PLAN_METADATOS"
    assert [x["granule"] for x in plan["escenas"]] == ["pre", "post"]
    assert plan["periodo_interes"] == ["2026-07-10", "2026-07-25"]


def test_fuera_ventana_y_qa_no_generan_mapa():
    escenas = [escena("pre", "2026-06-01"), escena("post", "2026-08-02", qa=None)]
    plan = planificar_periodo(escenas, AOI, "2026-07-10", "2026-07-25",
                             margen_dias=20)
    assert plan["estado"] == "SIN_DATOS"
    assert plan["fuera_ventana"] == 1
    escenas[0]["observed_at"] = "2026-07-01"
    plan = planificar_periodo(escenas, AOI, "2026-07-10", "2026-07-25",
                             margen_dias=20)
    assert plan["estado"] == "SIN_QA"
    assert plan["escenas"] == []


def test_intervalo_invertido_rechazado():
    with pytest.raises(ValueError):
        planificar_periodo([], AOI, "2026-08-01", "2026-07-01")


def test_fecha_aproximada():
    plan = planificar_periodo([escena("pre", "2026-07-01"),
                              escena("post", "2026-07-20")],
                             AOI, "2026-07-10")
    assert plan["estado"] == "PLAN_METADATOS"
