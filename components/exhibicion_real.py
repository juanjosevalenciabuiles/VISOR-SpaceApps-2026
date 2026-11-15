"""Muestra científica sin red: observaciones y productos reales ya almacenados.

- Solo usa manifiestos NASA Harmony de trabajos APTO y sus GeoTIFF locales.
- Nunca descarga ni solicita datos nuevos; ninguna imagen o inferencia sintética.
- Comparación visual de gamma0 NISAR en dos fechas: misma rampa radiométrica.
- GeoTIFF ΔdB únicamente mediante el motor QA ya existente, sin omitir controles.
- Resultados anteriores del visor SOLO con procedencia real trazable.
"""
from __future__ import annotations

import json
from pathlib import Path

import folium
import numpy as np
import streamlit as st
from streamlit_folium import st_folium

from utils import alcance_geografico, sesion, trabajos
from utils.config import DATA_DIR
from utils.geotiff import ErrorCapa, a_web_mercator, colorizar, leer_geotiff
from utils.resultados import cargar_resultados, leer_resultado
from utils.v9_nisar_puente import QAInsuficiente, escenas_preparadas, leer_preparacion
from utils.v9_trabajo_mapa import iniciar

COLORES = ("#101a3b", "#2254a0", "#39b7db", "#f2dc82", "#ef833a")
MAX_LADO = 600


def preparaciones_locales(carpeta: Path | None = None) -> list[tuple[dict, list[dict]]]:
    """Inventario exclusivamente local de pares con dos tomas identificables."""
    carpeta = Path(carpeta) if carpeta is not None else DATA_DIR / "trabajos"
    if not carpeta.is_dir():
        return []
    candidatos = []
    for archivo in sorted(carpeta.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:200]:
        try:
            trabajo = json.loads(archivo.read_text(encoding="utf-8"))
            if (trabajo.get("estado") != trabajos.APTO
                    or trabajo.get("tipo") != "adquisicion_nisar_gcov"
                    or trabajo.get("procesador") != "harmony_cog"
                    or not isinstance(trabajo.get("job_id"), str)):
                continue
            manifiesto = leer_preparacion(trabajo["job_id"])
            tomas = escenas_preparadas(manifiesto)
            if len(tomas) != 2:
                continue
            if not all(Path(toma["cog"]).is_file() and Path(toma["qa_mask"]).is_file()
                       and Path(toma["looks"]).is_file() for toma in tomas):
                continue
            candidatos.append((trabajo, tomas))
        except (OSError, ValueError, TypeError, KeyError, QAInsuficiente):
            continue
    return candidatos


@st.cache_data(show_spinner=False, max_entries=8)
def _intensidad_local(path: str, firma: tuple) -> tuple[np.ma.MaskedArray, tuple]:
    """Gamma0 real lineal -> dB; ningún dato interpolado entre fechas."""
    capa = leer_geotiff(Path(path), max_lado=MAX_LADO, categorico=False)
    valores = np.ma.masked_invalid(capa.datos)
    valores = np.ma.masked_less_equal(valores, 0)
    if valores.count() == 0:
        raise ValueError("la toma no contiene intensidades gamma0 positivas en esta zona")
    with np.errstate(divide="ignore", invalid="ignore"):
        db = np.ma.masked_invalid(10.0 * np.ma.log10(valores))
    if db.count() == 0:
        raise ValueError("la toma no tiene píxeles válidos para colorización")
    return db.astype("float32"), capa.limites


def _obtener_intensidad(path: str):
    p = Path(path)
    stat = p.stat()
    return _intensidad_local(path, (stat.st_size, stat.st_mtime_ns))


def _normalizacion(d1, d2) -> tuple[float, float]:
    """Estiramiento compartido para evitar escalas engañosas entre fechas."""
    v1, v2 = d1.compressed(), d2.compressed()
    # Ambas vistas tendrán la misma escala, derivada SOLO de los datos observados.
    p1 = np.percentile(v1, (2, 98))
    p2 = np.percentile(v2, (2, 98))
    bajo, alto = min(p1[0], p2[0]), max(p1[1], p2[1])
    if alto <= bajo:
        alto = bajo + 0.1
    return float(bajo), float(alto)


