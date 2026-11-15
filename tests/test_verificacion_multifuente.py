"""Reglas de regresión para evidencia histórica, deduplicación y falsas confirmaciones."""
from datetime import date
from types import SimpleNamespace

import pytest

from utils.verificacion_multifuente import casos_documentados, evaluar_evidencias

INI, FIN = date(2026, 9, 28), date(2026, 10, 10)


def registro(tipo, origen, **otros):
    return {"tipo": tipo, "origen": origen, "valid": True,
            "observed_at": "2026-10-03", "relacion_espacial": "aoi", **otros}


def test_evento_oficial_unico_y_sectores_no_poligono():
    m = [SimpleNamespace(nombre="Chigorodó", departamento="Antioquia")]
    casos = casos_documentados(m, INI, FIN)
    assert len(casos) == 1
    assert len(casos[0]["fuentes"]) == 3
    assert "NO hay polígono exacto" in casos[0]["alcance"]
    assert "397" in casos[0]["resumen"]


def test_municipio_no_coincidente_o_fecha_posterior():
    m = [SimpleNamespace(nombre="Turbo", departamento="Antioquia")]
    assert casos_documentados(m, INI, FIN) == []
    ch = [SimpleNamespace(nombre="Chigorodo", departamento="Antioquia")]
    assert casos_documentados(ch, date(2026, 10, 22), date(2026, 11, 3)) == []


def test_lluvia_sola_no_confirma_inundacion():
    res = evaluar_evidencias([registro("lluvia", "GPM:IMERG:20261003")], INI, FIN)
    assert res["estados"] == ["CONDICIONES_METEOROLOGICAS_O_HIDROLOGICAS"]


def test_qa_invalida_es_informacion_insuficiente():
    res = evaluar_evidencias([registro("qa_sar", "NISAR:22-10", valid=False)], INI, FIN)
    assert res["estados"] == ["INFORMACION_INSUFICIENTE"]


def test_agua_y_lluvia_permite_posible_no_confirmada():
    res = evaluar_evidencias([
        registro("cambio_agua", "S1:20261003", relacion_espacial="aoi"),
        registro("lluvia", "IMERG:20261002")], INI, FIN)
    assert "POSIBLE_INUNDACION" in res["estados"]
    assert "INUNDACION_DOCUMENTADA_POR_AUTORIDAD" not in res["estados"]


def test_no_confirmar_por_imagen_sola():
    res = evaluar_evidencias([registro("agua_satelital", "DSWX:S1-6oct")], INI, FIN)
    assert res["estados"] == ["AGUA_OBSERVADA_POR_SATELITE"]


def test_producto_heredado_del_mismo_sentinel_no_es_una_nueva_observacion():
    res = evaluar_evidencias([
        registro("agua_satelital", "S1-GRANULE-1", fuente="DSWx"),
        registro("agua_satelital", "S1-GRANULE-1", fuente="GFM")], INI, FIN)
    assert res["registros_utilizables"] == 1


def test_informe_municipal_no_es_observacion_de_agua_en_aoi():
    res = evaluar_evidencias([registro("reporte_oficial", "DAGRAN:EVENTO1",
                                        relacion_espacial="municipio")], INI, FIN)
    assert "AGUA_OBSERVADA_POR_SATELITE" not in res["estados"]
    assert "INUNDACION_DOCUMENTADA_POR_AUTORIDAD" in res["estados"]


def test_fechas_mal_formadas_y_fuera_de_ventana():
    res = evaluar_evidencias([registro("cambio_agua", "A", observed_at="mal"),
                              registro("agua_satelital", "B", observed_at="2026-11-03")], INI, FIN)
    assert res["registros_descartados"] == 2
    assert res["estados"] == ["INFORMACION_INSUFICIENTE"]


def test_intervalos_invertidos():
    with pytest.raises(ValueError):
        evaluar_evidencias([], FIN, INI)
