"""Panel informativo: qué se está viendo, de dónde sale y cómo NO interpretarlo."""
from html import escape

import streamlit as st

from utils.config import ADVERTENCIA_GENERAL, Fenomeno
from utils.geotiff import Capa


def _fila(etiqueta: str, valor: str) -> str:
    return (
        f'<div class="visor-fila"><span>{escape(etiqueta)}</span>'
        f"<strong>{escape(valor)}</strong></div>"
    )


def render(fenomeno: Fenomeno, capa: Capa | None, error: str | None) -> None:
    partes = [
        f'<div class="visor-panel-titulo">{fenomeno.icono} {escape(fenomeno.nombre)}</div>',
        f'<p class="visor-texto">{escape(fenomeno.descripcion)}</p>',
    ]

    if capa is not None and capa.es_demo:
        partes.append(
            '<div class="visor-aviso visor-aviso-demo"><strong>Datos sintéticos.</strong> '
            "Esta capa fue generada por computador para probar la interfaz. "
            "No proviene de un satélite ni representa hechos reales.</div>"
        )

    if capa is not None:
        m = capa.metadatos
        fuente = "Sintética (generada para pruebas)" if capa.es_demo else m.get("FUENTE", fenomeno.fuente)
        alto, ancho = capa.forma_original
        crs = capa.crs_original + (" → EPSG:4326" if capa.reproyectada else "")
        partes += [
            '<div class="visor-seccion">Producto</div>',
            _fila("Tipo", m.get("PRODUCTO", fenomeno.producto)),
            _fila("Fuente", fuente),
            _fila("Fecha", m.get("FECHA", "No disponible")),
            _fila("Archivo", f"data/{fenomeno.archivo}"),
            _fila("Dimensiones", f"{ancho} × {alto} px"),
            _fila("CRS", crs),
        ]
        for aviso in capa.avisos:
            partes.append(f'<div class="visor-aviso">{escape(aviso)}</div>')

    partes.append('<div class="visor-seccion">Cómo interpretar</div>')
    partes.append(f'<div class="visor-aviso visor-aviso-general">{escape(ADVERTENCIA_GENERAL)}</div>')
    partes.append(
        '<ul class="visor-lista">'
        + "".join(f"<li>{escape(a)}</li>" for a in fenomeno.advertencias)
        + "</ul>"
    )

    st.markdown(f'<div class="visor-panel">{"".join(partes)}</div>', unsafe_allow_html=True)

    if error:
        st.error(error, icon="⚠️")
        st.caption(
            f"Coloca un GeoTIFF llamado `{fenomeno.archivo}` en la carpeta `data/` "
            "o ejecuta `python scripts/generar_datos_demo.py`."
        )
