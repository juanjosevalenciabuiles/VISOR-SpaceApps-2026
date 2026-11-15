"""Interfaz Mission Control Earth Explorer: superficies flotantes sobre un único mapa.

El mapa ocupa todo el viewport y nunca se reemplaza. Encima flotan:

    barra superior · explorador · panel científico · Herramientas SAR · línea temporal

Reglas de diseño que este módulo respeta:

- Ocultar un panel NO deja de dibujarlo: se oculta con CSS. Así sus controles
  conservan su valor (por ejemplo, el fenómeno elegido) y el mapa no se toca.
- Todo el estado de la interfaz vive en `st.session_state` con las claves de
  ESTADO_INICIAL.
- Mover la vista ("Ir a…", "Área inicial") envía centro y zoom al mapa existente;
  nunca lo recrea (ver components/mapa.destino_vista).
"""
from __future__ import annotations

import math
from html import escape

import streamlit as st

from components import barra_lateral, eco, flujo, panel_info
from components import contexto_zona
from components import herramientas_sar as herramientas
from components import v9_experiencia
from components import resultados as ui_resultados
from components.barra_lateral import Controles
from components.panel_info import insignia
from utils import alcance_geografico
from utils.config import MAPA_CENTRO, MAPA_ZOOM, Fenomeno
from utils import procedencia, trabajos
from utils.geotiff import Capa

ESTADO_INICIAL = {
    "ui_explorador": True,              # panel izquierdo de exploración
    "ui_info": True,                    # panel científico de la derecha
    "ui_sar": "cerrado",                # "cerrado" | "abierto" | "minimizado"
    "ui_explorador_previo": True,       # cómo estaba el explorador antes de abrir SAR
    "vista": None,                      # {"centro": [lat, lon], "zoom": z, "n": k}
}
ESTADOS_SAR = ("cerrado", "abierto", "minimizado")
PASOS_SAR = ("1 · Zona", "2 · Imágenes", "3 · Análisis", "4 · Resultado")


def inicializar_estado() -> None:
    for clave, valor in ESTADO_INICIAL.items():
        st.session_state.setdefault(clave, valor)
    flujo.inicializar()
    if st.session_state["ui_sar"] not in ESTADOS_SAR:
        st.session_state["ui_sar"] = "cerrado"


# ---------------------------------------------------------------------------
# Acciones (callbacks): solo cambian estado de interfaz, nunca el mapa ni datos
# ---------------------------------------------------------------------------

def alternar_explorador() -> None:
    abrir = not st.session_state["ui_explorador"]
    st.session_state["ui_explorador"] = abrir
    if abrir and st.session_state["ui_sar"] == "abierto":
        st.session_state["ui_sar"] = "minimizado"   # ambos ocupan el lado izquierdo


def alternar_info() -> None:
    st.session_state["ui_info"] = not st.session_state["ui_info"]


def abrir_sar() -> None:
    if st.session_state["ui_sar"] == "cerrado":
        st.session_state["ui_explorador_previo"] = st.session_state["ui_explorador"]
    st.session_state["ui_sar"] = "abierto"
    st.session_state["ui_explorador"] = False


def cambiar_zona() -> None:
    """Quita la zona confirmada y abre el paso «Área» para elegir otra."""
    flujo.quitar_zona()
    abrir_sar()


def minimizar_sar() -> None:
    st.session_state["ui_sar"] = "minimizado"


def cerrar_sar() -> None:
    st.session_state["ui_sar"] = "cerrado"
    st.session_state["ui_explorador"] = st.session_state["ui_explorador_previo"]


def ir_a(lat: float, lon: float, zoom: float) -> None:
    anterior = st.session_state.get("vista") or {}
    st.session_state["vista"] = {"centro": [float(lat), float(lon)], "zoom": float(zoom),
                                 "n": int(anterior.get("n", 0)) + 1}


