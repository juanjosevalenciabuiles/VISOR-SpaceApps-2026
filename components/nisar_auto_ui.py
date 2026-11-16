"""NISAR GCOV principal para inundaciones: Harmony AOI primero, HDF5 opt-in.

El usuario confirma AOI y fechas, ve cobertura real de catálogo, límites de MB
y autoriza la transferencia. No se publican mapas de inundaciones sin análisis
científico y validación independientes. No se necesitan GeoTIFF manuales.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone

import streamlit as st

from utils.i18n import tr
from utils import nisar_auto, nisar_catalogo as cat, nisar_descarga, nisar_gcov, trabajos
from utils.config import DATA_DIR

METODOS = ("Recorte optimizado · NASA Harmony", "HDF5 completo · alternativa")


def _huella(plan, metodo, max_mb, madurez="VALIDATED"):
    contenido = json.dumps({
        "granules": plan.granules, "aoi": list(plan.aoi), "termino": plan.termino,
        "metodo": metodo, "madurez": madurez,
        "presupuesto_mb": max_mb, "motor": "NISAR GCOV insumos",
    }, sort_keys=True)
    return hashlib.sha256(contenido.encode()).hexdigest()


def _ejecutar_en_cola(resultado, plan, metodo, max_mb):
    registro = cat.registro_json(resultado)
    carpeta = DATA_DIR / "nisar" / "catalogo"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"auto_{uuid.uuid4().hex}.json"
    with ruta.open("x", encoding="utf-8") as archivo:
        json.dump(registro, archivo, indent=2, ensure_ascii=False)
    identificador = _huella(plan, metodo, max_mb, madurez=resultado.madurez)

    def tarea(ctx: trabajos.Contexto):
        ctx.fase("zona", trabajos.APTO, "AOI admitida por la política Colombia")
        ctx.fase("escenas", trabajos.APTO, f"{len(plan.candidatos)} productos GCOV NASA/ASF")
        ctx.fase("datos", trabajos.EN_CURSO, "Solicitando datos de banda L")
        ctx.comprobar("antes de solicitar")

        def notificar(etapa, detalle):
            ctx.comprobar(etapa)
            if etapa == "progreso":
                hecho, total = detalle
                if hecho == total or hecho % (128 * 1024**2) < nisar_descarga.BLOQUE:
                    ctx.fase("datos", trabajos.EN_CURSO,
                             f"Descarga HDF5: {hecho / 1e9:.2f} de {total / 1e9:.2f} GB")
            elif etapa == "Harmony: preparando recorte":
                # Mostrar únicamente el progreso comunicado por NASA Harmony;
                # no inferir una estimación de tiempo de descarga.
                try:
                    progreso = float(detalle)
                except (TypeError, ValueError):
                    progreso = -1
                sufijo = f" ({progreso:.0f}% indicado por NASA)" if 0 <= progreso <= 100 else ""
                ctx.fase("preparacion", trabajos.EN_CURSO, "NASA Harmony prepara los COG" + sufijo)
            else:
                ctx.fase("datos", trabajos.EN_CURSO, str(etapa))

        if metodo == METODOS[0]:
            salida = nisar_auto.preparar_harmony(
                plan, max_mb=max_mb, notificar=notificar,
                comprobar=lambda: ctx.comprobar("descarga Harmony"),
            )
            geotiffs = [
                DATA_DIR / "nisar" / "harmony" / escena["carpeta_relativa"] / archivo
                for escena in salida["escenas"] for archivo in escena["archivos"]
            ]
            detalle = f"COG recortados a la AOI · {salida['bytes_totales']/1024**2:.1f} MB"
        else:
            salida = nisar_auto.preparar(plan, ruta, notificar=notificar)
            geotiffs = [nisar_gcov.CARPETA_NISAR / x["geotiff"] for x in salida["escenas"]]
            detalle = "HDF5 íntegros y recortes GCOV"
        if metodo == METODOS[0] and salida.get("madurez") != resultado.madurez:
            raise nisar_auto.ErrorAutoNISAR("La colección obtenida no coincide con la madurez solicitada.")
        salida["madurez"] = resultado.madurez  # Etiqueta de origen confirmada por Harmony
        ctx.fase("datos", trabajos.APTO, "Descarga auténtica finalizada")
        ctx.fase("preparacion", trabajos.APTO, detalle)
        ctx.comprobar("verificación")
        ctx.fase("verificacion", trabajos.EN_CURSO, "Guardando metadatos y huellas de los insumos")
        resumen = carpeta / f"resultado_{ctx.job_id}.json"
        with resumen.open("x", encoding="utf-8") as archivo:
            json.dump(salida, archivo, indent=2, ensure_ascii=False)
        # Este trabajo prepara insumos, NO un resultado ambiental dibujable.
        # El principal será el MANIFIESTO, no un supuesto mapa de inundación.
        ctx.resultado(resumen, resumen, [*geotiffs, resumen], list(plan.avisos))
        ctx.fase("verificacion", trabajos.APTO, "Insumos preparados; sin clasificación de inundación")

    t, _ = trabajos.crear_o_reutilizar(
        identificador, {
            "tipo": "adquisicion_nisar_gcov", "sensor": "NISAR",
            "procesador": "harmony_cog" if metodo == METODOS[0] else "nisar_gcov_hdf5",
            "aoi": {"limites": list(plan.aoi)},
            "escenas": {"antes": plan.granules[0], "despues": plan.granules[-1]},
        }, tarea,
    )
    return t


def _cambio_automatico(preparacion: dict) -> None:
    """Completar el camino antiguo de preparación Harmony hasta GeoTIFF ΔdB.

    El flujo público V9 ya calcula y publica mediante su propio seguimiento;
    no iniciar un segundo trabajo en paralelo para la misma preparación.
    """
    job_id = preparacion["job_id"]
    if st.session_state.get("v9_preparacion") == job_id:
        return
    if preparacion.get("procesador") != "harmony_cog":
        st.caption("Los recortes HDF5 de este flujo no se convierten automáticamente al "
                   "GeoTIFF de cambio V9. Usa el flujo público Harmony con área y periodo.")
        return
    from components import flujo
    from utils import sesion
    from utils.resultados import id_resultado, leer_resultado
    from utils.v9_datos.cambio_cog import QAInsuficiente
    from utils.v9_trabajo_mapa import iniciar

    zona = flujo.zona_confirmada()
    limites = (preparacion.get("aoi") or {}).get("limites") or []
    if zona is None or tuple(zona) != tuple(limites):
        st.caption("La zona ha cambiado; estos insumos NISAR no corresponden a la zona activa.")
        return
    if st.session_state.get("nisar_auto_cambio_origen") != job_id:
        try:
            trabajo = iniciar(preparacion)
        except (ValueError, OSError, QAInsuficiente) as exc:
            st.warning("No se puede generar un cambio a partir de estos insumos: " + str(exc))
            return
        st.session_state["nisar_auto_cambio_origen"] = job_id
        st.session_state["nisar_auto_cambio_job"] = trabajo["job_id"]
        st.session_state["nisar_auto_cambio_publicado"] = None
        flujo.limpiar_resultado()
    cambio_id = st.session_state.get("nisar_auto_cambio_job")
    cambio = trabajos.leer(cambio_id) if cambio_id else None
    if not cambio:
        st.warning("No se puede recuperar el trabajo de cálculo NISAR.")
        return
    if cambio["estado"] in trabajos.ACTIVOS:
        st.info("Calculando GeoTIFF NISAR de diferencia de retrodispersión con QA real…")
        return
    if cambio["estado"] != trabajos.APTO:
        st.warning("No se generó el GeoTIFF: " + str(cambio.get("error") or cambio["estado"]))
        st.caption("No se publican capas cuando faltan datos válidos, QA o alineación de cuadrículas.")
        return
    ruta = DATA_DIR / "analisis" / str(cambio.get("principal") or "")
    if not ruta.is_file():
        st.warning("El trabajo terminó, pero falta el GeoTIFF en data/analisis/.")
        return
    resultado = leer_resultado(ruta)
    if not resultado.dibujable or not resultado.capa or not resultado.capa.procedencia.es_real:
        st.warning("El GeoTIFF no superó la validación de procedencia y QA; no se publica.")
        return
    st.success("GeoTIFF de cambio NISAR preparado y verificado: " + ruta.name)
    st.caption("Cambio real de señal SAR en dB. NO confirma inundación.")
    if st.session_state.get("nisar_auto_cambio_publicado") != cambio_id:
        flujo.activar(id_resultado(ruta), sesion.ANALISIS, cambio["run_id"])
        st.session_state["nisar_auto_cambio_publicado"] = cambio_id
        st.session_state["ui_explorador"] = True
        st.rerun(scope="app")


@st.fragment(run_every=2.0)
def _mostrar_trabajo(job_id: str):
    t = trabajos.leer(job_id)
    if not t:
        st.warning(tr("No se encontró el trabajo NISAR.", "NISAR job not found."))
        return
    st.markdown(f"**{tr('Estado de preparación', 'Preparation status')}:** {t['estado']}")
    for f in t.get("fases") or []:
        if f["estado"] != trabajos.PENDIENTE:
            # La cola genérica dice «Resultado publicado», pero aquí solo se publica
            # el manifiesto de INSUMOS, no una capa ambiental dibujable.
            if f["clave"] == "listo" and t["estado"] == trabajos.APTO:
                st.caption(tr("Insumos NISAR guardados; no hay clasificación de agua.",
                              "NISAR inputs saved; no water classification."))
            else:
                st.caption(f"{f['nombre']}: {f['estado']} · {f.get('detalle') or ''}")
    if t["estado"] in trabajos.ACTIVOS:
        st.info(tr("Preparando las capas NISAR solicitadas; puedes continuar explorando el mapa.",
                   "Preparing requested NISAR layers; you can continue exploring the map."))
        if st.button(tr("Solicitar cancelación", "Request cancellation"), key="nisar_cancelar"):
            trabajos.cancelar(job_id)
    elif t["estado"] == trabajos.APTO:
        st.success(tr("Los insumos NISAR están preparados. Todavía no son un mapa de inundación.",
                      "NISAR inputs are ready. They are not a flood map."))
        st.caption(tr("Datos y manifiestos en data/nisar/; se conserva resolución nativa y procedencia.",
                      "Data and manifests saved in data/nisar/; native resolution and provenance preserved."))
        _cambio_automatico(t)
    else:
        st.warning(f"{tr('El trabajo no se completó', 'Job did not finish')}: {t.get('error') or t['estado']}")


def render(region, error: str | None):
    st.markdown(tr("### NISAR · sensor principal para estudiar inundaciones",
                   "### NISAR · primary sensor for flood-related studies"))
    st.caption(tr("NASA/ASF L2 GCOV banda L. Con Harmony descargamos solo tu área y las capas científicas "
               "necesarias, sin traer el HDF5 completo de varios GB.",
               "NASA/ASF L2 GCOV L-band radar. Harmony requests only your area and necessary "
               "scientific layers instead of downloading multi-GB HDF5 files."))
    if region is None:
        st.info(error or tr("Primero dibuja y confirma un área en Colombia.",
                            "First draw and confirm an area in Colombia."))
        return

    a, b = st.columns(2)
    inicio = a.date_input(tr("Desde", "From"), value=cat.INICIO_VALIDATED, key="nisar_auto_inicio")
    fin = b.date_input(tr("Hasta", "To"), value=datetime.now(timezone.utc).date(), key="nisar_auto_fin")
    metodo = st.radio(tr("Forma de obtener los datos", "Data acquisition method"), METODOS,
                      format_func=lambda opcion: tr(opcion,
                          "Optimized subset · NASA Harmony" if opcion == METODOS[0]
                          else "Full HDF5 · alternative"), horizontal=True,
                      key="nisar_auto_metodo", help=tr("Harmony es mejor para áreas pequeñas.", "Harmony is more efficient for small AOIs."))
    if metodo == METODOS[0]:
        max_mb = st.slider(tr("Almacenamiento máximo para imágenes recortadas (MB)",
                          "Maximum storage for subsets (MB)"), 128, 512, 384, 64,
                           key="nisar_max_mb",
                           help=tr("Límite de transferencia, sin reducir resolución.",
                                   "Download limit without downsampling."))
        max_gb = 15
        st.caption(tr("Se solicitan capas HH/HV y QA disponibles; una fecha no basta para analizar cambios.",
                       "Requests available HH/HV and QA layers; a single date cannot show change."))
    else:
        max_gb = st.slider(tr("Presupuesto máximo para HDF5 completos (GB)",
                          "Maximum storage for full HDF5 (GB)"), 1, 10, 5,
                           key="nisar_max_gb",
                           help=tr("Alternativa que necesita varios GB.", "Alternative requiring several GB of storage."))
        max_mb = 0
        st.warning(tr("Esta alternativa descarga HDF5 de varios GB. Prefiere Harmony.",
                       "This downloads multi-GB HDF5 files. Prefer Harmony where available."))

    clave = (tuple(region.limites), str(inicio), str(fin), metodo, max_mb, max_gb)
    if st.button(tr("1. Buscar imágenes NISAR", "1. Find NISAR images"), key="nisar_auto_buscar", type="primary"):
        with st.spinner(tr("Consultando NASA/ASF, sin descargar imágenes…",
                            "Querying NASA/ASF metadata without downloading imagery…")):
            try:
                if inicio > fin:
                    raise nisar_auto.ErrorAutoNISAR("Revisa el orden de fechas.")
                resultado = cat.buscar(*region.limites, inicio, fin, madurez="VALIDATED")
                plan = nisar_auto.planear(resultado, max_gb=float(max_gb))
                st.session_state["nisar_auto_plan"] = {"clave": clave, "resultado": resultado, "plan": plan}
                st.session_state["nisar_auto_error"] = None
            except Exception as exc:
                st.session_state["nisar_auto_error"] = str(exc) if isinstance(exc, nisar_auto.ErrorAutoNISAR) else (
                    "No se pudo consultar el catálogo NISAR. Comprueba la conexión y las fechas.")
                st.session_state.pop("nisar_auto_plan", None)

    if st.session_state.get("nisar_auto_error"):
        st.warning(st.session_state["nisar_auto_error"])
    guardado = st.session_state.get("nisar_auto_plan")
    if guardado and guardado["clave"] == clave:
        plan = guardado["plan"]
        st.markdown(f"**{tr('Propuesta', 'Plan')}:** {plan.tipo.replace('_', ' ').lower()} · "
                    f"{len(plan.candidatos)} {tr('fecha(s)', 'date(s)')} · "
                    f"{tr('cobertura aproximada', 'estimated coverage')} **{plan.cobertura:.0%}**.")
        if metodo == METODOS[0]:
            st.caption(tr(f"El HDF5 completo suma {plan.tamano_bytes/1e9:.2f} GB, pero NO se descargará. "
                      f"Límite de recortes: {max_mb} MB.",
                      f"Full HDF5 size: {plan.tamano_bytes/1e9:.2f} GB, NOT downloaded. "
                      f"Subset download limit: {max_mb} MB."))
        else:
            st.caption(tr(f"Tamaño de HDF5 completos: {plan.tamano_bytes/1e9:.2f} GB.",
                           f"Full HDF5 size: {plan.tamano_bytes/1e9:.2f} GB."))
        for aviso in plan.avisos:
            st.caption(aviso)
        if not os.environ.get(nisar_descarga.VARIABLE_TOKEN, "").strip():
            st.info(tr("Configura EARTHDATA_TOKEN mediante Replit Secrets para autorizar a NASA. "
                    "Nunca escribas el token en el chat ni en GitHub.",
                    "Configure EARTHDATA_TOKEN in Replit Secrets to authorize NASA downloads. "
                    "Never share tokens in a chat or GitHub."))
        elif st.button(tr("2. Descargar y preparar las capas automáticamente",
                            "2. Download and prepare layers automatically"), key="nisar_auto_descargar",
                       type="primary"):
            try:
                t = _ejecutar_en_cola(guardado["resultado"], plan, metodo, max_mb)
                st.session_state["nisar_auto_job"] = t["job_id"]
            except (OSError, ValueError):
                st.error("No se pudo iniciar el trabajo; revisa el espacio disponible.")
    elif guardado:
        st.info(tr("Has cambiado el área, las fechas o el presupuesto. Busca de nuevo antes de descargar.",
                   "Area, dates or storage limits changed. Search again before downloading."))
    if st.session_state.get("nisar_auto_job"):
        _mostrar_trabajo(st.session_state["nisar_auto_job"])
    st.caption(tr("Los COG son datos calibrados de radar. Su contenido NO es una clasificación "
               "automática de agua ni una confirmación de inundaciones.",
               "COGs contain calibrated radar observations. They are NOT automatic water "
               "classifications or confirmed floods."))
