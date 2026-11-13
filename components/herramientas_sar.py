"""Contenido de Herramientas SAR: 01 Área · 02 Escenas · 03 Análisis · 04 Resultados.

- 01 valida el AOI y el período (mismas reglas que el buscador).
- 02 consulta el catálogo público de ASF (solo lectura) y recomienda un par
  compatible SIN VALIDAR; la persona puede elegir otro.
- 03 muestra qué RTC de data/sar/ corresponden al par y corre el motor con
  los umbrales de cada polarización. No descarga ni procesa en HyP3.
- 04 lista lo producido; los resultados se activan en el explorador.

Las acciones lentas (consulta, análisis) muestran un indicador de espera
sin porcentaje: no se inventa progreso.
"""
from __future__ import annotations

import os
from datetime import date
from html import escape
from pathlib import Path

import folium
import streamlit as st

from utils import buscador_sar as bus
from utils import flujo_sar
from utils.analisis_sar import ErrorSAR
from utils.config import AOI_CHIGORODO

INICIO_DEFECTO, FIN_DEFECTO = date(2026, 9, 20), date(2026, 10, 10)
CAMPOS_AOI = (("sar_oeste", "Oeste"), ("sar_sur", "Sur"), ("sar_este", "Este"), ("sar_norte", "Norte"))


def _nota(texto: str, clase: str = "visor-leyenda-nota") -> None:
    st.markdown(f'<div class="{clase}">{escape(texto)}</div>', unsafe_allow_html=True)


def region_actual() -> tuple[bus.Region | None, str | None]:
    """AOI escrita en el paso 01 (o la de Chigorodó si aún no se tocó)."""
    valores = [st.session_state.get(k, f"{v:.4f}") for (k, _), v in zip(CAMPOS_AOI, AOI_CHIGORODO, strict=True)]
    try:
        return bus.validar_region(*[str(v).replace(",", ".") for v in valores]), None
    except bus.ErrorBusqueda as e:
        return None, str(e)


def periodo_actual() -> tuple[tuple[date, date] | None, str | None]:
    try:
        return bus.validar_fechas(st.session_state.get("sar_inicio", INICIO_DEFECTO),
                                  st.session_state.get("sar_fin", FIN_DEFECTO)), None
    except bus.ErrorBusqueda as e:
        return None, str(e)


def par_elegido() -> bus.ParEscenas | None:
    busqueda = st.session_state.get("sar_busqueda")
    if busqueda is None or not busqueda.pares:
        return None
    i = st.session_state.get("sar_par", 0)
    return busqueda.pares[i] if isinstance(i, int) and 0 <= i < len(busqueda.pares) else busqueda.pares[0]


def grupos_mapa() -> list[folium.FeatureGroup]:
    """AOI y huellas del par elegido sobre el mapa principal, solo con el panel SAR abierto."""
    if st.session_state.get("ui_sar") != "abierto":
        return []
    from components import regional as panel_regional
    regional = [g for g in (panel_regional.grupo_mapa(),) if g is not None]
    region, _ = region_actual()
    if region is None:
        return regional
    grupo = folium.FeatureGroup(name="Herramientas SAR · AOI y par")
    o, s, e, n = region.oeste, region.sur, region.este, region.norte
    folium.Rectangle([[s, o], [n, e]], color="#ffffff", weight=2, dash_array="6 6", fill=False,
                     tooltip="AOI de Herramientas SAR").add_to(grupo)
    par = par_elegido()
    if par is not None:
        for escena, color in ((par.antes, "#8e8e93"), (par.despues, "#d1d1d6")):
            # Polígono con estilo explícito (style_function no viaja a las capas dinámicas de streamlit-folium).
            poligonos = getattr(escena.huella, "geoms", [escena.huella])
            for pol in poligonos:
                folium.Polygon([[y, x] for x, y in pol.exterior.coords], color=color, weight=1.5, fill=False,
                               dash_array="2 6", tooltip=f"Huella {escena.inicio:%Y-%m-%d} · {escena.plataforma}"
                               ).add_to(grupo)
    return [grupo, *regional]


# ---------------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------------

