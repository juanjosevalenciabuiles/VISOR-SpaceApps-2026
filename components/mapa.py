"""Mapa Folium multicapa.

El mapa en sí (`mapa_fijo`) nunca cambia: no lleva teselas ni datos. Todo lo
demás va en grupos de capas independientes que streamlit-folium actualiza sin
reiniciar el mapa:

    mapa base  →  capa SAR  →  hidrografía / vías  →  cobertura y referencia

Por eso cambiar el fondo, el fenómeno o la opacidad no mueve la ubicación ni
el zoom, y la capa SAR no depende del mapa base elegido.

Pantalla completa: streamlit-folium fija la altura del mapa en píxeles al
crearlo. Para que ocupe todo el viewport, `mapa_fijo` lleva un bloque de estilo
que se inserta DENTRO del marco del mapa (ESTILO_LIENZO); el marco en sí se
fija a pantalla completa desde assets/mission_control.css.
"""

import folium
import streamlit as st
from streamlit_folium import st_folium

from components.barra_lateral import Controles
from utils import geo
from utils.capas_contexto import CAPAS_CONTEXTO, cargar_contexto
from utils.config import MAPA_CENTRO, MAPA_ZOOM, Fenomeno
from utils.geotiff import Capa, a_web_mercator, colorizar_capa, colorizar_categorico
from utils.mapas_base import MapaBase, obtener, url_teselas
from utils.diferencia_db import colorizar_diferencia, escala_de
from utils.resultados import ResultadoSAR, _firma


# Estilo que viaja dentro del marco del mapa. Debe ser constante: si cambiara,
# el mapa se recrearía y se perdería la vista.
ESTILO_LIENZO = """<style id="visor-lienzo">
html, body { margin: 0; height: 100%; overflow: hidden; background: #06121e; }
#map_div, #map_div2 { width: 100vw !important; height: 100vh !important; height: 100dvh !important; }
.leaflet-container { background: #06121e; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
/* El zoom pasa a la esquina inferior derecha, justo encima de la atribución: por debajo
   del panel de información (que termina a 190 px del borde) y lejos de la línea temporal. */
.leaflet-top.leaflet-left { top: auto; left: auto; right: 14px; bottom: 40px; }
.leaflet-bar { border: 1px solid rgba(255,255,255,.16) !important; border-radius: 12px !important; overflow: hidden;
               box-shadow: 0 8px 24px rgba(0,0,0,.35) !important; }
.leaflet-bar a, .leaflet-bar a:hover { background: rgba(8,22,36,.78); color: #f5f5f7; border-bottom-color: rgba(255,255,255,.12);
               width: 34px; height: 34px; line-height: 34px; }
.leaflet-bar a:hover { background: rgba(30,52,72,.9); }
.leaflet-control-attribution { background: rgba(6,18,30,.72) !important; color: #c7c7cc !important;
               border-radius: 8px 0 0 0; font-size: 10px; }
.leaflet-control-attribution a { color: #8fd3ff !important; }
.leaflet-control-scale-line { background: rgba(6,18,30,.6); color: #e5e5ea; border-color: #c7c7cc; }
/* La escala queda en la esquina inferior izquierda, bajo el explorador (que termina a
   118 px del borde) y fuera del recorrido de la línea temporal. */
@media (max-width: 980px) {
  /* El panel de información baja a la esquina inferior derecha: el zoom sube. */
  .leaflet-top.leaflet-left { bottom: auto; top: 88px; }
}
@media (max-width: 720px) {
  .leaflet-top.leaflet-left { bottom: auto; top: 76px; right: 10px; }
  .leaflet-control-scale { display: none; }
  .leaflet-control-attribution { font-size: 9px; max-width: 100vw; }
}
</style>"""


def mapa_fijo() -> folium.Map:
    """Lienzo centrado en Antioquia, sin navegación fuera del mundo."""
    m = folium.Map(
        location=MAPA_CENTRO,
        zoom_start=MAPA_ZOOM,
        tiles=None,
        control_scale=True,
        min_zoom=2,
        max_bounds=True,
        max_bounds_viscosity=1.0,
    )
    m.get_root().header.add_child(folium.Element(ESTILO_LIENZO), name="visor_lienzo")
    return m


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


