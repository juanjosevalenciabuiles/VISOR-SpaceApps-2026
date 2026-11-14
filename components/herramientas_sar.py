"""Contenido de Herramientas SAR: 01 Área · 02 Escenas · 03 Análisis · 04 Resultados.

- 01 define la ZONA: se dibuja en el mapa, se toma del área visible o (avanzado) se escribe o se
  carga. No hay zona hasta confirmarla, y confirmarla no busca ni analiza nada.
- 02 consulta el catálogo público de ASF (solo lectura), lista las imágenes y propone pares
  comparables SIN VALIDAR. Los pares ya analizados en esa zona se apartan (se pueden volver a ver).
- 03 muestra qué RTC de data/sar/ corresponden al par. «Analizar» es el ÚNICO disparador del motor;
  el resultado solo se publica en el mapa tras verificar sus salidas. No descarga ni usa HyP3.
- 04 resume el resultado activo.

Las acciones lentas (consulta, análisis) muestran un indicador de espera
sin porcentaje: no se inventa progreso.
"""
from __future__ import annotations

import os
from html import escape
from pathlib import Path

import folium
import streamlit as st

from components import flujo
from utils import buscador_sar as bus
from utils import flujo_sar, sesion
from utils.analisis_sar import ErrorSAR
from utils.resultados import id_resultado, leer_resultado

CAMPOS_AOI = (("sar_oeste", "Oeste", "-76.80"), ("sar_sur", "Sur", "7.55"), ("sar_este", "Este", "-76.55"),
              ("sar_norte", "Norte", "7.80"))
SIN_ZONA = "Primero define y confirma la zona en el paso 01."


def _nota(texto: str, clase: str = "visor-leyenda-nota") -> None:
    st.markdown(f'<div class="{clase}">{escape(texto)}</div>', unsafe_allow_html=True)


def region_actual() -> tuple[bus.Region | None, str | None]:
    """La zona CONFIRMADA. Sin confirmar no hay región: nada se busca ni se analiza."""
    zona = flujo.zona_confirmada()
    if zona is None:
        return None, SIN_ZONA
    try:
        return bus.validar_region(*zona), None
    except bus.ErrorBusqueda as e:
        return None, str(e)


def periodo_actual():
    inicio, fin = flujo.periodo_por_defecto()
    try:
        return bus.validar_fechas(st.session_state.get("sar_inicio", inicio),
                                  st.session_state.get("sar_fin", fin)), None
    except bus.ErrorBusqueda as e:
        return None, str(e)


def par_elegido() -> bus.ParEscenas | None:
    return flujo.par_actual()


def necesita_vista() -> bool:
    """El mapa solo informa de su encuadre mientras se elige «usar el área visible»."""
    return bool(st.session_state.get("zona_por_vista")) and st.session_state.get("ui_sar") != "cerrado"


def grupos_mapa() -> list[folium.FeatureGroup]:
    """Lo que el recorrido añade al mapa: marcador del lugar, zona confirmada y huellas de las
    imágenes de ENTRADA del par elegido. Ninguno es un resultado y así lo dice su rótulo."""
    grupo = folium.FeatureGroup(name="Recorrido · lugar, zona y huellas de entrada")
    hay = False
    lugar = st.session_state.get("lugar")
    if lugar:
        folium.CircleMarker([lugar["latitud"], lugar["longitud"]], radius=7, color="#ffffff", weight=2,
                            fill=True, fill_color="#0a84ff", fill_opacity=0.9,
                            tooltip=f"{lugar['etiqueta']} (lugar buscado; no es un resultado)").add_to(grupo)
        hay = True
    zona = st.session_state.get("zona")
    if zona:
        o, s, e, n = zona["limites"]
        folium.Rectangle([[s, o], [n, e]], color="#ffffff", weight=2, fill=False,
                         tooltip="Zona de análisis confirmada").add_to(grupo)
        geometria = zona.get("geometria") or {}
        if geometria.get("type") == "Polygon":
            folium.Polygon([[y, x] for x, y in geometria["coordinates"][0]], color="#ffd60a", weight=1.5,
                           fill=False, dash_array="4 4", tooltip="Polígono dibujado (se analiza su rectángulo "
                           "envolvente)").add_to(grupo)
        hay = True
        par = par_elegido()
        if par is not None:
            for escena, color in ((par.antes, "#8e8e93"), (par.despues, "#d1d1d6")):
                # Polígono con estilo explícito (style_function no viaja a las capas dinámicas de streamlit-folium).
                for pol in getattr(escena.huella, "geoms", [escena.huella]):
                    folium.Polygon([[y, x] for x, y in pol.exterior.coords], color=color, weight=1.5, fill=False,
                                   dash_array="2 6", tooltip=f"Huella de la imagen de entrada {escena.inicio:%Y-%m-%d}"
                                   f" · {escena.plataforma} (cobertura; no es un resultado)").add_to(grupo)
    return [grupo] if hay else []