def leer_coordenada(texto, minimo: float, maximo: float, nombre: str) -> float:
    """Convierte lo escrito en un número dentro del rango. Acepta coma decimal (7,675)."""
    limpio = str(texto).strip().replace(" ", "")
    if limpio.count(",") == 1 and "." not in limpio:
        limpio = limpio.replace(",", ".")
    try:
        valor = float(limpio)
    except ValueError:
        raise ValueError(f"La {nombre} «{texto}» no es un número (usa punto decimal, por ejemplo 7.675).") from None
    if not minimo <= valor <= maximo:
        raise ValueError(f"La {nombre} debe estar entre {minimo:g} y {maximo:g}; se escribió {valor:g}.")
    return valor


def centrar_en(limites: tuple[float, float, float, float]) -> None:
    """Centra el mapa en una extensión (oeste, sur, este, norte) con un zoom que la abarca."""
    oeste, sur, este, norte = limites
    lado = max(este - oeste, norte - sur, 1e-6)
    zoom = max(3, min(14, int(math.log2(360.0 / lado)) + 1))
    ir_a((sur + norte) / 2, (oeste + este) / 2, zoom)


def volver_al_inicio() -> None:
    if alcance_geografico.restringido():
        (lat, lon), zoom = alcance_geografico.VISTA_INICIAL["centro"], alcance_geografico.VISTA_INICIAL["zoom"]
        ir_a(lat, lon, zoom)
    else:
        ir_a(MAPA_CENTRO[0], MAPA_CENTRO[1], MAPA_ZOOM)


# ---------------------------------------------------------------------------
# Estilos dependientes del estado
# ---------------------------------------------------------------------------

def css_estado() -> str:
    """Oculta con CSS los paneles cerrados (siguen dibujados y conservan su estado)."""
    ocultos = []
    if not st.session_state["ui_explorador"]:
        ocultos.append(".st-key-panel_explorador")
    if not st.session_state["ui_info"]:
        ocultos.append(".st-key-panel_info")
    if st.session_state["ui_sar"] != "abierto":
        ocultos.append(".st-key-panel_sar")
    if st.session_state["ui_sar"] != "minimizado":
        ocultos.append(".st-key-sar_minimizado")
    css = (",".join(ocultos) + "{display:none !important}") if ocultos else ""
    if not st.session_state.get("ui_capas_abierto", True):
        css += (".st-key-panel_capas_body{display:none !important}"
                "@media(min-width:721px){.st-key-panel_info{"
                "top:calc(var(--mc-arriba) + 72px) !important;"
                "max-height:calc(100vh - var(--mc-arriba) - 260px) !important}}")
    if st.session_state["ui_explorador"]:
        # Móvil: ambas son hojas inferiores; con el explorador abierto, la información sube.
        css += ("@media (max-width:720px){.st-key-panel_info{bottom:calc(46vh + 38px) !important;"
                "max-height:24vh !important}}")
    return css