def paso_area(centrar) -> None:
    st.caption("ÁREA DE INTERÉS (GRADOS, WGS84)")
    for clave, rotulo in CAMPOS_AOI:
        valor = AOI_CHIGORODO[[c for c, _ in CAMPOS_AOI].index(clave)]
        st.text_input(rotulo, f"{valor:.4f}", key=clave)
    st.caption("PERÍODO DE BÚSQUEDA")
    st.date_input("Desde", INICIO_DEFECTO, key="sar_inicio", format="YYYY-MM-DD")
    st.date_input("Hasta", FIN_DEFECTO, key="sar_fin", format="YYYY-MM-DD")
    st.date_input("Fecha de interés (opcional)", None, key="sar_evento", format="YYYY-MM-DD",
                  help="Si se indica, se prefieren pares que la encierren (antes < fecha ≤ después).")
    region, error = region_actual()
    periodo, error_p = periodo_actual()
    if error or error_p:
        _nota(error or error_p, "mc-aviso")
        return
    import math
    alto_km = (region.norte - region.sur) * 111.32
    ancho_km = (region.este - region.oeste) * 111.32 * math.cos(math.radians((region.norte + region.sur) / 2))
    _nota(f"AOI de {ancho_km:.1f} × {alto_km:.1f} km · {(periodo[1] - periodo[0]).days + 1} días. "
          "Se dibuja con línea discontinua blanca mientras este panel está abierto.")
    st.button("Centrar el mapa en el AOI", key="sar_centrar", icon=":material/center_focus_strong:",
              type="tertiary", on_click=centrar, args=((region.oeste, region.sur, region.este, region.norte),))


def catalogo_simulado() -> Path | None:
    """Solo pruebas automáticas: VISOR_ASF_SIMULADO apunta a una respuesta de ASF guardada.
    Cuando está activa, el paso 02 lo dice en pantalla: nunca pasa por una consulta real."""
    ruta = os.environ.get("VISOR_ASF_SIMULADO")
    return Path(ruta) if ruta else None


class _RespuestaGuardada:
    def __init__(self, cuerpo: bytes):
        self.cuerpo = cuerpo

    def read(self) -> bytes:
        return self.cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _buscar() -> None:
    region, error = region_actual()
    periodo, error_p = periodo_actual()
    if error or error_p:
        st.session_state.update(sar_busqueda=None, sar_error_busqueda=error or error_p)
        return
    simulado = catalogo_simulado()
    abrir = (lambda *_a, **_k: _RespuestaGuardada(simulado.read_bytes())) if simulado else None
    try:
        r = bus.buscar(region.oeste, region.sur, region.este, region.norte, *periodo,
                       fecha_evento=st.session_state.get("sar_evento"), abrir=abrir)
    except bus.ErrorBusqueda as e:
        st.session_state.update(sar_busqueda=None, sar_error_busqueda=str(e))
        return
    st.session_state.update(sar_busqueda=r, sar_error_busqueda=None, sar_par=0, mc_informe_sar=None)


def etiqueta_par(p: bus.ParEscenas) -> str:
    sat = p.antes.plataforma if p.misma_plataforma else f"{p.antes.plataforma}/{p.despues.plataforma}"
    return (f"{'★ ' if p.recomendado else ''}{p.antes.inicio:%Y-%m-%d} → {p.despues.inicio:%Y-%m-%d} · {sat} · "
            f"órb. {p.antes.orbita_relativa} {p.antes.direccion_es[:3].lower()}. · "
            f"{'+'.join(p.polarizaciones_comunes)} · {p.cobertura_comun:.0%}")


