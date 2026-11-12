"""Interfaz Mission Control Earth Explorer: superficies flotantes sobre un único mapa.

El mapa ocupa todo el viewport y nunca se reemplaza. Encima flotan:

    barra superior · explorador · panel científico · Herramientas SAR · línea temporal

Reglas de diseño que este módulo respeta:

- Ocultar un panel NO deja de dibujarlo: se oculta con CSS. Así sus controles
  conservan su valor (por ejemplo, el fenómeno elegido) y el mapa no se toca.
- Todo el estado de la interfaz vive en `st.session_state` con las claves de
  ESTADO_INICIAL.
- Mover la vista ("Ir a…", "Área inicial") envía centro y zoom al mapa existente;
  nunca lo recrea (ver components/mapa.destino_vista).
"""
from __future__ import annotations

from html import escape

import streamlit as st

from components import barra_lateral, panel_info
from components.barra_lateral import Controles
from components.panel_info import insignia
from utils.config import MAPA_CENTRO, MAPA_ZOOM, Fenomeno
from utils import procedencia
from utils.geotiff import Capa

ESTADO_INICIAL = {
    "ui_explorador": True,              # panel izquierdo de exploración
    "ui_info": True,                    # panel científico de la derecha
    "ui_sar": "cerrado",                # "cerrado" | "abierto" | "minimizado"
    "ui_explorador_previo": True,       # cómo estaba el explorador antes de abrir SAR
    "vista": None,                      # {"centro": [lat, lon], "zoom": z, "n": k}
}
ESTADOS_SAR = ("cerrado", "abierto", "minimizado")
PASOS_SAR = ("01 · Área", "02 · Escenas", "03 · Análisis", "04 · Resultados")


def inicializar_estado() -> None:
    for clave, valor in ESTADO_INICIAL.items():
        st.session_state.setdefault(clave, valor)
    if st.session_state["ui_sar"] not in ESTADOS_SAR:
        st.session_state["ui_sar"] = "cerrado"


# ---------------------------------------------------------------------------
# Acciones (callbacks): solo cambian estado de interfaz, nunca el mapa ni datos
# ---------------------------------------------------------------------------

def alternar_explorador() -> None:
    abrir = not st.session_state["ui_explorador"]
    st.session_state["ui_explorador"] = abrir
    if abrir and st.session_state["ui_sar"] == "abierto":
        st.session_state["ui_sar"] = "minimizado"   # ambos ocupan el lado izquierdo


def alternar_info() -> None:
    st.session_state["ui_info"] = not st.session_state["ui_info"]


def abrir_sar() -> None:
    if st.session_state["ui_sar"] == "cerrado":
        st.session_state["ui_explorador_previo"] = st.session_state["ui_explorador"]
    st.session_state["ui_sar"] = "abierto"
    st.session_state["ui_explorador"] = False


def minimizar_sar() -> None:
    st.session_state["ui_sar"] = "minimizado"


def cerrar_sar() -> None:
    st.session_state["ui_sar"] = "cerrado"
    st.session_state["ui_explorador"] = st.session_state["ui_explorador_previo"]


def ir_a(lat: float, lon: float, zoom: float) -> None:
    anterior = st.session_state.get("vista") or {}
    st.session_state["vista"] = {"centro": [float(lat), float(lon)], "zoom": float(zoom),
                                 "n": int(anterior.get("n", 0)) + 1}


def _ir_a_coordenadas() -> None:
    ir_a(st.session_state["ir_lat"], st.session_state["ir_lon"], st.session_state["ir_zoom"])


def volver_al_inicio() -> None:
    ir_a(MAPA_CENTRO[0], MAPA_CENTRO[1], MAPA_ZOOM)


# ---------------------------------------------------------------------------
# Estilos dependientes del estado
# ---------------------------------------------------------------------------

def css_estado() -> str:
    """Oculta con CSS los paneles cerrados (siguen dibujados y conservan su estado)."""
    ocultos = []
    if not st.session_state["ui_explorador"]:
        ocultos.append(".st-key-panel_explorador")
    if not st.session_state["ui_info"]:
        ocultos.append(".st-key-panel_info")
    if st.session_state["ui_sar"] != "abierto":
        ocultos.append(".st-key-panel_sar")
    if st.session_state["ui_sar"] != "minimizado":
        ocultos.append(".st-key-sar_minimizado")
    return (",".join(ocultos) + "{display:none !important}") if ocultos else ""


