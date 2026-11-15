"""Pruebas de perfiles con fichas sintéticas, nunca escenas satelitales."""
import pytest
from components.v9_desktop.perfiles import perfil_publicable, CLASES


def ficha(tipo="diferencia_db", estado="real_sin_validar"):
    return {"schema": "visor.ficha.v1", "sha256": "a" * 64, "qa_apto": True,
            "fecha_inicio": "2026-10-01", "fecha_fin": "2026-11-01",
            "estado": estado, "tipo_producto": tipo, "unidad": "dB"}


def test_cambio_db_exploratorio_sin_clases():
    r = perfil_publicable(ficha(), raster_verificado=True)
    assert r["mostrar_mapa"] and r["unidad"] == "dB"
    assert r["leyenda"] == {} and "no predicción" in r["mensaje"]


@pytest.mark.parametrize("cambio", [
    {"qa_apto": False}, {"sha256": ""}, {"estado": "demo"},
    {"fecha_inicio": None}, {"schema": "otro"},
])
def test_metadatos_inseguros_no_publican(cambio):
    f = {**ficha(), **cambio}
    assert not perfil_publicable(f, raster_verificado=True)["mostrar_mapa"]


def test_ficha_sola_no_publica():
    assert not perfil_publicable(ficha())["mostrar_mapa"]


def test_clases_propuestas_no_se_publican():
    f = ficha("clases_inundacion_nisar", "validado")
    assert not perfil_publicable(f, raster_verificado=True)["mostrar_mapa"]


def test_clases_requieren_validacion_explicita():
    f = ficha("clases_inundacion_nisar", "validado")
    f["clases_verificadas"] = True
    r = perfil_publicable(f, raster_verificado=True)
    assert r["mostrar_mapa"] and r["leyenda"] == CLASES
    assert r["leyenda"]["sin_datos"][1] == "transparente"


def test_clases_no_validadas_no_se_publican():
    f = ficha("clases_inundacion_nisar")
    f["clases_verificadas"] = True
    assert not perfil_publicable(f, raster_verificado=True)["mostrar_mapa"]
