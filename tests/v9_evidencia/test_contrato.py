"""Casos de control sin red; no son observaciones satelitales reales."""
from datetime import date

import pytest

from utils.v9_evidencia import evaluar_paquete, normalizar_evidencias

INI, FIN = date(2026, 10, 1), date(2026, 10, 10)


def dato(tipo="cambio_agua", **extra):
    return {"tipo": tipo, "observed_at": "2026-10-03", "valid": True,
            "relacion_espacial": "aoi", "origen": "S1-GRANULE-A",
            "fuente": "OPERA", "producto": "DSWx-S1",
            "url": "https://example.org/product", "evidencia_observacional": True,
            "qa": {"pixeles_validos": 100}, **extra}


def test_catalogo_solo_no_es_observacion():
    item = dato("agua_satelital")
    item["evidencia_observacional"] = False
    r = evaluar_paquete([item], INI, FIN)
    assert r["estados"] == ["INFORMACION_INSUFICIENTE"]
    assert r["descartados_con_motivo"][0]["motivo"] == "QA_OBSERVACIONAL_INSUFICIENTE"


def test_qa_cero_no_es_ausencia_de_inundacion():
    item = dato()
    item["qa"]["pixeles_validos"] = 0
    r = evaluar_paquete([item], INI, FIN)
    assert r["estados"] == ["INFORMACION_INSUFICIENTE"]


def test_agua_con_qa_indica_agua_no_confirmacion():
    r = evaluar_paquete([dato("agua_satelital")], INI, FIN)
    assert r["estados"] == ["AGUA_OBSERVADA_POR_SATELITE"]


def test_lluvia_sola_no_afirma_inundacion():
    lluvia = dato("lluvia")
    lluvia["origen"] = "IMERG:20261003"
    lluvia["fuente"] = "NASA GPM IMERG"
    r = evaluar_paquete([lluvia], INI, FIN)
    assert r["estados"] == ["CONDICIONES_METEOROLOGICAS_O_HIDROLOGICAS"]


def test_mismo_granule_no_es_otra_evidencia():
    a = dato("agua_satelital")
    b = dato("agua_satelital")
    b["producto"], b["fuente"] = "GFM", "Copernicus"
    r = evaluar_paquete([a, b], INI, FIN)
    assert r["registros_utilizables"] == 1 and r["grupos_de_origen"] == 1


def test_reporte_municipal_no_equivale_a_pixel():
    oficial = dato("reporte_oficial")
    oficial["relacion_espacial"] = "municipio"
    oficial["fuente"], oficial["origen"] = "DAGRAN", "EVENTO-2026"
    r = evaluar_paquete([oficial], INI, FIN)
    assert "INUNDACION_DOCUMENTADA_POR_AUTORIDAD" in r["estados"]
    assert "AGUA_OBSERVADA_POR_SATELITE" not in r["estados"]


def test_fechas_fuera_de_rango_y_origen_faltante():
    a = dato()
    a["observed_at"] = "2026-11-01"
    b = dato()
    b["origen"] = ""
    r = normalizar_evidencias([a, b], INI, FIN)
    assert not r["aceptados"] and len(r["descartados"]) == 2


def test_fechas_invertidas():
    with pytest.raises(ValueError):
        evaluar_paquete([], FIN, INI)
