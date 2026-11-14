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
from folium import MacroElement
from folium.plugins import Draw
from folium.template import Template
from streamlit_folium import st_folium

from components.barra_lateral import Controles
from utils import geo
from utils.capas_contexto import CAPAS_CONTEXTO, recortar
from utils.config import MAPA_CENTRO, MAPA_ZOOM, Fenomeno
from utils.geotiff import Capa, a_web_mercator, colorizar_capa, colorizar_categorico
from utils.mapas_base import MapaBase, obtener, url_teselas
from utils.diferencia_db import colorizar_diferencia
from utils.resultados import ResultadoSAR, _firma


# Estilo que viaja dentro del marco del mapa. Debe ser constante: si cambiara,
# el mapa se recrearía y se perdería la vista.
ESTILO_LIENZO = """<style id="visor-lienzo">
html, body { margin: 0; height: 100%; overflow: hidden; background: #06121e; }
#map_div, #map_div2 { width: 100vw !important; height: 100vh !important; height: 100dvh !important; }
.leaflet-container { background: #06121e; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
/* El zoom pasa a la esquina inferior derecha, justo encima de la atribución: por debajo
   del panel de información (que termina a 190 px del borde) y lejos de la línea temporal. */
.leaflet-top.leaflet-left { top: auto; left: auto; right: 14px; bottom: 40px;
               display: flex; flex-direction: row-reverse; align-items: flex-end; gap: 8px; }
.leaflet-top.leaflet-left .leaflet-control { margin: 0 !important; float: none; clear: none; }
/* Herramientas de dibujo de la zona (rectángulo, polígono, editar, borrar), encima del zoom.
   Iconos SVG propios: no dependen de la hoja de imágenes del complemento ni de las fuentes. */
.leaflet-draw-toolbar a { background-color: rgba(8,22,36,.78) !important; background-size: 18px 18px !important;
               background-position: center !important; background-repeat: no-repeat !important; }
.leaflet-draw-toolbar a .sr-only { display: none; }
.leaflet-draw-toolbar a.leaflet-disabled { opacity: .38; }
.leaflet-draw-draw-rectangle { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f5f5f7' stroke-width='2' stroke-linejoin='round' stroke-linecap='round'%3E%3Crect x='4' y='6' width='16' height='12' rx='1'/%3E%3C/svg%3E") !important; }
.leaflet-draw-draw-polygon { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f5f5f7' stroke-width='2' stroke-linejoin='round' stroke-linecap='round'%3E%3Cpath d='M12 3l8 6-3 11H7L4 9z'/%3E%3C/svg%3E") !important; }
.leaflet-draw-edit-edit { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f5f5f7' stroke-width='2' stroke-linejoin='round' stroke-linecap='round'%3E%3Cpath d='M4 20h4L19 9l-4-4L4 16z'/%3E%3Cpath d='M13 7l4 4'/%3E%3C/svg%3E") !important; }
.leaflet-draw-edit-remove { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f5f5f7' stroke-width='2' stroke-linejoin='round' stroke-linecap='round'%3E%3Cpath d='M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13'/%3E%3C/svg%3E") !important; }
.leaflet-draw-actions { left: auto; right: 36px; white-space: nowrap; }
.leaflet-draw-actions a { background: rgba(8,22,36,.94); color: #f5f5f7; border-left-color: rgba(255,255,255,.2); }
.leaflet-bar { border: 1px solid rgba(255,255,255,.16) !important; border-radius: 12px !important; overflow: hidden;
               box-shadow: 0 8px 24px rgba(0,0,0,.35) !important; }
.leaflet-bar a, .leaflet-bar a:hover { background: rgba(8,22,36,.78); color: #f5f5f7; border-bottom-color: rgba(255,255,255,.12);
               width: 34px; height: 34px; line-height: 34px; }
.leaflet-bar a:hover { background: rgba(30,52,72,.9); }
.leaflet-control-attribution { background: rgba(6,18,30,.72) !important; color: #c7c7cc !important;
               border-radius: 8px 0 0 0; font-size: 10px; }
.leaflet-control-attribution a { color: #8fd3ff !important; }
/* Fondo oscuro sin clave: las teselas de OpenStreetMap con los colores invertidos (solo el fondo). */
.visor-base-oscura { filter: invert(1) hue-rotate(180deg) brightness(.92) contrast(.88) saturate(.55); }
/* Aviso cuando las teselas del fondo no cargan (sin red, 401/403/429, proveedor caído). */
.visor-aviso-teselas { display: none; position: fixed; top: 86px; left: 50%; transform: translateX(-50%);
               width: min(340px, 86vw); padding: 8px 10px; border-radius: 10px; z-index: 1000;
               background: rgba(58,20,20,.92); color: #ffd6d6; border: 1px solid rgba(255,105,97,.6);
               font: 12px/1.35 Inter, -apple-system, "Segoe UI", sans-serif; }
.visor-aviso-teselas.visible { display: block; }
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


class AvisoTeselas(MacroElement):
    """Diagnóstico en el navegador: si las teselas de un mapa base fallan sin que ninguna cargue
    (sin red, clave rechazada, límite de uso, proveedor caído), muestra un aviso sobre el mapa.
    Nunca sustituye el fondo en silencio. Es constante: no recrea el mapa."""
    _template = Template("""{% macro script(this, kwargs) %}