def _mapa_local(limites, rgba, key: str, encuadre=None):
    oeste, sur, este, norte = limites
    contorno = encuadre or limites
    o, s, e, n = contorno
    m = folium.Map(location=[(s + n)/2, (o + e)/2], tiles="OpenStreetMap",
                   zoom_start=10, control_scale=True)
    folium.raster_layers.ImageOverlay(
        image=a_web_mercator(rgba, sur, norte),
        bounds=[[sur, oeste], [norte, este]],
        opacity=0.95, name="Medición satelital real",
    ).add_to(m)
    m.fit_bounds([[s, o], [n, e]])
    st_folium(m, height=360, use_container_width=True, key=key, returned_objects=[])


def _mostrar_tomas(job_id: str, tomas: list[dict]) -> None:
    st.markdown("#### Comparación de dos adquisiciones NISAR reales")
    st.caption("Fuente: NASA/ASF · NISAR L2 GCOV, banda L · recortes existentes de Harmony. "
               "Los colores representan intensidad de retrodispersión γ⁰ (dB), no agua detectada.")
    try:
        (antes, a_limites), (despues, d_limites) = [
            _obtener_intensidad(toma["cog"]) for toma in tomas
        ]
    except (ErrorCapa, OSError, ValueError) as exc:
        st.warning("No es posible visualizar este par: " + str(exc))
        return
    vmin, vmax = _normalizacion(antes, despues)
    amplitud = (min(a_limites[0], d_limites[0]), min(a_limites[1], d_limites[1]),
                max(a_limites[2], d_limites[2]), max(a_limites[3], d_limites[3]))
    col1, col2 = st.columns(2, gap="medium")
    for columna, etiqueta, datos, limites, toma in (
        (col1, "ANTES", antes, a_limites, tomas[0]),
        (col2, "DESPUÉS", despues, d_limites, tomas[1]),
    ):
        with columna:
            st.markdown(f"**{etiqueta} · {toma['observed_at'][:10]}**")
            st.caption(f"NISAR · {toma['polarizacion']} · {toma['orbita']}")
            rgba = colorizar(datos, COLORES, vmin=vmin, vmax=vmax, transparencia="nodata")
            _mapa_local(limites, rgba, "visor_muestra_" + job_id + etiqueta, amplitud)
    st.caption(f"Escala común: {vmin:.1f} a {vmax:.1f} dB · oscuro = retorno menor, "
               "naranja = retorno mayor. La comparación es visual, sin inferir inundación.")
    with st.expander("Ver imágenes sin mapa base (misma escala cromática)"):
        a, b = st.columns(2)
        a.image(colorizar(antes, COLORES, vmin=vmin, vmax=vmax, transparencia="nodata"),
                caption="ANTES · píxeles satelitales")
        b.image(colorizar(despues, COLORES, vmin=vmin, vmax=vmax, transparencia="nodata"),
                caption="DESPUÉS · píxeles satelitales")
    st.caption("Visualización de gamma0: para calcular ΔdB deben coincidir las cuadrículas "
               "y superar las máscaras y looks originales. Esas comprobaciones se hacen en el cálculo.")


def abrir_resultado_en_mapa_principal(res, origen: str) -> None:
    """Activa un resultado REAL en el mapa principal, nunca solo en una vista aislada.

    Se retira la AOI de otra sesión para no atribuirle erróneamente estos píxeles.
    No escribe ni descarga nada: conserva el GeoTIFF y su ficha original.
    """
    if not res.dibujable or not res.capa or not res.capa.procedencia.es_real:
        raise ValueError("Solo se pueden exhibir GeoTIFF con procedencia satelital real.")
    permitidos, _ = alcance_geografico.filtrar_resultados([res])
    if not permitidos:
        raise ValueError("El producto no tiene píxeles válidos dentro de Colombia.")
    from components import flujo, interfaz

    flujo.quitar_zona()
    st.session_state["lugar"] = None
    st.session_state["capa_sar"] = False  # nunca confundir una capa DEMO con el producto real
    flujo.activar(res.id, origen)
    st.session_state.update(
        visor_modo_muestra_real=False,
        ui_explorador=True,
        ui_info=True,
        ui_sar="cerrado",
    )
    interfaz.centrar_en(res.capa.limites)


