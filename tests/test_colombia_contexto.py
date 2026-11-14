"""Modo Colombia y contexto EONET; pruebas puras sin red ni datos SAR."""
from __future__ import annotations

import io
import json
import urllib.error
from datetime import date

import pytest
from shapely.geometry import Polygon, mapping

from utils import colombia, contexto_ambiental


@pytest.fixture(autouse=True)
def solo_colombia(monkeypatch):
    monkeypatch.setenv("VISOR_REGION_MODE", "CO")


def test_puntos_nacionales_e_insulares():
    assert colombia.contiene_punto(-74.07, 4.71)  # Bogotá
    assert colombia.contiene_punto(-76.68, 7.67)  # Chigorodó
    assert colombia.contiene_punto(-81.70, 12.58)  # San Andrés
    assert not colombia.contiene_punto(-78.47, -0.18)  # Quito
    assert not colombia.contiene_punto(2.35, 48.86)  # París


def test_aoi_completa_no_solo_centro():
    assert colombia.validar_aoi((-74.10, 4.68, -74.05, 4.72))
    with pytest.raises(colombia.FueraDeColombia):
        colombia.validar_aoi((-78.5, -0.2, -78.4, -0.1))
    # Una zona extensa que incluya Bogotá, pero cruce frontera, no es válida.
    with pytest.raises(colombia.FueraDeColombia):
        colombia.validar_aoi((-83, -5, -66, 15))


def test_modo_global_conservado(monkeypatch):
    monkeypatch.setenv("VISOR_REGION_MODE", "GLOBAL")
    assert colombia.contiene_punto(2.35, 48.86)
    assert colombia.validar_aoi((2.3, 48.8, 2.4, 48.9))


def test_cobertura_archipielago():
    geom = colombia.geometria_colombia()
    assert geom.is_valid
    assert geom.geom_type in {"Polygon", "MultiPolygon"}


def test_eonet_bbox_orden_oficial():
    url = contexto_ambiental.url_eonet((-76.8, 7.55, -76.55, 7.8),
                                     date(2026, 9, 24), date(2026, 10, 6))
    assert "bbox=-76.80000%2C7.80000%2C-76.55000%2C7.55000" in url
    assert "status=all" in url


def test_eonet_no_confundir_bbox_con_poligono():
    aoi = mapping(Polygon([(-74.2, 4.6), (-74.0, 4.6), (-74.2, 4.8)]))
    respuesta = {"events": [
        {"id": "falso", "title": "Dentro bbox, fuera del polígono",
         "geometry": [{"type": "Point", "coordinates": [-74.01, 4.79],
                        "date": "2026-10-01T12:00:00Z"}]},
        {"id": "verdadero", "title": "Dentro del polígono",
         "categories": [{"title": "Floods"}],
         "sources": [{"url": "https://example.org/evento"}],
         "geometry": [{"type": "Point", "coordinates": [-74.15, 4.65],
                        "date": "2026-10-01T12:00:00Z"}]},
    ]}
    items = contexto_ambiental.normalizar_eonet(respuesta, aoi,
                                               date(2026, 9, 20), date(2026, 10, 10))
    assert len(items) == 1 and items[0]["id"] == "EONET:verdadero"
    assert items[0]["geo_relation"] == "intersects_aoi"
    assert items[0]["published_at"] is None


def test_eonet_red_caida_no_bloquea_sar():
    aoi = mapping(Polygon([(-74.2, 4.6), (-74.1, 4.6), (-74.2, 4.7)]))
    def fallar(*_args, **_kwargs):
        raise urllib.error.URLError("fuente sin red")
    res = contexto_ambiental.consultar_eonet(aoi, date(2026, 9, 24),
                                              date(2026, 10, 6), abrir=fallar)
    assert res["estado"] == "ERROR_FUENTE" and res["items"] == []
    assert "NASA EONET" in res["fuentes_con_error"][0]


def test_eonet_respuesta_simulada_no_afirma_hechos():
    aoi = mapping(Polygon([(-74.2, 4.6), (-74.1, 4.6), (-74.2, 4.7)]))
    class Respuesta:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return json.dumps({"events": []}).encode()
    res = contexto_ambiental.consultar_eonet(aoi, date(2026, 9, 24),
                                              date(2026, 10, 6), abrir=lambda *_args, **_kw: Respuesta())
    assert res["estado"] == "SIN_COINCIDENCIAS"
    assert res["items"] == []