(function(m){
  var caja = L.DomUtil.create('div', 'visor-aviso-teselas');
  caja.id = 'visor-aviso-teselas';
  var Ctl = L.Control.extend({onAdd: function(){ return caja; }});
  new Ctl({position: 'bottomleft'}).addTo(m);
  function vigilar(capa){
    if (!(capa instanceof L.TileLayer) || capa._visorVigilada) return;
    capa._visorVigilada = true; var fallos = 0, cargas = 0;
    capa.on('tileerror', function(){ fallos++;
      if (fallos >= 4 && cargas === 0) { caja.className = 'visor-aviso-teselas visible';
        caja.textContent = 'El mapa base no responde (sin conexión, clave rechazada o límite de uso del proveedor). '
          + 'Elige otro mapa base en el Explorador. Los análisis y resultados no se ven afectados.'; } });
    capa.on('tileload', function(){ cargas++; caja.className = 'visor-aviso-teselas'; });
  }
  m.eachLayer(vigilar);
  m.on('layeradd', function(e){ vigilar(e.layer); });
})({{ this._parent.get_name() }});
{% endmacro %}""")


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
    # Dibujo de la zona de análisis: solo rectángulo y polígono. Lo dibujado es un borrador;
    # no se convierte en zona hasta confirmarlo en Herramientas SAR («Usar esta zona»).
    Draw(position="topleft", export=False,
         draw_options={"polyline": False, "circle": False, "marker": False, "circlemarker": False,
                       "rectangle": {"shapeOptions": {"color": "#ffd60a", "weight": 2, "fillOpacity": 0.05}},
                       "polygon": {"allowIntersection": False,
                                   "shapeOptions": {"color": "#ffd60a", "weight": 2, "fillOpacity": 0.05}}},
         edit_options={"edit": True, "remove": True}).add_to(m)
    AvisoTeselas().add_to(m)
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
        **({"class_name": mapa.clase_css} if mapa.clase_css else {}),
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
    rgba = (colorizar_diferencia(_res.capa.datos) if _res.perfil.continuo
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


def grupo_contexto(clave: str, limites=None, zoom: float | None = None) -> folium.FeatureGroup | None:
    """Ríos/lagos o carreteras dentro del encuadre (limites = oeste, sur, este, norte). None si no hay
    datos o en esa vista no se dibuja nada (sin elementos o zoom insuficiente)."""
    if limites is None:                     # nunca el mundo entero: la ventana alrededor del último destino
        limites, zoom = vista_actual(st.session_state.get("vista") if st.runtime.exists() else None)
    datos = recortar(clave, limites, zoom)
    if datos is None or not datos.elementos:
        return None
    capa = CAPAS_CONTEXTO[clave]
    estilo = {"color": capa.color, "weight": capa.grosor, "opacity": 0.9,
              "fill": capa.relleno, "fillColor": capa.color, "fillOpacity": 0.25}
    grupo = folium.FeatureGroup(name=capa.nombre)
    folium.GeoJson(
        datos.geojson, name=capa.nombre, style_function=lambda _: estilo,
        tooltip=folium.GeoJsonTooltip(fields=["name"], labels=False) if '"name"' in datos.geojson[:4000] else None,
    ).add_to(grupo)
    return grupo


def vista_actual(vista: dict | None = None) -> tuple[tuple[float, float, float, float], float]:
    """Encuadre y zoom que el mapa informó por última vez; si aún no informó, una ventana alrededor
    del último destino («Ir a…» o lugar buscado)."""
    ultimo = st.session_state.get("mapa") if st.runtime.exists() else None
    if isinstance(ultimo, dict):
        limites = limites_de_vista(ultimo.get("bounds"))
        if limites is not None and limites[0] < limites[2]:
            return limites, float(ultimo.get("zoom") or MAPA_ZOOM)
    centro = (vista or {}).get("centro") or list(MAPA_CENTRO)
    zoom = float((vista or {}).get("zoom") or MAPA_ZOOM)
    lado = 360 / 2 ** zoom * 3
    return (centro[1] - lado, centro[0] - lado / 2, centro[1] + lado, centro[0] + lado / 2), zoom


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
            grupo = grupo_contexto(clave, c.vista_limites, c.vista_zoom)
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
           resultados: list[ResultadoSAR] | tuple = (), extras: list[folium.FeatureGroup] | tuple = (),
           seguir_vista: bool = False) -> None:
    """`extras`: grupos adicionales encima de todo (zona, marcador del lugar y huellas de entrada).

    El mapa devuelve el borrador de zona dibujado y su encuadre (para recortar ríos y carreteras a lo
    que se ve y para «usar el área visible»). Nada de lo que devuelve el mapa lanza un análisis."""
    centro, zoom = destino_vista(vista)
    salida = st_folium(
        mapa_fijo(),
        feature_group_to_add=[*construir_capas(fenomeno, capa, c, resultados), *extras],
        height=720,                   # inicial; ESTILO_LIENZO lo lleva a pantalla completa
        use_container_width=True,
        # streamlit-folium fija esta lista al montar el mapa y no la vuelve a leer: tiene que ser
        # constante. Mover el mapa provoca una recarga ligera (sin recálculo) para conocer el encuadre.
        returned_objects=["all_drawings", "bounds", "zoom"],
        center=centro,
        zoom=zoom,
        key="mapa",                   # misma clave siempre: se conserva ubicación y zoom
    ) or {}
    dibujos = salida.get("all_drawings") or []
    st.session_state["mapa_dibujo"] = dibujos[-1] if dibujos else None
    limites = limites_de_vista(salida.get("bounds"))
    st.session_state["mapa_limites"] = limites if limites is not None and limites[0] < limites[2] else None


def limites_de_vista(bounds) -> tuple[float, float, float, float] | None:
    """(oeste, sur, este, norte) de lo que devuelve streamlit-folium, o None si aún no hay vista."""
    try:
        so, ne = bounds["_southWest"], bounds["_northEast"]
        return float(so["lng"]), float(so["lat"]), float(ne["lng"]), float(ne["lat"])
    except (TypeError, KeyError, ValueError):
        return None
