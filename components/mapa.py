"""Mapa Folium multicapa.

El mapa en sí (`mapa_fijo`) nunca cambia: no lleva teselas ni datos. Todo lo
demás va en grupos de capas independientes que streamlit-folium actualiza sin
reiniciar el mapa:

    mapa base  →  capa SAR  →  hidrografía / vías  →  cobertura y referencia

Por eso cambiar el fondo, el fenómeno o la opacidad no mueve la ubicación ni
el zoom, y la capa SAR no depende del mapa base elegido.
"""

import folium
from streamlit_folium import st_folium

from components.barra_lateral import Controles
from utils import geo
from utils.capas_contexto import CAPAS_CONTEXTO, cargar_contexto
from utils.config import MAPA_CENTRO, MAPA_ZOOM, Fenomeno
from utils.geotiff import Capa, a_web_mercator, colorizar_capa
from utils.mapas_base import MapaBase, obtener, url_teselas


def mapa_fijo() -> folium.Map:
    """Lienzo vacío centrado en Antioquia. Debe generar siempre el mismo código."""
    return folium.Map(
        location=MAPA_CENTRO, zoom_start=MAPA_ZOOM, tiles=None, control_scale=True
    )


def grupo_mapa_base(mapa: MapaBase) -> folium.FeatureGroup:
    grupo = folium.FeatureGroup(name=f"Mapa base · {mapa.nombre}")
    folium.TileLayer(
        tiles=url_teselas(mapa),
        attr=mapa.atribucion,
        name=mapa.nombre,
        subdomains=mapa.subdominios,
        max_zoom=mapa.max_zoom,
        max_native_zoom=mapa.max_zoom_nativo or mapa.max_zoom,
        no_wrap=True,
    ).add_to(grupo)
    return grupo


def grupo_sar(fenomeno: Fenomeno, capa: Capa, opacidad: float) -> folium.FeatureGroup:
    oeste, sur, este, norte = capa.limites
    grupo = folium.FeatureGroup(name=f"SAR · {fenomeno.nombre}")
    folium.raster_layers.ImageOverlay(
        image=a_web_mercator(colorizar_capa(capa, fenomeno), sur, norte),
        bounds=[[sur, oeste], [norte, este]],
        opacity=opacidad,
        name=fenomeno.nombre,
    ).add_to(grupo)
    return grupo


def grupo_contexto(clave: str) -> folium.FeatureGroup | None:
    """Hidrografía, vías u otra capa vectorial. None si no hay datos."""
    datos = cargar_contexto(clave)
    if datos is None:
        return None
    capa = CAPAS_CONTEXTO[clave]
    estilo = {"color": capa.color, "weight": capa.grosor, "opacity": 0.9, "fill": False}
    grupo = folium.FeatureGroup(name=capa.nombre)
    folium.GeoJson(
        datos.geojson, name=capa.nombre, style_function=lambda _: estilo
    ).add_to(grupo)
    return grupo


def _grupo_rectangulo(gdf, nombre: str, estilo: dict) -> folium.FeatureGroup:
    grupo = folium.FeatureGroup(name=nombre)
    folium.GeoJson(
        gdf,
        name=nombre,
        style_function=lambda _: estilo,
        tooltip=folium.GeoJsonTooltip(fields=["nombre"], labels=False),
    ).add_to(grupo)
    return grupo


def construir_capas(
    fenomeno: Fenomeno, capa: Capa | None, c: Controles
) -> list[folium.FeatureGroup]:
    """Grupos de capas activos, de abajo hacia arriba."""
    grupos = [grupo_mapa_base(obtener(c.mapa_base))]

    if capa is not None and c.mostrar_capa:
        grupos.append(grupo_sar(fenomeno, capa, c.opacidad))

    for clave, activa in (("hidrografia", c.hidrografia), ("vias", c.vias)):
        if activa:
            grupo = grupo_contexto(clave)
            if grupo is not None:
                grupos.append(grupo)

    if c.mostrar_referencia:
        grupos.append(
            _grupo_rectangulo(
                geo.area_referencia(),
                "Área de referencia",
                {"color": "#8E8E93", "weight": 1, "fill": False, "dashArray": "4 6"},
            )
        )
    if capa is not None and c.mostrar_huella:
        etiqueta = f"Cobertura · {fenomeno.nombre}" + (
            " (DEMO)" if capa.es_demo else ""
        )
        grupos.append(
            _grupo_rectangulo(
                geo.huella(capa.limites, etiqueta),
                "Cobertura de la capa",
                {
                    "color": fenomeno.color,
                    "weight": 1.5,
                    "fill": False,
                    "dashArray": "6 6",
                },
            )
        )
    return grupos


def construir(fenomeno: Fenomeno, capa: Capa | None, c: Controles) -> folium.Map:
    """Mapa completo y autónomo (para exportar a HTML o para pruebas)."""
    m = mapa_fijo()
    for grupo in construir_capas(fenomeno, capa, c):
        grupo.add_to(m)
    return m


def render(fenomeno: Fenomeno, capa: Capa | None, c: Controles) -> None:
    st_folium(
        mapa_fijo(),
        feature_group_to_add=construir_capas(fenomeno, capa, c),
        height=640,
        use_container_width=True,
        returned_objects=[],  # el mapa no provoca recargas de la app al moverlo
        key="mapa",  # misma clave siempre: se conserva ubicación y zoom
    )