# ---------------------------------------------------------------------------
# Paso 01 · Zona
# ---------------------------------------------------------------------------

def _confirmar(limites, origen: str, geometria: dict | None = None) -> None:
    try:
        flujo.confirmar_zona(limites, origen, geometria)
    except sesion.ErrorZona as e:
        st.session_state["error_zona"] = str(e)


def _confirmar_coordenadas() -> None:
    valores = [str(st.session_state.get(k, "")).strip().replace(",", ".") for k, _, _ in CAMPOS_AOI]
    if not all(valores):
        st.session_state["error_zona"] = "Escribe las cuatro coordenadas (oeste, sur, este y norte)."
        return
    _confirmar(valores, "coordenadas")


def _resumen(limites) -> str:
    ancho, alto = sesion.dimensiones_km(limites)
    return f"{ancho:.1f} × {alto:.1f} km · unos {sesion.pixeles_estimados(limites) / 1e6:.2f} millones de píxeles a 30 m"


def _candidata(limites, geometria, origen: str, clave: str, rotulo: str) -> None:
    """Muestra una zona candidata y su botón de confirmación, o por qué no sirve."""
    try:
        zona = sesion.validar_zona(limites)
    except sesion.ErrorZona as e:
        _nota(str(e), "mc-aviso")
        return
    _nota(f"{rotulo}: {_resumen(zona)}.")
    st.button("Usar esta zona", key=clave, icon=":material/check:", type="primary", on_click=_confirmar,
              args=(zona, origen, geometria))


