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

import math
from html import escape

import streamlit as st

from components import barra_lateral, panel_info
from components import herramientas_sar as herramientas
from components import resultados as ui_resultados
from components.barra_lateral import Controles
from components.panel_info import insignia
from utils.config import CHIGORODO_CENTRO, CHIGORODO_ZOOM, MAPA_CENTRO, MAPA_ZOOM, Fenomeno
from utils import procedencia
from utils.geotiff import Capa

ESTADO_INICIAL = {
    "ui_explorador": True,              # panel izquierdo de exploración
    "ui_info": True,                    # panel científico de la derecha
    "ui_sar": "cerrado",                # "cerrado" | "abierto" | "minimizado"
    "ui_explorador_previo": True,       # cómo estaba el explorador antes de abrir SAR
    "vista": None,                      # {"centro": [lat, lon], "zoom": z, "n": k}
    "ir_error": None,                   # mensaje si las coordenadas de «Ir a…» no son válidas
}
# Valores iniciales de «Ir a…»: centro del AOI de Chigorodó.
IR_A_INICIAL = {"ir_lat": f"{CHIGORODO_CENTRO[0]:.4f}", "ir_lon": f"{CHIGORODO_CENTRO[1]:.4f}",
                "ir_zoom": CHIGORODO_ZOOM}
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


def leer_coordenada(texto, minimo: float, maximo: float, nombre: str) -> float:
    """Convierte lo escrito en un número dentro del rango. Acepta coma decimal (7,675)."""
    limpio = str(texto).strip().replace(" ", "")
    if limpio.count(",") == 1 and "." not in limpio:
        limpio = limpio.replace(",", ".")
    try:
        valor = float(limpio)
    except ValueError:
        raise ValueError(f"La {nombre} «{texto}» no es un número (usa punto decimal, por ejemplo 7.675).") from None
    if not minimo <= valor <= maximo:
        raise ValueError(f"La {nombre} debe estar entre {minimo:g} y {maximo:g}; se escribió {valor:g}.")
    return valor


def _ir_a_coordenadas() -> None:
    try:
        lat = leer_coordenada(st.session_state["ir_lat"], -85.0, 85.0, "latitud")
        lon = leer_coordenada(st.session_state["ir_lon"], -180.0, 180.0, "longitud")
    except ValueError as e:
        st.session_state["ir_error"] = str(e)
        return
    st.session_state["ir_error"] = None
    ir_a(lat, lon, st.session_state["ir_zoom"])


def centrar_en(limites: tuple[float, float, float, float]) -> None:
    """Centra el mapa en una extensión (oeste, sur, este, norte) con un zoom que la abarca."""
    oeste, sur, este, norte = limites
    lado = max(este - oeste, norte - sur, 1e-6)
    zoom = max(3, min(14, int(math.log2(360.0 / lado)) + 1))
    ir_a((sur + norte) / 2, (oeste + este) / 2, zoom)


def ir_a_chigorodo() -> None:
    """Lleva el mapa al AOI de Chigorodó. No reescribe los campos: asignar el
    valor de un widget desde código hace que Streamlit muestre un aviso."""
    st.session_state["ir_error"] = None
    ir_a(CHIGORODO_CENTRO[0], CHIGORODO_CENTRO[1], CHIGORODO_ZOOM)


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
    css = (",".join(ocultos) + "{display:none !important}") if ocultos else ""
    if st.session_state["ui_explorador"]:
        # Móvil: ambas son hojas inferiores; con el explorador abierto, la información sube.
        css += ("@media (max-width:720px){.st-key-panel_info{bottom:calc(46vh + 38px) !important;"
                "max-height:24vh !important}}")
    return css


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
- **Ir a…**: lleva el mapa a unas coordenadas (por defecto, el AOI de Chigorodó), a Chigorodó o
  de vuelta a la vista general de Antioquia.
- **Resultados SAR** (explorador): capas opcionales de `data/analisis/` que se superponen a la del
  fenómeno, cada una con su interruptor, opacidad, leyenda y ficha científica.
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


