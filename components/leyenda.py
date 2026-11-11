"""Leyenda del fenómeno activo: describe la escala de valores, no un nivel de riesgo."""
from html import escape

import streamlit as st

from utils.capas_contexto import CAPAS_CONTEXTO
from utils.config import Fenomeno
from utils.geotiff import Capa, rango_visual

NOTA = "Transparente = sin dato. El color describe la señal medida, no un nivel de riesgo."


def _continua(fenomeno: Fenomeno, capa: Capa | None) -> str:
    # La barra va siempre de valores bajos (izquierda) a altos (derecha).
    colores = fenomeno.colores[::-1] if fenomeno.invertir else fenomeno.colores
    numeros = ""
    if capa is not None:
        vmin, vmax = rango_visual(capa.datos, fenomeno.vmin, fenomeno.vmax, fenomeno.percentiles)
        numeros = (
            f'<div class="visor-leyenda-ejes"><span>{vmin:.3g}</span>'
            f"<span>{escape(fenomeno.unidades)}</span><span>{vmax:.3g}</span></div>"
        )
    return (
        f'<div class="visor-leyenda-barra" style="background:linear-gradient(90deg, {", ".join(colores)});"></div>'
        f"{numeros}"
        f'<div class="visor-leyenda-ejes"><span>{escape(fenomeno.leyenda_min)}</span>'
        f"<span>{escape(fenomeno.leyenda_max)}</span></div>"
    )


def _categorica(fenomeno: Fenomeno) -> str:
    filas = []
    for _valor, etiqueta, color in fenomeno.clases:
        fondo = color or "transparent"
        filas.append(
            f'<div class="visor-leyenda-clase"><i style="background:{fondo}"></i>{escape(etiqueta)}</div>'
        )
    return "".join(filas)


def render(fenomeno: Fenomeno, capa: Capa | None) -> None:
    cuerpo = _categorica(fenomeno) if fenomeno.categorico else _continua(fenomeno, capa)
    st.markdown(
        f'<div class="visor-leyenda">{cuerpo}<div class="visor-leyenda-nota">{NOTA}</div></div>',
        unsafe_allow_html=True,
    )


def render_contexto(claves: list[str]) -> None:
    """Leyenda de las capas de contexto activas (hidrografía, vías)."""
    if not claves:
        return
    filas = []
    for clave in claves:
        capa = CAPAS_CONTEXTO[clave]
        filas.append(
            f'<div class="visor-leyenda-clase"><i class="linea" style="background:{capa.color}"></i>'
            f"{escape(capa.nombre)}</div>"
            f'<div class="visor-leyenda-nota">{escape(capa.alcance)}</div>'
        )
    st.markdown(f'<div class="visor-leyenda visor-leyenda-ctx">{"".join(filas)}</div>', unsafe_allow_html=True)
