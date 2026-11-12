"""Página de análisis temporal SAR.

Elige dos GeoTIFF RTC locales (antes / después), ejecuta el motor de
utils/analisis_sar.py y muestra la capa resultante. No descarga datos ni usa
HyP3: solo lee archivos que ya están en data/sar/.
"""
import json
import os
import sys
from html import escape
from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from components import estilos, leyenda, mapa  # noqa: E402
from utils import analisis_sar as sar  # noqa: E402
from utils.config import DATA_DIR, Fenomeno  # noqa: E402
from utils.geotiff import ErrorCapa, cargar_capa  # noqa: E402
from utils.mapas_base import MAPA_BASE_PREDETERMINADO, MAPAS_BASE, obtener  # noqa: E402

SAR_DIR = Path(os.environ.get("VISOR_SAR_DIR", DATA_DIR / "sar"))
ANALISIS_DIR = Path(os.environ.get("VISOR_ANALISIS_DIR", DATA_DIR / "analisis"))
ACENTO = "#00F0FF"

# Recuadros de partida (oeste, sur, este, norte). Son aproximados: sirven para
# no cargar la escena completa, no son límites oficiales.
AOIS = {
    "Chigorodó y alrededores (aproximado)": (-76.80, 7.55, -76.55, 7.80),
    "Recuadro personalizado": None,
    "Toda la zona común (puede ser muy grande)": None,
}

st.set_page_config(page_title="V.I.S.O.R. · Análisis SAR", page_icon="🛰️", layout="wide")
estilos.inyectar_css(ACENTO)


def perfil_diferencia(rango: float) -> Fenomeno:
    return Fenomeno(
        clave="sar_dif", nombre="Cambio de retrodispersión", icono="📉", archivo="-",
        descripcion="", producto="Cambio de retrodispersión (posterior − anterior)", advertencias=(),
        tipo_valores="continuo", unidades="dB", colores=("#00B7FF", "#1C1C1E", "#FF9F0A"),
        vmin=-rango, vmax=rango, transparencia="nodata",
        leyenda_min="La señal disminuyó", leyenda_max="La señal aumentó",
    )


PERFIL_MASCARA = Fenomeno(
    clave="sar_mascara", nombre="Cambios SAR significativos", icono="🧭", archivo="-",
    descripcion="", producto="Cambios SAR significativos (indicios, sin validar)", advertencias=(),
    tipo_valores="categorico", unidades="clase", clases=sar.CLASES_MASCARA, colores=("#1C1C1E", ACENTO),
)


def escenas_disponibles() -> tuple[list[sar.EscenaRTC], list[str]]:
    """GeoTIFF analizables en data/sar/ y los que se omiten (DEM, mapas auxiliares, etc.)."""
    utiles, omitidos = [], []
    if SAR_DIR.is_dir():
        for ruta in sorted(p for p in SAR_DIR.rglob("*") if p.suffix.lower() in (".tif", ".tiff")):
            try:
                utiles.append(sar.describir_escena(ruta))
            except sar.ErrorSAR:
                omitidos.append(ruta.name)
    return utiles, omitidos


def etiqueta(e: sar.EscenaRTC) -> str:
    fecha = f"{e.fecha:%Y-%m-%d}" if e.fecha else "sin fecha"
    return f"{fecha} · {e.polarizacion} · {e.plataforma or 'satélite sin identificar'} · {e.ruta.name}"


def informes_guardados() -> list[Path]:
    if not ANALISIS_DIR.is_dir():
        return []
    return sorted(ANALISIS_DIR.glob("*_analisis.json"), key=lambda p: p.stat().st_mtime, reverse=True)


