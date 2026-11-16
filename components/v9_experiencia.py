"""Experiencia PC: área + periodo -> COG NISAR -> mapa real de cambio SAR.

No afirma inundaciones ni predicciones; evita volver a descargar COG ya preparados.
Las opciones especializadas continúan en Herramientas SAR por compatibilidad.
"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import streamlit as st

from utils.i18n import tr

from components import flujo
from utils import nisar_auto, nisar_catalogo as cat, nisar_descarga, sesion, trabajos
from utils.config import DATA_DIR
from utils.resultados import id_resultado, leer_resultado
from utils.v9_nisar_puente import QAInsuficiente, escenas_preparadas, leer_preparacion
from utils.v9_trabajo_mapa import iniciar

MAX_HARMONY_MB = 384
MARGEN_DIAS = 45
INICIO_PROVISIONAL = date(2026, 6, 17)
FIN_PROVISIONAL = date(2026, 10, 23)
DISTANCIA_SUGERENCIAS_DIAS = 180


def _madurez_del_periodo(inicio: date, fin: date) -> str:
    """Elegir UNA colección compatible, sin mezclar procesamientos."""
    if inicio > fin:
        raise ValueError("El período debe estar ordenado.")
    if inicio < cat.INICIO_VALIDATED and fin <= FIN_PROVISIONAL:
        return "PROVISIONAL"
    return "VALIDATED"


def _limites_coleccion(madurez: str, inicio: date, fin: date,
                       margen: int = MARGEN_DIAS) -> tuple[date, date]:
    hoy = datetime.now(timezone.utc).date()
    minimo = INICIO_PROVISIONAL if madurez == "PROVISIONAL" else cat.INICIO_VALIDATED
    maximo = FIN_PROVISIONAL if madurez == "PROVISIONAL" else hoy
    primero = max(minimo, inicio - timedelta(days=margen))
    ultimo = min(maximo, hoy, fin + timedelta(days=margen))
    if primero > ultimo:
        raise ValueError("No hay adquisiciones públicas NISAR de esta madurez "
                         "cerca del período seleccionado.")
    return primero, ultimo


def _distancia_fechas(par, inicio: date, fin: date) -> tuple[int, int, int]:
    a = par.antes.nombre.inicio.date()
    b = par.despues.nombre.inicio.date()
    separacion = ((inicio - b).days if b < inicio else
                  (a - fin).days if a > fin else 0)
    return max(0, separacion), abs((a - inicio).days) + abs((b - fin).days), (b - a).days


def _sugerencias_cercanas(pares, inicio: date, fin: date, limite: int = 3) -> list:
    """Ordena PARES documentados por CMR, no inventa fechas ni valida píxeles."""
    unicos = {}
    for par in pares:
        a = par.antes.nombre.inicio.date()
        b = par.despues.nombre.inicio.date()
        if a >= b:
            continue
        unicos.setdefault((a, b), par)
    return sorted(unicos.values(), key=lambda par: _distancia_fechas(par, inicio, fin))[:limite]


def _limpiar_v9(limpiar_fechas: bool = False) -> None:
    for clave in ("v9_firma", "v9_preparacion", "v9_mapa_job", "v9_publicado",
                  "v9_error", "v9_sugerencias", "v9_preflight_provisional",
                  "nisar_auto_job"):
        st.session_state.pop(clave, None)
    if limpiar_fechas:
        for clave in ("v9_inicio_periodo", "v9_fin_periodo"):
            st.session_state.pop(clave, None)


def _nuevo_analisis(nueva_zona: bool) -> None:
    """Preparar otra exploración sin borrar archivos ni el historial."""
    _limpiar_v9(limpiar_fechas=nueva_zona)
    flujo.limpiar_resultado()
    if nueva_zona:
        flujo.quitar_zona()
        st.session_state["lugar"] = None
        st.session_state["ui_explorador"] = True
        st.session_state["ui_sar"] = "minimizado"
    else:
        st.session_state["ui_sar"] = "abierto"
        st.session_state["ui_explorador"] = False


def _usar_fechas_sugeridas(inicio: date, fin: date) -> None:
    _limpiar_v9()
    st.session_state["v9_inicio_periodo"] = inicio
    st.session_state["v9_fin_periodo"] = fin



def _firma(zona, inicio: date, fin: date):
    return (tuple(zona), inicio.isoformat(), fin.isoformat())


def _fechas_de_preparacion(job_id: str):
    datos = leer_preparacion(job_id)
    pares = escenas_preparadas(datos)
    return (date.fromisoformat(pares[0]["observed_at"][:10]),
            date.fromisoformat(pares[1]["observed_at"][:10]))


def _fechas_compatibles(pre: date, post: date, inicio: date, fin: date) -> bool:
    """El usuario elige un intervalo: acepta dos tomas dentro de él o que lo rodeen.

    Siempre exige dos observaciones distintas, reales y ordenadas. Las fechas
    efectivas del producto quedan en la ficha; no se inventan observaciones.
    """
    return (pre < post and inicio <= fin and
            ((inicio <= pre and post <= fin) or (pre < inicio and fin < post)))


def _pares_del_periodo(pares, inicio: date, fin: date) -> list:
    """Prioriza adquisiciones dentro del rango y, si faltan, pares pre/post.

    Para intervalos cortos entre pasadas NISAR, una toma anterior y otra
    posterior permiten estudiar el cambio sin fingir fechas intermedias.
    """
    dentro = [p for p in pares if inicio <= p.antes.nombre.inicio.date()
              < p.despues.nombre.inicio.date() <= fin]
    if dentro:
        return dentro
    return [p for p in pares if p.antes.nombre.inicio.date() < inicio
            and p.despues.nombre.inicio.date() > fin]


def _compatible(job: dict | None, zona, inicio: date, fin: date) -> bool:
    if not isinstance(job, dict) or job.get("estado") != trabajos.APTO:
        return False
    if job.get("tipo") != "adquisicion_nisar_gcov" or job.get("procesador") != "harmony_cog":
        return False
    if tuple((job.get("aoi") or {}).get("limites") or ()) != tuple(zona):
        return False
    try:
        pre, post = _fechas_de_preparacion(job["job_id"])
    except (QAInsuficiente, OSError, KeyError, ValueError):
        return False
    return _fechas_compatibles(pre, post, inicio, fin)


def _preparacion_existente(zona, inicio: date, fin: date) -> dict | None:
    """Recuperar el par Harmony compatible más reciente aun en otra sesión.

    Los trabajos se registran en disco; guardar solo el último job_id en
    session_state hacía invisible un par válido preparado previamente.
    """
    for job in trabajos.listar(200):
        if _compatible(job, zona, inicio, fin):
            return job
    return None


def _explorar_provisional(zona, inicio: date, fin: date):
    """Preflight CMR sin descargas: solo metadatos de la madurez PROVISIONAL.

    No envía trabajos Harmony, no calcula ΔdB y no confunde un candidato de
    catálogo con cobertura de píxeles aptos ni con una inundación confirmada.
    """
    hoy = datetime.now(timezone.utc).date()
    if inicio > fin or fin > hoy:
        raise ValueError("El intervalo debe estar ordenado y no incluir fechas futuras.")
    primero = max(date(2026, 6, 17), inicio - timedelta(days=MARGEN_DIAS))
    ultimo = min(date(2026, 10, 23), hoy, fin + timedelta(days=MARGEN_DIAS))
    if primero > ultimo:
        raise ValueError("La consulta queda fuera de las fechas públicas de NISAR PROVISIONAL.")
    resultado = cat.buscar(*zona, primero, ultimo, madurez="PROVISIONAL")
    return resultado, _pares_del_periodo(resultado.pares, inicio, fin)


def _mostrar_preflight(preflight, firma):
    if not isinstance(preflight, dict) or preflight.get("firma") != firma:
        return
    if preflight.get("error"):
        st.warning("No fue posible consultar el catálogo PROVISIONAL: " + preflight["error"])
        return
    resultado, pares = preflight["resultado"], preflight["pares"]
    st.caption(
        f"NASA CMR · colección PROVISIONAL · {resultado.total_catalogo} registros, "
        f"{len(resultado.candidatos)} escenas candidatas en la región · "
        f"{len(pares)} pares que cumplen las fechas. Solo metadatos, sin descargas."
    )
    if not pares:
        st.info(
            "No se identificó un par comparable que encierre o esté dentro de estas fechas "
            "para el área consultada. Esto no demuestra ausencia de inundación ni "
            "autoriza a fabricar un mapa."
        )
        return
    st.warning(
        "Hay candidatos PROVISIONAL por metadatos, NO datos descargados ni "
        "píxeles aptos verificados. Su procesamiento requiere controles científicos "
        "adicionales; no se ha iniciado."
    )
    for par in pares[:3]:
        st.caption(
            f"Posible par: {par.antes.nombre.inicio:%Y-%m-%d} → "
            f"{par.despues.nombre.inicio:%Y-%m-%d} · "
            f"órbita {par.antes.nombre.track}, frame {par.antes.nombre.frame}"
        )


def _abrir_modo_jurado():
    """Abrir solo archivos satelitales locales, nunca crear escenas sintéticas."""
    st.session_state["visor_modo_muestra_real"] = True


def _solicitar(zona, inicio: date, fin: date):
    hoy = datetime.now(timezone.utc).date()
    if inicio > fin or fin > hoy:
        raise ValueError("El intervalo debe estar ordenado y no incluir fechas futuras.")
    madurez = _madurez_del_periodo(inicio, fin)
    desde, hasta = _limites_coleccion(madurez, inicio, fin)
    resultado = cat.buscar(*zona, desde, hasta, madurez=madurez)
    candidatos = _pares_del_periodo(resultado.pares, inicio, fin)
    if not candidatos:
        pares = resultado.pares
        # Buscar también en la ventana ampliada por METADATOS para sugerir
        # un par más cercano, sin descargar ni extrapolar adquisiciones.
        amplio_desde, amplio_hasta = _limites_coleccion(
            madurez, inicio, fin, margen=DISTANCIA_SUGERENCIAS_DIAS)
        if (amplio_desde, amplio_hasta) != (desde, hasta):
            mas = cat.buscar(*zona, amplio_desde, amplio_hasta, madurez=madurez)
            pares = [*pares, *mas.pares]
        st.session_state["v9_sugerencias"] = {
            "firma": _firma(zona, inicio, fin), "madurez": madurez,
            "pares": _sugerencias_cercanas(pares, inicio, fin),
        }
        raise ValueError(
            "No se encontró un par NISAR compatible para estas fechas. "
            "Consulta los intervalos reales más cercanos sugeridos abajo."
        )
    if not os.environ.get(nisar_descarga.VARIABLE_TOKEN, "").strip():
        raise ValueError("Para adquirir nuevos recortes NISAR configura EARTHDATA_TOKEN "
                         "en los Secrets de Replit; no lo pegues en el chat.")
    plan = nisar_auto.planear(
        replace(resultado, pares=candidatos), max_gb=15.0, aceptar_escena_unica=False,
    )
    # Un clic autoriza recortes auténticos de hasta 384 MiB, nunca HDF5 completos.
    from components import nisar_auto_ui
    preparado = nisar_auto_ui._ejecutar_en_cola(
        resultado, plan, nisar_auto_ui.METODOS[0], MAX_HARMONY_MB,
    )
    return preparado["job_id"]


def _mostrar_sugerencias(firma) -> None:
    estado = st.session_state.get("v9_sugerencias") or {}
    if estado.get("firma") != firma:
        return
    pares = estado.get("pares") or []
    if not pares:
        st.info(tr("NASA CMR no encontró pares comparables. Prueba otra zona o fechas.",
                   "NASA CMR found no comparable pairs. Try another area or date range."))
        return
    st.markdown(tr("**Fechas NISAR más cercanas disponibles**",
                   "**Closest available NISAR acquisition dates**"))
    st.caption(tr("Sugerencias basadas en metadatos NASA; verificar cobertura y QA.",
                  "Suggestions based on NASA metadata; pixel coverage and QA must be verified."))
    for i, par in enumerate(pares):
        a, b = par.antes.nombre.inicio.date(), par.despues.nombre.inicio.date()
        st.button(
            f"{tr('Usar', 'Use')} {a:%Y-%m-%d} → {b:%Y-%m-%d} · {estado['madurez']}",
            key=f"v9_usar_sugerencia_{i}",
            on_click=_usar_fechas_sugeridas,
            args=(a, b),
            use_container_width=True,
        )


def _mostrar_progreso(trabajo: dict, fase: str) -> None:
    """Porcentaje de ETAPAS completadas, nunca ETA o bytes inventados."""
    claves = (("zona", "escenas", "datos", "preparacion", "verificacion")
              if fase == "preparacion" else ("calculo", "verificacion"))
    por_clave = {f["clave"]: f for f in trabajo.get("fases") or []}
    hechos = sum(por_clave.get(c, {}).get("estado") == trabajos.APTO for c in claves)
    activo = next((por_clave.get(c) for c in claves
                   if por_clave.get(c, {}).get("estado") == trabajos.EN_CURSO), None)
    if fase == "preparacion":
        porcentaje = int(5 + 65 * hechos / len(claves))
    else:
        porcentaje = int(72 + 26 * hechos / len(claves))
    porcentaje = 100 if trabajo.get("estado") == trabajos.APTO and fase == "calculo" else porcentaje
    detalle = (activo.get("detalle") or activo["nombre"]) if activo else (
        "En cola para iniciar" if trabajo.get("estado") in trabajos.ACTIVOS else
        "Etapas completadas" if trabajo.get("estado") == trabajos.APTO else
        "Trabajo detenido")
    etapas_en = {"zona": "Area", "escenas": "Scenes", "datos": "Data",
                 "preparacion": "Preparation", "calculo": "SAR computation",
                 "verificacion": "Quality checks"}
    fase_en = etapas_en.get(activo["clave"], "Processing") if activo else "Queued / complete"
    st.progress(min(100, max(0, porcentaje)),
                text=f"{porcentaje}% {tr('de etapas', 'of steps')} · "
                     f"{tr(detalle, fase_en)}")
    estado_en = {
        "EN_CURSO": "RUNNING", "APTO": "COMPLETE", "PENDIENTE": "PENDING",
        "ERROR": "FAILED", "CANCELADO": "CANCELLED",
    }.get(str(trabajo["estado"]), str(trabajo["estado"]))
    st.caption(tr("El porcentaje indica etapas, no tiempo restante.",
                  "Progress is based on completed steps, not remaining time.") +
               f" · {tr('Estado', 'Status')}: {tr(str(trabajo['estado']), estado_en)}")


@st.fragment(run_every=2.0)
def _seguimiento(firma):
    if st.session_state.get("v9_firma") != firma:
        return
    prep_id = st.session_state.get("v9_preparacion")
    if not prep_id:
        return
    preparacion = trabajos.leer(prep_id)
    if preparacion is None:
        st.warning(tr("No se pudo recuperar el trabajo NISAR.", "NISAR job could not be recovered."))
        return
    if preparacion["estado"] in trabajos.ACTIVOS:
        st.info(tr("Preparando observaciones NISAR reales…", "Preparing real NISAR observations…"))
        _mostrar_progreso(preparacion, "preparacion")
        return
    if preparacion["estado"] != trabajos.APTO:
        st.warning(tr("La preparación NISAR falló", "NISAR preparation failed") + ": " +
                   str(preparacion.get("error") or preparacion["estado"]))
        return
    zona = flujo.zona_confirmada()
    inicio, fin = date.fromisoformat(firma[1]), date.fromisoformat(firma[2])
    if not zona or tuple(zona) != firma[0] or not _compatible(preparacion, zona, inicio, fin):
        st.warning(tr("Los COG no coinciden con la zona y fechas activas; no se publica el mapa.",
                          "Prepared COGs do not match the current AOI and dates; no map is published."))
        return
    mapa_job = st.session_state.get("v9_mapa_job")
    if not mapa_job:
        try:
            mapa_job = iniciar(preparacion)["job_id"]
            st.session_state["v9_mapa_job"] = mapa_job
        except (ValueError, OSError, QAInsuficiente) as exc:
            st.warning(tr("No se pudo iniciar el análisis", "Could not start analysis") + ": " + str(exc))
            return
    cambio = trabajos.leer(mapa_job)
    if not cambio:
        st.warning(tr("El trabajo de comparación no está disponible.", "Change analysis job is unavailable."))
        return
    if cambio["estado"] in trabajos.ACTIVOS:
        st.info(tr("Calculando el cambio SAR de ambas fechas…", "Calculating two-date SAR change…"))
        _mostrar_progreso(cambio, "calculo")
        return
    if cambio["estado"] != trabajos.APTO:
        st.warning(tr("No se pudo construir el mapa", "Could not generate map") + ": " +
                   str(cambio.get("error") or cambio["estado"]))
        st.caption(tr("Sin píxeles válidos y cuadrículas compatibles no se publica nada.",
                      "No layer is published without valid pixels and aligned grids."))
        if st.button(tr("Reintentar el cálculo", "Retry calculation"), key="v9_reintentar"):
            st.session_state["v9_mapa_job"] = None
            st.rerun(scope="app")
        return
    ruta = DATA_DIR / "analisis" / str(cambio.get("principal") or "")
    if not ruta.is_file():
        st.warning(tr("El GeoTIFF del análisis no está disponible.", "Analysis GeoTIFF is unavailable."))
        return
    res = leer_resultado(ruta)
    if not res.dibujable or not res.capa or not res.capa.procedencia.es_real:
        st.warning(tr("El mapa no supera los controles de procedencia y QA.",
                          "The map did not pass provenance and QA checks."))
        return
    _mostrar_progreso(cambio, "calculo")
    st.success(tr("Cambio NISAR preparado: señales, no inundaciones confirmadas.",
                  "NISAR change map ready: signal differences, not confirmed floods."))
    st.caption(tr("Colección", "Collection") + ": " +
               str((leer_preparacion(prep_id).get("madurez") or "VALIDATED")) +
               tr(" · Ver fechas y procedencia en la ficha.", " · See dates and provenance in Information."))
    if st.session_state.get("v9_publicado") != mapa_job:
        flujo.activar(id_resultado(ruta), sesion.ANALISIS, cambio["run_id"])
        st.session_state["v9_publicado"] = mapa_job
        st.session_state["ui_explorador"] = True
        st.rerun(scope="app")


def render() -> None:
    """Panel principal PC, preserva el editor científico existente sin reemplazarlo."""
    st.markdown(tr("### Analizar cambios en el agua", "### Analyze changes in surface water"))
    st.caption(tr("Selecciona únicamente la zona y el periodo. El motor elige las escenas compatibles "
               "y aplica QA; no tienes que escoger satélite ni descargar archivos manualmente. "
               "El resultado NISAR disponible es exploratorio, no una inundación confirmada.",
               "Select only your study area and time range. The system finds compatible scenes "
               "and applies quality checks; you do not need to choose a satellite or manually "
               "download files. NISAR changes are exploratory, not confirmed floods."))
    zona = flujo.zona_confirmada()
    if zona is None:
        st.info(tr("Elige otro lugar en el buscador y confirma su zona para empezar un nuevo análisis.",
                   "Find a location and confirm your study area to start a new analysis."))
        return
    if (st.session_state.get("v9_preparacion") or st.session_state.get("resultado_activo")):
        c1, c2 = st.columns(2)
        c1.button(tr("Nueva zona", "New area"), key="v9_nueva_zona", type="primary",
                  on_click=_nuevo_analisis, args=(True,), use_container_width=True)
        c2.button(tr("Otro período", "Different period"), key="v9_otro_periodo",
                  on_click=_nuevo_analisis, args=(False,), use_container_width=True)
        st.caption(tr("El historial se conserva. Puedes volver a abrir cualquier GeoTIFF anterior.",
                      "History is preserved. You can reopen any previous GeoTIFF."))
    st.caption(tr("Área confirmada en el mapa; no necesitas copiar coordenadas.",
                  "Your study area is confirmed on the map; no need to copy coordinates."))
    hoy = datetime.now(timezone.utc).date()
    inicio_def = hoy - timedelta(days=23)
    fin_def = hoy - timedelta(days=16)
    col_a, col_b = st.columns(2)
    inicio = col_a.date_input(tr("Inicio del periodo", "Start date"), value=inicio_def,
                              key="v9_inicio_periodo", format="YYYY-MM-DD")
    fin = col_b.date_input(tr("Fin del periodo", "End date"), value=fin_def,
                           key="v9_fin_periodo", format="YYYY-MM-DD")
    firma = _firma(zona, inicio, fin)
    # Priorizar los recortes aptos ya guardados, incluso si se prepararon
    # en una sesión anterior. No descargar el mismo par una segunda vez.
    preparado_prev = _preparacion_existente(zona, inicio, fin)
    if preparado_prev:
        st.caption(tr("Ya hay un par NISAR preparado para esta zona y periodo. "
                   "Se reutilizará sin repetir descargas de NASA Harmony.",
                   "A prepared NISAR pair already exists for this area and period. "
                   "It will be reused without repeating NASA Harmony downloads."))
    madurez = _madurez_del_periodo(inicio, fin)
    if madurez == "PROVISIONAL":
        st.caption(tr("Fuente seleccionada automáticamente: **NISAR PROVISIONAL** "
                   "(calibración parcial; visible en la ficha, no es inundación confirmada).",
                   "Automatically selected collection: **NISAR PROVISIONAL** "
                   "(partial calibration, reported in metadata; not a confirmed flood)."))
    else:
        st.caption(tr("Fuente seleccionada automáticamente: **NISAR VALIDATED**.",
                  "Automatically selected collection: **NISAR VALIDATED**."))
    if st.button(tr("Buscar y analizar cambios", "Find and analyze changes"), key="v9_analizar", type="primary",
                 use_container_width=True):
        _limpiar_v9()
        flujo.limpiar_resultado()
        if preparado_prev:
            st.session_state.update(v9_firma=firma, v9_preparacion=preparado_prev["job_id"],
                                    nisar_auto_job=preparado_prev["job_id"])
        else:
            with st.spinner(tr("Consultando NASA CMR para elegir un par comparable…",
                            "Querying NASA CMR for a comparable image pair…")):
                try:
                    job_id = _solicitar(zona, inicio, fin)
                    st.session_state.update(v9_firma=firma, v9_preparacion=job_id,
                                            nisar_auto_job=job_id)
                except (ValueError, nisar_auto.ErrorAutoNISAR) as exc:
                    st.session_state["v9_error"] = str(exc)
                except Exception:
                    st.session_state["v9_error"] = tr(
                        "No se pudo consultar el catálogo ni preparar las imágenes. Revisa Harmony.",
                        "Could not query the catalog or prepare imagery. Check Harmony.")
    if st.session_state.get("v9_error"):
        st.warning(st.session_state["v9_error"])
    _mostrar_sugerencias(firma)
    _seguimiento(firma)
    if st.button(
        tr("Ver GeoTIFF anteriores (sin volver a descargar)",
           "View previous GeoTIFFs (without redownloading)"),
        key="v9_ver_guardados",
        on_click=_abrir_modo_jurado,
        help="Archivos reales del historial; podrían ser de fechas distintas a las seleccionadas.",
    ):
        st.rerun(scope="app")
    st.caption(tr("El producto inicial será ΔdB (cambio SAR real). No genera probabilidades, "
               "clases de inundación ni predicciones de Machine Learning.",
               "The initial output is ΔdB (actual SAR signal change). It does not produce flood "
               "probabilities, flood classes or machine-learning predictions."))
