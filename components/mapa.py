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

import json
import hashlib

import folium
import numpy as np
import streamlit as st
from folium import MacroElement
from folium.plugins import Draw, Fullscreen
from folium.template import Template
from streamlit_folium import st_folium

from components import flujo
from components.barra_lateral import Controles
from utils import geo, sesion
from utils.capas_contexto import CAPAS_CONTEXTO, recortar
from utils import alcance_geografico
from utils.config import MAPA_CENTRO, MAPA_ZOOM, Fenomeno
from utils.geotiff import Capa, a_web_mercator, colorizar_capa, colorizar_categorico
from utils.mapas_base import MapaBase, obtener, url_teselas
from utils.diferencia_db import UMBRAL_TRANSPARENCIA_VISUAL_DB, colorizar_diferencia
from utils.resultados import ResultadoSAR, _firma
from utils.i18n import idioma, tr


# Estilo que viaja dentro del marco del mapa. Debe ser constante: si cambiara,
# el mapa se recrearía y se perdería la vista.
ESTILO_LIENZO = """<style id="visor-lienzo">
.visor-rotulo-fuera { position: absolute; left: 10px; bottom: 58px; z-index: 800; pointer-events: none;
  font: 600 11px/1.3 system-ui, sans-serif; color: #c9d4e0; background: rgba(2,6,12,.72);
  border: 1px solid rgba(46,230,200,.35); border-radius: 8px; padding: 4px 8px; }
.visor-rotulo-muestra { display: inline-block; width: 10px; height: 10px; margin-right: 6px; vertical-align: -1px;
  background: #02060c; border: 1px solid #2ee6c8; border-radius: 2px; }
@media (max-width: 600px) { .visor-rotulo-fuera { bottom: 64px; font-size: 10px; } }

html, body { margin: 0; height: 100%; overflow: hidden; background: #06121e; }
#map_div, #map_div2 { width: 100vw !important; height: 100vh !important; height: 100dvh !important; }
.leaflet-container { background: #06121e; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
/* El zoom pasa a la esquina inferior derecha, justo encima de la atribución: por debajo
   del panel de información (que termina a 190 px del borde) y lejos de la línea temporal. */
.leaflet-top.leaflet-left { top: auto; left: auto; right: 14px; bottom: 40px;
               display: flex; flex-direction: row-reverse; align-items: flex-end; gap: 8px; }
.leaflet-top.leaflet-left .leaflet-control { margin: 0 !important; float: none; clear: none; }
/* Barra de dibujo horizontal: conserva todos los controles sin invadir el
   panel de Información cuando la ventana es baja (regresión Playwright). */
.leaflet-draw { display: flex !important; align-items: flex-end; gap: 6px; }
.leaflet-draw-section { display: flex !important; flex: 0 0 auto; }
.leaflet-draw-toolbar { display: flex !important; margin: 0 !important; }
.leaflet-draw-toolbar a { display: block !important; float: none !important; border-bottom: 0 !important;
                        border-right: 1px solid rgba(255,255,255,.12); }
.leaflet-draw-toolbar a:last-child { border-right: 0; }
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
.leaflet-control-zoom-fullscreen { background: rgba(8,22,36,.78) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f5f5f7' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5'/%3E%3C/svg%3E") center/18px 18px no-repeat !important; width: 34px !important; height: 34px !important; }
.leaflet-fullscreen-on .leaflet-control-zoom-fullscreen { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f5f5f7' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M9 4v5H4M20 9h-5V4M15 20v-5h5M4 15h5v5'/%3E%3C/svg%3E") !important; }
.leaflet-draw-actions a { background: rgba(8,22,36,.94); color: #f5f5f7; border-left-color: rgba(255,255,255,.2); }
/* Acción directa para dibujar una zona arrastrando desde una esquina a la otra. */
.visor-zona-drag a, .visor-zona-drag a:hover {
  display: flex !important; align-items: center; justify-content: center; gap: 6px;
  width: 153px !important; min-height: 38px; line-height: 1.2 !important;
  color: #06121e !important; font: 700 12px/1.1 system-ui, sans-serif !important;
  background: #45e4f4 !important; border-radius: 9px; text-decoration: none;
}
.visor-zona-drag a:focus-visible { outline: 2px solid #ffd60a; outline-offset: 2px; }
/* Botón arriba a la izquierda, junto al panel SAR; NO debajo del asistente ECO. */
.visor-zona-drag {
  position: fixed !important; top: 94px; left: 388px; right: auto; bottom: auto;
  z-index: 800 !important; margin: 0 !important; pointer-events: auto;
}
@media (max-width: 980px) {
  .visor-zona-drag { top: 90px; left: 12px; }
}
@media (max-width: 720px) {
  .visor-zona-drag { top: 140px; left: 12px; }
}
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
  .leaflet-top.leaflet-left { bottom: auto; top: 134px; right: 10px; }   /* bajo el buscador flotante */
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
        caja.textContent = 'Basemap tiles unavailable (connection, key, or provider limits). '
          + 'Choose another basemap in Explorer. SAR results are unchanged.'; } });
    capa.on('tileload', function(){ cargas++; caja.className = 'visor-aviso-teselas'; });
  }
  m.eachLayer(vigilar);
  m.on('layeradd', function(e){ vigilar(e.layer); });
})({{ this._parent.get_name() }});
{% endmacro %}""")