def paso_escenas() -> None:
    _nota("Consulta de solo lectura al catálogo público de ASF (Sentinel-1 GRD, modo IW). "
          "No descarga imágenes ni usa credenciales.")
    if catalogo_simulado():
        _nota(f"CATÁLOGO SIMULADO (pruebas automáticas): respuesta guardada {catalogo_simulado().name}, "
              "no una consulta real a ASF.", "mc-aviso")
    if st.button("Buscar escenas en ASF", key="sar_buscar", icon=":material/travel_explore:", type="primary"):
        with st.spinner("Consultando ASF… (hasta 30 s)"):
            _buscar()
        if st.session_state.get("sar_busqueda") is not None:
            st.rerun()   # el mapa (dibujado antes) debe mostrar las huellas del par
    if st.session_state.get("sar_error_busqueda"):
        _nota(st.session_state["sar_error_busqueda"], "mc-aviso")
    r = st.session_state.get("sar_busqueda")
    if r is None:
        return
    _nota(f"{len(r.escenas)} escenas · {len(r.pares)} pares compatibles · {r.recibidos} productos recibidos"
          + (" · ASF devolvió el máximo pedido: puede haber más; acota el período." if r.truncado else ""))
    if not r.pares:
        _nota("No hay pares compatibles (misma órbita relativa y dirección, polarización común, cobertura ≥ 50 %).",
              "mc-aviso")
        return
    st.selectbox("Par antes / después", range(len(r.pares)), key="sar_par",
                 format_func=lambda i: etiqueta_par(r.pares[i]))
    p = par_elegido()
    st.markdown(
        f'<span class="mc-insignia mc-insignia-tenue">{escape(p.estado.upper())}</span>'
        '<ul class="visor-lista">' + "".join(f"<li>{escape(m)}</li>" for m in p.motivos) + "</ul>"
        + "".join(f'<div class="visor-aviso">{escape(a)}</div>' for a in p.avisos),
        unsafe_allow_html=True,
    )
    _nota(f"Antes: {p.antes.nombre} · Después: {p.despues.nombre}")
    st.link_button("Ver el par en ASF Vertex", p.enlace_vertex, icon=":material/open_in_new:", type="tertiary")


def _celda_rtc(e, tipo, empatados) -> str:
    if tipo == flujo_sar.AMBIGUA:
        return f'<span class="mc-falta">ambiguo: {len(empatados)} candidatos</span>'
    if e is None:
        return '<span class="mc-falta">falta</span>'
    marca = "" if tipo == flujo_sar.EXACTA else ' <span class="mc-falta">(solo mismo día: no confirmada)</span>'
    return f"<code>{escape(e.ruta.name)}</code>{marca}"


def _clave_par(p) -> str | None:
    return None if p is None else f"{p.antes.nombre}|{p.despues.nombre}"


def _informe_del_par(p) -> dict | None:
    """El informe del último análisis, solo si corresponde al par elegido ahora."""
    inf = st.session_state.get("mc_informe_sar")
    return inf if isinstance(inf, dict) and inf.get("par") == _clave_par(p) else None