def estado_html(fenomeno: Fenomeno, capa: Capa | None, activos: list | tuple = (),
                capa_visible: bool = True) -> str:
    """Dos grupos separados y rotulados: la capa del fenómeno y los resultados SAR activos.
    Así una capa DEMO del fenómeno nunca se confunde con un resultado real, ni lo oculta."""
    fen = (f'<span class="mc-grupo" title="Capa del fenómeno"><span class="mc-grupo-rot">Fenómeno</span>'
           f'<span class="mc-chip">{fenomeno.icono} {escape(fenomeno.nombre)}</span>'
           f"{insignia_procedencia(capa)}"
           + ('' if capa_visible else '<span class="mc-grupo-nota">capa oculta</span>') + "</span>")
    if not activos:
        return f'<div class="mc-estado">{fen}</div>'
    visibles = list(activos)[:2]
    res = "".join(f'<span class="mc-chip mc-chip-res">{escape(r.nombre)}</span>{insignia(r.capa.procedencia)}'
                  for r in visibles)
    if len(activos) > 2:
        res += f'<span class="mc-grupo-nota">+{len(activos) - 2}</span>'
    return (f'<div class="mc-estado">{fen}<span class="mc-separador"></span>'
            f'<span class="mc-grupo" title="Resultados SAR activos"><span class="mc-grupo-rot">Resultado SAR</span>'
            f"{res}</span></div>")