def vista_inicio() -> tuple[tuple[float, float], int]:
    """Centro y zoom de partida: Colombia entera (con San Andrés) en Modo Colombia; Antioquia en GLOBAL."""
    if alcance_geografico.restringido():
        return alcance_geografico.VISTA_INICIAL["centro"], alcance_geografico.VISTA_INICIAL["zoom"]
    return MAPA_CENTRO, MAPA_ZOOM


def _modo_colombia(m: folium.Map) -> None:
    """Velo oscuro sobre el resto del mundo y contorno de Colombia, en un panel propio por encima de
    ríos, vías y resultados, que NO captura clics, arrastres ni dibujos (pointer-events: none)."""
    capas = alcance_geografico.capas_dibujo()
    if capas is None:
        return
    contorno, velo = capas
    folium.map.CustomPane("visor_velo", z_index=450, pointer_events=False).add_to(m)
    folium.GeoJson(velo, name="Fuera de Colombia", pane="visor_velo", interactive=False, control=False,
                   style_function=lambda _: {"color": "#000000", "weight": 0, "fillColor": "#02060c",
                                             "fillOpacity": 0.62, "interactive": False}).add_to(m)
    # La atribución del límite (DANE, CC BY 4.0) va en la propia capa: Leaflet la muestra en su control.
    folium.GeoJson(contorno, name="Colombia", pane="visor_velo", interactive=False, control=False,
                   attribution=alcance_geografico.ATRIBUCION,
                   style_function=lambda _: {"color": "#2ee6c8", "weight": 2.2, "opacity": 0.95, "fill": False,
                                             "interactive": False}).add_to(m)
    # Rótulo cartográfico fijo (abajo a la izquierda, sobre la escala): explica el velo sin taparlo todo.
    m.get_root().html.add_child(folium.Element(
        '<div class="visor-rotulo-fuera" id="rotulo-fuera"><span class="visor-rotulo-muestra"></span>'
        f"{tr('Fuera de Colombia: zona no disponible en esta versión', 'Outside Colombia: area unavailable in this release')}</div>"))


