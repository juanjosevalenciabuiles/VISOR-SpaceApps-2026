"""Panel informativo: qué se está viendo, de dónde sale y cómo NO interpretarlo."""
from html import escape

import streamlit as st

from utils import procedencia
from utils.config import ADVERTENCIA_GENERAL, Fenomeno
from utils.geotiff import Capa
from utils.procedencia import Procedencia


def _fila(etiqueta: str, valor: str) -> str:
    return (
        f'<div class="visor-fila"><span>{escape(etiqueta)}</span>'
        f"<strong>{escape(valor)}</strong></div>"
    )


def bloque_procedencia(estado: Procedencia | None, es_demo: bool = False) -> str:
    """Estado de procedencia con su explicación y, si la ficha falla, por qué."""
    if es_demo:
        estado = Procedencia(procedencia.DEMO, "El GeoTIFF lleva la marca de datos sintéticos (VISOR_DEMO=1).")
    elif estado is None:
        estado = Procedencia(procedencia.NO_DECLARADA, "Procedencia no evaluada.")
    detalle = escape(estado.motivo)
    if estado.faltantes:
        detalle += " Falta: " + escape(", ".join(estado.faltantes)) + "."
    return (
        '<div class="visor-seccion">Procedencia</div>'
        f'<div class="visor-procedencia">{insignia(estado)}'
        f'<p class="visor-texto">{escape(estado.descripcion)}</p>'
        f'<p class="visor-nota-procedencia">{detalle}</p></div>'
    )


CLASE_INSIGNIA = {
    procedencia.DEMO: "mc-insignia-demo",
    procedencia.NO_DECLARADA: "mc-insignia-nodeclarada",
    procedencia.REAL_SIN_VALIDAR: "mc-insignia-real",
    procedencia.VALIDADO: "mc-insignia-validado",
}


def insignia(estado: Procedencia | None) -> str:
    """Insignia de uno de los cuatro estados de procedencia (sin estado = no declarada)."""
    if estado is None:
        estado = Procedencia(procedencia.NO_DECLARADA, "Procedencia no evaluada.")
    return (f'<span class="mc-insignia {CLASE_INSIGNIA[estado.estado]}" title="{escape(estado.descripcion)}">'
            f"{escape(estado.etiqueta)}</span>")


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
        partes.append(bloque_procedencia(capa.procedencia, capa.es_demo))
        m = capa.metadatos
        sin_meta = "No disponible (sin metadatos)"
        alto, ancho = capa.forma_original
        crs = capa.crs_original + (" → EPSG:4326" if capa.reproyectada else "")
        minimo, maximo = capa.rango
        partes += [
            '<div class="visor-seccion">Producto</div>',
            _fila("Tipo", m.get("PRODUCTO") or f"{fenomeno.producto} (esperado)"),
            _fila("Valores", "Categóricos (clases)" if fenomeno.categorico else "Continuos"),
            _fila("Unidades", m.get("UNIDADES") or fenomeno.unidades),
            _fila("Rango de datos", f"{minimo:.3g} a {maximo:.3g}"),
            # Fuente y fecha solo se afirman si vienen en los metadatos del archivo.
            _fila("Fuente", "Sintética (generada para pruebas)" if capa.es_demo else m.get("FUENTE", sin_meta)),
            _fila("Fecha", m.get("FECHA", sin_meta)),
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
