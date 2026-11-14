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
        filas = "".join(f'<li data-servicio="{escape(e.clave)}" data-estado="{escape(e.estado)}">'
                        f"{_insignia(e.estado)} {escape(e.nombre)}<div class='visor-leyenda-nota'>{escape(e.detalle)}"
                        "</div></li>" for e in resultados)
        st.markdown(f'<ul class="mc-lista-sistema" id="tabla-servicios">{filas}</ul>'
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
        filas.append(f'<li data-procesador="{escape(d.clave)}" data-estado="{escape(d.estado)}">{_insignia(d.estado)} '
                     f"<b>{escape(d.nombre)}</b> <span class='visor-leyenda-nota'>· {escape(d.sensor)}</span>"
                     f"<div class='visor-leyenda-nota'>{escape(d.motivo)}</div><ul class='visor-lista'>{detalle}</ul></li>")
    st.markdown(f'<ul class="mc-lista-sistema" id="tabla-procesadores">{"".join(filas)}</ul>', unsafe_allow_html=True)
