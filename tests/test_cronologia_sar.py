"""La línea de tiempo nunca inventa imágenes ni dates intermedias (fixtures sintéticos)."""
from datetime import date
from types import SimpleNamespace

import pytest

from utils import cronologia_sar as crono


ZONA = (-76.8, 7.5, -76.7, 7.6)


def _res(identificador, sensor, fechas, *, real=True, area=ZONA, estado="real_sin_validar"):
    procedencia = SimpleNamespace(es_real=real)
    capa = SimpleNamespace(procedencia=procedencia, limites=area)
    ficha = {"tipo_producto": "diferencia_db", "procedencia": {
        "sensor": sensor, "fechas": fechas, "estado": estado}}
    return SimpleNamespace(id=identificador, dibujable=True, capa=capa, ficha=ficha)


def test_rechaza_una_fecha_o_fecha_no_declarada():
    for fechas in ([], ["2026-11-01"], ["2026-11-02", "2026-11-01"],
                   ["sin fecha", "2026-11-02"], ["2026-11-02", "2026-11-02"]):
        assert crono.producto_de_resultado(_res("x", "NISAR", fechas)) is None


def test_excluye_demos_y_fuentes_no_identificadas():
    assert crono.producto_de_resultado(_res("fake", "NISAR", ["2026-10-22", "2026-11-03"], real=False)) is None
    assert crono.producto_de_resultado(_res("fake", "sensor raro", ["2026-10-22", "2026-11-03"])) is None


def test_periodo_y_ubicacion_limitan_el_mapa():
    n = _res("nisar", "NISAR L", ["2026-10-22T01:00:00Z", "2026-11-03T02:00:00Z"])
    fuera = _res("externo", "Sentinel-1", ["2026-10-22", "2026-11-03"],
                 area=(-75.6, 7.1, -75.5, 7.2))
    assert [x.identificador for x in crono.productos_disponibles([n, fuera], ZONA)] == ["nisar"]
    assert crono.productos_disponibles([n], ZONA, date(2026, 11, 5), date(2026, 11, 12)) == []


def test_dos_sensores_comparan_solo_rasters_reales_de_su_aoi():
    n = _res("nisar", "NISAR", ["2026-10-22", "2026-11-03"])
    s = _res("sentinel", "Sentinel-1C", ["2026-10-25", "2026-11-05"], estado="validado")
    datos = [s, n]
    inicio, fin = date(2026, 10, 29), date(2026, 11, 1)
    assert crono.capas_visibles(datos, ZONA, inicio, fin, "Ambos") == {
        "nisar": 0.7, "sentinel": 0.7}
    assert crono.capas_visibles(datos, ZONA, inicio, fin, "NISAR") == {"nisar": 0.85}
    assert crono.capas_visibles(datos, ZONA, inicio, fin, "sin modo") == {}
    puntos = crono.puntos_observados(crono.productos_disponibles(datos, ZONA))
    assert len(puntos) == 4  # dos fechas NISAR y dos fechas Sentinel, no se interpola


def test_seleccion_por_identificador_no_por_fecha_aproximada():
    n1 = _res("n1", "NISAR", ["2026-10-22", "2026-11-03"])
    n2 = _res("n2", "NISAR", ["2026-10-24", "2026-11-05"])
    inicio, fin = date(2026, 10, 27), date(2026, 11, 1)
    assert crono.capas_visibles([n1, n2], ZONA, inicio, fin, "NISAR",
                                {"NISAR": "n1"}) == {"n1": 0.85}


@pytest.mark.parametrize("fechas", [["2026-10-21", "2026-11-03"], ["2026-10-22", "2026-11-03"]])
def test_metadatos_fecha_reales_sin_inventar_intervalos(fechas):
    resultado = crono.producto_de_resultado(_res("n", "NISAR", fechas))
    assert resultado.antes == date.fromisoformat(fechas[0])
    assert resultado.despues == date.fromisoformat(fechas[1])


def test_cobertura_parcial_insuficiente():
    r = _res("solo_esquina", "Sentinel-1", ["2026-10-22", "2026-11-02"],
             area=(-76.75, 7.5, -76.7, 7.6))
    assert not crono.dentro_de_zona(r, ZONA)


@pytest.mark.parametrize("zona,limites", [
    ((float("nan"), 7.5, -76.7, 7.6), ZONA),
    (ZONA, (-76.8, 7.5, float("inf"), 7.6)),
    ((-76.7, 7.5, -76.8, 7.6), ZONA),
    (ZONA, (-76.7, 7.5, -76.8, 7.6)),
    ((-181, 7.5, -180, 7.6), ZONA),
])
def test_aoi_invalida_no_habilita_overlays(zona, limites):
    r = _res("n", "NISAR", ["2026-10-22", "2026-11-03"], area=limites)
    assert not crono.dentro_de_zona(r, zona)
    assert crono.capas_visibles([r], zona, date(2026, 10, 22), date(2026, 11, 3), "NISAR") == {}


@pytest.mark.parametrize("inicio,fin", [
    (date(2026, 11, 4), date(2026, 10, 22)),
    (None, date(2026, 11, 4)),
    (date(2026, 10, 22), None),
])
def test_intervalo_invalido_no_reutiliza_overlays(inicio, fin):
    r = _res("nisar", "NISAR", ["2026-10-22", "2026-11-03"])
    assert crono.capas_visibles([r], ZONA, inicio, fin, "NISAR") == {}