class SelectorZonaUnica(MacroElement):
    """Control nativo Leaflet: un clic activa arrastre y reemplaza el dibujo.

    Hijo del objeto Draw para usar sus nombres estables también cuando
    streamlit-folium normaliza los IDs de Folium entre reruns.
    """

    _template = Template("""{% macro script(this, kwargs) %}
    (function(mapa, dibujos) {
        // streamlit-folium observa exactamente esta colección de dibujos.
        window.drawnItems = dibujos;

        // Al iniciar otra selección, el dibujo antiguo deja de estar activo.
        mapa.on('draw:drawstart', function(e) {
            if (e.layerType === 'rectangle' || e.layerType === 'polygon') {
                dibujos.clearLayers();
            }
        });
        // En Leaflet Draw el evento llega después de insertar la capa.
        // Conservar exclusivamente la última, aun si se usó la barra clásica.
        mapa.on('draw:created', function(e) {
            dibujos.clearLayers();
            dibujos.addLayer(e.layer);
        });

        var selector = L.control({position: 'topleft'});
        var en = '{{ this.lang }}' === 'en';
        selector.onAdd = function() {
            var contenedor = L.DomUtil.create('div', 'leaflet-control visor-zona-drag');
            var boton = L.DomUtil.create('a', 'leaflet-bar', contenedor);
            boton.href = '#';
            boton.setAttribute('role', 'button');
            boton.setAttribute('aria-label', en ? 'Draw a study area by dragging' : 'Dibujar zona rectangular arrastrando');
            boton.title = en ? 'Click and drag between opposite corners' : 'Clic, arrastra desde una esquina hasta la otra y suelta';
            boton.textContent = en ? '▭ Select area' : '▭ Seleccionar zona';
            L.DomEvent.disableClickPropagation(contenedor);
            L.DomEvent.disableScrollPropagation(contenedor);
            L.DomEvent.on(boton, 'click', L.DomEvent.stop)
                .on(boton, 'click', function() {
                    dibujos.clearLayers();
                    new L.Draw.Rectangle(mapa, {
                        shapeOptions: {color: '#ffd60a', weight: 2, fillOpacity: 0.05}
                    }).enable();
                });
            return contenedor;
        };
        selector.addTo(mapa);
    })(
        {{ this._parent._parent.get_name() }},
        drawnItems_{{ this._parent.get_name() }}
    );
    {% endmacro %}""")

    def __init__(self) -> None:
        super().__init__()
        self._name = "SelectorZonaUnica"
        self.lang = idioma()


def _identificador_vista_zona(zona: dict | None) -> str:
    """ID solo de navegacion, estable por AOI; nunca examina el raster."""
    if not isinstance(zona, dict) or not zona.get("limites"):
        return "sin_zona"
    try:
        bbox = tuple(round(float(v), 6) for v in zona["limites"])
    except (TypeError, ValueError):
        return "sin_zona"
    if len(bbox) != 4 or not all(np.isfinite(v) for v in bbox):
        return "sin_zona"
    return hashlib.sha256(json.dumps(bbox).encode("ascii")).hexdigest()[:12]


class RecordarVistaNavegador(MacroElement):
    """Conservar pan/zoom entre remontajes Leaflet sin pedir reruns a Streamlit.

    sessionStorage dura solo esta pestaña; no guarda ni transmite geometrías SAR.
    El centro/zoom de una navegación explícita enviado por Python tiene prioridad.
    """

    _template = Template("""{% macro script(this, kwargs) %}
(function(m) {
  // Guardar el encuadre por AOI para no recuperar una ciudad antigua.
  var clave = 'visor-mapa-vista:{{ this.id_zona }}';
  // Una navegacion explicita desde Python (AOI nueva / buscar) tiene prioridad.
  if (!{{ this.ignorar_restauracion }}) {
    try {
      var guardada = JSON.parse(window.sessionStorage.getItem(clave) || 'null');
      if (guardada && Number.isFinite(guardada.lat) && Number.isFinite(guardada.lon) &&
          Number.isFinite(guardada.zoom) && Math.abs(guardada.lat) <= 90 &&
          Math.abs(guardada.lon) <= 180 && guardada.zoom >= 2 && guardada.zoom <= 22) {
        m.setView([guardada.lat, guardada.lon], guardada.zoom, {animate: false});
      }
    } catch (_) { /* sin almacenamiento: el mapa mantiene la vista normal */ }
  }
  function guardar() {
    try {
      var centro = m.getCenter(), zoom = m.getZoom();
      if (Number.isFinite(centro.lat) && Number.isFinite(centro.lng) &&
          Number.isFinite(zoom)) {
        window.sessionStorage.setItem(clave, JSON.stringify({
          lat: centro.lat, lon: centro.lng, zoom: zoom
        }));
      }
    } catch (_) { /* almacenamiento deshabilitado: la navegación sigue funcionando */ }
  }
  m.on('moveend', guardar);
  guardar();
})({{ this._parent.get_name() }});
{% endmacro %}""")

    def __init__(self, id_zona: str = "sin_zona",
                 ignorar_restauracion: bool = False) -> None:
        super().__init__()
        self._name = "RecordarVistaNavegador"
        self.id_zona = id_zona
        self.ignorar_restauracion = "true" if ignorar_restauracion else "false"