def aplicar_css_estado() -> None:
    st.markdown(f"<style>{css_estado()}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Superficies
# ---------------------------------------------------------------------------

def insignia_procedencia(capa: Capa | None) -> str:
    if capa is None:
        return '<span class="mc-insignia mc-insignia-tenue">SIN CAPA</span>'
    if capa.es_demo:  # la marca del propio GeoTIFF manda, aunque falte la evaluación
        return insignia(procedencia.Procedencia(procedencia.DEMO, "VISOR_DEMO=1"))
    return insignia(capa.procedencia)


@st.dialog("Ayuda · V.I.S.O.R.", width="large")
def mostrar_ayuda() -> None:
    st.markdown(
        """
**Cómo usar el visor**

- El mapa ocupa toda la pantalla. Arrástralo y usa la rueda o los botones **+ / −** para el zoom.
- Al abrir, el mapa está vacío: **no hay ningún resultado hasta que analices** o abras uno del historial.
- **Buscador** (arriba a la izquierda): escribe un municipio y elige una sugerencia; también acepta
  coordenadas (`7.67, -76.68`). El botón de la casa vuelve a la vista general.
- **Explorador** (izquierda): controla el resultado en el mapa, el historial y el mapa base.
- **Información** (derecha): qué muestra el resultado, de dónde viene, leyenda y créditos.
- **Herramientas SAR**: define la zona (dibújala con las herramientas ▭ y ⬠ del mapa), busca imágenes,
  elige dos fechas y pulsa **Analizar**. Solo entonces aparece el resultado, uno a la vez.
- **Historial** (explorador): resultados guardados de análisis anteriores. Se abren con «Ver» y quedan
  rotulados como HISTÓRICO; abrirlos no ejecuta nada.
- Si cambias la zona, las fechas o los parámetros, el resultado anterior se retira del mapa (el archivo
  no se borra).
- **Demostración** (explorador): capas sintéticas de ejemplo, apagadas por defecto.
- Cierra los paneles para ver el mapa completo; vuelve a abrirlos desde la barra superior.

**Qué significan las etiquetas**

| Etiqueta | Significado |
| --- | --- |
| DEMO | Datos sintéticos generados para probar la interfaz. No son observaciones. |
| PROCEDENCIA NO DECLARADA | Falta una ficha de procedencia completa: no se puede afirmar de qué datos ni de qué proceso sale la capa. |
| REAL SIN VALIDAR | Producto derivado de datos satelitales reales, con ficha de procedencia completa; resultado exploratorio. |
| VALIDADO | Además, respaldado por una verificación independiente documentada en su ficha. |

Las etiquetas REAL SIN VALIDAR y VALIDADO nunca se asignan por defecto: exigen una ficha JSON que
corresponda exactamente al archivo (huella SHA-256).

Un cambio de retrodispersión de radar **no confirma** una inundación ni ningún otro fenómeno.

**Datos de radar.** NISAR (NASA-ISRO, banda L) es el sensor principal para estudiar inundaciones;
Sentinel-1 (ESA/Copernicus, banda C) queda como respaldo. Un GCOV no confirma una inundación.

**Uso de inteligencia artificial.** Parte del código y de la documentación de V.I.S.O.R. se
desarrolló con asistencia de IA (Claude, de Anthropic), bajo revisión del equipo.
"""
    )


def estado_html(fenomeno: Fenomeno, capa: Capa | None, activos: list | tuple = (),
                capa_visible: bool = True) -> str:
    """Qué hay en el mapa ahora. Sin resultado ni DEMO lo dice con todas las letras; la capa DEMO
    (solo si se encendió a propósito) y el resultado van en grupos separados y rotulados."""
    grupos = []
    if capa is not None and capa_visible:
        grupos.append(
            '<span class="mc-grupo" title="Capa de demostración"><span class="mc-grupo-rot">Demostración</span>'
            f'<span class="mc-chip">{fenomeno.icono} {escape(fenomeno.nombre)}</span>'
            f"{insignia_procedencia(capa)}</span>")
    if activos:
        res = "".join(
            f'<span class="mc-chip mc-chip-res">{escape(r.nombre)}</span>'
            f'<span class="mc-insignia mc-insignia-origen">{flujo.etiqueta_origen()}</span>'
            f"{insignia(r.capa.procedencia)}" for r in list(activos)[:1])
        grupos.append('<span class="mc-grupo" title="Resultado en el mapa"><span class="mc-grupo-rot">Resultado SAR'
                      f"</span>{res}</span>")
    if not grupos:
        grupos.append('<span class="mc-grupo" title="No hay ningún resultado en el mapa">'
                      '<span class="mc-insignia mc-insignia-tenue">SIN RESULTADO</span>'
                      '<span class="mc-grupo-nota">Busca un lugar, define la zona y analiza</span></span>')
    return '<div class="mc-estado">' + '<span class="mc-separador"></span>'.join(grupos) + "</div>"


def barra_superior(fenomeno: Fenomeno, capa: Capa | None, activos: list | tuple = (),
                   capa_visible: bool = True) -> None:
    with st.container(key="barra_superior", horizontal=True, vertical_alignment="center", gap="small"):
        sub = ('<span class="mc-marca-sub mc-insignia-pais" id="insignia-colombia" title="En esta versión solo se '
               'explora y analiza el territorio colombiano (continental e insular).">'
               f'<span class="mc-insignia-larga">{escape(alcance_geografico.INSIGNIA)}</span>'
               '<span class="mc-insignia-corta">COLOMBIA</span></span>' if alcance_geografico.restringido()
               else '<span class="mc-marca-sub">Mission Control · Earth Explorer</span>')
        st.markdown('<div class="mc-marca"><span class="mc-marca-linea">'
                    '<span class="mc-marca-nombre">V.I.S.O.R.</span>'
                    '<span class="mc-marca-olas" role="img" aria-label="Agua e inundaciones" '
                    'title="Observación de agua e inundaciones">'
                    '<svg viewBox="0 0 42 32" width="33" height="27" '
                    'fill="none" xmlns="http://www.w3.org/2000/svg">'
                    '<path d="M2 10 C8 4, 14 4, 20 10 S32 16,40 10" '
                    'stroke="#38ddf5" stroke-width="2.8" stroke-linecap="round"/>'
                    '<path d="M2 19 C8 13,14 13,20 19 S32 25,40 19" '
                    'stroke="#b8f3ff" stroke-width="2.8" stroke-linecap="round"/>'
                    '<path d="M5 28 Q20 22 37 28" stroke="#38ddf5" '
                    'stroke-width="2.8" stroke-linecap="round"/>'
                    '</svg></span></span>' + sub + '</div>',
                    unsafe_allow_html=True, width="content")
        st.markdown(estado_html(fenomeno, capa, activos, capa_visible), unsafe_allow_html=True, width="content")
        st.space("stretch")
        st.button("Explorador", key="btn_explorador", help="Explorador: buscar lugar, resultado en el mapa, historial y mapa base", icon=":material/layers:", on_click=alternar_explorador,
                  type="primary" if st.session_state["ui_explorador"] else "secondary")
        st.button("Información", key="btn_info", help="Información científica de las capas activas", icon=":material/info:", on_click=alternar_info,
                  type="primary" if st.session_state["ui_info"] else "secondary")
        if activos:
            st.button("Nuevo análisis", key="btn_nuevo_analisis",
                      help="Elegir otra zona sin borrar los GeoTIFF del historial",
                      icon=":material/add_location_alt:",
                      on_click=v9_experiencia._nuevo_analisis, args=(True,),
                      type="primary")
        st.button("Herramientas SAR", key="btn_sar", help="Herramientas SAR: área, escenas, análisis y resultados", icon=":material/satellite_alt:", on_click=abrir_sar,
                  type="primary" if st.session_state["ui_sar"] == "abierto" else "secondary")
        if st.button("Ayuda", key="btn_ayuda", help="Ayuda y estados de procedencia", icon=":material/help:"):
            mostrar_ayuda()


def buscador() -> None:
    """Buscador flotante, siempre visible sobre el mapa (aunque el Explorador esté cerrado)."""
    with st.container(key="buscador_flotante"):
        barra_lateral.buscador_lugar(ir_a, volver_al_inicio)


def panel_explorador(resultados: list | None = None, activo=None) -> Controles:
    panel = st.container(key="panel_explorador")
    with panel:
        with st.container(horizontal=True, vertical_alignment="center", key="cabecera_explorador"):
            st.markdown('<div class="mc-titulo-panel">Explorador</div>', unsafe_allow_html=True)
            st.button("Contraer", key="cerrar_explorador", icon=":material/chevron_left:", type="tertiary",
                      on_click=alternar_explorador)
        st.button("Ver datos reales · modo jurado", key="visor_boton_muestra_real",
                  icon=":material/satellite_alt:", type="primary", use_container_width=True,
                  on_click=lambda: st.session_state.__setitem__("visor_modo_muestra_real", True),
                  help="Abre GeoTIFF y tomas NISAR ya guardados, sin consultar ni descargar datos.")
    return barra_lateral.render(panel, titulo=False, resultados=resultados or [], centrar=centrar_en,
                                activo=activo, ir_a=ir_a, abrir_zona=abrir_sar)


GUIA_INICIO = (
    '<div class="mc-guia" id="guia-inicio"><div class="mc-ctx-titulo">Cómo empezar</div>'
    '<ol class="mc-pasos-guia">'
    '<li><span class="mc-paso-num">1</span><div><b>Busca un lugar</b><small>Escribe un municipio en el '
    "buscador (arriba a la izquierda) o dibuja un rectángulo en el mapa.</small></div></li>"
    '<li><span class="mc-paso-num">2</span><div><b>Confirma la zona</b><small>Aquí verás su foto, alertas del '
    "IDEAM y datos del territorio.</small></div></li>"
    '<li><span class="mc-paso-num">3</span><div><b>Analiza con radar</b><small>Busca NISAR primero; Sentinel-1 es respaldo. Compara dos fechas: '
    "solo entonces se calcula y se dibuja el resultado.</small></div></li></ol>"
    '<p class="visor-leyenda-nota">Todavía no hay ningún resultado en el mapa. V.I.S.O.R. solo muestra lo que tú '
    "analices en esta sesión o abras a propósito desde el historial.</p>"
    '<div class="visor-aviso visor-aviso-general">Un cambio en la señal de radar no confirma una inundación ni '
    "ningún otro fenómeno.</div></div>")


def panel_informacion(fenomeno: Fenomeno, capa: Capa | None, error: str | None, controles: Controles,
                      resultados: list | None = None) -> None:
    activos = [r for r in (resultados or []) if r.dibujable and r.id in controles.resultados]
    demo = controles.mostrar_capa
    panel = st.container(key="panel_info")
    with panel:
        with st.container(horizontal=True, vertical_alignment="center", key="cabecera_info"):
            st.markdown('<div class="mc-titulo-panel">Información</div>', unsafe_allow_html=True)
            st.button("Cerrar", key="cerrar_info", icon=":material/close:", type="tertiary",
                      on_click=alternar_info)
        if activos:
            st.button("Analizar otra zona · conservar este resultado en historial",
                      key="v9_nueva_zona_desde_info",
                      on_click=v9_experiencia._nuevo_analisis, args=(True,),
                      use_container_width=True)
        for res in activos:
            if flujo.es_historico():
                abierto = str((st.session_state.get("resultado_activo") or {}).get("abierto", ""))[:16]
                st.caption("RESULTADO HISTÓRICO")
                st.markdown('<div class="mc-aviso" id="aviso-historico">Abierto desde el historial '
                            f'({escape(abierto.replace("T", " "))} UTC). Es un resultado guardado de un análisis '
                            "anterior: no se ejecutó un análisis nuevo.</div>", unsafe_allow_html=True)
            else:
                st.caption("RESULTADO DE ESTE ANÁLISIS")
            st.markdown(ui_resultados.ficha_html(res), unsafe_allow_html=True)
            ui_resultados.boton_qgis(res)
        # Contexto de la zona confirmada (sin pulsar nada); sin zona, una invitación a elegirla.
        hay_zona = contexto_zona.render(activos, {"analizar": abrir_sar, "centrar": centrar_en,
                                                   "cambiar": cambiar_zona})
        if not activos and not demo and not hay_zona:
            st.markdown(GUIA_INICIO, unsafe_allow_html=True)
        if demo:
            st.caption("CAPA DE DEMOSTRACIÓN")
            panel_info.render(fenomeno, capa, error)
    barra_lateral.render_leyenda(fenomeno, capa if demo else None, controles, panel)


def guia_eco(activos: list) -> None:
    """ECO en la esquina inferior derecha, con un mensaje sacado del estado real de la app."""
    zona = contexto_zona.zona_actual()
    lugar, ocupado = None, False
    if zona is not None:
        lugar = contexto_zona.local_de(zona).lugar
        inicio, fin, _ = contexto_zona.periodo_actual()
        ocupado = contexto_zona.consultando(contexto_zona.consultas(zona, inicio, fin))
    trabajo = None
    if st.session_state.get("trabajo_activo"):
        try:
            trabajo = trabajos.leer(st.session_state["trabajo_activo"])
        except Exception:  # noqa: BLE001 — ECO nunca rompe la app
            trabajo = None
    trabajo_nisar = None
    if st.session_state.get("nisar_auto_job"):
        try:
            trabajo_nisar = trabajos.leer(st.session_state["nisar_auto_job"])
        except Exception:  # noqa: BLE001 — ECO nunca bloquea la app
            trabajo_nisar = None
    eco.render(eco.decidir(lugar, zona is not None, ocupado, trabajo, bool(activos), flujo.es_historico(),
                          trabajo_nisar=trabajo_nisar))


SUBIR_AL_CAMBIAR_DE_PASO = """<script>
(() => {          // Al cambiar de paso, el panel vuelve arriba (antes quedaba a mitad de camino).
  const panel = document.querySelector('.st-key-panel_sar');
  if (!panel || panel.dataset.subir) return;
  panel.dataset.subir = '1';
  panel.addEventListener('click', (e) => {
    if (e.target.closest('[role="tab"]')) setTimeout(() => { panel.scrollTop = 0; }, 60);
  });
})();
</script>"""


def herramientas_sar() -> None:
    with st.container(key="panel_sar"):
        with st.container(horizontal=True, vertical_alignment="center", key="cabecera_sar"):
            st.markdown('<div class="mc-titulo-panel">Herramientas SAR</div>', unsafe_allow_html=True)
            st.button("Minimizar", key="minimizar_sar", icon=":material/remove:", type="tertiary",
                      on_click=minimizar_sar)
            st.button("Cerrar", key="cerrar_sar", icon=":material/close:", type="tertiary",
                      on_click=cerrar_sar)
        # La selección de fuente es una decisión del motor, no una pregunta
        # al visitante. No prometer Sentinel automático antes de tener su
        # pipeline OPERA integrado y científicamente validado.
        import os
        modo_legado = os.environ.get("VISOR_SENSOR_DEFECTO") == "SENTINEL"
        if modo_legado:
            st.caption("Sentinel-1 requiere RTC locales para el diagnóstico avanzado; no es un análisis automático.")
        else:
            st.caption("Selecciona el área y las fechas: V.I.S.O.R. gestiona la búsqueda NISAR "
                       "sin pedirte escoger satélite. Sentinel-1 automático sigue en validación.")
            v9_experiencia.render()
        herramientas.render(centrar_en, alternar_explorador, PASOS_SAR)
        st.html(SUBIR_AL_CAMBIAR_DE_PASO, unsafe_allow_javascript=True)
    with st.container(key="sar_minimizado"):
        st.button("Herramientas SAR · restaurar", key="restaurar_sar", icon=":material/open_in_full:",
                  on_click=abrir_sar)


def linea_temporal(fechas: list[str] | None = None) -> None:
    """Línea temporal de solo lectura. Con un resultado activo cuya ficha válida
    declara dos fechas, las muestra; nunca interpola ni sugiere estados intermedios."""
    if fechas:
        titulo = "LÍNEA TEMPORAL · FECHAS DEL RESULTADO ACTIVO"
        t1, t2 = f"T₁ · {escape(fechas[0])}", f"T₂ · {escape(fechas[1])}"
        nota = "Comparación de dos fechas. No hay observaciones intermedias en este producto."
        clase = " mc-linea-fechada"
    else:
        return          # sin resultado no hay fechas que mostrar: no ocupa sitio sobre el mapa
    with st.container(key="linea_temporal"):
        st.markdown(
            f'<div class="mc-linea{clase}" aria-disabled="true">'
            f'<div class="mc-linea-titulo">{titulo}</div>'
            f'<div class="mc-linea-pista"><span class="mc-linea-punto">{t1}</span>'
            f'<span class="mc-linea-barra"></span><span class="mc-linea-punto">{t2}</span></div>'
            f'<div class="mc-linea-nota">{nota}</div></div>',
            unsafe_allow_html=True,
        )