def paso_area(centrar) -> None:
    zona = st.session_state.get("zona")
    if zona:
        st.markdown('<span class="mc-insignia mc-insignia-real" id="zona-confirmada">ZONA CONFIRMADA</span>',
                    unsafe_allow_html=True)
        o, s, e, n = zona["limites"]
        _nota(f"Origen: {zona['origen']}. Oeste {o:.4f} · sur {s:.4f} · este {e:.4f} · norte {n:.4f} (WGS84). "
              f"{_resumen(zona['limites'])}.")
        if (zona.get("geometria") or {}).get("type") == "Polygon":
            _nota("Dibujaste un polígono: el motor analiza su rectángulo envolvente (línea blanca).")
        with st.container(horizontal=True):
            st.button("Centrar el mapa en la zona", key="sar_centrar", icon=":material/center_focus_strong:",
                      type="tertiary", on_click=centrar, args=(zona["limites"],))
            st.button("Cambiar zona", key="zona_quitar", icon=":material/edit_location_alt:", type="tertiary",
                      on_click=flujo.quitar_zona,
                      help="Quita la zona confirmada. El resultado que dependía de ella se retira del mapa.")
    else:
        _nota("Aún no hay zona. Buscar un lugar solo mueve el mapa: la zona la defines tú aquí.", "mc-aviso")
    if st.session_state.get("error_zona"):
        _nota(st.session_state["error_zona"], "mc-aviso")

    st.caption("DIBUJAR SOBRE EL MAPA")
    _nota("Usa las herramientas ▭ (rectángulo) o ⬠ (polígono) del mapa, junto a los botones de zoom. "
          "Puedes editar o borrar el dibujo; no es una zona hasta que pulses «Usar esta zona».")
    dibujo = st.session_state.get("mapa_dibujo")
    if dibujo:
        try:
            limites, geometria = sesion.zona_de_geojson(dibujo)
        except sesion.ErrorZona as e:
            _nota(str(e), "mc-aviso")
        else:
            _candidata(limites, geometria, "dibujo en el mapa", "zona_usar_dibujo", "Dibujo actual")
    else:
        _nota("Todavía no has dibujado nada.")

    st.caption("O USAR LO QUE SE VE")
    if st.toggle("Usar el área visible del mapa", value=False, key="zona_por_vista",
                 help="Toma como zona el encuadre actual. Mientras está activo, el mapa informa de su encuadre "
                      "al moverlo."):
        vista = st.session_state.get("mapa_limites")
        if vista is None:
            _nota("Mueve o acerca el mapa para tomar su encuadre.")
        else:
            _candidata(vista, None, "área visible del mapa", "zona_usar_vista", "Área visible")

    st.caption("MUNICIPIO")
    _nota("Los límites municipales oficiales no están incluidos en esta versión. Busca el municipio por su "
          "nombre para ubicarlo y dibuja la zona: no se usa ningún límite aproximado en su lugar.")

    with st.expander("Avanzado: coordenadas o GeoJSON", expanded=False, key="zona_avanzado"):
        st.caption("RECUADRO EN GRADOS (WGS84)")
        for clave, rotulo, ejemplo in CAMPOS_AOI:
            st.text_input(rotulo, key=clave, placeholder=f"Ej.: {ejemplo}")
        st.button("Usar estas coordenadas", key="zona_usar_coordenadas", icon=":material/check:",
                  on_click=_confirmar_coordenadas)
        archivo = st.file_uploader("GeoJSON con un polígono (WGS84, longitud-latitud)", type=["geojson", "json"],
                                   key="zona_geojson")
        if archivo is not None:
            try:
                limites, geometria = sesion.zona_de_geojson(archivo.getvalue())
            except sesion.ErrorZona as e:
                _nota(str(e), "mc-aviso")
            else:
                _candidata(limites, geometria, f"GeoJSON {archivo.name}", "zona_usar_geojson", "GeoJSON")

    st.caption("PERÍODO DE BÚSQUEDA")
    inicio, fin = flujo.periodo_por_defecto()
    st.date_input("Desde", inicio, key="sar_inicio", format="YYYY-MM-DD")
    st.date_input("Hasta", fin, key="sar_fin", format="YYYY-MM-DD")
    st.date_input("Fecha de interés (opcional)", None, key="sar_evento", format="YYYY-MM-DD",
                  help="Si se indica, se prefieren pares que la encierren (antes < fecha ≤ después).")
    _, error_p = periodo_actual()
    if error_p:
        _nota(error_p, "mc-aviso")


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
    st.session_state.update(sar_busqueda=r, sar_error_busqueda=None, mc_informe_sar=None)
    # Par inicial: el primero que aún no se ha analizado en esta zona (si lo hay).
    pendientes = [i for i, par in enumerate(r.pares)
                  if not sesion.ejecuciones_del_par(_carpeta_analisis(), region.limites, par.antes.nombre,
                                                    par.despues.nombre)]
    st.session_state["sel_par"] = pendientes[0] if pendientes else None


def etiqueta_par(p: bus.ParEscenas) -> str:
    sat = p.antes.plataforma if p.misma_plataforma else f"{p.antes.plataforma}/{p.despues.plataforma}"
    return (f"{'★ ' if p.recomendado else ''}{p.antes.inicio:%Y-%m-%d} → {p.despues.inicio:%Y-%m-%d} · {sat} · "
            f"órb. {p.antes.orbita_relativa} {p.antes.direccion_es[:3].lower()}. · "
            f"{'+'.join(p.polarizaciones_comunes)} · {p.cobertura_comun:.0%}")


def _carpeta_analisis() -> Path:
    return flujo_sar.CARPETA_ANALISIS


