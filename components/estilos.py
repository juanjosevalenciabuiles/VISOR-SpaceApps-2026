"""Inyecta las hojas de estilo de la app.

- `inyectar_css`: tema clásico (assets/style.css). Lo usan también las páginas
  experimentales de análisis y búsqueda.
- `inyectar_tema`: interfaz Mission Control (style.css + mission_control.css)
  con las variables de color del fenómeno activo.
"""
import streamlit as st

from utils.config import ASSETS_DIR, Fenomeno


def inyectar_css(color_acento: str) -> None:
    css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
    st.markdown(
        f"<style>:root{{--acento:{color_acento};}}\n{css}</style>",
        unsafe_allow_html=True,
    )


def variables_tema(fenomeno: Fenomeno) -> str:
    """Variables CSS del tema: el HEX aprobado y sus componentes RGB exactos."""
    r, g, b = fenomeno.tema_rgb
    return f":root{{--theme-rgb:{r}, {g}, {b};--theme-accent:{fenomeno.tema};--acento:{fenomeno.tema};}}"


def inyectar_tema(fenomeno: Fenomeno) -> None:
    clasico = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
    mision = (ASSETS_DIR / "mission_control.css").read_text(encoding="utf-8")
    st.markdown(
        f"<style>{variables_tema(fenomeno)}\n{clasico}\n{mision}</style>",
        unsafe_allow_html=True,
    )