def mapa_fijo() -> folium.Map:
    """Lienzo fijo. En Modo Colombia: centrado en el país, paneo limitado a su extensión con margen,
    velo exterior y contorno nacional. En GLOBAL: Antioquia y el mundo entero."""
    centro, zoom = vista_inicio()
    if alcance_geografico.restringido():
        o, s, e, n = alcance_geografico.EXTENSION_NAVEGACION
        limites = {"min_lon": o, "min_lat": s, "max_lon": e, "max_lat": n, "min_zoom": alcance_geografico.ZOOM_MINIMO}
    else:
        limites = {"min_zoom": 2}
    m = folium.Map(
        location=centro,
        zoom_start=zoom,
        tiles=None,
        control_scale=True,
        max_bounds=True,
        max_bounds_viscosity=1.0,
        **limites,
    )
    # folium solo pasa min_zoom a las teselas por defecto (aquí no hay): se fija en el propio mapa.
    m.options["min_zoom"] = limites["min_zoom"]
    # Transiciones Leaflet más fluidas; mover el mapa ya no recalcula los paneles
    # Streamlit gracias al fragmento render (solo la AOI fuerza rerun completo).
    m.options.update({
        "preferCanvas": True,
        "zoomAnimation": True,
        "zoomAnimationThreshold": 8,
        "wheelDebounceTime": 55,
        "wheelPxPerZoomLevel": 45,
    })
    if alcance_geografico.restringido():
        _modo_colombia(m)
    # Vista por pestaña en el navegador: al cambiar de resultado SAR no saltar
    # al último zoom registrado antes de la optimización.
    RecordarVistaNavegador(
        id_zona=_identificador_vista_zona(st.session_state.get("zona")),
        ignorar_restauracion=bool(st.session_state.get("mapa_navegacion_explicita")),
    ).add_to(m)
    m.get_root().header.add_child(folium.Element(ESTILO_LIENZO), name="visor_lienzo")
    # Dibujo de la zona de análisis: solo rectángulo y polígono. Lo dibujado es un borrador;
    # no se convierte en zona hasta confirmarlo en Herramientas SAR («Usar esta zona»).
    control_dibujo = Draw(position="topleft", export=False, show_geometry_on_click=False,
         draw_options={"polyline": False, "circle": False, "marker": False, "circlemarker": False,
                       "rectangle": {"shapeOptions": {"color": "#ffd60a", "weight": 2, "fillOpacity": 0.05}},
                       "polygon": {"allowIntersection": False,
                                   "shapeOptions": {"color": "#ffd60a", "weight": 2, "fillOpacity": 0.05}}},
         edit_options={"edit": True, "remove": True}).add_to(m)
    control_dibujo.add_child(SelectorZonaUnica())
    # Pantalla completa del mapa (API Fullscreen del navegador; el iframe de Streamlit la permite).
    Fullscreen(position="topleft", title=tr("Pantalla completa", "Fullscreen"), title_cancel=tr("Salir de pantalla completa", "Exit fullscreen"),
               force_separate_button=True).add_to(m)
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
        # Mantener teselas ya vistas al arrastrar, sin descargar en cada
        # fotograma del zoom. Se conserva el proveedor/licencia original.
        keep_buffer=4,
        update_when_zooming=False,
        update_when_idle=True,
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


def _soporte_local(mascara: np.ndarray) -> np.ndarray:
    """Vecinos de la misma señal en 3×3, sin filtros sobre el dato SAR original."""
    altura, ancho = mascara.shape
    extendida = np.pad(mascara.astype(np.uint8), 1, mode="constant")
    soporte = np.zeros((altura, ancho), dtype=np.uint8)
    for fila in range(3):
        for columna in range(3):
            soporte += extendida[fila:fila + altura, columna:columna + ancho]
    return soporte