def _ver_anterior(registro: dict) -> None:
    """Abre como HISTÓRICO el resultado de una ejecución anterior. No recalcula nada."""
    principal = sesion.resultado_principal(registro)
    if principal:
        flujo.activar(id_resultado(_carpeta_analisis() / principal), sesion.HISTORICO, registro.get("run_id"))


def _tabla_escenas(r, rtcs) -> str:
    filas = []
    for e in r.escenas:
        locales = sorted({x.polarizacion for x in rtcs if flujo_sar.coincidencia(x, e.plataforma, e.inicio)})
        estado = ("RTC local: " + "+".join(locales)) if locales else "sin RTC local"
        tamano = f"{e.tamano_bytes / 1e9:.1f} GB" if e.tamano_bytes else "—"
        filas.append(f"<tr><td>{e.inicio:%Y-%m-%d %H:%M}</td><td>{escape(e.plataforma)} · banda C</td>"
                     f"<td>{e.orbita_relativa} {e.direccion_es[:3].lower()}.</td><td>{'+'.join(e.polarizaciones)}</td>"
                     f"<td>{e.cobertura:.0%}</td><td>{escape(e.nivel)} · {tamano}</td><td>{estado}</td></tr>")
    return ('<table class="mc-tabla mc-tabla-rtc"><thead><tr><th>Fecha (UTC)</th><th>Satélite</th><th>Órbita</th>'
            "<th>Pol.</th><th>Cobertura de la zona</th><th>Producto</th><th>Datos de análisis</th></tr></thead>"
            f'<tbody>{"".join(filas)}</tbody></table>')


def _ampliar_periodo() -> None:
    from datetime import timedelta
    _, fin = periodo_actual()[0] or flujo.periodo_por_defecto()
    st.session_state["sar_inicio"] = fin - timedelta(days=180)
    _buscar()


def _elegir_par() -> None:
    elegido = st.session_state.get("sar_par")
    if isinstance(elegido, int):
        st.session_state["sel_par"] = elegido


def _fijar(polarizacion: str, clave: str, control: str) -> None:
    flujo.fijar_parametro(polarizacion, clave, st.session_state[control])