def aplicar_css_estado() -> None:
    st.markdown(f"<style>{css_estado()}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Superficies
# ---------------------------------------------------------------------------

def insignia_procedencia(capa: Capa | None) -> str:
    if capa is None:
        return '<span class="mc-insignia mc-insignia-tenue">SIN CAPA</span>'
    if capa.es_demo:  # la marca del propio GeoTIFF manda, aunque falte la evaluación
        return insignia(procedencia.Procedencia(procedencia.DEMO, "VISOR_DEMO=1"))
    return insignia(capa.procedencia)


@st.dialog("Ayuda · V.I.S.O.R.", width="large")
def mostrar_ayuda() -> None:
    st.markdown(
        """
**Cómo usar el visor**

- El mapa ocupa toda la pantalla. Arrástralo y usa la rueda o los botones **+ / −** para el zoom.
- **Explorador** (izquierda): fenómeno, mapa base, capas y opacidad.
- **Información** (derecha): qué muestra la capa, de dónde viene, leyenda y créditos.
- **Ir a…**: lleva el mapa a unas coordenadas o de vuelta al área inicial.
- **Herramientas SAR**: flujo de búsqueda y análisis de imágenes de radar. Puedes minimizarlo o
  cerrarlo sin perder el mapa ni sus capas.
- Cierra los paneles para ver el mapa completo; vuelve a abrirlos desde la barra superior.

**Qué significan las etiquetas**

| Etiqueta | Significado |
| --- | --- |
| DEMO | Datos sintéticos generados para probar la interfaz. No son observaciones. |
| PROCEDENCIA NO DECLARADA | Falta una ficha de procedencia completa: no se puede afirmar de qué datos ni de qué proceso sale la capa. |
| REAL SIN VALIDAR | Producto derivado de datos satelitales reales, con ficha de procedencia completa; resultado exploratorio. |
| VALIDADO | Además, respaldado por una verificación independiente documentada en su ficha. |

Las etiquetas REAL SIN VALIDAR y VALIDADO nunca se asignan por defecto: exigen una ficha JSON que
corresponda exactamente al archivo (huella SHA-256).

Un cambio de retrodispersión de radar **no confirma** una inundación ni ningún otro fenómeno.

**Datos de radar.** Las capas reales provienen de Sentinel-1 (ESA/Copernicus, banda C).
No deben confundirse con la misión NASA-ISRO NISAR (banda L).

**Uso de inteligencia artificial.** Parte del código y de la documentación de V.I.S.O.R. se
desarrolló con asistencia de IA (Claude, de Anthropic), bajo revisión del equipo.
"""
    )


def barra_superior(fenomeno: Fenomeno, capa: Capa | None) -> None:
    with st.container(key="barra_superior", horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(
            '<div class="mc-marca"><span class="mc-marca-nombre">V.I.S.O.R.</span>'
            '<span class="mc-marca-sub">Mission Control · Earth Explorer</span></div>',
            unsafe_allow_html=True, width="content",
        )
        st.markdown(
            f'<div class="mc-estado"><span class="mc-chip">{fenomeno.icono} {escape(fenomeno.nombre)}</span>'
            f"{insignia_procedencia(capa)}</div>",
            unsafe_allow_html=True, width="content",
        )
        st.space("stretch")
        st.button("Explorador", key="btn_explorador", icon=":material/layers:", on_click=alternar_explorador,
                  type="primary" if st.session_state["ui_explorador"] else "secondary")
        st.button("Información", key="btn_info", icon=":material/info:", on_click=alternar_info,
                  type="primary" if st.session_state["ui_info"] else "secondary")
        with st.popover("Ir a…", icon=":material/my_location:", key="popover_ir"):
            st.number_input("Latitud", -85.0, 85.0, float(MAPA_CENTRO[0]), 0.05, format="%.4f", key="ir_lat")
            st.number_input("Longitud", -180.0, 180.0, float(MAPA_CENTRO[1]), 0.05, format="%.4f", key="ir_lon")
            st.slider("Zoom", 3, 18, 11, key="ir_zoom")
            with st.container(horizontal=True):
                st.button("Ir", key="btn_ir", type="primary", on_click=_ir_a_coordenadas)
                st.button("Área inicial", key="btn_inicio", icon=":material/home:", on_click=volver_al_inicio)
        st.button("Herramientas SAR", key="btn_sar", icon=":material/satellite_alt:", on_click=abrir_sar,
                  type="primary" if st.session_state["ui_sar"] == "abierto" else "secondary")
        if st.button("Ayuda", key="btn_ayuda", icon=":material/help:"):
            mostrar_ayuda()


def panel_explorador() -> Controles:
    panel = st.container(key="panel_explorador")
    with panel:
        with st.container(horizontal=True, vertical_alignment="center", key="cabecera_explorador"):
            st.markdown('<div class="mc-titulo-panel">Explorador</div>', unsafe_allow_html=True)
            st.button("Contraer", key="cerrar_explorador", icon=":material/chevron_left:", type="tertiary",
                      on_click=alternar_explorador)
    return barra_lateral.render(panel, titulo=False)


def panel_informacion(fenomeno: Fenomeno, capa: Capa | None, error: str | None, controles: Controles) -> None:
    panel = st.container(key="panel_info")
    with panel:
        with st.container(horizontal=True, vertical_alignment="center", key="cabecera_info"):
            st.markdown('<div class="mc-titulo-panel">Información</div>', unsafe_allow_html=True)
            st.button("Cerrar", key="cerrar_info", icon=":material/close:", type="tertiary",
                      on_click=alternar_info)
        panel_info.render(fenomeno, capa, error)
    barra_lateral.render_leyenda(fenomeno, capa, controles, panel)


def _paso_pendiente(titulo: str, texto: str, fuente: str) -> None:
    st.markdown(
        f'<div class="mc-paso"><div class="mc-paso-titulo">{escape(titulo)}</div>'
        f'<p>{escape(texto)}</p>'
        f'<div class="mc-paso-fuente">{escape(fuente)}</div>'
        '<span class="mc-insignia mc-insignia-tenue">AÚN NO CONECTADO</span></div>',
        unsafe_allow_html=True,
    )


def herramientas_sar() -> None:
    with st.container(key="panel_sar"):
        with st.container(horizontal=True, vertical_alignment="center", key="cabecera_sar"):
            st.markdown('<div class="mc-titulo-panel">Herramientas SAR</div>', unsafe_allow_html=True)
            st.button("Minimizar", key="minimizar_sar", icon=":material/remove:", type="tertiary",
                      on_click=minimizar_sar)
            st.button("Cerrar", key="cerrar_sar", icon=":material/close:", type="tertiary",
                      on_click=cerrar_sar)
        st.markdown(
            '<div class="mc-aviso">Este panel prepara el flujo de búsqueda y análisis. Todavía no ejecuta '
            "consultas ni procesamientos: ningún resultado de aquí es real.</div>",
            unsafe_allow_html=True,
        )
        area, escenas, analisis, resultados = st.tabs(list(PASOS_SAR), key="sar_paso")
        with area:
            _paso_pendiente(
                "Área y período",
                "Definir la región de interés por coordenadas (ejemplo inicial: Chigorodó) y las fechas "
                "de búsqueda, y verla sobre este mismo mapa.",
                "Validación de coordenadas y fechas del buscador de V.I.S.O.R.",
            )
        with escenas:
            _paso_pendiente(
                "Escenas Sentinel-1",
                "Consultar el catálogo de ASF y elegir el par antes/después que recomienda V.I.S.O.R. "
                "(sin validar), con su cobertura, fechas, órbita, dirección y polarizaciones.",
                "Buscador de catálogo ASF (PR #3). Solo lectura: no descarga imágenes.",
            )
        with analisis:
            _paso_pendiente(
                "Cambio de retrodispersión",
                "Comparar dos productos RTC del par elegido: polarización, recorte, filtro de speckle y "
                "umbrales. Es el único método disponible en el motor. Las escenas GRD del catálogo deben "
                "procesarse antes a RTC; esa conversión no se hace aquí.",
                "Motor de análisis temporal SAR (PR #2).",
            )
        with resultados:
            _paso_pendiente(
                "Resultados en el mapa",
                "Mostrar la máscara y la diferencia en dB como capas de este mapa, con interruptor, "
                "opacidad, leyenda, procedencia y descarga. Se conservan al cerrar el panel.",
                "Resultados de data/analisis/ con su ficha de procedencia.",
            )
    with st.container(key="sar_minimizado"):
        st.button("Herramientas SAR · restaurar", key="restaurar_sar", icon=":material/open_in_full:",
                  on_click=abrir_sar)


def linea_temporal() -> None:
    with st.container(key="linea_temporal"):
        # Solo visual y deshabilitada: no hay control que mover hasta tener dos productos fechados.
        st.markdown(
            '<div class="mc-linea" aria-disabled="true">'
            '<div class="mc-linea-titulo">LÍNEA TEMPORAL · CONCEPTUAL</div>'
            '<div class="mc-linea-pista"><span class="mc-linea-punto">T₁ · sin producto</span>'
            '<span class="mc-linea-barra"></span><span class="mc-linea-punto">T₂ · sin producto</span></div>'
            '<div class="mc-linea-nota">Se habilitará cuando haya dos productos fechados y comparables. '
            "No interpola imágenes ni sugiere cambios.</div></div>",
            unsafe_allow_html=True,
        )
