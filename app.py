"""V.I.S.O.R. — Visualización Inteligente de Superficies y Observación por Radar.

Punto de entrada. Solo orquesta: cada pieza de interfaz vive en components/
y la lógica de datos en utils/.
"""
import streamlit as st

from components import barra_lateral, encabezado, estilos, mapa, panel_info
from utils.config import FENOMENOS
from utils.geotiff import ErrorCapa, cargar_capa

st.set_page_config(
    page_title="V.I.S.O.R.",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

controles = barra_lateral.render()
fenomeno = FENOMENOS[controles.clave]
estilos.inyectar_css(fenomeno.color)

capa, error = None, None
try:
    capa = cargar_capa(fenomeno.ruta, categorico=fenomeno.categorico)
except ErrorCapa as e:
    error = str(e)

barra_lateral.render_leyenda(fenomeno, capa, controles)
encabezado.render(fenomeno, capa)

col_mapa, col_info = st.columns([2.7, 1], gap="medium")
with col_mapa:
    mapa.render(fenomeno, capa, controles)
with col_info:
    panel_info.render(fenomeno, capa, error)
