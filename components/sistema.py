"""Panel «Estado del sistema»: servicios externos y procesadores, con su motivo.

Se muestra lo último comprobado (con la hora). «Comprobar ahora» repite la comprobación
de forma síncrona (unos segundos como máximo por servicio). Nada aquí ejecuta análisis.
"""
from __future__ import annotations

from html import escape

import streamlit as st

from utils import diagnostico, procesadores

_CLASE = {"APTO": "mc-pastilla-apto", "ERROR": "mc-pastilla-error", "NO DISPONIBLE": "mc-pastilla-bloqueado",
          "DESHABILITADO": "mc-pastilla-bloqueado", "NO COMPROBADO": "mc-pastilla-pendiente"}


def _insignia(estado: str) -> str:
    return f'<span class="mc-pastilla {_CLASE.get(estado, "mc-pastilla-pendiente")}">{escape(estado)}</span>'


def _comprobar() -> None:
    with st.spinner("Comprobando servicios… (máx. unos segundos por servicio)"):
        diagnostico.comprobar()


def render() -> None:
    cuando, resultados, en_curso = diagnostico.ultimo()
    st.markdown('<div class="visor-seccion">Servicios externos</div>', unsafe_allow_html=True)
    if diagnostico.desactivado():
        st.markdown('<div class="visor-leyenda-nota">Comprobación automática desactivada en este entorno '
                    "(VISOR_DIAGNOSTICO=desactivado).</div>", unsafe_allow_html=True)
    if resultados:
        filas = "".join(f"<tr><td>{escape(e.nombre)}</td><td>{_insignia(e.estado)}</td><td>{escape(e.detalle)}</td></tr>"
                        for e in resultados)
        st.markdown(f'<table class="mc-tabla mc-tabla-sistema" id="tabla-servicios"><tbody>{filas}</tbody></table>'
                    f'<div class="visor-leyenda-nota">Comprobado {cuando:%Y-%m-%d %H:%M} UTC. Un mapa base con ERROR '
                    "deja de ofrecerse hasta la próxima comprobación correcta.</div>", unsafe_allow_html=True)
    else:
        st.markdown('<div class="visor-leyenda-nota">' + ("Comprobación en curso…" if en_curso else
                    "Aún no se ha comprobado ningún servicio.") + "</div>", unsafe_allow_html=True)
    st.button("Comprobar ahora", key="sistema_comprobar", icon=":material/network_check:", on_click=_comprobar,
              help="Una petición ligera a cada servicio: una tesela por mapa base, el estado del buscador, "
                   "un conteo en ASF y la página de Earthdata.")

    st.markdown('<div class="visor-seccion">Procesadores de datos SAR</div>', unsafe_allow_html=True)
    filas = []
    for d in procesadores.diagnosticos():
        detalle = "".join(f"<li>{'✓' if ok else '✗'} {escape(q)}: {escape(v)}</li>" for q, ok, v in d.comprobaciones)
        filas.append(f"<tr><td>{escape(d.nombre)}<br><span class='visor-leyenda-nota'>{escape(d.sensor)}</span></td>"
                     f"<td>{_insignia(d.estado)}</td><td>{escape(d.motivo)}<ul class='visor-lista'>{detalle}</ul></td></tr>")
    st.markdown(f'<table class="mc-tabla mc-tabla-sistema" id="tabla-procesadores"><tbody>{"".join(filas)}</tbody>'
                "</table>", unsafe_allow_html=True)
