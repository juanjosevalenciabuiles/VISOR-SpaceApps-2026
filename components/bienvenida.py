"""Ventana emergente persistente, bilingüe y de cierre explícito de V.I.S.O.R.

A diferencia de un diálogo de Streamlit, este panel se dibuja en cada ejecución
y solo se cierra por una acción explícita del visitante. Nunca toca el estado SAR.
"""
from __future__ import annotations

import streamlit as st

from utils.i18n import idioma, seleccionar, tr

CLAVE_ABIERTA = "visor_guia_abierta"
CLAVE_CAPITULO = "visor_guia_capitulo"

ESTILO = """
<style id="visor-guia-emergente">
/* Ventana emergente propia: NO usa st.dialog, porque el rerun de Folium
   destruye diálogos de Streamlit. El fondo no contiene botones de cierre. */
.visor-guia-sombra {
  position: fixed !important; inset: 0 !important; z-index: 90 !important;
  background: rgba(1, 9, 20, .75) !important;
  backdrop-filter: blur(4px) !important;
  pointer-events: none !important;
}
.st-key-visor_guia_panel {
  position: fixed !important; z-index: 110 !important;
  top: 50% !important; left: 50% !important; bottom: auto !important;
  transform: translate(-50%, -50%) !important;
  width: min(740px, calc(100vw - 32px)) !important;
  max-height: min(85vh, 850px) !important;
  max-height: min(85dvh, 850px) !important;
  overflow-y: auto !important; overscroll-behavior: contain;
  padding: 22px 26px 24px !important;
  border: 1px solid rgba(69,228,244,.65) !important;
  border-radius: 22px !important; color: #edf6ff !important;
  background: rgba(7,20,36,.98) !important;
  box-shadow: 0 22px 85px rgba(0,0,0,.74) !important;
}
.st-key-visor_guia_panel p, .st-key-visor_guia_panel li {
  color: #e2ecf7 !important; line-height: 1.5 !important;
}
.st-key-visor_guia_panel h2, .st-key-visor_guia_panel h3 {
  color: #45e4f4 !important;
}
.st-key-visor_guia_panel [data-testid="stMarkdownContainer"] a {
  color: #91eaff !important;
}
.st-key-visor_guia_launcher {
  position: fixed !important; z-index: 100 !important;
  bottom: 12px !important; left: 12px !important;
  width: auto !important; max-width: calc(100vw - 24px) !important;
  padding: 5px 8px !important; background: rgba(5,17,31,.96) !important;
  border: 1px solid rgba(69,228,244,.6); border-radius: 14px;
  color: #f5f8ff !important;
}
.st-key-visor_guia_launcher button {
  color: #f5f8ff !important; min-height: 34px !important;
  padding: 4px 10px !important; white-space: nowrap !important;
}
@media (max-width: 720px) {
  .st-key-visor_guia_panel {
    top: 49% !important; width: calc(100vw - 16px) !important;
    max-height: 80dvh !important; padding: 12px 15px 16px !important;
    border-radius: 14px !important;
  }
  .st-key-visor_guia_launcher { bottom: 5px !important; left: 5px !important; }
  .st-key-visor_guia_launcher button { padding: 3px 6px !important; }
}

/* El único cierre de la bienvenida es una X discreta arriba a la derecha. */
.st-key-visor_guia_cerrar {
  position: sticky !important;
  top: 0 !important;
  float: right !important;
  width: 40px !important;
  z-index: 115 !important;
  margin: 0 0 4px 8px !important;
}
.st-key-visor_guia_cerrar button {
  width: 38px !important; height: 38px !important;
  min-height: 38px !important; padding: 0 !important;
  border-radius: 50% !important;
  background: rgba(255,255,255,.09) !important;
  border: 1px solid rgba(255,255,255,.22) !important;
  color: white !important;
}
</style>
"""
CAPITULOS = {
    "es": [
        ("Empezar · qué es V.I.S.O.R.", """
### Bienvenido a V.I.S.O.R. 🛰️

V.I.S.O.R. permite explorar observaciones de radar de apertura sintética (SAR)
y estudiar cambios en la superficie terrestre, especialmente relacionados con
el agua. No hace falta tener experiencia previa en teledetección.

**La regla más importante:** un cambio en la señal del radar **no confirma por
sí solo una inundación**. La lluvia, la humedad del suelo, los cultivos, el
relieve y el ruido radar también pueden afectar a los resultados.

**Recorrido recomendado:** buscar un municipio → seleccionar un área → escoger
un intervalo → buscar datos SAR → revisar el resultado → consultar procedencia.
No todos los lugares ni fechas disponen de adquisiciones compatibles.
"""),
        ("Buscar lugares y navegar", """
### 1. Encuentra tu territorio

1. En el buscador superior izquierdo escribe un municipio de Colombia, por
   ejemplo Chigorodó o Rionegro. También puedes introducir coordenadas como
   7.67, -76.68.
2. Selecciona la sugerencia correcta o pulsa **Buscar**.
3. Arrastra el mapa para desplazarte y utiliza la rueda o los controles de
   zoom para ampliar y reducir.
4. Usa **Vista inicial** para volver al encuadre general.

**Importante:** desplazar el mapa no debería cambiar el GeoTIFF del resultado
activo. Si aparece otra capa, repórtalo como un error de visualización.
"""),
        ("Delimitar el área (AOI)", """
### 2. Dibuja la zona de estudio

1. Abre **Herramientas SAR**.
2. Pulsa **▭ Seleccionar zona** sobre el mapa.
3. Presiona una esquina, arrastra hasta la opuesta y suelta para crear un
   rectángulo. También puedes usar las herramientas de dibujo de Leaflet.
4. Si aparece **Usar esta zona**, púlsalo para confirmar.
5. Comprueba las coordenadas y el tamaño del área. Las áreas muy grandes
   pueden superar los límites del procesamiento.

La zona (AOI, *Area of Interest*) delimita dónde buscar imágenes. No indica
que exista una inundación. Cambiar de zona puede retirar de la pantalla el
resultado anterior, pero **no borra su archivo del historial**.
"""),
        ("Sensores y adquisición de imágenes", """
### 3. ¿De dónde vienen las imágenes?

**NISAR (NASA–ISRO)** observa mediante radar de banda L. Es la fuente principal
del flujo de inundaciones de esta versión. Sus productos GCOV pueden
encontrarse en distintas etapas de madurez, como **VALIDATED** o
**PROVISIONAL**; el estado debe leerse en la ficha y no confundirse con una
validación de inundación.

**Sentinel-1** (ESA/Copernicus) usa banda C. Actúa como fuente de respaldo en
los flujos donde esté configurado y existan datos adecuados; **no debe asumirse
que se activa automáticamente en todos los casos**.

1. Confirma una AOI.
2. Indica las fechas de inicio y fin.
3. Abre el paso de búsqueda/preparación NISAR y sigue las opciones presentes
   en tu versión.
4. Revisa cobertura, polarizaciones, disponibilidad y avisos de calidad antes
   de analizar.

Si no aparecen escenas, prueba otra zona o período. No sustituyas
silenciosamente imágenes de otras fechas o sensores.
"""),
        ("Ejecutar e interpretar análisis", """
### 4. Interpretación del cambio SAR

Cuando existan dos observaciones comparables y preparadas, podrás solicitar
un cálculo. V.I.S.O.R. debe conservar las fechas, el sensor y el proceso
utilizados; algunos análisis requieren servicios externos y pueden no estar
disponibles para una AOI determinada.

- **ΔdB (delta en decibelios):** diferencia entre la retrodispersión posterior
  y la anterior. Es una medición de cambio de señal, no una probabilidad.
- **Cian/azul:** normalmente se usa para disminuciones de retrodispersión.
- **Naranja/rojo:** normalmente señala aumentos en las vistas continuas.
- **Transparencia/NoData:** píxeles sin dato válido, fuera de cobertura o
  excluidos por la visualización; no los interpretes como ausencia de agua.
- **Máscaras de clases:** usan categorías y leyendas distintas de un ΔdB
  continuo. Comprueba el nombre y tipo del producto antes de comparar colores.

Revisa los avisos científicos, la cobertura y la ficha antes de concluir.
Para confirmar una inundación se necesitan evidencias independientes.
"""),
        ("Capas ambientales y controles", """
### 5. Panel CAPAS DEL MAPA

El panel flotante permite activar fuentes de contexto sin iniciar un análisis:

- **IDEAM:** alertas hidrológicas. Una alerta no es detección de inundación.
- **DANE:** límites municipales y referencias geográficas.
- **NASA EONET:** catálogo de eventos naturales, no un mapa de daños.
- **Cartografía y fondo:** cambia el mapa de referencia.
- **Resultados SAR y opacidad:** muestra, oculta o ajusta la transparencia
  del GeoTIFF que se ha seleccionado.

Cambiar el fondo, la opacidad o una capa contextual **no debería sustituir**
el resultado activo ni sus fechas. Consulta siempre la atribución de las capas.
"""),
        ("Resultados, historial y procedencia", """
### 6. Distingue un análisis nuevo del historial

El resultado nuevo se identifica como **ANÁLISIS DE ESTA SESIÓN**. El historial
contiene GeoTIFF anteriores y solo deben mostrarse cuando los abras de forma
explícita. Si eliges un archivo viejo, aparecerá como **HISTÓRICO**.

En **Explorador → Historial** puedes pulsar **Ver**. En **Información** revisa
las fechas, los datos de entrada, las unidades, el producto y su procedencia.
Cuando la opción exista, exporta a QGIS para una inspección más detallada.

**Estados de evidencia:**

- **DEMO:** capa sintética; no son observaciones de satélite.
- **PROCEDENCIA NO DECLARADA:** falta documentación suficiente del archivo.
- **REAL SIN VALIDAR:** hay datos satelitales reales y procedencia, pero el
  resultado es exploratorio.
- **VALIDADO:** exige verificación independiente documentada, no se otorga
  automáticamente.

La ficha JSON y la huella SHA-256 ayudan a comprobar correspondencia entre
archivo y metadatos. No borres resultados por cambiar la visualización.
"""),
        ("Laboratorio IA", """
### 7. ¿Qué hace el Laboratorio IA?

El **Laboratorio IA** muestra experimentos históricos de aprendizaje automático
sobre datos del territorio. Úsalo para conocer las variables, métodos,
métricas y limitaciones del entrenamiento.

No interpretes una predicción histórica como una clasificación en tiempo real
de la zona que acabas de dibujar. El Laboratorio IA y el análisis SAR operativo
son flujos distintos mientras no se haya documentado una integración validada.
"""),
        ("Problemas frecuentes", """
### 8. Solución de problemas

**La guía se cerraba al mover el mapa:** esta versión usa un panel persistente,
no una ventana emergente. Solo el botón de cerrar debería ocultarlo; el botón
**Guía / Guide** lo recupera en cualquier momento.

**No hay escenas NISAR compatibles:** revisa la AOI, período, cobertura y
madurez del producto. La ausencia en una consulta no prueba la ausencia de
observaciones de otros sensores.

**No se puede descargar o preparar un producto:** comprueba la disponibilidad
del servicio NASA/ASF/Harmony y la necesidad de autenticación en el entorno.
Nunca introduzcas contraseñas en la guía pública.

**El resultado cambia al desplazar el mapa:** vuelve a revisar el selector de
**Resultados SAR y opacidad**. Mover el mapa no debe activar un archivo antiguo.
Si persiste, informa el archivo mostrado y las fechas de la ficha.

**Veo píxeles de colores dispersos:** puede tratarse de un producto continuo
ΔdB con variación local o una máscara antigua. Antes de interpretarlos revisa
leyenda, umbrales, NoData, procedencia y fecha.

**No encuentro un botón:** revisa que el panel correspondiente esté abierto
y utiliza la búsqueda dentro de esta guía.
"""),
    ],
    "en": [
        ("Getting started · What is V.I.S.O.R.?", """
### Welcome to V.I.S.O.R. 🛰️

V.I.S.O.R. helps you explore synthetic aperture radar (SAR) observations and
study changes at Earth's surface, especially changes related to water.
No remote-sensing experience is required.

**The essential rule:** a change in radar backscatter **does not, by itself,
confirm a flood**. Rainfall, soil moisture, agriculture, terrain and radar
noise can also change the signal.

**Suggested workflow:** search for a place → select an area → choose a date
range → look for SAR data → inspect results → check data provenance.
Compatible observations are not guaranteed for every date or location.
"""),
        ("Find places and navigate", """
### 1. Locate your study area

1. Enter a municipality in Colombia in the search field at the upper left,
   such as Chigorodó or Rionegro. Coordinates such as 7.67, -76.68 also work.
2. Select the appropriate suggestion or press **Search**.
3. Drag the map to pan; use the mouse wheel or zoom controls to zoom.
4. Use **Initial view** to return to the overview.

**Important:** map panning should never switch your currently displayed
GeoTIFF to a different historical product. If it does, report a display bug.
"""),
        ("Draw an area of interest (AOI)", """
### 2. Define your area

1. Open **SAR Tools**.
2. Press **▭ Select area** on the map.
3. Click one corner, drag to the opposite corner and release to draw a
   rectangle. You may also use Leaflet drawing tools.
4. If **Use this area** appears, confirm your selection.
5. Check the bounding coordinates and area size; very large areas may
   exceed processing limits.

The AOI defines where imagery should be searched; it is **not** a flood
footprint. Changing it may remove the current result from the map, but will
**not delete the historical GeoTIFF**.
"""),
        ("Satellites and data acquisition", """
### 3. Where do the observations come from?

**NISAR (NASA–ISRO)** uses L-band radar and is the primary source in this
version's flood-related workflow. GCOV products may have different maturity
levels, such as **VALIDATED** or **PROVISIONAL**. Product maturity does not
mean a flood has been independently confirmed.

**Sentinel-1** (ESA/Copernicus) uses C-band radar and can provide a fallback
in configured workflows with compatible data; **do not assume an automatic
fallback is available in every environment**.

1. Confirm an AOI and set the start/end dates.
2. Open the NISAR search and preparation step available in your version.
3. Check coverage, polarizations, scene availability and quality warnings.
4. Analyze only when suitable observations have been prepared.

If no scenes match, choose another area or time range. Never silently
substitute a different sensor or acquisition period.
"""),
        ("Run and interpret SAR analysis", """
### 4. Understanding SAR change maps

When two compatible observations are available, you can request a change
analysis. The source sensor, dates and processing steps must be preserved.
External services or valid prepared scenes may be required.

- **ΔdB (decibels):** post-event minus pre-event radar backscatter. This is
  a signal difference, **not a flood probability**.
- **Cyan/blue:** generally highlights decreases in backscatter.
- **Orange/red:** generally highlights increases on continuous difference maps.
- **Transparent/NoData:** absent, invalid or excluded data. Transparency does
  not mean there is no water.
- **Categorical masks:** use different legends from continuous ΔdB products.
  Check the product type before interpreting a color.

Use provenance and independent evidence before reporting a possible flood.
"""),
        ("Environmental layers and map controls", """
### 5. MAP LAYERS

The floating layers panel provides context independently of SAR processing:

- **IDEAM:** hydrological alerts, not satellite-confirmed floods.
- **DANE:** municipal boundaries and geographic references.
- **NASA EONET:** natural-event records, not damage footprints.
- **Basemaps:** change the reference map underneath your observations.
- **SAR results / opacity:** toggle the active GeoTIFF and adjust transparency.

Changing a basemap, contextual layer or opacity **must not replace** the
selected SAR product or its acquisition dates. Always review attribution.
"""),
        ("Results, history and provenance", """
### 6. Current results versus history

A new result is labeled **ANALYSIS FROM THIS SESSION**. The history contains
previous GeoTIFFs, which should only appear after you deliberately open them.
A previously saved product should be labeled **HISTORICAL**.

Open **Explorer → History** and select **View**. Use **Information** to read
acquisition dates, sensor, processing method, units and provenance. Export
to QGIS where that feature is available.

**Evidence status labels:**

- **DEMO:** synthetic illustration, not satellite observations.
- **PROVENANCE NOT DECLARED:** insufficient metadata to establish source.
- **REAL — NOT VALIDATED:** derived from real observations with documented
  provenance, but still exploratory.
- **VALIDATED:** requires a separate, documented verification step; never
  assigned automatically.

A JSON record and SHA-256 checksum can help link metadata to a GeoTIFF.
Changing the view must never delete underlying results.
"""),
        ("AI Laboratory", """
### 7. What does the AI Laboratory show?

The **AI Laboratory** presents historical machine-learning experiments over
territorial datasets. It can help you explore variables, training methods,
metrics and limitations.

A historical model experiment is **not a live flood classification** for the
area you just selected. Do not present it as operational inference unless
a documented, independently validated integration is available.
"""),
        ("Troubleshooting", """
### 8. Troubleshooting

**The guide used to disappear when panning:** this version uses a persistent
panel rather than an automatically dismissed dialog. Use **Guide** to open
it again after closing it intentionally.

**No NISAR scenes:** check AOI, date range, coverage and product maturity.
A query with no matches does not establish that no other sensor observed the area.

**Download or processing fails:** check NASA/ASF/Harmony service availability
and any required authentication configured on the server. Never submit
credentials to the public guide.

**A historical layer appears when you pan:** inspect **SAR results and
opacity**. Panning should not change the selected file; report the product
name and date if the issue persists.

**Scattered colored pixels:** these may come from a continuous ΔdB difference
map or a historical categorical mask. Check thresholds, NoData, legend,
acquisition dates and provenance before interpreting them.

**A button is missing:** open its corresponding panel or search this guide.
"""),
    ],
}


