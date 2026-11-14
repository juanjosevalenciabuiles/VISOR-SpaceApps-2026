"""Paso «05 · Regional» de Herramientas SAR: AOI configurable y cruce SAR × JRC por municipio.

1. Área: municipios oficiales (unión de los elegidos) o cualquier GeoJSON.
2. Cobertura: cuánto de cada municipio cubre la cuadrícula de la máscara SAR
   elegida y, si se pide, qué pasadas y pares de Sentinel-1 hay en el catálogo.
3. Cruce con agua histórica (JRC): solo si ya se reprodujo con los GeoTIFF
   reales el resultado de Chigorodó; tabla por municipio con denominadores y
   N/D donde no hay datos válidos.

Solo Sentinel-1 (banda C): las clases VV/VH no se aplican a NISAR.
Nada se descarga; los resultados nuevos van a data/analisis/ sin sobrescribir.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

import folium
import rasterio
import streamlit as st
from rasterio.warp import transform_bounds
from shapely.geometry import box

from utils import cobertura, regiones, resultados, sar_jrc
from utils.buscador_sar import ErrorBusqueda
from utils.combinacion_sar import TIPO_PRODUCTO

ORIGENES = ("Municipios oficiales", "GeoJSON propio")
MAX_MB_SUBIDA = 20


def _nota(texto: str, clase: str = "visor-leyenda-nota") -> None:
    st.markdown(f'<div class="{clase}">{escape(texto)}</div>', unsafe_allow_html=True)


def _nd(valor, sufijo: str = "", decimales: int = 1) -> str:
    return "N/D" if valor is None else f"{valor:,.{decimales}f}{sufijo}"


# ---------------------------------------------------------------------------
# AOI
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=4)
def _limites(ruta: str, firma: tuple) -> regiones.Limites:
    return regiones.cargar_limites(Path(ruta))


def _firma(ruta: Path) -> tuple:
    e = ruta.stat()
    return e.st_size, e.st_mtime_ns


def aoi_actual() -> tuple[regiones.AOI | None, str | None]:
    """El AOI elegido en el panel (o None y el motivo)."""
    origen = st.session_state.get("reg_origen", ORIGENES[0])
    try:
        if origen == ORIGENES[1]:
            subido = st.session_state.get("reg_geojson")
            if subido is None:
                return None, "Sube un GeoJSON en WGS84 con uno o varios polígonos."
            if subido.size > MAX_MB_SUBIDA * 2 ** 20:
                return None, f"El archivo supera {MAX_MB_SUBIDA} MB."
            return regiones.aoi_desde_geojson(subido.getvalue(), Path(subido.name).stem), None
        archivos = regiones.archivos_limites()
        if not archivos:
            return None, ("No hay límites oficiales en data/limites/. Copia ahí el GeoJSON de municipios de DANE "
                          "(MGN) o IGAC, o usa «GeoJSON propio». No se usan polígonos inventados.")
        limites = _limites(str(archivos[0]), _firma(archivos[0]))
        codigos = st.session_state.get("reg_municipios") or []
        if not codigos:
            return None, "Elige al menos un municipio."
        nombre = next((n for n, c in regiones.GRUPOS.items() if set(c) == set(codigos)), None)
        return limites.seleccionar(codigos, nombre), None
    except regiones.ErrorAOI as e:
        return None, str(e)


def _elegir_grupo() -> None:
    grupo = st.session_state.get("reg_grupo")
    if grupo in regiones.GRUPOS:
        disponibles = st.session_state.get("reg_disponibles", ())
        st.session_state["reg_municipios"] = [c for c in regiones.GRUPOS[grupo] if c in disponibles]


def _seccion_aoi(centrar) -> regiones.AOI | None:
    st.radio("Área de interés", ORIGENES, key="reg_origen", horizontal=True, label_visibility="collapsed")
    if st.session_state["reg_origen"] == ORIGENES[1]:
        st.file_uploader("GeoJSON (WGS84)", type=["geojson", "json"], key="reg_geojson",
                         help="Polygon o MultiPolygon. Cada Feature se trata como una zona para las estadísticas.")
    else:
        archivos = regiones.archivos_limites()
        if archivos:
            try:
                limites = _limites(str(archivos[0]), _firma(archivos[0]))
            except regiones.ErrorAOI as e:
                _nota(str(e), "mc-aviso")
                return None
            st.session_state["reg_disponibles"] = tuple(limites.zonas)
            opciones = sorted(limites.zonas, key=lambda c: limites.zonas[c].nombre)
            if "reg_municipios" not in st.session_state:
                st.session_state["reg_municipios"] = [c for c in regiones.PILOTO if c in limites.zonas]
            st.selectbox("Grupo", ["(selección propia)", *regiones.GRUPOS], key="reg_grupo", on_change=_elegir_grupo)
            st.multiselect("Municipios", opciones, key="reg_municipios",
                           format_func=lambda c: f"{limites.zonas[c].nombre} ({c})")
            _nota(f"Límites: {archivos[0].name} · SHA-256 {limites.sha256[:12]}…")
    aoi, motivo = aoi_actual()
    if aoi is None:
        _nota(motivo, "mc-aviso")
        return None
    _nota(f"AOI «{aoi.nombre}»: {len(aoi.zonas)} zona(s), {aoi.area_km2:,.0f} km². Se dibuja en amarillo. "
          "Un AOI no implica que haya escenas que lo cubran.")
    for a in aoi.avisos[:3]:
        _nota(a, "mc-aviso")
    c1, c2 = st.columns(2)
    c1.button("Centrar el mapa", key="reg_centrar", icon=":material/center_focus_strong:", type="tertiary",
              on_click=centrar, args=(aoi.limites,))
    if c2.button("Guardar AOI", key="reg_guardar", icon=":material/save:", type="tertiary"):
        st.session_state["reg_mensaje"] = f"AOI guardado: data/aoi/{aoi.guardar().name}"
    return aoi


def grupo_mapa() -> folium.FeatureGroup | None:
    """Contorno de cada zona del AOI regional (polígonos explícitos: viajan a las capas dinámicas)."""
    if st.session_state.get("ui_sar") != "abierto":
        return None
    aoi, _ = aoi_actual()
    if aoi is None:
        return None
    grupo = folium.FeatureGroup(name="AOI regional")
    for z in aoi.zonas:
        simple = z.geometria.simplify(0.0005, preserve_topology=True)      # ~50 m: solo para dibujar
        for pol in getattr(simple, "geoms", [simple]):
            folium.Polygon([[y, x] for x, y in pol.exterior.coords], color="#FFD60A", weight=1.6, fill=False,
                           tooltip=f"{z.nombre} · AOI regional").add_to(grupo)
    return grupo


# ---------------------------------------------------------------------------
# Cobertura
# ---------------------------------------------------------------------------

def _mascaras_vv_vh() -> list[resultados.ResultadoSAR]:
    return [r for r in resultados.cargar_resultados() if r.perfil is not None and r.perfil.clave == TIPO_PRODUCTO]


@st.cache_data(show_spinner=False, max_entries=16)
def _huella_cuadricula(ruta: str, firma: tuple) -> tuple[float, float, float, float]:
    with rasterio.open(ruta) as src:
        return transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)


def _seccion_cobertura(aoi: regiones.AOI, mascara: resultados.ResultadoSAR) -> None:
    huella = box(*_huella_cuadricula(str(mascara.ruta), _firma(mascara.ruta)))
    total = cobertura.fraccion(huella, aoi.geometria)
    filas = "".join(f"<tr><td>{escape(z.nombre)}</td><td>{cobertura.fraccion(huella, z.geometria):.0%}</td></tr>"
                    for z in aoi.zonas)
    st.markdown('<table class="mc-tabla"><thead><tr><th>Zona</th><th>Dentro de la cuadrícula SAR</th></tr></thead>'
                f"<tbody>{filas}<tr><td><b>AOI</b></td><td><b>{total:.0%}</b></td></tr></tbody></table>",
                unsafe_allow_html=True)
    if total < cobertura.COBERTURA_COMPLETA:
        _nota(f"La máscara elegida solo abarca el {total:.0%} del AOI. El resto es SIN DATO, no «sin cambio»: "
              "hacen falta escenas (o un mosaico) que lo cubran.", "mc-aviso")


def _seccion_catalogo(aoi: regiones.AOI) -> None:
    from components.herramientas_sar import _RespuestaGuardada, catalogo_simulado, periodo_actual
    with st.expander("Escenas Sentinel-1 del catálogo sobre el AOI (solo metadatos)"):
        periodo, error = periodo_actual()
        if error:
            _nota(error, "mc-aviso")
            return
        _nota(f"Período del paso 01: {periodo[0]:%Y-%m-%d} a {periodo[1]:%Y-%m-%d}. No se descarga nada.")
        if st.button("Buscar cobertura", key="reg_buscar", icon=":material/search:"):
            simulado = catalogo_simulado()
            abrir = (lambda *_a, **_k: _RespuestaGuardada(simulado.read_bytes())) if simulado else None
            try:
                _, c = cobertura.buscar(aoi, *periodo, abrir=abrir)
                st.session_state.update(reg_cobertura=(aoi.nombre, c), reg_error=None)
            except ErrorBusqueda as e:
                st.session_state.update(reg_cobertura=None, reg_error=str(e))
        if st.session_state.get("reg_error"):
            _nota(st.session_state["reg_error"], "mc-aviso")
        guardada = st.session_state.get("reg_cobertura")
        if not guardada or guardada[0] != aoi.nombre:
            return
        c = guardada[1]
        if catalogo_simulado():
            _nota("CATÁLOGO SIMULADO (pruebas automáticas): no es una consulta real.", "mc-aviso")
        _nota(f"{len(c.escenas)} escenas · {len(c.pasadas)} pasadas · {len(c.pares)} pares comparables (sin validar).")
        nombres = {z.codigo: z.nombre for z in aoi.zonas}
        for p in c.pares[:5]:
            zonas = ", ".join(f"{nombres[k]} {v:.0%}" for k, v in p.cobertura_zonas.items())
            _nota(f"{p.antes.inicio:%Y-%m-%d} → {p.despues.inicio:%Y-%m-%d} · órbita {p.antes.orbita_relativa} "
                  f"{'asc' if p.antes.direccion == 'ASCENDING' else 'desc'} · {len(p.antes.escenas)}+"
                  f"{len(p.despues.escenas)} cuadros · cubre {p.cobertura_comun:.0%} del AOI ({zonas})")
        for a in c.avisos:
            _nota(a, "mc-aviso")


# ---------------------------------------------------------------------------
# Cruce JRC
# ---------------------------------------------------------------------------

def _archivos_jrc() -> list[Path]:
    carpeta = sar_jrc.CARPETA_JRC
    return sorted([*carpeta.glob("*.tif"), *carpeta.glob("*.vrt")]) if carpeta.is_dir() else []


def tabla_html(datos: dict, umbral: int) -> str:
    """Tabla por zona para un umbral JRC. Cada tasa lleva su denominador; sin datos → N/D."""
    def fila(nombre: str, e: dict, negrita: bool = False) -> str:
        u = next(x for x in e["umbrales_jrc"] if x["umbral_ocurrencia_pct"] == umbral)
        pc = u["por_clase"]
        if e["sin_observaciones_validas"]:
            celdas = ["N/D"] * 5
        else:
            celdas = [f"{e['detecciones']:,}",
                      f"{_nd(u['pct_jrc_entre_detecciones'], ' %')}<br>{u['pixeles_sar_jrc']:,} / {u['denominador_detecciones']:,}",
                      *(f"{_nd(pc[k]['pct_dentro_clase'], ' %')}<br>{pc[k]['coincidentes']:,} / {pc[k]['total']:,}"
                        for k in ("solo_VV", "solo_VH", "VV_y_VH"))]
        cob = _nd(e.get("cobertura_cuadricula_pct"), " %", 0) if "cobertura_cuadricula_pct" in e else "—"
        n = f"<b>{escape(nombre)}</b>" if negrita else escape(nombre)
        return (f"<tr><td>{n}</td><td>{cob}<br>{_nd(e['cobertura_sar_valida_pct'], ' %', 0)} válido</td>"
                + "".join(f"<td>{c}</td>" for c in celdas) + "</tr>")
    filas = "".join(fila(e["nombre"], e) for e in datos["zonas"].values()) + fila("Total del AOI", datos["global"], True)
    return ('<table class="mc-tabla mc-tabla-regional"><thead><tr><th>Zona</th><th>Cobertura SAR</th><th>Detecciones</th>'
            f"<th>Sobre JRC ≥ {umbral} %</th><th>Solo VV</th><th>Solo VH</th><th>VV y VH</th></tr></thead>"
            f"<tbody>{filas}</tbody></table>")


def _seccion_jrc(aoi: regiones.AOI, mascara: resultados.ResultadoSAR, abrir_explorador) -> None:
    st.markdown('<div class="visor-seccion">Cruce con agua histórica (JRC 1984–2024)</div>', unsafe_allow_html=True)
    habilitado, motivo = sar_jrc.estado_habilitacion()
    _nota(motivo, "visor-leyenda-nota" if habilitado else "mc-aviso")
    jrc = _archivos_jrc()
    if not jrc:
        _nota("No hay JRC Occurrence en data/jrc/ (GeoTIFF original o VRT). La app no lo descarga.", "mc-aviso")
    else:
        st.selectbox("JRC Occurrence", [p.name for p in jrc], key="reg_jrc")
    if st.button("Cruzar con JRC por municipio", key="reg_cruzar", type="primary", icon=":material/water:",
                 disabled=not (habilitado and jrc)):
        try:
            with st.spinner("Cruzando por bloques…"):
                r = sar_jrc.cruzar(mascara.ruta, sar_jrc.CARPETA_JRC / st.session_state["reg_jrc"], aoi)
            st.session_state.update(reg_resultado=str(r.informe), reg_mensaje=(
                ("Resultado reutilizado (mismas entradas): " if r.desde_cache else "Generado en data/analisis/: ")
                + r.informe.name + ". Nada se sobrescribió."))
            st.rerun()          # el explorador (dibujado antes) debe listar las capas nuevas
        except (sar_jrc.ErrorJRC, regiones.ErrorAOI) as e:
            st.session_state["reg_mensaje"] = str(e)
    ruta = st.session_state.get("reg_resultado")
    if not ruta or not Path(ruta).is_file():
        return
    import json
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    umbral = st.segmented_control("Umbral de ocurrencia JRC", datos["configuracion"]["umbrales_jrc"],
                                  default=datos["configuracion"]["umbrales_jrc"][0], key="reg_umbral",
                                  format_func=lambda t: f"≥ {t} %") or datos["configuracion"]["umbrales_jrc"][0]
    st.markdown(tabla_html(datos, umbral), unsafe_allow_html=True)
    _nota("Porcentaje y, debajo, coincidentes / total de esa clase. N/D = sin observaciones válidas (no es 0 %). "
          f"{sar_jrc.ADVERTENCIA}")
    for a in datos["avisos"][:5]:
        _nota(a, "mc-aviso")
    csv = Path(ruta).parent / datos["salidas_tabla"]["csv"]
    if csv.is_file():
        st.download_button("Descargar CSV", csv.read_bytes(), file_name=csv.name, mime="text/csv", key="reg_csv",
                           icon=":material/download:", type="tertiary")
    st.button("Ver las capas y exportar para QGIS", key="reg_ir_explorador", icon=":material/layers:",
              type="tertiary", on_click=abrir_explorador)


def render(centrar, abrir_explorador) -> None:
    _nota("Sentinel-1 (banda C). Las clases VV/VH y sus umbrales no se aplican a NISAR.", "mc-aviso")
    aoi = _seccion_aoi(centrar)
    if st.session_state.get("reg_mensaje"):
        _nota(st.session_state["reg_mensaje"], "mc-aviso")
    if aoi is None:
        return
    mascaras = _mascaras_vv_vh()
    st.markdown('<div class="visor-seccion">Cobertura de la máscara SAR</div>', unsafe_allow_html=True)
    if not mascaras:
        _nota("No hay ninguna combinación VV/VH en data/analisis/ (pasos 02–03 o scripts/combinar_vv_vh.py).",
              "mc-aviso")
    else:
        nombres = {r.ruta.name: r for r in mascaras}
        mascara = nombres[st.selectbox("Máscara VV/VH (Sentinel-1)", list(nombres), key="reg_mascara")]
        _seccion_cobertura(aoi, mascara)
    _seccion_catalogo(aoi)
    if mascaras:
        _seccion_jrc(aoi, mascara, abrir_explorador)
