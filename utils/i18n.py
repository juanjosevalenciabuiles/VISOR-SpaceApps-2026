"""Idioma de la interfaz V.I.S.O.R. sin alterar el estado geoespacial.

El idioma se almacena por sesión; cambiarlo solo vuelve a dibujar textos.
Los nombres de misiones, archivos, unidades y etiquetas científicas no se traducen.
"""
from __future__ import annotations

import streamlit as st

IDIOMAS = ("es", "en")


def idioma() -> str:
    """Idioma activo (español por defecto)."""
    valor = st.session_state.get("visor_idioma", "es")
    return valor if valor in IDIOMAS else "es"


def seleccionar(codigo: str) -> None:
    """Callback seguro: jamás modifica zonas, resultados o trabajos SAR."""
    if codigo not in IDIOMAS:
        raise ValueError("Idioma desconocido / Unknown language")
    st.session_state["visor_idioma"] = codigo


def tr(es: str, en: str) -> str:
    """Traducción directa de mensajes visibles; siempre existe alternativa ES."""
    return en if idioma() == "en" else es
