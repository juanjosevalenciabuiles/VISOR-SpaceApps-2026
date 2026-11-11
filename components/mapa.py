"""Mapa Folium centrado en Antioquia con la capa SAR superpuesta."""
import folium
from streamlit_folium import st_folium

from components.barra_lateral import Controles
from utils import geo
from utils.config import MAPA_ATRIBUCION, MAPA_CENTRO, MAPA_ZOOM, Fenomeno, url_mapa_base
from utils.geotiff import Capa, a_web_mercator, colorizar


def construir(fenomeno: Fenomeno, capa: Capa | None, c: Controles) -> folium.Map:
    m = folium.Map(location=MAPA_CENTRO, zoom_start=MAPA_ZOOM, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles=url_mapa_base(),
        attr=MAPA_ATRIBUCION,
        name="CartoDB Dark Matter",
        subdomains="abcd",
        max_zoom=20,
    ).add_to(m)

    if c.mostrar_referencia:
        folium.GeoJson(
            geo.area_referencia(),
            name="Área de referencia",
            style_function=lambda _: {"color": "#8E8E93", "weight": 1, "fill": False, "dashArray": "4 6"},
            tooltip=folium.GeoJsonTooltip(fields=["nombre"], labels=False),
        ).add_to(m)

    if capa is not None:
        oeste, sur, este, norte = capa.limites
        if c.mostrar_capa:
            rgba = colorizar(capa.datos, fenomeno.colores, fenomeno.vmin, fenomeno.vmax, fenomeno.invertir)
            folium.raster_layers.ImageOverlay(
                image=a_web_mercator(rgba, sur, norte),
                bounds=[[sur, oeste], [norte, este]],
                opacity=c.opacidad,
                name=fenomeno.nombre,
            ).add_to(m)
        if c.mostrar_huella:
            etiqueta = f"Cobertura · {fenomeno.nombre}" + (" (DEMO)" if capa.es_demo else "")
            color = fenomeno.color
            folium.GeoJson(
                geo.huella(capa.limites, etiqueta),
                name="Cobertura de la capa",
                style_function=lambda _: {"color": color, "weight": 1.5, "fill": False, "dashArray": "6 6"},
                tooltip=folium.GeoJsonTooltip(fields=["nombre"], labels=False),
            ).add_to(m)

    return m


def render(fenomeno: Fenomeno, capa: Capa | None, c: Controles) -> None:
    # returned_objects=[] evita que cada movimiento del mapa recargue la app.
    st_folium(
        construir(fenomeno, capa, c),
        height=640,
        use_container_width=True,
        returned_objects=[],
        key=f"mapa-{fenomeno.clave}",
    )
