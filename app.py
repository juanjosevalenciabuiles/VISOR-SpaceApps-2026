"""V.I.S.O.R. — Visualización Inteligente de Superficies y Observación por Radar.

Punto de entrada · interfaz Mission Control Earth Explorer: un único mapa a
pantalla completa con superficies flotantes. Solo orquesta: cada pieza de
interfaz vive en components/ y la lógica de datos en utils/.
"""
import streamlit as st

from components import estilos, interfaz, mapa
from utils.config import FENOMENOS
from utils.geotiff import ErrorCapa, cargar_capa

st.set_page_config(
    page_title="V.I.S.O.R.",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

interfaz.inicializar_estado()

# 1. Controles del explorador (se dibujan siempre; si el panel está cerrado, solo se ocultan).
controles = interfaz.panel_explorador()
fenomeno = FENOMENOS[controles.clave]
estilos.inyectar_tema(fenomeno)
interfaz.aplicar_css_estado()

capa, error = None, None
try:
    capa = cargar_capa(fenomeno.ruta, categorico=fenomeno.categorico)
except ErrorCapa as e:
    error = str(e)

# 2. El mapa único, detrás de todo.
with st.container(key="lienzo_mapa"):
    mapa.render(fenomeno, capa, controles, st.session_state["vista"])

# 3. Superficies flotantes.
interfaz.barra_superior(fenomeno, capa)
interfaz.panel_informacion(fenomeno, capa, error, controles)
interfaz.herramientas_sar()
interfaz.linea_temporal()
