"""Página del buscador de escenas Sentinel-1.

Consulta de solo lectura al catálogo de ASF mediante utils/buscador_sar.py.
No descarga imágenes, no envía trabajos a HyP3 y no usa credenciales.
"""
import sys
from datetime import date, timedelta
from html import escape
from pathlib import Path

import folium
import streamlit as st
from shapely.geometry import mapping
from streamlit_folium import st_folium

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from components import estilos, mapa  # noqa: E402
from utils import buscador_sar as buscador  # noqa: E402
from utils.mapas_base import MAPA_BASE_PREDETERMINADO, obtener  # noqa: E402

ACENTO = "#00F0FF"
# Recuadro de partida: Chigorodó, Antioquia (aproximado).
EJEMPLO = {"oeste": -76.85, "sur": 7.40, "este": -76.40, "norte": 7.95}

st.set_page_config(page_title="V.I.S.O.R. · Buscador SAR", page_icon="🛰️", layout="wide")
estilos.inyectar_css(ACENTO)

st.markdown(
    """
    <div class="visor-header">
      <div>
        <div class="visor-titulo">V.I.S.O.R.</div>
        <div class="visor-subtitulo">Buscador de escenas Sentinel-1 · catálogo de Alaska Satellite Facility</div>
      </div>
      <div class="visor-header-der">
        <span class="visor-chip">Sentinel-1 GRD · IW</span>
        <span class="visor-chip visor-chip-tenue">Solo consulta</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="visor-aviso visor-aviso-general">Este buscador solo consulta el catálogo: no descarga '
    "imágenes ni lanza procesamientos. Un par <b>recomendado</b> es el mejor candidato por órbita, "
    "polarización, cobertura y fechas; <b>no es un par validado científicamente</b>.</div>",
    unsafe_allow_html=True,
)

col_controles, col_resultado = st.columns([1, 2.4], gap="medium")

# ---------------------------------------------------------------------------
# Región, período y búsqueda
# ---------------------------------------------------------------------------
with col_controles:
    st.subheader("1 · Región")
    modo = st.radio("Región", ["Recuadro", "Punto y radio"], horizontal=True, label_visibility="collapsed", key="bus_modo")
    if modo == "Recuadro":
        c1, c2 = st.columns(2)
        oeste = c1.number_input("Oeste (lon)", value=EJEMPLO["oeste"], format="%.4f", step=0.05, key="bus_oeste")
        este = c2.number_input("Este (lon)", value=EJEMPLO["este"], format="%.4f", step=0.05, key="bus_este")
        sur = c1.number_input("Sur (lat)", value=EJEMPLO["sur"], format="%.4f", step=0.05, key="bus_sur")
        norte = c2.number_input("Norte (lat)", value=EJEMPLO["norte"], format="%.4f", step=0.05, key="bus_norte")
        st.caption("Grados decimales. Oeste y sur son negativos al oeste de Greenwich y al sur del ecuador.")
    else:
        c1, c2 = st.columns(2)
        latitud = c1.number_input("Latitud", value=7.67, format="%.4f", step=0.05, key="bus_lat")
        longitud = c2.number_input("Longitud", value=-76.68, format="%.4f", step=0.05, key="bus_lon")
        radio_km = st.slider("Radio (km)", 1, 100, 20, key="bus_radio")

    st.subheader("2 · Período")
    hoy = date.today()
    c1, c2 = st.columns(2)
    inicio = c1.date_input("Desde", value=hoy - timedelta(days=30), max_value=hoy, key="bus_inicio")
    fin = c2.date_input("Hasta", value=hoy, key="bus_fin")
    con_evento = st.toggle("Tengo una fecha de interés", value=False, key="bus_con_evento",
                           help="Por ejemplo el día de una lluvia fuerte. Se prefieren pares con una imagen antes y otra después.")
    evento = st.date_input("Fecha de interés", value=inicio + (fin - inicio) / 2 if fin >= inicio else inicio,
                           key="bus_evento") if con_evento else None

    st.subheader("3 · Criterio")
    cobertura_min = st.slider("Cobertura mínima de la región por el par (%)", 10, 100, 50, 5, key="bus_cobertura")

    if st.button("Buscar imágenes", type="primary", use_container_width=True):
        st.session_state.pop("bus_resultado", None)
        try:
            if modo == "Recuadro":
                region = buscador.validar_region(oeste, sur, este, norte)
            else:
                region = buscador.region_desde_punto(latitud, longitud, radio_km)
            with st.spinner("Consultando el catálogo de ASF…"):
                st.session_state["bus_resultado"] = buscador.buscar(
                    *region.limites, inicio, fin, fecha_evento=evento, min_cobertura=cobertura_min / 100,
                )
        except buscador.ErrorConexion as e:
            st.error(str(e), icon="📡")
        except buscador.ErrorBusqueda as e:
            st.error(str(e), icon="⚠️")

# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------
with col_resultado:
    r: buscador.ResultadoBusqueda | None = st.session_state.get("bus_resultado")
    if r is None:
        st.markdown(
            '<div class="visor-panel"><div class="visor-panel-titulo">Cómo usarlo</div>'
            '<p class="visor-texto">Indica la región y el período y pulsa <b>Buscar imágenes</b>. '
            "Verás las escenas Sentinel-1 disponibles y los pares antes/después que se pueden comparar. "
            "Los valores iniciales corresponden a Chigorodó, Antioquia.</p></div>",
            unsafe_allow_html=True,
        )
        st.stop()

    o, s, e, n = r.region.limites
    st.caption(f"REGIÓN {o:.3f}, {s:.3f}, {e:.3f}, {n:.3f} · {r.inicio:%Y-%m-%d} a {r.fin:%Y-%m-%d}")
    m1, m2, m3 = st.columns(3)
    m1.metric("Escenas utilizables", len(r.escenas))
    m2.metric("Pares compatibles", len(r.pares))
    m3.metric("Recibidas de ASF", r.recibidos)
    notas = []
    if r.versiones:
        notas.append(f"{r.versiones} repetidas: ASF publica la misma adquisición con otro identificador.")
    if r.duplicados:
        notas.append(f"{r.duplicados} duplicadas exactas.")
    notas += [f"{cantidad} descartadas: {motivo}." for motivo, cantidad in r.descartes.items()]
    if notas:
        st.caption(" ".join(notas))
    if r.truncado:
        st.warning("ASF devolvió el máximo de resultados por consulta: puede haber más escenas. Reduce la región o el período.")

    if not r.escenas:
        st.info("No hay escenas Sentinel-1 GRD (modo IW) para esa región y ese período. Prueba con un período más largo.", icon="🔍")
        st.stop()

    enlace = st.column_config.LinkColumn("ASF", display_text="Ver en ASF")
    porcentaje = st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100)

    st.subheader("Escenas")
    st.dataframe(buscador.filas_escenas(r.escenas), hide_index=True, use_container_width=True,
                 column_config={"ASF": enlace, "Cubre la región": porcentaje})

    st.subheader("Pares antes / después")
    if not r.pares:
        st.info(
            "Ningún par cumple los criterios: hacen falta dos fechas con la misma órbita relativa y dirección, "
            "alguna polarización en común y cobertura suficiente. Amplía el período o baja la cobertura mínima.",
            icon="🔍",
        )
        st.stop()
    st.dataframe(buscador.filas_pares(r.pares), hide_index=True, use_container_width=True,
                 column_config={"ASF": enlace, "Cobertura común": porcentaje})

    def nombre_par(i: int) -> str:
        p = r.pares[i]
        return (f"{p.antes.inicio:%Y-%m-%d} → {p.despues.inicio:%Y-%m-%d} · órbita {p.antes.orbita_relativa} "
                f"{p.antes.direccion_es.lower()} · {p.estado}")

    st.subheader("Par seleccionado")
    par = r.pares[st.selectbox("Par", range(len(r.pares)), format_func=nombre_par, label_visibility="collapsed",
                               key="bus_par")]
    st.markdown(f'<div class="visor-aviso visor-aviso-demo">{escape(buscador.ADVERTENCIA_PAR)}</div>',
                unsafe_allow_html=True)

    col_mapa, col_meta = st.columns([1, 1.25], gap="medium")
    with col_mapa:
        lienzo = folium.Map(location=list(r.region.centro), zoom_start=7, tiles=None, control_scale=True)
        huellas = folium.FeatureGroup(name="Huellas")
        for escena, color in ((par.antes, "#FFD60A"), (par.despues, "#FF9F0A")):
            folium.GeoJson(mapping(escena.huella), style_function=lambda _, c=color: {
                "color": c, "weight": 2, "fillOpacity": 0.06}).add_to(huellas)
        folium.Rectangle([[s, o], [n, e]], color=ACENTO, weight=2, fill=False).add_to(huellas)
        st_folium(lienzo, feature_group_to_add=[mapa.grupo_mapa_base(obtener(MAPA_BASE_PREDETERMINADO)), huellas],
                  height=330, use_container_width=True, returned_objects=[], key="mapa_buscador")
        st.caption("Cian: región · amarillo: huella anterior · naranja: huella posterior")
    with col_meta:
        for titulo, escena in (("Antes", par.antes), ("Después", par.despues)):
            tamano = f"{escena.tamano_bytes / 1e9:.2f} GB" if escena.tamano_bytes else "sin dato"
            st.markdown(
                f'<div class="visor-panel" style="margin-bottom:0.6rem">'
                f'<div class="visor-panel-titulo">{titulo} · {escena.inicio:%Y-%m-%d %H:%M} UTC</div>'
                f'<div class="visor-fila"><span>Satélite</span><strong>{escape(escena.plataforma)}</strong></div>'
                f'<div class="visor-fila"><span>Órbita relativa</span><strong>{escena.orbita_relativa} · '
                f"{escena.direccion_es}</strong></div>"
                f'<div class="visor-fila"><span>Modo y producto</span><strong>{escape(escena.modo)} · '
                f"{escape(escena.nivel)}</strong></div>"
                f'<div class="visor-fila"><span>Polarizaciones</span><strong>{"+".join(escena.polarizaciones)}</strong></div>'
                f'<div class="visor-fila"><span>Cubre la región</span><strong>{escena.cobertura:.0%}</strong></div>'
                f'<div class="visor-fila"><span>Tamaño del producto</span><strong>{tamano}</strong></div>'
                f'<div class="visor-fila"><span>Escena</span><strong>{escape(escena.nombre)}</strong></div>'
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("**Por qué este par**\n" + "\n".join(f"- {t}" for t in par.motivos))
    for aviso in par.avisos:
        st.markdown(f'<div class="visor-aviso">{escape(aviso)}</div>', unsafe_allow_html=True)
    st.link_button("Abrir el par en ASF Vertex", par.enlace_vertex)
    st.caption("Descargar o procesar las escenas requiere una cuenta gratuita de NASA Earthdata y se hace en ASF, no desde aquí.")
    with st.expander("Metadatos del par (para el motor de análisis)"):
        st.json(par.para_motor(), expanded=False)
    with st.expander("Consulta enviada a ASF"):
        st.code(r.url, language=None)
