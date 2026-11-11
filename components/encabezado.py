"""Encabezado con la identidad del proyecto."""
import streamlit as st

from utils.config import Fenomeno
from utils.geotiff import Capa


def render(fenomeno: Fenomeno, capa: Capa | None) -> None:
    insignia = ""
    if capa is not None and capa.es_demo:
        insignia = '<span class="visor-demo">DATOS SINTÉTICOS · DEMOSTRACIÓN</span>'
    st.markdown(
        f"""
        <div class="visor-header">
          <div>
            <div class="visor-titulo">V.I.S.O.R.</div>
            <div class="visor-subtitulo">Visualización Inteligente de Superficies y Observación por Radar</div>
          </div>
          <div class="visor-header-der">
            {insignia}
            <span class="visor-chip">{fenomeno.icono} {fenomeno.nombre}</span>
            <span class="visor-chip visor-chip-tenue">Antioquia, Colombia</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
