"""Leyenda de color del fenómeno activo."""
import streamlit as st

from utils.config import Fenomeno


def render(fenomeno: Fenomeno) -> None:
    gradiente = ", ".join(fenomeno.colores)
    st.markdown(
        f"""
        <div class="visor-leyenda">
          <div class="visor-leyenda-barra" style="background:linear-gradient(90deg, transparent, {gradiente});"></div>
          <div class="visor-leyenda-ejes"><span>{fenomeno.leyenda_min}</span><span>{fenomeno.leyenda_max}</span></div>
          <div class="visor-leyenda-nota">Sin color = sin dato o sin indicio.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
