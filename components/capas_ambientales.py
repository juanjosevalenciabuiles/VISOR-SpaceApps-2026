"""Capas Folium de contexto ambiental: IDEAM, DANE y NASA EONET.

No usan mapas SAR como insumo ni alteran su visualización. Usan solo
geometrías comprobadas de proveedores y las recortan al AOI confirmado.
Los interruptores están en el panel derecho, no dentro del mapa móvil.
"""
from __future__ import annotations

from html import escape

import folium
import streamlit as st
from shapely.geometry import shape

from components import contexto_zona
from utils import capas_ambientales_mapa as geodatos

CLAVES = {
    "ideam": "visor_mapa_alertas_ideam",
    "municipios": "visor_mapa_municipios_dane",
    "eonet": "visor_mapa_eventos_eonet",
}
DEFECTO = {"ideam": True, "municipios": True, "eonet": False}


def inicializar() -> None:
    for capa, clave in CLAVES.items():
        st.session_state.setdefault(clave, DEFECTO[capa])


def controles() -> None:
    """Interruptores en panel derecho para escritorio; cambian capas al rerun."""
    inicializar()
    with st.expander("Capas ambientales en el mapa", expanded=False):
        st.toggle("Alertas hidrológicas del IDEAM", key=CLAVES["ideam"],
                  help="Polígonos de subzonas de alerta que intersectan el área estudiada.")
        st.toggle("Municipios y porcentajes · DANE", key=CLAVES["municipios"],
                  help="Fragmentos municipales dentro de la zona y su porcentaje de superficie.")
        st.toggle("Eventos ambientales · NASA EONET", key=CLAVES["eonet"],
                  help="Geometrías catalogadas en el periodo; no equivalen a áreas afectadas.")
        st.caption("IDEAM: amarillo, naranja y rojo según la alerta vigente al consultar. "
                   "Los polígonos no representan inundaciones detectadas.")
        st.caption("DANE: cada color corresponde a un municipio; sus porcentajes son "
                   "fracciones aproximadas del área seleccionada, no niveles de riesgo.")


def _municipios(grupo: folium.FeatureGroup, geojson: dict) -> None:
    features = geojson.get("features") or []
    if not features:
        return
    folium.GeoJson(
        geojson, name="Distribución municipal · DANE",
        style_function=lambda f: {
            "color": f["properties"]["color"], "weight": 2,
            "opacity": 0.9, "fillColor": f["properties"]["color"], "fillOpacity": 0.08,
        },
        highlight_function=lambda f: {"weight": 3.5, "fillOpacity": 0.20},
        tooltip=folium.GeoJsonTooltip(fields=["nombre", "porcentaje"],
                                     aliases=["Municipio:", "Parte del área:"]),
        popup=folium.GeoJsonPopup(fields=["nombre", "departamento", "porcentaje", "fuente"],
                                 aliases=["Municipio:", "Departamento:", "Porcentaje:", "Fuente:"]),
    ).add_to(grupo)
    # Rotular solo las áreas destacadas para no saturar el mapa.
    for feature in features[:6]:
        p = feature["properties"]
        if float(p["fraccion"]) < 0.06:
            continue
        geom = shape(feature["geometry"]).representative_point()
        label = escape(p["nombre"]) + " · " + escape(p["porcentaje"])
        icono = folium.DivIcon(
            html=('<div style="pointer-events:none;white-space:nowrap;'
                  'font:600 11px Arial,sans-serif;background:rgba(6,20,30,.87);'
                  'color:#fff;border:1px solid #7e9ab0;border-radius:7px;'
                  'padding:3px 6px;transform:translate(-50%,-50%)">' + label + "</div>"),
            icon_size=(0, 0), icon_anchor=(0, 0),
        )
        folium.Marker([geom.y, geom.x], icon=icono, interactive=False).add_to(grupo)


def _alertas(grupo: folium.FeatureGroup, geojson: dict) -> None:
    if not geojson.get("features"):
        return
    folium.GeoJson(
        geojson, name="Zonas de alerta IDEAM",
        style_function=lambda f: {
            "color": f["properties"]["color"], "weight": 2.5,
            "opacity": 0.9, "dashArray": "5 4",
            "fillColor": f["properties"]["color"], "fillOpacity": 0.14,
        },
        highlight_function=lambda f: {"weight": 4, "fillOpacity": 0.25},
        tooltip=folium.GeoJsonTooltip(fields=["nombre", "nivel"],
                                     aliases=["Subzona:", "Alerta:"]),
        popup=folium.GeoJsonPopup(
            fields=["nombre", "nivel", "zona", "fuente", "consulta", "limitacion"],
            aliases=["Subzona:", "Nivel:", "Zona hidrográfica:", "Fuente:",
                     "Consulta:", "Interpretación:"]),
    ).add_to(grupo)


def _eonet(grupo: folium.FeatureGroup, geojson: dict) -> None:
    if not geojson.get("features"):
        return
    folium.GeoJson(
        geojson, name="Eventos NASA EONET",
        marker=folium.CircleMarker(radius=6, color="#48D5E9", weight=2,
                                   fill=True, fill_color="#48D5E9", fill_opacity=0.8),
        style_function=lambda f: {"color": "#48D5E9", "weight": 2, "fillOpacity": 0.10},
        tooltip=folium.GeoJsonTooltip(fields=["nombre", "tipo"],
                                     aliases=["Evento:", "Categoría:"]),
        popup=folium.GeoJsonPopup(fields=["nombre", "tipo", "fecha", "fuente"],
                                 aliases=["Evento:", "Categoría:", "Fecha:", "Fuente:"]),
    ).add_to(grupo)


def grupos_mapa() -> list[folium.FeatureGroup]:
    """Obtener capas desde estados cacheados; no bloquea ni descarga rasters."""
    inicializar()
    zona = contexto_zona.zona_actual()
    if not zona:
        return []
    aoi = zona["geometria"]
    grupos = []
    if st.session_state[CLAVES["municipios"]]:
        try:
            local = contexto_zona.local_de(zona)
            geo = geodatos.municipios_del_area(aoi, local)
            if geo["features"]:
                grupo = folium.FeatureGroup(name="Municipios DANE · % del área")
                _municipios(grupo, geo)
                grupos.append(grupo)
        except (OSError, ValueError, KeyError, TypeError):
            # Sin cartografía DANE no se inventan polígonos.
            pass
    if st.session_state[CLAVES["ideam"]] or st.session_state[CLAVES["eonet"]]:
        inicio, fin, _ = contexto_zona.periodo_actual()
        fuentes = contexto_zona.consultas(zona, inicio, fin)
        if st.session_state[CLAVES["ideam"]]:
            geo = geodatos.alertas_ideam_del_area(aoi, fuentes["ideam"])
            if geo["features"]:
                grupo = folium.FeatureGroup(name="IDEAM · alertas hidrológicas actuales")
                _alertas(grupo, geo)
                grupos.append(grupo)
        if st.session_state[CLAVES["eonet"]]:
            geo = geodatos.eventos_eonet_del_area(aoi, fuentes["eonet"])
            if geo["features"]:
                grupo = folium.FeatureGroup(name="NASA EONET · eventos catalogados")
                _eonet(grupo, geo)
                grupos.append(grupo)
    return grupos
