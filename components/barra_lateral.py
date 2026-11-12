"""Explorador: fenómeno, configuración cartográfica, leyendas y créditos.

Por defecto se dibuja en la barra lateral de Streamlit; la app principal lo
dibuja dentro de un panel flotante pasando `contenedor`. Cada control tiene
una clave estable para que su valor se conserve aunque el panel se oculte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

import streamlit as st

from components import leyenda
from components.panel_info import insignia
from utils.capas_contexto import CAPAS_CONTEXTO, disponibles
from utils.config import FENOMENOS, Fenomeno, carto_estado
from utils.geotiff import Capa
from utils.mapas_base import MAPA_BASE_PREDETERMINADO, MAPAS_BASE, obtener


@dataclass
class Controles:
    clave: str
    mostrar_capa: bool
    opacidad: float
    mostrar_huella: bool
    mostrar_referencia: bool
    mapa_base: str = MAPA_BASE_PREDETERMINADO
    hidrografia: bool = False
    vias: bool = False
    # Resultados de data/analisis/ activos: id → opacidad. Independientes del fenómeno.
    resultados: dict[str, float] = field(default_factory=dict)


def _interruptor_contexto(clave: str, hay_datos: bool) -> bool:
    capa = CAPAS_CONTEXTO[clave]
    ayuda = f"{capa.alcance} Fuente: {capa.fuente}." if hay_datos else (
        f"Sin datos: falta data/contexto/{capa.archivo}. Ver README."
    )
    return st.toggle(capa.nombre, value=False, disabled=not hay_datos, help=ayuda, key=f"ctx_{clave}") and hay_datos


def _controles_resultados(resultados: list, centrar=None) -> dict[str, float]:
    """Un interruptor y una opacidad por resultado. La opacidad se dibuja siempre
    (deshabilitada si la capa está apagada) para que conserve su valor."""
    st.caption("RESULTADOS SAR · DATA/ANALISIS")
    if not resultados:
        st.markdown('<div class="visor-leyenda-nota">No hay resultados en <code>data/analisis/</code>.</div>',
                    unsafe_allow_html=True)
        return {}
    activos: dict[str, float] = {}
    for res in resultados:
        if not res.dibujable:
            st.markdown(
                f'<div class="mc-resultado mc-resultado-off"><code>{escape(res.ruta.name)}</code>'
                f'<div class="visor-leyenda-nota">{escape(res.error or "No se puede mostrar.")}</div></div>',
                unsafe_allow_html=True,
            )
            continue
        visible = st.toggle(res.nombre, value=False, key=f"res_{res.id}",
                            help=f"{res.archivo}. Capa opcional: se superpone a la del fenómeno sin reemplazarla.")
        st.markdown(
            f'<div class="mc-resultado">{insignia(res.capa.procedencia)}'
            f'<code>{escape(res.ruta.name)}</code></div>',
            unsafe_allow_html=True,
        )
        opacidad = st.slider(f"Opacidad · {res.nombre}", 0.0, 1.0, 0.85, 0.05, disabled=not visible,
                             key=f"res_op_{res.id}", label_visibility="collapsed")
        if centrar is not None:
            st.button("Centrar en el mapa", key=f"res_ir_{res.id}", icon=":material/center_focus_strong:",
                      type="tertiary", on_click=centrar, args=(res.capa.limites,))
        if visible:
            activos[res.id] = opacidad
    return activos


def render(contenedor=None, titulo: bool = True, resultados: list | None = None, centrar=None) -> Controles:
    with contenedor if contenedor is not None else st.sidebar:
        if titulo:
            st.markdown('<div class="visor-lateral-titulo">🛰️ V.I.S.O.R.</div>', unsafe_allow_html=True)

        st.caption("FENÓMENO")
        clave = st.radio(
            "Fenómeno",
            options=list(FENOMENOS),
            format_func=lambda k: f"{FENOMENOS[k].icono}  {FENOMENOS[k].nombre}",
            label_visibility="collapsed",
            key="fenomeno",
        )

        st.caption("CONFIGURACIÓN CARTOGRÁFICA")
        mapa_base = st.selectbox(
            "Mapa base",
            options=list(MAPAS_BASE),
            index=list(MAPAS_BASE).index(MAPA_BASE_PREDETERMINADO),
            format_func=lambda k: MAPAS_BASE[k].nombre,
            help="Cambia solo el fondo. La capa SAR, la ubicación y el zoom se conservan.",
            key="mapa_base",
        )
        st.markdown(
            f'<div class="visor-leyenda-nota visor-nota-base">{escape(MAPAS_BASE[mapa_base].uso)}</div>',
            unsafe_allow_html=True,
        )

        mostrar_capa = st.toggle("Capa SAR", value=True, key="capa_sar")
        opacidad = st.slider("Opacidad SAR", 0.0, 1.0, 0.85, 0.05, disabled=not mostrar_capa, key="opacidad_sar")

        hay = disponibles()
        hidrografia = _interruptor_contexto("hidrografia", hay["hidrografia"])
        vias = _interruptor_contexto("vias", hay["vias"])

        mostrar_huella = st.toggle("Cobertura de la capa", value=True, key="huella")
        mostrar_referencia = st.toggle("Área de referencia", value=False, key="referencia")

        activos = _controles_resultados(resultados, centrar) if resultados is not None else {}

    return Controles(
        clave, mostrar_capa, opacidad, mostrar_huella, mostrar_referencia,
        mapa_base, hidrografia, vias, activos,
    )


def _creditos(fenomeno: Fenomeno, capa: Capa | None, c: Controles) -> str:
    mapa = obtener(c.mapa_base)
    filas = [f"<b>Mapa base:</b> {escape(mapa.proveedor)}. {escape(mapa.licencia)}"]
    for clave, activa in (("hidrografia", c.hidrografia), ("vias", c.vias)):
        if activa:
            ctx = CAPAS_CONTEXTO[clave]
            filas.append(f"<b>{escape(ctx.nombre)}:</b> {escape(ctx.fuente)}. {escape(ctx.licencia)}.")
    if capa is not None:
        if capa.es_demo:
            origen = "datos sintéticos de demostración (no satelitales)"
        else:
            origen = escape(capa.metadatos.get("FUENTE", "fuente no declarada en los metadatos"))
        filas.append(f"<b>Capa SAR · {escape(fenomeno.nombre)}:</b> {origen}.")
    return "".join(f'<div class="visor-credito">{f}</div>' for f in filas)


def render_leyenda(fenomeno: Fenomeno, capa: Capa | None, c: Controles, contenedor=None) -> None:
    """Leyendas, créditos y estado del mapa base. Va aparte porque necesita la capa ya cargada."""
    with contenedor if contenedor is not None else st.sidebar:
        st.caption("LEYENDA")
        leyenda.render(fenomeno, capa)
        leyenda.render_contexto([k for k, activa in (("hidrografia", c.hidrografia), ("vias", c.vias)) if activa])

        st.caption("CRÉDITOS Y FUENTES")
        st.markdown(_creditos(fenomeno, capa, c), unsafe_allow_html=True)

        estado = carto_estado()
        if obtener(c.mapa_base).usa_clave_carto and estado != "ok":
            motivo = (
                "Falta la variable <code>CARTO_API_KEY</code>" if estado == "ausente"
                else "<code>CARTO_API_KEY</code> tiene una forma inválida y no se usó"
            )
            st.markdown(
                f'<div class="visor-leyenda-nota">{motivo}: este mapa base puede verse '
                "con marca de agua. Ver README.</div>",
                unsafe_allow_html=True,
            )
