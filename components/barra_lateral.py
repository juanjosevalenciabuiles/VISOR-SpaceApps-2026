"""Explorador: fenómeno, configuración cartográfica, leyendas y créditos.

Por defecto se dibuja en la barra lateral de Streamlit; la app principal lo
dibuja dentro de un panel flotante pasando `contenedor`. Cada control tiene
una clave estable para que su valor se conserve aunque el panel se oculte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

import streamlit as st

from components import flujo, leyenda
from components.panel_info import insignia
from utils import lugares, sesion
from utils import mapas_base
from utils.capas_contexto import CAPAS_CONTEXTO, disponibles, recortar
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
    # Encuadre del mapa (oeste, sur, este, norte) y zoom: solo para recortar ríos y carreteras.
    vista_limites: tuple | None = None
    vista_zoom: float | None = None


def _interruptor_contexto(clave: str, hay_datos: bool) -> bool:
    capa = CAPAS_CONTEXTO[clave]
    ayuda = f"{capa.alcance} Fuente: {capa.fuente}." if hay_datos else (
        f"No disponible: falta data/contexto/{capa.archivo}. Ver README."
    )
    return st.toggle(capa.nombre, value=False, disabled=not hay_datos, help=ayuda, key=f"ctx_{clave}") and hay_datos


def _buscar_lugar(ir_a) -> None:
    """Callback de «Buscar»: solo consulta nombres y, si hay una única coincidencia, centra el mapa.
    No define ninguna zona ni lanza ningún análisis."""
    texto = str(st.session_state.get("lugar_texto", "")).strip()
    encontrados, fuente, aviso = lugares.buscar(texto)
    st.session_state["lugares_encontrados"] = {"consulta": texto, "lugares": encontrados, "fuente": fuente,
                                               "aviso": aviso}
    if len(encontrados) == 1:
        _ir_a_lugar(encontrados[0], ir_a)


def _ir_a_lugar(lugar, ir_a) -> None:
    st.session_state["lugar"] = {"etiqueta": lugar.etiqueta, "latitud": lugar.latitud, "longitud": lugar.longitud,
                                 "fuente": lugar.fuente}
    # Un resultado pertenece a su zona: si el lugar queda fuera de ella, se retira de la pantalla (los
    # archivos y el Historial no cambian) para que nunca parezca un resultado del lugar nuevo.
    zona = flujo.zona_confirmada()
    if st.session_state.get("resultado_activo"):
        dentro = zona is not None and zona[0] <= lugar.longitud <= zona[2] and zona[1] <= lugar.latitud <= zona[3]
        if not dentro:
            flujo.limpiar_resultado(f"Se retiró el resultado del mapa al ir a {lugar.etiqueta}: corresponde a otra "
                                    "zona. Sigue disponible en el Historial.")
    ir_a(lugar.latitud, lugar.longitud, lugar.zoom)


def buscador_lugar(ir_a, abrir_zona=None) -> None:
    """«¿Qué lugar quieres analizar?»: busca por nombre y lleva el mapa allí."""
    st.caption("¿QUÉ LUGAR QUIERES ANALIZAR?")
    st.text_input("Lugar", key="lugar_texto", placeholder="Ciudad, municipio o lugar · ej.: Chigorodó, Nairobi, Tokio",
                  label_visibility="collapsed")
    st.button("Buscar", key="lugar_buscar", icon=":material/search:", type="primary", on_click=_buscar_lugar,
              args=(ir_a,))
    hallazgo = st.session_state.get("lugares_encontrados")
    if hallazgo:
        encontrados = hallazgo["lugares"]
        if hallazgo.get("aviso"):
            st.markdown(f'<div class="mc-aviso">{escape(hallazgo["aviso"])}</div>', unsafe_allow_html=True)
        if not encontrados and not hallazgo.get("aviso"):
            alcance = ("" if hallazgo["fuente"] == lugares.EN_LINEA else
                       " Sin geocodificador en línea solo se buscan las ciudades del catálogo local (capitales de "
                       "Colombia, Urabá y ciudades principales del mundo).")
            st.markdown(f'<div class="mc-aviso">No se encontró «{escape(hallazgo["consulta"])}».{alcance} '
                        "Puedes mover el mapa a mano y dibujar la zona.</div>", unsafe_allow_html=True)
        elif len(encontrados) > 1:
            st.markdown('<div class="visor-leyenda-nota">Hay varias coincidencias. Elige una:</div>',
                        unsafe_allow_html=True)
            for i, lugar in enumerate(encontrados):
                st.button(lugar.etiqueta, key=f"lugar_ir_{i}", icon=":material/location_on:", type="tertiary",
                          on_click=_ir_a_lugar, args=(lugar, ir_a))
        if encontrados:
            fuente = (lugares.ATRIBUCION_NOMINATIM if hallazgo["fuente"] == lugares.EN_LINEA
                      and lugares.proveedor() == lugares.NOMINATIM else f"Fuente: {hallazgo['fuente']}")
            st.markdown(f'<div class="visor-leyenda-nota">{escape(fuente)}. Posición aproximada, solo para ubicar '
                        "el mapa: no es un límite ni una zona de análisis.</div>", unsafe_allow_html=True)
    lugar = st.session_state.get("lugar")
    if lugar:
        st.markdown(f'<div class="mc-resultado"><span class="mc-insignia mc-insignia-tenue">UBICADO</span>'
                    f'{escape(lugar["etiqueta"])}</div>', unsafe_allow_html=True)
    if abrir_zona is not None:
        st.button("Definir la zona de análisis", key="lugar_definir_zona", icon=":material/crop_free:",
                  on_click=abrir_zona, help="Abre Herramientas SAR en el paso 01: dibuja la zona sobre el mapa.")


def _ver_historico(id_resultado: str) -> None:
    flujo.activar(id_resultado, sesion.HISTORICO)


def _controles_resultados(resultados: list, centrar=None, activo=None) -> dict[str, float]:
    """Un único resultado en el mapa: el del último análisis de esta sesión o el que se abra a
    propósito desde el historial. Lo que hay en data/analisis/ NO se dibuja por existir."""
    st.caption("RESULTADO EN EL MAPA")
    activos: dict[str, float] = {}
    if st.session_state.get("aviso_resultado"):
        st.markdown(f'<div class="mc-aviso">{escape(st.session_state["aviso_resultado"])}</div>',
                    unsafe_allow_html=True)
    if activo is None:
        st.markdown('<div class="visor-leyenda-nota" id="sin-resultado">Ninguno. Aparecerá aquí cuando termines un '
                    "análisis en Herramientas SAR o abras uno del historial.</div>", unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div class="mc-resultado"><span class="mc-insignia mc-insignia-origen">{flujo.etiqueta_origen()}</span>'
            f"{insignia(activo.capa.procedencia)}<code>{escape(activo.ruta.name)}</code></div>",
            unsafe_allow_html=True)
        activos[activo.id] = st.slider("Opacidad del resultado", 0.0, 1.0, 0.85, 0.05, key="res_opacidad")
        with st.container(horizontal=True):
            if centrar is not None:
                st.button("Centrar", key="res_centrar", icon=":material/center_focus_strong:", type="tertiary",
                          on_click=centrar, args=(activo.capa.limites,))
            st.button("Limpiar resultado", key="res_limpiar", icon=":material/layers_clear:", type="tertiary",
                      on_click=flujo.limpiar_resultado,
                      help="Lo quita del mapa. No borra ningún archivo: sigue en el historial.")
    dibujables = [r for r in resultados if r.dibujable]
    ocultos = [r for r in resultados if not r.dibujable]
    with st.expander(f"Historial ({len(dibujables)})", expanded=False, key="historial"):
        st.markdown('<div class="visor-leyenda-nota">Resultados guardados en <code>data/analisis/</code> por '
                    "análisis anteriores. Ninguno se muestra hasta que pulses «Ver»; abrirlo no ejecuta un "
                    "análisis nuevo.</div>", unsafe_allow_html=True)
        if not dibujables:
            st.markdown('<div class="visor-leyenda-nota">Todavía no hay resultados guardados.</div>',
                        unsafe_allow_html=True)
        for res in dibujables:
            st.markdown(f'<div class="mc-resultado">{insignia(res.capa.procedencia)}'
                        f'<code>{escape(res.ruta.name)}</code></div>'
                        f'<div class="visor-leyenda-nota">{escape(res.nombre)} · {escape(_fecha_archivo(res))}</div>',
                        unsafe_allow_html=True)
            st.button("Ver", key=f"hist_ver_{res.id}", icon=":material/history:", type="tertiary",
                      on_click=_ver_historico, args=(res.id,), disabled=activo is not None and activo.id == res.id,
                      help="Lo muestra en el mapa rotulado como HISTÓRICO.")
        if ocultos:
            st.markdown(
                f'<details class="mc-detalles mc-resultado-off"><summary>{len(ocultos)} archivo(s) no se muestran'
                "</summary>" + "".join(f'<div class="visor-leyenda-nota"><code>{escape(r.ruta.name)}</code> · '
                                       f"{escape(r.error or 'No se puede mostrar.')}</div>" for r in ocultos)
                + "</details>", unsafe_allow_html=True)
    return activos


def _fecha_archivo(res) -> str:
    """Cuándo se generó: lo que declara la ficha válida o, si no, la fecha del archivo."""
    bloque = (res.ficha or {}).get("procedencia") if res.capa.procedencia.es_real else None
    if isinstance(bloque, dict) and bloque.get("generado_utc"):
        return f"generado {str(bloque['generado_utc'])[:16].replace('T', ' ')} UTC"
    from datetime import datetime, timezone
    try:
        return f"archivo del {datetime.fromtimestamp(res.ruta.stat().st_mtime, timezone.utc):%Y-%m-%d %H:%M} UTC"
    except OSError:
        return "fecha no disponible"


def render(contenedor=None, titulo: bool = True, resultados: list | None = None, centrar=None, activo=None,
           ir_a=None, abrir_zona=None) -> Controles:
    with contenedor if contenedor is not None else st.sidebar:
        if titulo:
            st.markdown('<div class="visor-lateral-titulo">🛰️ V.I.S.O.R.</div>', unsafe_allow_html=True)

        if ir_a is not None:
            buscador_lugar(ir_a, abrir_zona)

        activos = _controles_resultados(resultados, centrar, activo) if resultados is not None else {}

        st.caption("MAPA BASE")
        opciones = mapas_base.ofrecidos()
        anterior = st.session_state.get("mapa_base")
        if anterior not in opciones:
            st.session_state["mapa_base"] = mapas_base.predeterminado()
            if anterior in MAPAS_BASE:      # el fondo elegido dejó de estar disponible: se dice, no se oculta
                st.session_state["aviso_mapa_base"] = (
                    f"{MAPAS_BASE[anterior].nombre} dejó de estar disponible "
                    f"({mapas_base.no_ofrecidos().get(anterior, 'sin respuesta')}); se cambió a "
                    f"{MAPAS_BASE[st.session_state['mapa_base']].nombre}.")
        if mapas_base.todos_caidos():
            st.markdown('<div class="mc-aviso" id="aviso-sin-mapas">Ningún mapa base respondió a la última '
                        "comprobación desde el servidor (ver «Estado del sistema»). Se siguen ofreciendo; si el "
                        "fondo no carga en tu navegador, el mapa avisará.</div>", unsafe_allow_html=True)
        if st.session_state.get("aviso_mapa_base"):
            st.markdown(f'<div class="mc-aviso" id="aviso-mapa-base">{escape(st.session_state["aviso_mapa_base"])}'
                        "</div>", unsafe_allow_html=True)
        mapa_base = st.selectbox(
            "Mapa base",
            options=opciones,
            format_func=lambda k: MAPAS_BASE[k].nombre,
            help="Cambia solo el fondo. Los resultados, la zona, la ubicación y el zoom se conservan.",
            key="mapa_base",
            on_change=lambda: st.session_state.pop("aviso_mapa_base", None),
        )
        st.markdown(
            f'<div class="visor-leyenda-nota visor-nota-base">{escape(MAPAS_BASE[mapa_base].uso)}</div>',
            unsafe_allow_html=True,
        )
        faltan = mapas_base.no_ofrecidos()
        if faltan:
            st.markdown('<div class="visor-leyenda-nota">No disponibles aquí: ' + "; ".join(
                f"{escape(MAPAS_BASE[k].nombre)} ({escape(m)})" for k, m in faltan.items()) + ".</div>",
                unsafe_allow_html=True)

        st.caption("INFORMACIÓN GEOGRÁFICA")
        hay = disponibles()
        hidrografia = _interruptor_contexto("hidrografia", hay["hidrografia"])
        vias = _interruptor_contexto("vias", hay["vias"])
        mostrar_referencia = st.toggle("Área de referencia (Antioquia)", value=False, key="referencia",
                                       help="Rectángulo aproximado de Antioquia, solo como referencia visual.")
        limites, zoom = (None, None)
        if hidrografia or vias:
            from components.mapa import vista_actual
            limites, zoom = vista_actual(st.session_state.get("vista"))
            for clave, activa in (("hidrografia", hidrografia), ("vias", vias)):
                datos = recortar(clave, limites, zoom) if activa else None
                if datos is not None and datos.aviso:
                    st.markdown(f'<div class="visor-leyenda-nota">{escape(datos.aviso)}</div>', unsafe_allow_html=True)
                elif datos is not None and not datos.elementos:
                    st.markdown(f'<div class="visor-leyenda-nota">{escape(CAPAS_CONTEXTO[clave].nombre)}: nada en esta '
                                "vista a escala general (puede haberlo en el mapa base «Calles»).</div>",
                                unsafe_allow_html=True)

        from components import sistema
        with st.expander("Estado del sistema", expanded=False, key="sistema"):
            sistema.render()

        # Las capas DEMO son sintéticas: apagadas por defecto y solo visibles si se piden a propósito.
        with st.expander("Demostración (datos sintéticos)", expanded=False, key="demo"):
            st.markdown('<div class="visor-leyenda-nota">Capas generadas por computador para probar la interfaz. '
                        "No son observaciones de satélite ni resultados de un análisis.</div>",
                        unsafe_allow_html=True)
            mostrar_capa = st.toggle("Mostrar capa DEMO", value=False, key="capa_sar")
            clave = st.radio(
                "Fenómeno",
                options=list(FENOMENOS),
                format_func=lambda k: f"{FENOMENOS[k].icono}  {FENOMENOS[k].nombre}",
                key="fenomeno",
            )
            opacidad = st.slider("Opacidad DEMO", 0.0, 1.0, 0.85, 0.05, disabled=not mostrar_capa, key="opacidad_sar")
            mostrar_huella = st.toggle("Cobertura de la capa DEMO", value=True, disabled=not mostrar_capa,
                                       key="huella")

    return Controles(
        clave, mostrar_capa, opacidad, mostrar_huella and mostrar_capa, mostrar_referencia,
        mapa_base, hidrografia, vias, activos, limites, zoom,
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
        filas.append(f"<b>Capa DEMO · {escape(fenomeno.nombre)}:</b> {origen}.")
    return "".join(f'<div class="visor-credito">{f}</div>' for f in filas)


def render_leyenda(fenomeno: Fenomeno, capa: Capa | None, c: Controles, contenedor=None) -> None:
    """Leyendas, créditos y estado del mapa base. Va aparte porque necesita la capa ya cargada."""
    with contenedor if contenedor is not None else st.sidebar:
        st.caption("LEYENDA")
        if capa is not None:
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