st.markdown(
    """
    <div class="visor-header">
      <div>
        <div class="visor-titulo">V.I.S.O.R.</div>
        <div class="visor-subtitulo">Análisis temporal SAR · cambio de retrodispersión entre dos fechas</div>
      </div>
      <div class="visor-header-der">
        <span class="visor-chip">Sentinel-1 RTC</span>
        <span class="visor-chip visor-chip-tenue">Resultado exploratorio</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(f'<div class="visor-aviso visor-aviso-general">{escape(sar.ADVERTENCIA)}</div>', unsafe_allow_html=True)

col_controles, col_resultado = st.columns([1, 2.2], gap="medium")

# ---------------------------------------------------------------------------
# Selección de archivos y parámetros
# ---------------------------------------------------------------------------
with col_controles:
    st.subheader("1 · Imágenes")
    escenas, omitidos = escenas_disponibles()
    if len(escenas) < 2:
        st.info(
            f"Copia en `data/sar/` los GeoTIFF RTC de HyP3 ya descomprimidos (por ejemplo los archivos "
            f"`…_VV.tif` de las dos fechas). Se encontraron {len(escenas)} utilizables.",
            icon="📂",
        )
    else:
        preferida = "VV" if any(e.polarizacion == "VV" for e in escenas) else escenas[0].polarizacion
        ordenadas = sorted(escenas, key=lambda e: (e.polarizacion != preferida, e.fecha is None, e.fecha or 0))
        antes = st.selectbox("Imagen anterior", ordenadas, format_func=etiqueta, key="sar_antes")
        candidatas = [e for e in escenas if e.polarizacion == antes.polarizacion and e.ruta != antes.ruta]
        candidatas.sort(key=lambda e: (e.fecha is None, e.fecha or 0), reverse=True)
        if not candidatas:
            st.warning(f"No hay otra imagen {antes.polarizacion} para comparar.")
            despues = None
        else:
            despues = st.selectbox("Imagen posterior", candidatas, format_func=etiqueta, key="sar_despues")
        st.caption(f"Solo se comparan imágenes de la misma polarización ({antes.polarizacion}).")

        st.subheader("2 · Zona de análisis")
        zona = st.radio("Zona", list(AOIS), label_visibility="collapsed", key="sar_zona")
        aoi = AOIS[zona]
        if zona == "Recuadro personalizado":
            base = AOIS["Chigorodó y alrededores (aproximado)"]
            c1, c2 = st.columns(2)
            oeste = c1.number_input("Oeste (lon)", value=base[0], format="%.4f", step=0.05)
            este = c2.number_input("Este (lon)", value=base[2], format="%.4f", step=0.05)
            sur = c1.number_input("Sur (lat)", value=base[1], format="%.4f", step=0.05)
            norte = c2.number_input("Norte (lat)", value=base[3], format="%.4f", step=0.05)
            aoi = (oeste, sur, este, norte)

        st.subheader("3 · Parámetros")
        umbral_dis = st.slider("Disminución significativa (dB)", 1.0, 10.0, 3.0, 0.5,
                               help="Se marca donde la retrodispersión bajó al menos este valor.")
        marcar_aumento = st.toggle("Marcar también aumentos", value=True)
        umbral_aum = st.slider("Aumento significativo (dB)", 1.0, 10.0, 3.0, 0.5, disabled=not marcar_aumento)
        ventana = st.select_slider("Filtro de speckle (píxeles)", options=[1, 3, 5, 7, 9, 11], value=5,
                                   help="Media móvil en potencia. 1 = sin filtro. Más grande = menos ruido y menos detalle.")
        sugerido = sar.UMBRAL_OSCURO_SUGERIDO[antes.polarizacion]
        marcar_oscuro = st.toggle("Marcar zonas de señal baja en ambas fechas", value=False,
                                  help="Posible agua permanente, sombra de radar o superficies lisas.")
        umbral_osc = st.slider("Umbral de señal baja (dB)", -30.0, -10.0, sugerido, 0.5, disabled=not marcar_oscuro)

        if st.button("Ejecutar análisis", type="primary", disabled=despues is None, use_container_width=True):
            try:
                with st.spinner("Alineando imágenes y calculando el cambio…"):
                    resultado = sar.analizar_par(
                        antes.ruta, despues.ruta, ANALISIS_DIR, aoi=aoi,
                        parametros=sar.ParametrosCambio(
                            umbral_disminucion_db=umbral_dis,
                            umbral_aumento_db=umbral_aum if marcar_aumento else None,
                            ventana_speckle=ventana,
                            umbral_oscuro_db=umbral_osc if marcar_oscuro else None,
                        ),
                    )
                st.session_state["sar_informe"] = resultado.informe.name
                st.success("Análisis terminado.")
            except sar.ErrorSAR as e:
                st.error(str(e), icon="⚠️")

    if omitidos:
        with st.expander(f"Archivos omitidos ({len(omitidos)})"):
            st.caption("No se reconocen como imagen RTC de una polarización (DEM, mapas de incidencia, RGB, etc.).")
            st.write(", ".join(omitidos))

# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------
with col_resultado:
    informes = informes_guardados()
    if not informes:
        st.markdown(
            '<div class="visor-panel"><div class="visor-panel-titulo">Sin resultados todavía</div>'
            '<p class="visor-texto">Elige las dos imágenes y pulsa <b>Ejecutar análisis</b>. '
            "Los resultados se guardan en <code>data/analisis/</code> y quedan disponibles aquí.</p></div>",
            unsafe_allow_html=True,
        )
        st.stop()

    nombres = [p.name for p in informes]
    elegido = st.session_state.get("sar_informe")
    indice = nombres.index(elegido) if elegido in nombres else 0
    informe = informes[st.selectbox("Resultado", range(len(informes)), index=indice,
                                    format_func=lambda i: nombres[i].replace("_analisis.json", ""))]
    try:
        p = json.loads(informe.read_text(encoding="utf-8"))
        ruta_dif = informe.parent / p["salidas"]["diferencia_db"]
        ruta_masc = informe.parent / p["salidas"]["mascara"]
    except (OSError, ValueError, KeyError):
        st.error(f"No se pudo leer el informe `{informe.name}`.", icon="⚠️")
        st.stop()

    c1, c2, c3 = st.columns([1.3, 1.3, 1])
    vista = c1.radio("Capa", ["Máscara de cambios", "Diferencia en dB"], horizontal=True)
    fondo = c2.selectbox("Mapa base", list(MAPAS_BASE), index=list(MAPAS_BASE).index(MAPA_BASE_PREDETERMINADO),
                         format_func=lambda k: MAPAS_BASE[k].nombre)
    opacidad = c3.slider("Opacidad", 0.0, 1.0, 0.8, 0.05)

    try:
        if vista == "Diferencia en dB":
            perfil = perfil_diferencia(max(6.0, 2 * p["parametros"]["umbral_disminucion_db"]))
            capa = cargar_capa(ruta_dif)
        else:
            perfil = PERFIL_MASCARA
            capa = cargar_capa(ruta_masc, categorico=True)
    except ErrorCapa as e:
        st.error(str(e), icon="⚠️")
        st.stop()

    oeste, sur, este, norte = p["cuadricula"]["limites_lonlat"]
    lienzo = folium.Map(location=[(sur + norte) / 2, (oeste + este) / 2], zoom_start=11, tiles=None,
                        control_scale=True)
    lienzo.fit_bounds([[sur, oeste], [norte, este]])
    st_folium(
        lienzo,
        feature_group_to_add=[mapa.grupo_mapa_base(obtener(fondo)), mapa.grupo_sar(perfil, capa, opacidad)],
        height=540, use_container_width=True, returned_objects=[], key=f"mapa_sar_{informe.stem}",
    )

    col_leyenda, col_datos = st.columns([1, 1.8], gap="medium")
    with col_leyenda:
        st.caption("LEYENDA")
        leyenda.render(perfil, capa)
    with col_datos:
        e, entradas = p["estadisticas"], p["entradas"]
        fechas = " → ".join((x["fecha"] or "sin fecha")[:10] for x in (entradas["antes"], entradas["despues"]))
        st.caption("RESUMEN")
        st.markdown(
            f"**{fechas}** · {entradas['antes']['polarizacion']} · "
            f"{p['cuadricula']['ancho']}×{p['cuadricula']['alto']} px · "
            f"{e['porcentaje_valido']:.0f}% con dato en ambas fechas"
        )
        filas = [
            {"Clase": c["etiqueta"], "% con dato": c["porcentaje_de_validos"], "ha": c["area_ha"]}
            for c in e["clases"].values() if c["pixeles"]
        ]
        st.dataframe(filas, hide_index=True, use_container_width=True)
        d = e.get("diferencia_db")
        if d:
            st.caption(f"Diferencia: mediana {d['mediana']} dB · 5 % {d['p5']} dB · 95 % {d['p95']} dB")

    for aviso in p["avisos"]:
        st.markdown(f'<div class="visor-aviso">{escape(aviso)}</div>', unsafe_allow_html=True)

    with st.expander("Cómo interpretar y limitaciones", expanded=True):
        st.markdown("\n".join(f"- {t}" for t in p["limitaciones"]))
    with st.expander("Procedencia y parámetros"):
        st.markdown("\n".join(f"- {t}" for t in p["metodo"]))
        st.json({k: p[k] for k in ("entradas", "parametros", "alineacion", "aoi_lonlat", "cuadricula",
                                   "salidas", "version_motor", "generado_utc")}, expanded=False)
