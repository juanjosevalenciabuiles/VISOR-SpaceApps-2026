"""Capas ambientales con fuentes/geom. auténticas y fixtures sin red.

Ningún polígono de alerta representa píxeles de inundación detectada.
"""
import json
from datetime import date

import folium
import pytest
from shapely.geometry import Point, box, mapping, shape

from components import capas_ambientales
from utils import capas_ambientales_mapa as capas_geo
from utils import contexto_ambiental as externo
from utils import contexto_local


AOI = mapping(box(-76.9, 7.5, -76.5, 7.9))


def _consulta(nivel=2, geometria=None):
    if geometria is None:
        geometria = mapping(box(-77.1, 7.7, -76.65, 8.1))
    return {"estado": "CON_RESULTADOS", "retrieved_at": "2026-11-15T05:30:00Z",
            "items": [{"gravedad": nivel, "geometry": geometria, "title": "Río León",
                       "zona_hidrografica": "Caribe - Litoral"}]}


def test_poligono_alerta_ideam_recortado_y_no_evento_inundacion():
    geo = capas_geo.alertas_ideam_del_area(AOI, _consulta())
    assert geo["type"] == "FeatureCollection" and len(geo["features"]) == 1
    feat = geo["features"][0]
    assert feat["properties"]["color"] == "#FB923C"
    assert "no es mapa de inundación" in feat["properties"]["limitacion"]
    assert shape(AOI).covers(shape(feat["geometry"]))
    assert 0 < shape(feat["geometry"]).area < shape(AOI).area


def test_sin_geometria_fuente_no_crea_pin_ni_poligono():
    sin_geo = _consulta()
    sin_geo["items"][0]["geometry"] = None
    assert capas_geo.alertas_ideam_del_area(AOI, sin_geo)["features"] == []
    assert capas_geo.alertas_ideam_del_area(AOI, {"estado": "ERROR_FUENTE", "items": []})["features"] == []
    assert capas_geo.alertas_ideam_del_area(AOI, {"estado": "SIN_COINCIDENCIAS", "items": []})["features"] == []


def test_colores_de_alerta_reales_y_mensaje_de_no_confirmacion():
    for nivel, color in ((1, "#FACC15"), (2, "#FB923C"), (3, "#EF4444")):
        feat = capas_geo.alertas_ideam_del_area(AOI, _consulta(nivel))["features"][0]
        assert feat["properties"]["color"] == color
        assert feat["properties"]["nivel"] in {"Amarilla", "Naranja", "Roja"}


def test_municipios_distribucion_dane_no_se_expande_fuera_de_aoi():
    local = contexto_local.contexto(AOI)
    datos = capas_geo.municipios_del_area(AOI, local)
    assert datos["features"]
    porcentajes = {f["properties"]["divipola"]: f["properties"]["porcentaje"]
                   for f in datos["features"]}
    assert local.municipios[0].divipola in porcentajes
    for feat in datos["features"]:
        assert shape(AOI).covers(shape(feat["geometry"]))
        assert 0 < feat["properties"]["fraccion"] <= 1
        assert feat["properties"]["porcentaje"].endswith("%")


def test_eonet_point_reportado_y_no_crear_desde_solo_texto():
    punto = Point(-76.8, 7.7)
    datos = {"estado": "CON_RESULTADOS", "items": [
        {"title": "Evento de ejemplo", "phenomenon": "Floods",
         "event_start": "2026-11-02", "geometry": mapping(punto)},
        {"title": "Sin coordenadas", "geometry": None},
        {"title": "Fuera", "geometry": mapping(Point(-77.5, 7.7))},
    ]}
    resultado = capas_geo.eventos_eonet_del_area(AOI, datos)
    assert len(resultado["features"]) == 1
    assert shape(resultado["features"][0]["geometry"]).equals(punto)
    assert "no extensión real" in resultado["features"][0]["properties"]["fuente"]


def test_proveedor_esri_conserva_interseccion_autentica_no_centroides():
    class Resp:
        def __init__(self, obj):
            self.obj = obj

        def read(self):
            return json.dumps(self.obj).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    campos = [{"name": "OBJECTID", "type": "esriFieldTypeOID"},
              {"name": "NIVEL_A", "type": "esriFieldTypeString"},
              {"name": "NOMSZH", "type": "esriFieldTypeString"}]
    meta = {"fields": campos, "objectIdField": "OBJECTID", "displayField": "NOMSZH"}
    features = [{"attributes": {"OBJECTID": 101, "NIVEL_A": "ALERTA AMARILLA", "NOMSZH": "Río Porce"},
                 "geometry": {"rings": [[[-77, 7.6], [-76.6, 7.6], [-76.6, 8.0],
                                          [-77, 8.0], [-77, 7.6]]]}}]

    def abrir(req, timeout):
        return Resp(meta if req.full_url.endswith("?f=json") else {"features": features})

    resultado = externo.consultar_ideam(AOI, abrir=abrir)
    assert resultado["estado"] == "CON_RESULTADOS"
    geom = resultado["items"][0]["geometry"]
    assert geom and shape(AOI).covers(shape(geom))
    assert shape(geom).area > 0
    capa = capas_geo.alertas_ideam_del_area(AOI, resultado)
    assert len(capa["features"]) == 1


def test_folium_crea_capas_con_tooltips_y_popups():
    m = folium.Map(location=[7.7, -76.7], zoom_start=8)
    g = folium.FeatureGroup(name="IDEAM · alertas")
    capas_ambientales._alertas(g, capas_geo.alertas_ideam_del_area(AOI, _consulta()))
    g.add_to(m)
    html = m.get_root().render()
    assert "Río León" in html and "Alerta:" in html
    assert "no es mapa de inundación" in html


def test_folium_etiqueta_municipal_no_requiere_centroide_fuera_del_area():
    g = folium.FeatureGroup(name="DANE · municipio")
    local = contexto_local.contexto(AOI)
    capas_ambientales._municipios(g, capas_geo.municipios_del_area(AOI, local))
    m = folium.Map(location=[7.7, -76.7])
    g.add_to(m)
    html = m.get_root().render()
    assert "Parte del área:" in html


def test_texto_externo_escapado_para_popup():
    resultado = _consulta()
    resultado["items"][0]["title"] = "<script>alert('riesgo')</script>"
    datos = capas_geo.alertas_ideam_del_area(AOI, resultado)
    assert "&lt;script&gt;" in datos["features"][0]["properties"]["nombre"]
    assert "<script>" not in datos["features"][0]["properties"]["nombre"]


@pytest.mark.parametrize("capa", ["ideam", "municipios", "eonet"])
def test_cada_capa_tiene_control_independiente(capa):
    assert capa in capas_ambientales.CLAVES