def paso_escenas() -> None:
    region, error = region_actual()
    if region is None:
        _nota(error, "mc-aviso")
        return
    _nota("Consulta de solo lectura al catálogo público de ASF (Sentinel-1 GRD, modo IW). "
          "No descarga imágenes, no usa credenciales y no analiza nada.")
    if catalogo_simulado():
        _nota(f"CATÁLOGO SIMULADO (pruebas automáticas): respuesta guardada {catalogo_simulado().name}, "
              "no una consulta real a ASF.", "mc-aviso")
    if st.button("Buscar imágenes SAR", key="sar_buscar", icon=":material/travel_explore:", type="primary"):
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
    if not r.escenas:
        st.markdown('<div class="mc-aviso" id="sin-escenas">No se encontraron escenas compatibles para esta zona y '
                    f"estas fechas ({r.inicio:%Y-%m-%d} → {r.fin:%Y-%m-%d}). El mapa sigue disponible para explorar; "
                    "no se muestra ningún resultado en su lugar.</div>", unsafe_allow_html=True)
        with st.container(horizontal=True):
            st.button("Ampliar el rango a 180 días", key="sar_ampliar", icon=":material/date_range:",
                      on_click=_ampliar_periodo, help="Busca de nuevo en los 180 días anteriores a la fecha final.")
        _nota("O cambia las fechas en el paso 01 · Área.")
        return
    rtcs, _ = flujo_sar.rtc_locales()
    with st.expander(f"Imágenes encontradas ({len(r.escenas)})", expanded=False, key="sar_escenas"):
        st.markdown(_tabla_escenas(r, rtcs), unsafe_allow_html=True)
        _nota("«Sin RTC local»: la imagen existe en el catálogo, pero sus datos de análisis todavía no están en "
              "data/sar/. No se descargan ni se procesan en HyP3 desde aquí.")
    if not r.pares:
        _nota("No hay dos fechas comparables (misma órbita relativa y dirección, polarización común, "
              "cobertura ≥ 50 %). Amplía el período en el paso 01.", "mc-aviso")
        return
    # «Ya analizado» = este par, sobre ESTA zona, con una ejecución correcta cuyas salidas existen.
    previas = {i: sesion.ejecuciones_del_par(_carpeta_analisis(), region.limites, p.antes.nombre, p.despues.nombre)
               for i, p in enumerate(r.pares)}
    usados = [i for i in previas if previas[i]]
    mostrar = st.toggle(f"Mostrar pares ya analizados ({len(usados)})", value=False, key="sar_mostrar_usados",
                        disabled=not usados, help="Pares que ya tienen un resultado guardado para esta zona.")
    # El par ya elegido sigue disponible aunque acabe de analizarse: apartarlo cambiaría la selección
    # (y con ella retiraría el resultado recién calculado) sin que nadie lo pidiera.
    actual = st.session_state.get("sel_par")
    opciones = [i for i in previas if mostrar or not previas[i] or i == actual]
    _nota(f"{len(r.pares) - len(usados)} por analizar · {len(usados)} ya analizados en esta zona.")
    if not opciones:
        st.session_state["sel_par"] = None
        _nota("Todos los pares comparables ya se analizaron en esta zona. Activa «Mostrar pares ya analizados» "
              "para abrir su resultado o reanalizarlos.", "mc-aviso")
        return
    if actual not in opciones:
        actual = st.session_state["sel_par"] = opciones[0]
    st.session_state["sar_par"] = actual        # el selector refleja la elección guardada, no al revés
    st.selectbox("Par antes / después", opciones, key="sar_par", on_change=_elegir_par,
                 format_func=lambda i: ("✓ " if previas[i] else "") + etiqueta_par(r.pares[i]))
    p = par_elegido()
    st.markdown(
        f'<span class="mc-insignia mc-insignia-tenue">{escape(p.estado.upper())}</span>'
        '<ul class="visor-lista">' + "".join(f"<li>{escape(m)}</li>" for m in p.motivos) + "</ul>"
        + "".join(f'<div class="visor-aviso">{escape(a)}</div>' for a in p.avisos),
        unsafe_allow_html=True,
    )
    _nota(f"Antes: {p.antes.nombre} · Después: {p.despues.nombre}")
    anteriores = previas[actual]
    if anteriores:
        _nota(f"Este par ya se analizó en esta zona ({len(anteriores)} vez/veces; la última el "
              f"{str(anteriores[0].get('generado_utc', '?'))[:16].replace('T', ' ')} UTC).")
        st.button("Ver resultado anterior", key="sar_ver_anterior", icon=":material/history:",
                  on_click=_ver_anterior, args=(anteriores[0],),
                  help="Lo abre rotulado como HISTÓRICO. No ejecuta un análisis nuevo.")
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


def _pedir_analisis() -> None:
    """Callback de «Analizar»: único disparador de un cálculo nuevo. Cada pulsación se consume una
    sola vez; mover la opacidad, el fondo o cualquier otro control nunca vuelve a calcular."""
    st.session_state["sar_lanzar"] = {"reanalizar": bool(st.session_state.get("sar_reanalizar"))}
    st.session_state["sar_reanalizar"] = False


