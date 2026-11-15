"""Dock de capas V.I.S.O.R. siempre disponible sobre el mapa principal.

Única fuente de controles para IDEAM/DANE/EONET, Natural Earth, mapa base y
resultados SAR. No se crean datos; se activan u ocultan SOLO capas existentes.
"""
from __future__ import annotations

import streamlit as st

from components import flujo
from utils import mapas_base, sesion
from utils.capas_contexto import CAPAS_CONTEXTO, disponibles
from utils.mapas_base import MAPAS_BASE


def _inicializar() -> None:
    st.session_state.setdefault("ui_capas_abierto", True)
    st.session_state.setdefault("visor_capa_resultado_visible", True)
    st.session_state.setdefault("res_opacidad", 0.85)
    st.session_state.setdefault("referencia", False)
    st.session_state.setdefault("ctx_hidrografia", False)
    st.session_state.setdefault("ctx_vias", False)
    from components import capas_ambientales
    capas_ambientales.inicializar()


def _alternar_dock() -> None:
    st.session_state["ui_capas_abierto"] = not st.session_state["ui_capas_abierto"]


def _cambiar_resultado(resultados: list) -> None:
    """Abre un raster real del historial y evita atribuirlo a una AOI ajena."""
    elegido = st.session_state.get("visor_seleccion_resultado")
    if elegido is None:
        flujo.limpiar_resultado()
        return
    res = next((r for r in resultados if r.id == elegido and r.dibujable), None)
    if res is None or res.capa is None:
        flujo.limpiar_resultado("No se puede abrir ese archivo: falta un GeoTIFF válido.")
        return
    actual = st.session_state.get("resultado_activo") or {}
    if actual.get("id") == elegido:
        return
    flujo.quitar_zona()
    st.session_state["lugar"] = None
    st.session_state["capa_sar"] = False
    flujo.activar(res.id, sesion.HISTORICO)
    st.session_state["visor_capa_resultado_visible"] = True
    from components import interfaz
    interfaz.centrar_en(res.capa.limites)


def _etiqueta_resultado(id_: str | None, por_id: dict) -> str:
    if id_ is None:
        return "Ningún resultado seleccionado"
    r = por_id[id_]
    es_real = r.capa is not None and r.capa.procedencia.es_real
    origen = "REAL" if es_real else "NO VALIDADO"
    fechas = ""
    datos = (r.ficha or {}).get("procedencia")
    if isinstance(datos, dict) and isinstance(datos.get("fechas"), list) and len(datos["fechas"]) >= 2:
        fechas = " · " + " → ".join(str(d)[:10] for d in datos["fechas"][:2])
    return f"{origen} · {r.nombre}{fechas}"


def _resultado(resultados: list, activo) -> None:
    dibujables = [r for r in resultados if r.dibujable and r.capa is not None]
    por_id = {r.id: r for r in dibujables}
    identificadores = [None, *por_id]
    actual = activo.id if activo is not None and activo.id in por_id else None

    # Mantener el selector sincronizado con la publicación automática de V9.
    # Ocurre ANTES de crear el widget, sin cambiar un estado ya dibujado.
    if st.session_state.get("visor_seleccion_resultado") != actual:
        st.session_state["visor_seleccion_resultado"] = actual

    st.selectbox(
        "Resultado satelital en el mapa",
        options=identificadores,
        key="visor_seleccion_resultado",
        format_func=lambda id_: _etiqueta_resultado(id_, por_id),
        on_change=_cambiar_resultado,
        args=(dibujables,),
        help="Los archivos son los del historial. Abrir uno no recalcula ni descarga nada. "
             "NO VALIDADO no significa inundación confirmada.",
    )
    st.toggle(
        "Mostrar resultado SAR",
        key="visor_capa_resultado_visible",
        disabled=actual is None,
        help="Oculta o vuelve a mostrar la capa sobre el mapa sin borrar el resultado.",
    )
    if actual is not None:
        st.slider("Opacidad SAR", 0.0, 1.0, 0.85, step=0.05, key="res_opacidad")
    else:
        st.caption("No hay GeoTIFF seleccionado. Puedes analizar una zona o abrir uno del historial.")


def render(resultados: list, activo=None) -> None:
    """Este contenedor nunca depende de que Explorador/Información estén abiertos."""
    _inicializar()
    from components import capas_ambientales

    with st.container(key="panel_capas"):
        with st.container(horizontal=True, vertical_alignment="center", key="cabecera_capas"):
            st.markdown('<div class="mc-titulo-panel">CAPAS DEL MAPA</div>', unsafe_allow_html=True)
            st.button(
                "Contraer" if st.session_state["ui_capas_abierto"] else "Expandir",
                key="visor_capas_plegar",
                icon=":material/layers:",
                type="tertiary",
                on_click=_alternar_dock,
                help="El selector de capas permanece visible incluso al cerrar otros paneles.",
            )
        with st.container(key="panel_capas_body"):
            st.caption("AMBIENTE · ACTIVAR / OCULTAR")
            st.toggle(
                "IDEAM · Alertas hidrológicas",
                key=capas_ambientales.CLAVES["ideam"],
                help="Alertas actuales o consultadas; no equivalen a inundaciones detectadas.",
            )
            st.toggle(
                "DANE · Municipios",
                key=capas_ambientales.CLAVES["municipios"],
                help="Límites y proporción del área estudiada, no clasificación de riesgo.",
            )
            st.toggle(
                "NASA EONET · Eventos",
                key=capas_ambientales.CLAVES["eonet"],
                help="Eventos catalogados. No representan automáticamente áreas afectadas.",
            )

            with st.expander("Cartografía y fondo", expanded=False):
                opciones = mapas_base.ofrecidos()
                if st.session_state.get("mapa_base") not in opciones:
                    st.session_state["mapa_base"] = mapas_base.predeterminado()
                st.selectbox(
                    "Mapa base",
                    options=opciones,
                    format_func=lambda k: MAPAS_BASE[k].nombre,
                    key="mapa_base",
                    help="Cambia únicamente el fondo; conserva resultados, zona y encuadre.",
                )
                faltan = mapas_base.no_ofrecidos()
                if faltan:
                    nombres = "; ".join(
                        f"{MAPAS_BASE[k].nombre} ({motivo})" for k, motivo in faltan.items()
                    )
                    st.caption("No disponibles aquí: " + nombres
                               + ". El mapa base nunca cambia silenciosamente a uno sin acceso.")
                hay = disponibles()
                for clave in ("hidrografia", "vias"):
                    capa = CAPAS_CONTEXTO[clave]
                    st.toggle(
                        capa.nombre,
                        key=f"ctx_{clave}",
                        disabled=not hay[clave],
                        help=capa.alcance if hay[clave] else "Archivo cartográfico no disponible.",
                    )
                st.toggle(
                    "Área de referencia",
                    key="referencia",
                    help="Rectángulo ilustrativo de Antioquia, no es una observación SAR.",
                )

            with st.expander("Resultados SAR y opacidad", expanded=activo is not None):
                _resultado(resultados, activo)
            st.caption("El color SAR muestra cambio de señal; no confirma inundaciones.")