def barra_superior(fenomeno: Fenomeno, capa: Capa | None, activos: list | tuple = (),
                   capa_visible: bool = True) -> None:
    with st.container(key="barra_superior", horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(
            '<div class="mc-marca"><span class="mc-marca-nombre">V.I.S.O.R.</span>'
            '<span class="mc-marca-sub">Mission Control · Earth Explorer</span></div>',
            unsafe_allow_html=True, width="content",
        )
        st.markdown(estado_html(fenomeno, capa, activos, capa_visible), unsafe_allow_html=True, width="content")
        st.space("stretch")
        st.button("Explorador", key="btn_explorador", help="Explorador: fenómeno, mapa base, capas y resultados SAR", icon=":material/layers:", on_click=alternar_explorador,
                  type="primary" if st.session_state["ui_explorador"] else "secondary")
        st.button("Información", key="btn_info", help="Información científica de las capas activas", icon=":material/info:", on_click=alternar_info,
                  type="primary" if st.session_state["ui_info"] else "secondary")
        with st.popover("Ir a…", icon=":material/my_location:", key="popover_ir"):
            # Campos de texto, no numéricos: la rueda del ratón o del panel táctil no los altera.
            # El valor inicial va como argumento (no en session_state) para que el navegador lo
            # muestre aunque el menú no se haya abierto antes.
            st.text_input("Latitud (−85 a 85)", IR_A_INICIAL["ir_lat"], key="ir_lat")
            st.text_input("Longitud (−180 a 180)", IR_A_INICIAL["ir_lon"], key="ir_lon")
            st.slider("Zoom", 3, 18, IR_A_INICIAL["ir_zoom"], key="ir_zoom")
            if st.session_state.get("ir_error"):
                st.markdown(f'<div class="mc-aviso">{escape(st.session_state["ir_error"])}</div>',
                            unsafe_allow_html=True)
            with st.container(horizontal=True):
                st.button("Ir", key="btn_ir", type="primary", on_click=_ir_a_coordenadas)
                st.button("Chigorodó", key="btn_chigorodo", icon=":material/location_on:", on_click=ir_a_chigorodo,
                          help="Centro del AOI del análisis VV/VH (−76,80 a −76,55; 7,55 a 7,80), zoom 11.")
                st.button("Área inicial", key="btn_inicio", icon=":material/home:", on_click=volver_al_inicio,
                          help="Vista general de Antioquia.")
        st.button("Herramientas SAR", key="btn_sar", help="Herramientas SAR: área, escenas, análisis y resultados", icon=":material/satellite_alt:", on_click=abrir_sar,
                  type="primary" if st.session_state["ui_sar"] == "abierto" else "secondary")
        if st.button("Ayuda", key="btn_ayuda", help="Ayuda y estados de procedencia", icon=":material/help:"):
            mostrar_ayuda()


def panel_explorador(resultados: list | None = None) -> Controles:
    panel = st.container(key="panel_explorador")
    with panel:
        with st.container(horizontal=True, vertical_alignment="center", key="cabecera_explorador"):
            st.markdown('<div class="mc-titulo-panel">Explorador</div>', unsafe_allow_html=True)
            st.button("Contraer", key="cerrar_explorador", icon=":material/chevron_left:", type="tertiary",
                      on_click=alternar_explorador)
    return barra_lateral.render(panel, titulo=False, resultados=resultados or [], centrar=centrar_en)


def panel_informacion(fenomeno: Fenomeno, capa: Capa | None, error: str | None, controles: Controles,
                      resultados: list | None = None) -> None:
    activos = [r for r in (resultados or []) if r.dibujable and r.id in controles.resultados]
    panel = st.container(key="panel_info")
    with panel:
        with st.container(horizontal=True, vertical_alignment="center", key="cabecera_info"):
            st.markdown('<div class="mc-titulo-panel">Información</div>', unsafe_allow_html=True)
            st.button("Cerrar", key="cerrar_info", icon=":material/close:", type="tertiary",
                      on_click=alternar_info)
        # El resultado activo va primero: es lo último que encendió la persona usuaria.
        for res in activos:
            st.caption("RESULTADO SAR ACTIVO")
            st.markdown(ui_resultados.ficha_html(res), unsafe_allow_html=True)
            ui_resultados.boton_qgis(res)
        if activos:
            st.caption("CAPA DEL FENÓMENO")
        panel_info.render(fenomeno, capa, error)
    barra_lateral.render_leyenda(fenomeno, capa, controles, panel)
    if activos:
        with panel:
            st.markdown("".join(ui_resultados.leyenda_html(r) for r in activos), unsafe_allow_html=True)


def herramientas_sar() -> None:
    with st.container(key="panel_sar"):
        with st.container(horizontal=True, vertical_alignment="center", key="cabecera_sar"):
            st.markdown('<div class="mc-titulo-panel">Herramientas SAR</div>', unsafe_allow_html=True)
            st.button("Minimizar", key="minimizar_sar", icon=":material/remove:", type="tertiary",
                      on_click=minimizar_sar)
            st.button("Cerrar", key="cerrar_sar", icon=":material/close:", type="tertiary",
                      on_click=cerrar_sar)
        st.markdown(
            '<div class="mc-aviso">Búsqueda de solo lectura en ASF y análisis de productos RTC ya presentes en '
            "<code>data/sar/</code>. No descarga ni procesa en HyP3. Los resultados son indicios de cambio de "
            "radar, no inundaciones confirmadas.</div>",
            unsafe_allow_html=True,
        )
        herramientas.render(centrar_en, alternar_explorador, PASOS_SAR)
    with st.container(key="sar_minimizado"):
        st.button("Herramientas SAR · restaurar", key="restaurar_sar", icon=":material/open_in_full:",
                  on_click=abrir_sar)


def linea_temporal(fechas: list[str] | None = None) -> None:
    """Línea temporal de solo lectura. Con un resultado activo cuya ficha válida
    declara dos fechas, las muestra; nunca interpola ni sugiere estados intermedios."""
    if fechas:
        titulo = "LÍNEA TEMPORAL · FECHAS DEL RESULTADO ACTIVO"
        t1, t2 = f"T₁ · {escape(fechas[0])}", f"T₂ · {escape(fechas[1])}"
        nota = "Comparación de dos fechas. No hay observaciones intermedias en este producto."
        clase = " mc-linea-fechada"
    else:
        titulo = "LÍNEA TEMPORAL · CONCEPTUAL"
        t1, t2 = "T₁ · sin producto", "T₂ · sin producto"
        nota = ("Se completa al activar un resultado con ficha de procedencia válida. "
                "No interpola imágenes ni sugiere cambios.")
        clase = ""
    with st.container(key="linea_temporal"):
        st.markdown(
            f'<div class="mc-linea{clase}" aria-disabled="true">'
            f'<div class="mc-linea-titulo">{titulo}</div>'
            f'<div class="mc-linea-pista"><span class="mc-linea-punto">{t1}</span>'
            f'<span class="mc-linea-barra"></span><span class="mc-linea-punto">{t2}</span></div>'
            f'<div class="mc-linea-nota">{nota}</div></div>',
            unsafe_allow_html=True,
        )