def paso_analisis() -> None:
    p = par_elegido()
    if p is None:
        _nota("Primero busca escenas y elige un par en el paso 02.")
        return
    rtcs, avisos = flujo_sar.rtc_locales()
    disp = flujo_sar.disponibilidad(p, rtcs)
    filas = [f"<tr><td>{d.polarizacion}</td><td>{_celda_rtc(d.antes, d.tipo_antes, d.empatados_antes)}</td>"
             f"<td>{_celda_rtc(d.despues, d.tipo_despues, d.empatados_despues)}</td></tr>" for d in disp]
    st.markdown('<div class="visor-seccion">Productos RTC en data/sar/</div>'
                '<table class="mc-tabla mc-tabla-rtc"><thead><tr><th>Pol.</th><th>Antes</th><th>Después</th>'
                f'</tr></thead><tbody>{"".join(filas)}</tbody></table>', unsafe_allow_html=True)
    for a in avisos[:4]:
        _nota(a)
    for d in disp:
        for fecha, empatados in (("antes", d.empatados_antes), ("después", d.empatados_despues)):
            if empatados:
                _nota(f"{d.polarizacion} {fecha}: {len(empatados)} RTC empatan para la misma escena "
                      f"({', '.join(empatados)}). Deja solo el correcto en data/sar/.", "mc-aviso")
    completas = [d for d in disp if d.completa]
    if not completas:
        _nota("Faltan productos RTC para este par. El catálogo entrega escenas GRD; convertirlas a RTC requiere "
              "ASF HyP3 con una cuenta de Earthdata (Fase D, solo con autorización expresa). Mientras tanto, "
              "copia los RTC ya procesados a data/sar/.", "mc-aviso")
        return
    _nota("Método: diferencia de retrodispersión (dB) entre las dos fechas, con umbral de disminución por "
          "polarización. Es el único método del motor.")
    for d in completas:
        st.slider(f"Umbral de disminución {d.polarizacion} (dB)", 1.0, 10.0, 3.0, 0.5,
                  key=f"sar_umbral_{d.polarizacion}")
    st.select_slider("Filtro de speckle (ventana en píxeles)", [1, 3, 5, 7], 5, key="sar_ventana")
    region, error = region_actual()
    if error:
        _nota(error, "mc-aviso")
        return
    por_dia = [d.polarizacion for d in completas if d.verificar]
    aceptar = False
    if por_dia:
        aceptar = st.checkbox(
            f"Acepto analizar {', '.join(por_dia)} con RTC que solo coinciden en el día (asociación NO confirmada)",
            value=False, key="sar_aceptar_mismo_dia",
            help="El RTC es del mismo satélite y día, pero no de la misma hora de adquisición: podría venir de "
                 "otra escena. Quedará registrado como asociación no confirmada.")
    if st.button("Analizar RTC disponibles", key="sar_analizar", type="primary", icon=":material/play_arrow:",
                 disabled=bool(por_dia) and not aceptar):
        with st.spinner("Analizando con el motor SAR… (sin porcentaje: depende del tamaño del AOI)"):
            try:
                inf = flujo_sar.analizar_disponibles(
                    p, disp, (region.oeste, region.sur, region.este, region.norte),
                    {d.polarizacion: st.session_state[f"sar_umbral_{d.polarizacion}"] for d in completas},
                    st.session_state["sar_ventana"], aceptar_mismo_dia=aceptar)
            except ErrorSAR as e:
                st.session_state.update(mc_informe_sar={"error": str(e), "par": _clave_par(p)})
            else:
                st.session_state.update(mc_informe_sar={"archivos": [x.name for x in inf.archivos],
                                                     "registro": inf.registro.name, "avisos": inf.avisos,
                                                     "par": _clave_par(p)})
                st.rerun()   # el explorador (dibujado antes) debe listar los resultados nuevos
    inf = _informe_del_par(p)
    if inf and inf.get("error"):
        _nota(inf["error"], "mc-aviso")
    elif inf:
        _nota(f"Listo: {len(inf['archivos'])} resultados nuevos. Ver el paso 04.")


def paso_resultados(abrir_explorador) -> None:
    inf = _informe_del_par(par_elegido())
    if not inf or inf.get("error"):
        _nota("Aún no hay resultados de este panel. Los resultados existentes de data/analisis/ se activan "
              "en Explorador → Resultados SAR.")
    else:
        st.markdown('<div class="visor-seccion">Generados en data/analisis/</div><ul class="visor-lista">'
                    + "".join(f"<li><code>{escape(n)}</code></li>" for n in inf["archivos"])
                    + f'</ul><div class="visor-leyenda-nota">Registro: <code>{escape(inf["registro"])}</code>. '
                    "Ningún archivo existente se sobrescribió.</div>", unsafe_allow_html=True)
        for a in inf["avisos"][:6]:
            _nota(a)
    _nota("Indicios de cambio en la señal de radar: no confirman inundaciones. Se muestran con su insignia de "
          "procedencia y se exportan para QGIS desde su ficha.")
    st.button("Abrir el explorador", key="sar_ir_explorador", icon=":material/layers:", type="tertiary",
              on_click=abrir_explorador)


def render(centrar, abrir_explorador, pasos) -> None:
    area, escenas, analisis, resultados, regional = st.tabs(list(pasos), key="sar_paso")
    with regional:
        from components import regional as panel_regional
        panel_regional.render(centrar, abrir_explorador)
    with area:
        paso_area(centrar)
    with escenas:
        paso_escenas()
    with analisis:
        paso_analisis()
    with resultados:
        paso_resultados(abrir_explorador)