def realzar_alpha_delta(rgba: np.ndarray, datos: np.ma.MaskedArray) -> np.ndarray:
    """Mapa exploratorio con disminuciones agrupadas en cian y fondo transparente.

    Reglas SOLO VISUALES: |Δ| ≤ 2 dB invisible, disminuciones ≤ -3 dB
    destacadas cuando hay al menos 3 píxeles negativos en 3×3; incrementos
    igualmente agrupados, en segundo plano. No constituye mapa de inundación.
    No interpola, no altera valores, QA, NoData ni la ficha del GeoTIFF.
    """
    imagen = rgba.copy()
    valores = np.ma.getdata(datos)
    mascara = np.ma.getmaskarray(datos)
    validos = (~mascara) & np.isfinite(valores)
    negativos = validos & (valores < -UMBRAL_TRANSPARENCIA_VISUAL_DB)
    positivos = validos & (valores > UMBRAL_TRANSPARENCIA_VISUAL_DB)
    coherentes_neg = negativos & (_soporte_local(negativos) >= 3)
    coherentes_pos = positivos & (_soporte_local(positivos) >= 3)
    moderados = coherentes_neg & (valores > -3.0)
    fuertes = coherentes_neg & (valores <= -3.0)
    intensos = fuertes & (valores <= -5.0)

    # Todo lo no representado queda transparente, incluidos los píxeles QA
    # inválidos y los cambios aislados (ruido visual).
    imagen[..., 3] = 0
    imagen[moderados, :3] = (76, 190, 255)
    imagen[moderados, 3] = 115
    imagen[fuertes, :3] = (0, 227, 255)
    imagen[fuertes, 3] = 238
    imagen[intensos, :3] = (24, 113, 255)
    imagen[intensos, 3] = 248
    imagen[coherentes_pos, :3] = (255, 145, 64)
    imagen[coherentes_pos, 3] = 82
    return imagen


@st.cache_data(show_spinner=False, max_entries=16)
def imagen_resultado(ruta: str, firma: tuple, perfil: str, _res: ResultadoSAR) -> str:
    """PNG (data URL) de un resultado. Colorear y codificar ~1000×1000 px cuesta ~60 ms y se
    repetía en cada recarga; ahora solo cambia si cambia el archivo o su ficha (`firma`)."""
    from folium.utilities import image_to_url
    oeste, sur, este, norte = _res.capa.limites
    rgba = (colorizar_diferencia(_res.capa.datos) if _res.perfil.continuo
            else colorizar_categorico(_res.capa.datos, _res.perfil.clases))
    if _res.perfil.continuo:
        rgba = realzar_alpha_delta(rgba, _res.capa.datos)
    # Mostrar los píxeles reales terrestres aunque su huella bounding-box
    # cruza la costa. Recorte SOLO visual; las matrices y estadísticas siguen
    # siendo las originales, sin reinterpretar mar ni zonas extranjeras.
    if (alcance_geografico.restringido()
            and _res.capa.procedencia is not None
            and _res.capa.procedencia.es_real
            and not alcance_geografico.admitida(_res.capa.limites)):
        dentro = alcance_geografico.mascara_pixeles_colombia(_res.capa)
        if dentro is not None:
            rgba[~dentro, 3] = 0
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
            return limites, float(ultimo.get("zoom") or vista_inicio()[1])
    centro = (vista or {}).get("centro") or list(vista_inicio()[0])
    zoom = float((vista or {}).get("zoom") or vista_inicio()[1])
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


def _centro_y_zoom_guardados(vista: dict | None):
    """Navegación explícita o último encuadre real; nunca volver a zoom_start."""
    anterior = st.session_state.get("mapa_encuadre_usuario")
    secuencia = vista.get("n") if vista else None
    if vista is not None and secuencia != st.session_state.get("mapa_ultimo_destino"):
        centro, zoom = destino_vista(vista)
        st.session_state["mapa_ultimo_destino"] = secuencia
        st.session_state["mapa_encuadre_usuario"] = {"centro": centro, "zoom": zoom}
        return centro, zoom
    if isinstance(anterior, dict):
        return anterior.get("centro"), anterior.get("zoom")
    return None, None


