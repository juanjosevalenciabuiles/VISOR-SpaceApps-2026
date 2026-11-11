"""Inyecta el CSS de assets/style.css en la app."""
import streamlit as st

from utils.config import ASSETS_DIR


def inyectar_css(color_acento: str) -> None:
    css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
    st.markdown(
        f"<style>:root{{--acento:{color_acento};}}\n{css}</style>",
        unsafe_allow_html=True,
    )