@st.cache_data(show_spinner=False, max_entries=16)
def imagen_resultado(ruta: str, firma: tuple, perfil: str, _res: ResultadoSAR) -> str:
    """PNG (data URL) de un resultado. Colorear y codificar ~1000×1000 px cuesta ~60 ms y se
    repetía en cada recarga; ahora solo cambia si cambia el archivo o su ficha (`firma`)."""
    from folium.utilities import image_to_url
    oeste, sur, este, norte = _res.capa.limites
    rgba = (colorizar_diferencia(_res.capa.datos, escala_de(_res.perfil.clave)) if _res.perfil.continuo
            else colorizar_categorico(_res.capa.datos, _res.perfil.clases))
    return image_to_url(a_web_mercator(rgba, sur, norte))


def grupo_resultado(res: ResultadoSAR, opacidad: float) -> folium.FeatureGroup:
    """Resultado de data/analisis/ coloreado por su perfil. Solo cambia la
    presentación: las clases transparentes (y NoData) no se dibujan, pero los
    valores del archivo no se alteran."""
    oeste, sur, este, norte = res.capa.limites
    grupo = folium.FeatureGroup(name=f"Resultado · {res.nombre}")
    folium.raster_layers.ImageOverlay(
        image=imagen_resultado(str(res.ruta), _firma(res.ruta), res.perfil.clave, res),
        bounds=[[sur, oeste], [norte, este]],
        opacity=opacidad,
        name=res.nombre,
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
    fenomeno: Fenomeno, capa: Capa | None, c: Controles, resultados: list[ResultadoSAR] | tuple = ()
) -> list[folium.FeatureGroup]:
    """Grupos de capas activos, de abajo hacia arriba."""
    grupos = [grupo_mapa_base(obtener(c.mapa_base))]

    if capa is not None and c.mostrar_capa:
        grupos.append(grupo_sar(fenomeno, capa, c.opacidad))

    # Resultados de análisis encima de la capa del fenómeno (no la reemplazan).
    for res in resultados:
        if res.dibujable and res.id in c.resultados:
            grupos.append(grupo_resultado(res, c.resultados[res.id]))

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


def construir(fenomeno: Fenomeno, capa: Capa | None, c: Controles, resultados=()) -> folium.Map:
    """Mapa completo y autónomo (para exportar a HTML o para pruebas)."""
    m = mapa_fijo()
    for grupo in construir_capas(fenomeno, capa, c, resultados):
        grupo.add_to(m)
    return m


def destino_vista(vista: dict | None) -> tuple[list[float] | None, float | None]:
    """Centro y zoom que se envían al mapa para moverlo sin recrearlo.

    streamlit-folium solo mueve la vista cuando el centro o el zoom enviados
    son distintos de los últimos que recibió. Para que "ir" funcione también
    al repetir el mismo destino (después de que el usuario haya arrastrado el
    mapa), cada petición suma un desplazamiento ínfimo y único: 1e-9 grados
    (menos de un milímetro) y 1e-6 niveles de zoom, que Leaflet redondea.
    """
    if not vista:
        return None, None
    n = int(vista.get("n", 0))
    lat, lon = vista["centro"]
    return [float(lat) + n * 1e-9, float(lon)], float(vista["zoom"]) + n * 1e-6


def render(fenomeno: Fenomeno, capa: Capa | None, c: Controles, vista: dict | None = None,
           resultados: list[ResultadoSAR] | tuple = (), extras: list[folium.FeatureGroup] | tuple = ()) -> None:
    """`extras`: grupos adicionales encima de todo (p. ej. AOI y huellas de Herramientas SAR)."""
    centro, zoom = destino_vista(vista)
    st_folium(
        mapa_fijo(),
        feature_group_to_add=[*construir_capas(fenomeno, capa, c, resultados), *extras],
        height=720,                   # inicial; ESTILO_LIENZO lo lleva a pantalla completa
        use_container_width=True,
        returned_objects=[],          # el mapa no provoca recargas de la app al moverlo
        center=centro,
        zoom=zoom,
        key="mapa",                   # misma clave siempre: se conserva ubicación y zoom
    )