def _guardar_encuadre_usuario() -> None:
    """Captura el viewport desde el widget ANTES de reconstruir el mapa."""
    datos = st.session_state.get(st.session_state.get("mapa_widget_key", "mapa"))
    if not isinstance(datos, dict):
        return
    zoom = datos.get("zoom")
    if not isinstance(zoom, (int, float)) or not np.isfinite(zoom) or not (2 <= zoom <= 22):
        return
    centro = datos.get("center")
    if isinstance(centro, dict):
        lat, lon = centro.get("lat"), centro.get("lng")
        centro = [lat, lon] if all(isinstance(v, (int, float)) for v in (lat, lon)) else None
    if not isinstance(centro, (list, tuple)) or len(centro) != 2:
        limites = limites_de_vista(datos.get("bounds"))
        if limites is None:
            return
        oeste, sur, este, norte = limites
        centro = [(sur + norte) / 2, (oeste + este) / 2]
    try:
        lat, lon = float(centro[0]), float(centro[1])
    except (TypeError, ValueError):
        return
    if not np.isfinite(lat) or not np.isfinite(lon):
        return
    st.session_state["mapa_encuadre_usuario"] = {
        "centro": [lat, lon], "zoom": float(zoom),
    }


def _sincronizar_zona_dibujada(dibujos: list | None) -> bool:
    """Al soltar el rectángulo, confirmar una sola AOI sin tocar ningún GeoTIFF.

    El marcador de firma impide confirmar la misma figura de nuevo en un rerun.
    Si el usuario borra la figura, la zona activa queda deseleccionada.
    """
    ultimo = dibujos[-1] if dibujos else None
    firma = json.dumps(ultimo, sort_keys=True) if ultimo is not None else None
    if firma == st.session_state.get("mapa_firma_dibujo"):
        return False
    st.session_state["mapa_firma_dibujo"] = firma
    # Retirar el AOI previo y el resultado ligado a él. Los archivos históricos
    # siguen en disco y el panel del historial no pierde referencias.
    if st.session_state.get("zona") is not None:
        flujo.quitar_zona()
    elif st.session_state.get("resultado_activo") is not None:
        flujo.limpiar_resultado("Se eligió otra zona; el resultado anterior sigue en el historial.")
    st.session_state["mapa_dibujo"] = ultimo
    if ultimo is None:
        return True
    for clave in ("v9_firma", "v9_preparacion", "v9_mapa_job",
                  "v9_publicado", "v9_error", "v9_sugerencias"):
        st.session_state.pop(clave, None)
    st.session_state["ui_sar"] = "abierto"
    st.session_state["ui_explorador"] = False
    try:
        limites, geometria = sesion.zona_de_geojson(ultimo)
        flujo.confirmar_zona(limites, "rectángulo dibujado en el mapa", geometria)
    except sesion.ErrorZona as exc:
        # Nunca aceptar un AOI demasiado grande, fuera de Colombia o inválido.
        st.session_state["error_zona"] = str(exc)
    return True