def _mostrar_delta(trabajo: dict, parent_id: str) -> None:
    st.markdown("#### GeoTIFF de diferencia real (ΔdB)")
    if trabajo["estado"] in trabajos.ACTIVOS:
        st.info("Calculando con los seis GeoTIFF locales y las máscaras originales. "
                "No se consulta ni descarga nada.")
        st.button("Actualizar progreso", key="visor_muestra_actualizar_" + parent_id)
    elif trabajo["estado"] == trabajos.APTO:
        nombre = trabajo.get("principal") or ""
        ruta = DATA_DIR / "analisis" / nombre
        if not ruta.is_file():
            st.warning("El trabajo terminó, pero no se encontró el GeoTIFF final.")
            return
        try:
            res = leer_resultado(ruta)
            if not res.dibujable or not res.capa.procedencia.es_real:
                st.warning("El resultado no superó la verificación de procedencia y QA.")
                return
            st.success("GeoTIFF verdadero generado: " + ruta.name)
            st.caption("Cambio de retrodispersión entre dos fechas, no inundación confirmada.")
            autorizados, _ = alcance_geografico.filtrar_resultados([res])
            if autorizados:
                st.button(
                    "Ver este GeoTIFF en el mapa principal de V.I.S.O.R.",
                    key="visor_abrir_delta_mapa_" + parent_id,
                    type="primary",
                    use_container_width=True,
                    on_click=abrir_resultado_en_mapa_principal,
                    args=(res, sesion.ANALISIS),
                )
            else:
                st.warning("Este GeoTIFF no tiene píxeles válidos comprobables dentro de Colombia; "
                           "no se puede presentar como resultado del territorio.")
            st.caption("Solo para contraste: el mapa inferior muestra el mismo archivo real. "
                       "En el mapa principal aparecen el control de opacidad y la leyenda ΔdB.")
            from components.mapa import grupo_resultado
            # Reutilizar exactamente los colores y la leyenda del mapa principal.
            m = folium.Map(location=[(res.capa.limites[1]+res.capa.limites[3])/2,
                                     (res.capa.limites[0]+res.capa.limites[2])/2],
                           tiles="OpenStreetMap", zoom_start=10)
            grupo_resultado(res, 0.9).add_to(m)
            o, s, e, n = res.capa.limites
            m.fit_bounds([[s, o], [n, e]])
            st_folium(m, height=420, use_container_width=True,
                      returned_objects=[], key="visor_muestra_delta_" + parent_id)
            st.caption("Archivo local disponible: data/analisis/" + ruta.name +
                       " · no se ha realizado ninguna descarga adicional.")
        except (OSError, ValueError, ErrorCapa) as exc:
            st.warning("No se pudo abrir el GeoTIFF: " + str(exc))
    else:
        st.warning("No se generó el ΔdB: " + str(trabajo.get("error") or trabajo["estado"]))
        st.caption("Los datos siguen siendo reales. El procesamiento no inventa celdas compatibles.")


