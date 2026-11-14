"""Panel complementario de eventos ambientales por AOI y fechas (NASA EONET).

Nunca altera 'resultado_activo', dispara 'Analizar' ni utiliza la cola SAR.
Solo consulta la red al pulsar el botón explícito y conserva caché por contexto.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from html import escape

import streamlit as st
from shapely.geometry import box, mapping

from components import flujo
from utils import contexto_ambiental, sesion


def _contexto():
    zona = st.session_state.get("zona")
    if not zona:
        return None
    par = flujo.par_actual()
    if par:
        inicio, fin = sorted((par.antes.inicio.date(), par.despues.inicio.date()))
    else:
        inicio, fin = flujo.periodo_por_defecto()
        inicio = st.session_state.get("sar_inicio", inicio)
        fin = st.session_state.get("sar_fin", fin)
    # Aunque un polígono haya sido dibujado, el contexto ambiental usa su
    # geometría real, no el rectángulo de análisis SAR.
    geom = zona.get("geometria") or mapping(box(*zona["limites"]))
    identidad = json.dumps({"geometria": geom, "inicio": str(inicio), "fin": str(fin)},
                          sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(identidad.encode()).hexdigest(), geom, inicio, fin


@st.cache_data(ttl=900, show_spinner=False, max_entries=32)
def _consulta(clave: str, geometria_texto: str, inicio: date, fin: date):
    desde, hasta = contexto_ambiental.ventana(inicio, fin)
    return contexto_ambiental.consultar_eonet(json.loads(geometria_texto), desde, hasta)


def render():
    with st.expander("Contexto ambiental · eventos reales", expanded=False):
        st.caption("NASA EONET · Información complementaria; no verifica inundaciones, deslizamientos ni cambios forestales.")
        actual = _contexto()
        if actual is None:
            st.info("Confirma una zona de análisis para consultar eventos ambientales.")
            return
        clave, geometria, inicio, fin = actual
        try:
            desde, hasta = contexto_ambiental.ventana(inicio, fin)
        except (TypeError, ValueError):
            st.warning("Selecciona un intervalo de fechas válido.")
            return
        st.caption(f"Período de eventos consultado: {desde:%Y-%m-%d} al {hasta:%Y-%m-%d} (±15 días).")
        if st.button("Consultar contexto", key="contexto_consultar", icon=":material/public:",
                     help="Consulta EONET cuando tú lo solicites. No realiza ningún cálculo SAR."):
            with st.spinner("Consultando el catálogo NASA EONET…"):
                try:
                    respuesta = _consulta(clave, json.dumps(geometria, sort_keys=True), inicio, fin)
                except (ValueError, TypeError, KeyError):
                    respuesta = {"estado": "ERROR_FUENTE", "items": [],
                                 "error": "Parámetros inválidos"}
            st.session_state["contexto_ambiental_activo"] = {"clave": clave, "respuesta": respuesta}
        guardado = st.session_state.get("contexto_ambiental_activo")
        if not guardado or guardado["clave"] != clave:
            st.caption("Sin consulta para esta zona y estas fechas. No se muestra contexto anterior.")
            return
        res = guardado["respuesta"]
        if res.get("estado") == "ERROR_FUENTE":
            st.warning("NASA EONET no respondió o no entregó datos válidos. El análisis SAR sigue disponible.")
            return
        items = res.get("items") or []
        if not items:
            st.info("No se encontraron eventos EONET geolocalizados dentro de la zona y período consultados. "
                    "Esto no significa que no hayan ocurrido fenómenos locales.")
        for item in items[:30]:
            with st.container(border=True):
                st.markdown("**" + escape(item["title"]) + "**")
                st.caption(f"{item.get('phenomenon') or 'Sin categoría'} · "
                           f"{item.get('event_start') or 'Fecha no informada'} · "
                           "Geometría EONET intersecta AOI")
                if item.get("url"):
                    st.link_button("Fuente del evento", item["url"], icon=":material/open_in_new:")
        st.caption("Fuente: NASA EONET v3. No se consultaron GDACS, GDELT ni IDEAM en esta versión. "
                   "No se infieren resultados SAR ni se muestran noticias inventadas.")