def render(fenomeno: Fenomeno, capa: Capa | None, c: Controles, vista: dict | None = None,
           resultados: list[ResultadoSAR] | tuple = (), extras: list[folium.FeatureGroup] | tuple = (),
           seguir_vista: bool = False, seleccionar_par: bool = False) -> None:
    """`extras`: grupos adicionales encima de todo (zona, marcador del lugar y huellas de entrada).

    El mapa devuelve el borrador de zona dibujado y su encuadre (para recortar ríos y carreteras a lo
    que se ve y para «usar el área visible»). Nada de lo que devuelve el mapa lanza un análisis."""
    # Cada rerun debe recibir resultados, controles y overlays actualizados.
    # Con @st.fragment el pan/zoom usaba argumentos obsoletos y restauraba el histórico.
    # Identidad estable del mapa para pan/zoom, nueva al elegir otro GeoTIFF.
    # Así el componente no conserva overlays anteriores al cambiar el historial.
    resultado = next(iter(sorted(c.resultados)), "none")
    clave_widget = "mapa" if resultado == "none" and idioma() == "es" else f"mapa__{resultado}__{idioma()}"
    # El cambio de AOI remonta Leaflet solo UNA vez, para descartar la vista
    # guardada y los dibujos del municipio anterior. Pan/zoom conservan la clave.
    id_zona = _identificador_vista_zona(st.session_state.get("zona"))
    if id_zona != "sin_zona":
        clave_widget += f"__zona_{id_zona}"
    # El mapa es interactivo en el navegador: un pan/zoom normal no necesita
    # ejecutar de nuevo Streamlit ni volver a serializar los overlays SAR.
    # Solo la AOI dibujada debe activar el servidor. Las herramientas que
    # necesitan la extensión visible y las capas de ríos/vías recortadas sí
    # reciben bounds/zoom/center para actualizarlas mientras se navega.
    seguir_encuadre = bool(seguir_vista or getattr(c, "hidrografia", False)
                           or getattr(c, "vias", False))
    objetos_devuelto = (["all_drawings", "bounds", "zoom", "center"]
                         if seguir_encuadre else ["all_drawings"])
    # Un clic en una huella selecciona el par, pero pan/zoom no vuelve a
    # consultar NASA ni necesita reejecutar Python. Solo activar en este modo.
    if seleccionar_par:
        objetos_devuelto.append("last_object_clicked")
    # streamlit-folium fija returned_objects al montar su iframe: entrar
    # o salir del modo de seguimiento requiere UNA nueva instancia, no un
    # remontaje por cada cambio de centro/zoom.
    if seguir_encuadre:
        clave_widget += "__seguir_vista"
    if seleccionar_par:
        clave_widget += "__pares_nisar"
    # Solo un clic en una recomendación recrea el componente para limpiar dibujos
    # antiguos de Leaflet. La clave permanece estable durante pan/zoom.
    sugerencia_version = int(st.session_state.get("visor_aoi_recomendacion_seq", 0))
    if sugerencia_version:
        clave_widget += f"__recomendacion_{sugerencia_version}"
    clave_anterior = st.session_state.get("mapa_widget_key")
    remontaje = clave_widget != clave_anterior
    nueva_navegacion = vista is not None and vista.get("n") != st.session_state.get("mapa_ultimo_destino")
    if remontaje:
        st.session_state["mapa_widget_key"] = clave_widget
        st.session_state["mapa_firma_dibujo"] = None
    st.session_state["mapa_navegacion_explicita"] = bool(nueva_navegacion)
    centro, zoom = _centro_y_zoom_guardados(vista)
    if remontaje and clave_anterior is not None and not nueva_navegacion:
        # Un cambio de GeoTIFF/seguimiento remonta Leaflet. La vista actual
        # permanece en sessionStorage del iframe y es más reciente que el
        # último encuadre enviado al servidor (que ya no recibe cada pan).
        centro, zoom = None, None
    salida = st_folium(
        mapa_fijo(),
        feature_group_to_add=[*construir_capas(fenomeno, capa, c, resultados), *extras],
        height=720,                   # inicial; ESTILO_LIENZO lo lleva a pantalla completa
        use_container_width=True,
        # streamlit-folium fija esta lista al montar el mapa y no la vuelve a leer: tiene que ser
        # constante. Mover el mapa provoca una recarga ligera (sin recálculo) para conocer el encuadre.
        returned_objects=objetos_devuelto,
        center=centro,
        zoom=zoom,
        key=clave_widget,            # estable en zoom; nueva al cambiar resultado
        on_change=_guardar_encuadre_usuario,
    ) or {}
    # El componente puede devolver una actualización parcial (zoom, capas).
    # Ausencia de all_drawings NO significa que el usuario borró su AOI.
    nueva_seleccion = (
        _sincronizar_zona_dibujada(salida["all_drawings"])
        if salida.get("all_drawings") is not None else False
    )
    limites = limites_de_vista(salida.get("bounds"))
    if limites is not None and limites[0] < limites[2]:
        st.session_state["mapa_limites"] = limites
    elif seguir_encuadre:
        # No pisar el último encuadre solo porque el componente aún está
        # montándose; queda disponible al moverlo en modo de seguimiento.
        st.session_state.setdefault("mapa_limites", None)
    if nueva_seleccion:
        st.rerun()  # Nueva AOI: refresca también los controles externos al mapa.
    if seleccionar_par and salida.get("last_object_clicked") is not None:
        from components import v9_experiencia
        if v9_experiencia.seleccionar_desde_mapa(
            salida["last_object_clicked"], clave_widget
        ):
            st.rerun()  # Solo selección explícita; nunca pan/zoom.


def limites_de_vista(bounds) -> tuple[float, float, float, float] | None:
    """(oeste, sur, este, norte) de lo que devuelve streamlit-folium, o None si aún no hay vista."""
    try:
        so, ne = bounds["_southWest"], bounds["_northEast"]
        return float(so["lng"]), float(so["lat"]), float(ne["lng"]), float(ne["lat"])
    except (TypeError, KeyError, ValueError):
        return None