def abrir() -> None:
    """Abrir sin tocar mapa, zona, análisis, trabajos ni resultados."""
    st.session_state[CLAVE_ABIERTA] = True


def cerrar() -> None:
    """Cerrar solamente cuando el visitante lo solicita."""
    st.session_state[CLAVE_ABIERTA] = False


def alternar() -> None:
    st.session_state[CLAVE_ABIERTA] = not st.session_state.get(CLAVE_ABIERTA, True)


def _lang_es() -> None:
    seleccionar("es")


def _lang_en() -> None:
    seleccionar("en")


def render() -> None:
    """Dibujar en TODOS los reruns. Sin st.dialog y sin temporizadores."""
    st.session_state.setdefault(CLAVE_ABIERTA, True)
    st.session_state.setdefault("visor_idioma", idioma())
    st.markdown(ESTILO, unsafe_allow_html=True)

    with st.container(key="visor_guia_launcher", horizontal=True,
                      vertical_alignment="center", gap="small"):
        st.button(
            tr("📖 Abrir guía", "📖 Open guide"), key="visor_guia_toggle",
            on_click=abrir,
            help=tr("Abrir u ocultar el manual; no modifica el mapa ni resultados.",
                    "Open or hide the manual without changing map or results."),
        )
        st.button("ES", key="visor_idioma_es", on_click=_lang_es,
                  type="primary" if idioma() == "es" else "secondary",
                  help="Español")
        st.button("EN", key="visor_idioma_en", on_click=_lang_en,
                  type="primary" if idioma() == "en" else "secondary",
                  help="English")

    if not st.session_state[CLAVE_ABIERTA]:
        return

    capitulos = CAPITULOS[idioma()]
    # Fondo bloquea interacciones accidentales, pero no cierra la ventana.
    # Un rerun del mapa reconstruye ambos elementos con el mismo estado abierto.
    st.markdown('<div class="visor-guia-sombra" aria-hidden="true"></div>',
                unsafe_allow_html=True)
    with st.container(key="visor_guia_panel"):
        st.markdown(tr("## Bienvenido a V.I.S.O.R. 🛰️", "## Welcome to V.I.S.O.R. 🛰️"))
        st.caption(tr(
            "Esta ventana solo se cierra al pulsar «Cerrar». Puedes volver a abrirla desde 📖.",
            "This window closes only when you press «Close». Reopen it any time using 📖."
        ))
        st.button("✕", key="visor_guia_cerrar",
                  on_click=cerrar,
                  help=tr("Cerrar bienvenida", "Close welcome window"))
        consulta = st.text_input(
            tr("🔎 Buscar en el manual", "🔎 Search this guide"),
            key="visor_guia_busqueda",
            placeholder=tr("Ej.: NISAR, colores, historial",
                           "E.g. NISAR, colors, history"),
        ).strip().casefold()
        if consulta:
            coincidencias = [(titulo, contenido) for titulo, contenido in capitulos
                             if consulta in (titulo + " " + contenido).casefold()]
            if not coincidencias:
                st.info(tr("No hay capítulos con esa palabra.",
                           "No chapters match your search."))
            for titulo, contenido in coincidencias:
                with st.expander(titulo, expanded=True):
                    st.markdown(contenido)
        else:
            actual = st.session_state.get(CLAVE_CAPITULO, 0)
            if not isinstance(actual, int) or actual not in range(len(capitulos)):
                st.session_state[CLAVE_CAPITULO] = 0
            seccion = st.selectbox(
                tr("Índice de capítulos", "Table of contents"),
                options=list(range(len(capitulos))),
                format_func=lambda indice: capitulos[indice][0],
                key=CLAVE_CAPITULO,
            )
            st.markdown(capitulos[seccion][1])

        st.info(tr(
            "Nota científica: los cambios SAR son indicios; no confirman por sí solos una inundación.",
            "Scientific note: SAR changes are indicators; they do not by themselves confirm flooding."
        ))

