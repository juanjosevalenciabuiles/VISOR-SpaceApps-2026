"""ECO, el murciélago bio-sensor de V.I.S.O.R.: guía flotante en la esquina inferior derecha.

ECO solo acompaña: dice en una línea en qué punto está la persona y qué puede hacer después.
Nunca inventa cifras ni resultados: cada mensaje sale del estado real de la app (zona confirmada,
consultas de contexto, trabajo SAR, resultado activo). No toca el motor SAR ni el mapa.

Clips (static/eco/, generados con scripts/preparar_eco.sh, sin audio, en bucle):
  saludo  → sin zona          enfoque → zona confirmada / consultando contexto
  escaneo → análisis en curso  listo   → resultado en el mapa
Con error, bloqueo o cancelación ECO no celebra: se muestra quieto (imagen fija) y explica el motivo.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

import streamlit as st

from utils import trabajos

RUTA = "app/static/eco/"      # servido por Streamlit (server.enableStaticServing)
CLIPS = {"saludo": "eco_01_saludo", "enfoque": "eco_02_enfoque", "escaneo": "eco_03_escaneo",
         "listo": "eco_04_listo"}


@dataclass(frozen=True)
class EstadoEco:
    clip: str            # clave de CLIPS
    mensaje: str
    animado: bool = True
    tono: str = "normal"   # normal | alerta


def decidir(zona_lugar: str | None, hay_zona: bool, consultando: bool, trabajo: dict | None,
            hay_resultado: bool, historico: bool, trabajo_nisar: dict | None = None) -> EstadoEco:
    """Estado de ECO a partir del estado real de la app (función pura, probada aparte)."""
    # NISAR prepara insumos: un trabajo APTO no representa inundación detectada.
    estado_nisar = (trabajo_nisar or {}).get("estado")
    if estado_nisar in trabajos.ACTIVOS:
        return EstadoEco("escaneo", "Estoy preparando datos NISAR con NASA Harmony. "
                                    "Todavía no es un análisis de inundación.")
    if estado_nisar in (trabajos.ERROR, trabajos.BLOQUEADO) and not hay_resultado:
        motivo = str((trabajo_nisar or {}).get("error") or "revisa la preparación NISAR")
        return EstadoEco("enfoque", f"No se pudieron preparar los datos NISAR: {motivo[:160]}",
                         animado=False, tono="alerta")
    if estado_nisar == trabajos.APTO and not hay_resultado:
        return EstadoEco("enfoque", "Los datos NISAR están preparados. Todavía no hay un mapa de inundación; "
                                    "verifica la calidad antes de interpretar cambios.")
    estado_trabajo = (trabajo or {}).get("estado")
    if estado_trabajo in trabajos.ACTIVOS:
        return EstadoEco("escaneo", "Estoy escuchando el radar: el análisis está en curso. Puedes seguir "
                                    "explorando el mapa mientras termina.")
    if estado_trabajo in (trabajos.ERROR, trabajos.BLOQUEADO) and not hay_resultado:
        motivo = str((trabajo or {}).get("error") or "revisa el detalle en Herramientas SAR")
        return EstadoEco("enfoque", f"No pude terminar el análisis: {motivo[:160]}", animado=False, tono="alerta")
    if estado_trabajo == trabajos.CANCELADO and not hay_resultado:
        return EstadoEco("enfoque", "Cancelaste el análisis. Puedes reintentarlo desde Herramientas SAR.",
                         animado=False)
    if hay_resultado:
        if historico:
            return EstadoEco("listo", "Abriste un resultado guardado del historial. Su ficha está en el panel "
                                      "derecho.")
        return EstadoEco("listo", "Listo: el resultado está en el mapa. Recuerda que es un cambio en la señal "
                                  "de radar, no una inundación confirmada.")
    if hay_zona:
        donde = f" en {zona_lugar}" if zona_lugar else ""
        if consultando:
            return EstadoEco("enfoque", f"Tengo tu zona{donde}. Estoy revisando alertas y contexto…")
        return EstadoEco("enfoque", f"Tengo tu zona{donde}. Abre Herramientas SAR: prepara imágenes y pulsa «Analizar» solo si hay un par válido.")
    return EstadoEco("saludo", "Hola, soy ECO. Busca un lugar de Colombia o dibuja una zona en el mapa para "
                               "empezar.")


def avatar_html(e: EstadoEco) -> str:
    """Video en bucle (webm + respaldo mp4) con imagen fija para «reducir movimiento» o sin animación."""
    base = RUTA + CLIPS[e.clip]
    fija = f'<img class="eco-fijo" src="{base}.webp" alt="ECO, el murciélago guía de V.I.S.O.R." />'
    if not e.animado:
        return f'<div class="eco-avatar eco-quieto" id="eco-avatar" data-clip="{e.clip}" data-animado="0">{fija}</div>'
    return (f'<div class="eco-avatar" id="eco-avatar" data-clip="{e.clip}" data-animado="1">'
            f'<video class="eco-video" autoplay loop muted playsinline preload="auto" poster="{base}.webp" '
            f'aria-label="ECO, el murciélago guía de V.I.S.O.R." disablepictureinpicture>'
            f'<source src="{base}.webm" type="video/webm"><source src="{base}.mp4" type="video/mp4"></video>'
            f"{fija}</div>")


def burbuja_html(e: EstadoEco) -> str:
    return (f'<div class="eco-burbuja eco-{e.tono}" id="eco-mensaje" role="status" aria-live="polite">'
            f'<span class="eco-nombre">ECO</span>{escape(e.mensaje)}</div>')


def _alternar() -> None:
    st.session_state["ui_eco"] = not st.session_state.get("ui_eco", True)


def render(e: EstadoEco) -> None:
    visible = st.session_state.setdefault("ui_eco", True)
    with st.container(key="eco" if visible else "eco_oculto"):
        if visible:
            st.button("Ocultar a ECO", key="eco_ocultar", icon=":material/close:", type="tertiary",
                      on_click=_alternar, help="Ocultar a ECO (vuelve con el botón de la esquina)")
            st.markdown(burbuja_html(e), unsafe_allow_html=True)
            # Elemento aparte: si solo cambia el mensaje, el video no se reinicia.
            st.markdown(avatar_html(e), unsafe_allow_html=True)
        else:
            st.button("ECO", key="eco_mostrar", icon=":material/support_agent:", on_click=_alternar,
                      help="Mostrar a ECO, el guía")
