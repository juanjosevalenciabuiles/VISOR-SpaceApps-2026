"""Barra lateral: selector de fenómeno, controles de capa y leyenda."""
from dataclasses import dataclass

import streamlit as st

from components import leyenda
from utils.config import FENOMENOS, carto_api_key


@dataclass
class Controles:
    clave: str
    mostrar_capa: bool
    opacidad: float
    mostrar_huella: bool
    mostrar_referencia: bool


def render() -> Controles:
    with st.sidebar:
        st.markdown('<div class="visor-lateral-titulo">🛰️ V.I.S.O.R.</div>', unsafe_allow_html=True)

        st.caption("FENÓMENO")
        clave = st.radio(
            "Fenómeno",
            options=list(FENOMENOS),
            format_func=lambda k: f"{FENOMENOS[k].icono}  {FENOMENOS[k].nombre}",
            label_visibility="collapsed",
        )

        st.caption("CAPAS")
        mostrar_capa = st.toggle("Capa SAR", value=True)
        opacidad = st.slider("Opacidad", 0.0, 1.0, 0.85, 0.05, disabled=not mostrar_capa)
        mostrar_huella = st.toggle("Cobertura de la capa", value=True)
        mostrar_referencia = st.toggle("Área de referencia", value=False)

        st.caption("LEYENDA")
        leyenda.render(FENOMENOS[clave])

        if not carto_api_key():
            st.caption("MAPA BASE")
            st.markdown(
                '<div class="visor-leyenda-nota">Falta la variable <code>CARTO_API_KEY</code>: '
                "el mapa base puede verse con marca de agua. Ver README.</div>",
                unsafe_allow_html=True,
            )

    return Controles(clave, mostrar_capa, opacidad, mostrar_huella, mostrar_referencia)