def _resultados_ya_existentes():
    st.markdown("#### Resultados SAR reales ya disponibles")
    resultados, _ = alcance_geografico.filtrar_resultados(cargar_resultados())
    reales = [r for r in resultados if r.dibujable and r.capa.procedencia.es_real]
    if not reales:
        st.info("No hay resultados de análisis con procedencia real verificada. "
                "Las imágenes NISAR de arriba siguen siendo mediciones auténticas.")
        return
    elegido = st.selectbox("GeoTIFF de análisis existente",
                           options=range(len(reales)),
                           format_func=lambda i: reales[i].nombre + " · " + reales[i].ruta.name,
                           key="visor_muestra_resultado_previo")
    res = reales[elegido]
    fuente = (res.ficha or {}).get("procedencia") or {}
    st.caption("Fuente: " + str(fuente.get("sensor", "satélite real")) +
               " · fechas: " + " / ".join(map(str, fuente.get("fechas") or [])))
    st.caption("Estado: " + res.capa.procedencia.etiqueta +
               ". Producto guardado previamente, sin procesamiento nuevo.")
    st.button(
        "Abrir este resultado real en el mapa principal",
        key="visor_abrir_previo_mapa_" + res.id,
        type="primary",
        use_container_width=True,
        on_click=abrir_resultado_en_mapa_principal,
        args=(res, sesion.HISTORICO),
    )
    from components.mapa import grupo_resultado
    o, s, e, n = res.capa.limites
    m = folium.Map(location=[(s+n)/2, (o+e)/2], tiles="OpenStreetMap", zoom_start=10)
    grupo_resultado(res, 0.9).add_to(m)
    m.fit_bounds([[s, o], [n, e]])
    st_folium(m, height=430, use_container_width=True, returned_objects=[],
              key="visor_muestra_previo_" + res.id)
    st.caption("Leyenda: consulta los metadatos del producto. "
               "El mapa no demuestra por sí mismo que hubo una inundación.")


def render() -> None:
    """Vista alternativa voluntaria, sin escenas sintéticas ni red SAR."""
    st.title("V.I.S.O.R. · Evidencia satelital real")
    st.caption("Modo jurado · solo archivos existentes · sin descargas de imágenes · "
               "sin datos sintéticos · resultados exploratorios.")
    if st.button("Volver a V.I.S.O.R.", key="visor_salir_muestra_real",
                 icon=":material/arrow_back:"):
        st.session_state["visor_modo_muestra_real"] = False
        st.rerun()
    pares = preparaciones_locales()
    if pares:
        indices = list(range(len(pares)))
        elegido = st.selectbox(
            "Elegir dos tomas NISAR auténticas almacenadas",
            indices,
            format_func=lambda i: ("NISAR " + pares[i][1][0]["observed_at"][:10] +
                                   " → " + pares[i][1][1]["observed_at"][:10] +
                                   " · lote " + pares[i][0]["job_id"][:8]),
            key="visor_muestra_par",
        )
        job, tomas = pares[elegido]
        st.caption("Par preparado en Replit: " + job["job_id"] +
                   " · órbita " + tomas[0]["orbita"] + " · mismo grupo de procesamiento.")
        _mostrar_tomas(job["job_id"], tomas)
        st.divider()
        st.markdown("#### Generar un mapa de cambio sin descargar nada")
        st.caption("Esta opción procesa los seis archivos ya existentes (intensidad, máscara y looks "
                   "en dos fechas). Solo publica un ΔdB si la geometría, QA y procedencia son válidos.")
        if st.button("Calcular GeoTIFF ΔdB con archivos locales",
                     key="visor_muestra_generar_" + job["job_id"], type="primary"):
            try:
                tarea = iniciar(job)
                st.session_state["visor_muestra_delta_job"] = tarea["job_id"]
                st.session_state["visor_muestra_delta_padre"] = job["job_id"]
            except (ValueError, OSError, QAInsuficiente) as exc:
                st.warning("No se puede iniciar este cálculo: " + str(exc))
        if st.session_state.get("visor_muestra_delta_padre") == job["job_id"]:
            job_calculo = trabajos.leer(st.session_state.get("visor_muestra_delta_job") or "")
            if job_calculo:
                _mostrar_delta(job_calculo, job["job_id"])
    else:
        st.warning("No se identificó un par Harmony con dos escenas y metadatos completos "
                   "en los archivos locales. No se crearán tomas ficticias.")
    st.divider()
    _resultados_ya_existentes()
    st.caption("Transparencia científica: los colores son representaciones de valores observados. "
               "La verificación independiente y el diagnóstico de inundación son trabajos distintos.")