def verificar_salida(informe: flujo_sar.InformeFlujo, identificador: str) -> Path:
    """La ejecución solo se publica en el mapa si sus salidas existen, se leen, tienen píxeles
    válidos y su registro corresponde a ESTA ejecución. Si algo falla, ErrorSAR: no se muestra nada."""
    import json
    principal = informe.combinado or next(iter(informe.analisis.values()), None)
    if principal is None or not Path(principal).is_file():
        raise ErrorSAR("El análisis terminó sin producir un archivo de resultado.")
    res = leer_resultado(principal)
    if not res.dibujable:
        raise ErrorSAR(f"El resultado se generó pero no se puede leer: {res.error or 'formato no reconocido'}.")
    if not (res.estadisticas or {}).get("pixeles_validos"):
        raise ErrorSAR("El resultado no tiene ningún píxel válido en esta zona (las imágenes no la cubren).")
    try:
        registro = json.loads(Path(informe.registro).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raise ErrorSAR("El análisis no dejó un registro de procedencia legible.") from None
    if registro.get("run_id") != identificador or Path(principal).name not in (registro.get("salidas") or []):
        raise ErrorSAR("El registro de la ejecución no corresponde a la zona, el par y los parámetros elegidos.")
    return Path(principal)


def paso_analisis() -> None:
    lanzar = st.session_state.pop("sar_lanzar", None)      # se consume siempre: nunca queda pendiente
    region, error = region_actual()
    if region is None:
        _nota(error, "mc-aviso")
        return
    p = par_elegido()
    if p is None:
        _nota("Primero busca imágenes y elige dos fechas en el paso 02.", "mc-aviso")
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
        _nota("Imágenes encontradas, pero sus datos de análisis todavía no están disponibles aquí: faltan los "
              "productos RTC de este par en data/sar/. El catálogo entrega escenas GRD; convertirlas a RTC "
              "requiere ASF HyP3 con una cuenta de Earthdata (solo con autorización expresa). No se calcula "
              "ni se muestra nada en su lugar.", "mc-aviso")
        st.button("Analizar", key="sar_analizar", type="primary", icon=":material/play_arrow:", disabled=True,
                  help="Bloqueado: faltan los productos RTC de este par.")
        return
    _nota("Método: diferencia de retrodispersión (dB) entre las dos fechas, posterior − anterior, con un umbral "
          "de disminución por polarización. Los umbrales son experimentales.")
    for d in completas:
        st.slider(f"Umbral de disminución {d.polarizacion} (dB)", 1.0, 10.0, flujo.UMBRAL_DEFECTO, 0.5,
                  key=f"sar_umbral_{d.polarizacion}", on_change=_fijar,
                  args=(d.polarizacion, "umbral_disminucion_db", f"sar_umbral_{d.polarizacion}"))
        st.select_slider(f"Filtro de speckle {d.polarizacion} (ventana en píxeles)", [1, 3, 5, 7],
                         flujo.VENTANA_DEFECTO, key=f"sar_ventana_{d.polarizacion}", on_change=_fijar,
                         args=(d.polarizacion, "ventana_speckle", f"sar_ventana_{d.polarizacion}"))
    pols = [d.polarizacion for d in completas]
    parametros = flujo.parametros_actuales(pols)
    identificador = sesion.run_id(region.limites, p.antes.nombre, p.despues.nombre, parametros)
    previa = sesion.ejecucion_con_id(_carpeta_analisis(), identificador)
    por_dia = [d.polarizacion for d in completas if d.verificar]
    aceptar = False
    if por_dia:
        aceptar = st.checkbox(
            f"Acepto analizar {', '.join(por_dia)} con RTC que solo coinciden en el día (asociación NO confirmada)",
            value=False, key="sar_aceptar_mismo_dia",
            help="El RTC es del mismo satélite y día, pero no de la misma hora de adquisición: podría venir de "
                 "otra escena. Quedará registrado como asociación no confirmada.")
    reanalizar = False
    if previa:
        _nota(f"Esta misma configuración (zona, fechas y parámetros) ya se analizó el "
              f"{str(previa.get('generado_utc', '?'))[:16].replace('T', ' ')} UTC. No se repite sola.")
        st.button("Ver resultado anterior", key="sar_ver_mismo", icon=":material/history:",
                  on_click=_ver_anterior, args=(previa,),
                  help="Lo abre rotulado como HISTÓRICO. No ejecuta un análisis nuevo.")
        reanalizar = st.checkbox("Reanalizar de todos modos (crea archivos nuevos; no sobrescribe)", value=False,
                                 key="sar_reanalizar")
    bloqueado = (bool(por_dia) and not aceptar) or (previa is not None and not reanalizar)
    st.button("Analizar", key="sar_analizar", type="primary", icon=":material/play_arrow:", disabled=bloqueado,
              on_click=_pedir_analisis)
    # Solo una pulsación de «Analizar» en esta misma ejecución deja `lanzar` con contenido.
    permitido = (isinstance(lanzar, dict) and not (bool(por_dia) and not aceptar)
                 and (previa is None or lanzar.get("reanalizar")))
    if permitido:
        # Mientras se calcula no hay resultado en el mapa: si falla, no queda el anterior como si fuera nuevo.
        flujo.limpiar_resultado()
        with st.spinner("Procesando: lectura de los RTC, diferencia en dB, máscaras y verificación de las "
                        "salidas… (sin porcentaje: depende del tamaño de la zona)"):
            try:
                inf = flujo_sar.analizar_disponibles(
                    p, disp, region.limites, {pol: parametros[pol]["umbral_disminucion_db"] for pol in pols},
                    {pol: parametros[pol]["ventana_speckle"] for pol in pols}, aceptar_mismo_dia=aceptar)
                principal = verificar_salida(inf, identificador)
            except (ErrorSAR, OSError) as e:
                st.session_state.update(mc_informe_sar={"error": str(e), "par": _clave_par(p)})
            else:
                st.session_state.update(mc_informe_sar={
                    "archivos": [x.name for x in inf.archivos], "registro": inf.registro.name,
                    "avisos": inf.avisos, "par": _clave_par(p), "run_id": identificador,
                    "principal": principal.name})
                flujo.activar(id_resultado(principal), sesion.ANALISIS, identificador)
        st.rerun()   # el explorador y el mapa (dibujados antes) deben reflejar el desenlace
    inf = _informe_del_par(p)
    if inf and inf.get("error"):
        _nota("El análisis no terminó: " + inf["error"] + " No se muestra ningún resultado. Corrige lo indicado "
              "y vuelve a pulsar «Analizar».", "mc-aviso")
    elif inf:
        _nota(f"Listo: {len(inf['archivos'])} archivos nuevos. El resultado está en el mapa (paso 04).")


def paso_resultados(abrir_explorador) -> None:
    activo = st.session_state.get("resultado_activo")
    inf = _informe_del_par(par_elegido())
    if not activo:
        _nota("No hay ningún resultado en el mapa. Aparece al terminar un análisis (paso 03) o al abrir uno "
              "del historial en el Explorador.")
    elif activo["origen"] == sesion.HISTORICO:
        _nota("En el mapa hay un resultado HISTÓRICO, abierto a propósito. No corresponde a un análisis nuevo.")
    elif inf and not inf.get("error"):
        st.markdown('<span class="mc-insignia mc-insignia-origen">ANÁLISIS DE ESTA SESIÓN</span>'
                    f'<div class="visor-leyenda-nota">En el mapa: <code>{escape(inf["principal"])}</code> · '
                    f'ejecución <code>{escape(inf["run_id"])}</code></div>'
                    '<div class="visor-seccion">Generados en data/analisis/</div><ul class="visor-lista">'
                    + "".join(f"<li><code>{escape(n)}</code></li>" for n in inf["archivos"])
                    + f'</ul><div class="visor-leyenda-nota">Registro: <code>{escape(inf["registro"])}</code>. '
                    "Ningún archivo existente se sobrescribió.</div>", unsafe_allow_html=True)
        for a in inf["avisos"][:6]:
            _nota(a)
    if activo:
        st.button("Limpiar resultado", key="sar_limpiar", icon=":material/layers_clear:",
                  on_click=flujo.limpiar_resultado, help="Lo quita del mapa. No borra ningún archivo.")
    _nota("Indicios de cambio en la señal de radar: no confirman inundaciones. La ficha, la leyenda y la "
          "exportación a QGIS del resultado activo están en el panel Información.")
    st.button("Abrir el explorador", key="sar_ir_explorador", icon=":material/layers:", type="tertiary",
              on_click=abrir_explorador)


def render(centrar, abrir_explorador, pasos) -> None:
    area, escenas, analisis, resultados = st.tabs(list(pasos), key="sar_paso")
    with area:
        paso_area(centrar)
    with escenas:
        paso_escenas()
    with analisis:
        paso_analisis()
    with resultados:
        paso_resultados(abrir_explorador)
