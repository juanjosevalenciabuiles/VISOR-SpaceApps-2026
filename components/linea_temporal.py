"""Línea temporal interactiva: intervalo común, observaciones reales y capas por sensor.

Solo selecciona resultados verificados en disco: NO interpola mapas entre fechas,
NO reproduce una película sintética y NO lanza descargas al tocar el calendario.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html import escape

import streamlit as st

from components import flujo
from utils import cronologia_sar

MODOS = ("Resultado actual", "NISAR", "Sentinel-1", "Ambos")


def inicializar() -> None:
    hoy = datetime.now(timezone.utc).date()
    st.session_state.setdefault("v9_inicio_periodo", hoy - timedelta(days=23))
    st.session_state.setdefault("v9_fin_periodo", hoy - timedelta(days=16))
    st.session_state.setdefault("visor_modo_comparacion", "Resultado actual")
    st.session_state.setdefault("visor_seleccion_sensor", {})


def _periodo_cambiado() -> None:
    """Cambiar fecha no ejecuta análisis: invalida la asociación con un trabajo viejo."""
    st.session_state["v9_firma"] = None
    st.session_state["visor_modo_comparacion"] = "Resultado actual"
    st.session_state["v9_publicado"] = None


def _seleccionar_producto(productos) -> None:
    elegido = str(st.session_state.get("visor_producto_temporal") or "")
    producto = next((p for p in productos if p.identificador == elegido), None)
    if producto is not None:
        seleccion = dict(st.session_state.get("visor_seleccion_sensor") or {})
        seleccion[producto.sensor] = producto.identificador
        st.session_state["visor_seleccion_sensor"] = seleccion
        st.session_state["visor_modo_comparacion"] = producto.sensor


def render(resultados: list | tuple) -> None:
    inicializar()
    zona = flujo.zona_confirmada()
    hoy = datetime.now(timezone.utc).date()
    with st.container(key="linea_temporal"):
        st.markdown('<div class="mc-linea-titulo">LÍNEA DE TIEMPO · OBSERVACIONES REALES</div>',
                    unsafe_allow_html=True)
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
            st.date_input("Desde", key="v9_inicio_periodo", format="YYYY-MM-DD",
                          min_value=date(2014, 4, 3), max_value=hoy, on_change=_periodo_cambiado)
            st.date_input("Hasta", key="v9_fin_periodo", format="YYYY-MM-DD",
                          min_value=date(2014, 4, 3), max_value=hoy, on_change=_periodo_cambiado)
        inicio, fin = st.session_state["v9_inicio_periodo"], st.session_state["v9_fin_periodo"]
        # Un resultado abierto desde Historial conserva sus T₁/T₂ verdaderos
        # aunque aún no exista un AOI nuevo confirmado.
        abierto = st.session_state.get("resultado_activo") or {}
        actual = next((r for r in resultados if r.id == abierto.get("id")), None)
        par_actual = cronologia_sar.producto_de_resultado(actual) if actual is not None else None
        if par_actual is not None:
            st.markdown(
                '<div class="mc-linea-pista"><span class="mc-linea-punto">T₁ · '
                + escape(par_actual.antes.isoformat()) + '</span><span class="mc-linea-barra"></span>'
                '<span class="mc-linea-punto">T₂ · ' + escape(par_actual.despues.isoformat())
                + '</span></div>', unsafe_allow_html=True,
            )
        if inicio > fin or fin >= hoy:
            st.caption("El periodo debe terminar antes de hoy para comparar con datos posteriores.")
            return
        if zona is None:
            st.caption("Selecciona tu zona con dos clics en el mapa; luego pulsa «Analizar cambios».")
            return
        productos = cronologia_sar.productos_disponibles(resultados, zona, inicio, fin)
        if not productos:
            st.caption("Sin mapas temporales verificables todavía. Al procesar escenas reales, "
                       "sus fechas aparecerán aquí; cambiar el periodo no inicia descargas.")
            return
        puntos = cronologia_sar.puntos_observados(productos)
        riel = "".join(
            '<span class="visor-marca-tiempo" title="Adquisición real; no fecha interpolada">'
            + escape(sensor) + " · " + escape(dia.isoformat()) + "</span>"
            for dia, sensor in puntos[:12]
        )
        st.markdown('<div class="visor-riel-tiempo">' + riel + "</div>", unsafe_allow_html=True)
        opciones = [p.identificador for p in productos]
        previo = st.session_state.get("visor_producto_temporal")
        if previo not in opciones:
            st.session_state["visor_producto_temporal"] = opciones[0]
        por_id = {p.identificador: p for p in productos}
        st.selectbox(
            "Explorar una comparación disponible", opciones,
            format_func=lambda k: (
                f"{por_id[k].sensor}: {por_id[k].antes.isoformat()} → {por_id[k].despues.isoformat()}"
                + (" · experimental" if por_id[k].estado != "validado" else "")
            ),
            key="visor_producto_temporal",
            on_change=_seleccionar_producto, args=(productos,),
            help="Cada opción es un producto ya calculado con dos fechas reales, no una estimación de otros días.",
        )
        sensores = {p.sensor for p in productos}
        disponibles = ["Resultado actual", *(["NISAR"] if "NISAR" in sensores else []),
                       *(["Sentinel-1"] if "Sentinel-1" in sensores else []),
                       *(["Ambos"] if len(sensores) > 1 else [])]
        if st.session_state.get("visor_modo_comparacion") not in disponibles:
            st.session_state["visor_modo_comparacion"] = "Resultado actual"
        st.radio("Mostrar capas", options=disponibles, horizontal=True,
                 key="visor_modo_comparacion", help=(
                     "Solo resultados reales compatibles con el área. "
                     "NISAR y Sentinel pueden tener fechas y métodos distintos."
                 ))
        if "Ambos" in disponibles:
            st.caption("Comparación de sensores: dos capas independientes; fechas distintas, "
                       "ninguna equivalencia de clases ni inferencia de inundación conjunta.")
        else:
            st.caption("No hay dos sensores comparables disponibles para esta área y periodo.")


def capas_para_mapa(resultados: list | tuple) -> dict[str, float] | None:
    """None conserva la vista anterior; dict es una selección explícita de la línea de tiempo."""
    modo = st.session_state.get("visor_modo_comparacion", "Resultado actual")
    if modo == "Resultado actual":
        return None
    zona = flujo.zona_confirmada()
    inicio, fin = st.session_state.get("v9_inicio_periodo"), st.session_state.get("v9_fin_periodo")
    if zona is None or not isinstance(inicio, date) or not isinstance(fin, date) or inicio > fin:
        return {}
    return cronologia_sar.capas_visibles(
        list(resultados), zona, inicio, fin, modo,
        st.session_state.get("visor_seleccion_sensor"),
    )
