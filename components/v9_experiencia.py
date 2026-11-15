"""Experiencia PC: área + periodo -> COG NISAR -> mapa real de cambio SAR.

No afirma inundaciones ni predicciones; evita volver a descargar COG ya preparados.
Las opciones especializadas continúan en Herramientas SAR por compatibilidad.
"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import streamlit as st

from components import flujo
from utils import nisar_auto, nisar_catalogo as cat, nisar_descarga, sesion, trabajos
from utils.config import DATA_DIR
from utils.resultados import id_resultado, leer_resultado
from utils.v9_nisar_puente import QAInsuficiente, escenas_preparadas, leer_preparacion
from utils.v9_trabajo_mapa import iniciar

MAX_HARMONY_MB = 384
MARGEN_DIAS = 45


def _firma(zona, inicio: date, fin: date):
    return (tuple(zona), inicio.isoformat(), fin.isoformat())


def _fechas_de_preparacion(job_id: str):
    datos = leer_preparacion(job_id)
    pares = escenas_preparadas(datos)
    return (date.fromisoformat(pares[0]["observed_at"][:10]),
            date.fromisoformat(pares[1]["observed_at"][:10]))


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
    return pre < inicio <= fin < post


def _solicitar(zona, inicio: date, fin: date):
    if inicio > fin or fin >= datetime.now(timezone.utc).date():
        raise ValueError("El periodo debe terminar antes de hoy para buscar una imagen posterior.")
    if inicio <= cat.INICIO_VALIDATED:
        raise ValueError(
            "Esta integración consulta NISAR VALIDATED (adquisiciones desde el 21/10/2026). "
            "Para periodos anteriores se requiere el flujo PROVISIONAL, separado y señalizado."
        )
    if not os.environ.get(nisar_descarga.VARIABLE_TOKEN, "").strip():
        raise ValueError("Configura EARTHDATA_TOKEN en los Secrets de Replit; no lo pegues en el chat.")
    desde = max(cat.INICIO_VALIDATED, inicio - timedelta(days=MARGEN_DIAS))
    hasta = min(datetime.now(timezone.utc).date(), fin + timedelta(days=MARGEN_DIAS))
    resultado = cat.buscar(*zona, desde, hasta, madurez="VALIDATED")
    candidatos = [p for p in resultado.pares
                  if p.antes.nombre.inicio.date() < inicio and p.despues.nombre.inicio.date() > fin]
    if not candidatos:
        raise ValueError(
            "Sin un par NISAR comparable antes y después del periodo. "
            "No se inventará un mapa: prueba con otra zona o un periodo histórico más corto."
        )
    plan = nisar_auto.planear(
        replace(resultado, pares=candidatos), max_gb=15.0, aceptar_escena_unica=False,
    )
    # El clic del usuario autoriza un recorte de máximo 384 MiB; nunca HDF5 completos.
    from components import nisar_auto_ui
    preparado = nisar_auto_ui._ejecutar_en_cola(
        resultado, plan, nisar_auto_ui.METODOS[0], MAX_HARMONY_MB,
    )
    return preparado["job_id"]


@st.fragment(run_every=2.0)
def _seguimiento(firma):
    if st.session_state.get("v9_firma") != firma:
        return
    prep_id = st.session_state.get("v9_preparacion")
    if not prep_id:
        return
    preparacion = trabajos.leer(prep_id)
    if preparacion is None:
        st.warning("No se pudo recuperar el trabajo NISAR de esta sesión.")
        return
    if preparacion["estado"] in trabajos.ACTIVOS:
        en_curso = next((f for f in preparacion.get("fases", [])
                         if f["estado"] == trabajos.EN_CURSO), None)
        st.info("Preparando imágenes NISAR reales: " +
                (en_curso.get("detalle") if en_curso else "trabajo en cola"))
        return
    if preparacion["estado"] != trabajos.APTO:
        st.warning("La preparación NISAR no terminó: " +
                   str(preparacion.get("error") or preparacion["estado"]))
        return
    zona = flujo.zona_confirmada()
    inicio, fin = date.fromisoformat(firma[1]), date.fromisoformat(firma[2])
    if not zona or tuple(zona) != firma[0] or not _compatible(preparacion, zona, inicio, fin):
        st.warning("Los COG preparados no corresponden a este AOI y periodo; se evita generar un mapa incorrecto.")
        return
    mapa_job = st.session_state.get("v9_mapa_job")
    if not mapa_job:
        try:
            mapa_job = iniciar(preparacion)["job_id"]
            st.session_state["v9_mapa_job"] = mapa_job
        except (ValueError, OSError, QAInsuficiente) as exc:
            st.warning("No se pudo iniciar el cálculo de cambio SAR: " + str(exc))
            return
    cambio = trabajos.leer(mapa_job)
    if not cambio:
        st.warning("El trabajo de comparación todavía no está disponible.")
        return
    if cambio["estado"] in trabajos.ACTIVOS:
        st.info("Analizando cambios entre dos fechas NISAR. No se está clasificando inundación.")
        return
    if cambio["estado"] != trabajos.APTO:
        st.warning("No se pudo construir el mapa de cambios: " +
                   str(cambio.get("error") or cambio["estado"]))
        st.caption("Sin datos válidos o cuadrículas compatibles no se publica ninguna capa.")
        if st.button("Reintentar el cálculo", key="v9_reintentar"):
            st.session_state["v9_mapa_job"] = None
            st.rerun(scope="app")
        return
    ruta = DATA_DIR / "analisis" / str(cambio.get("principal") or "")
    if not ruta.is_file():
        st.warning("El análisis terminó, pero su GeoTIFF no está disponible.")
        return
    res = leer_resultado(ruta)
    if not res.dibujable or not res.capa or not res.capa.procedencia.es_real:
        st.warning("El mapa todavía no supera los controles de procedencia y QA.")
        return
    st.success("Mapa de cambio NISAR preparado. Muestra diferencias de señal, no inundaciones confirmadas.")
    if st.session_state.get("v9_publicado") != mapa_job:
        flujo.activar(id_resultado(ruta), sesion.ANALISIS, cambio["run_id"])
        st.session_state["v9_publicado"] = mapa_job
        st.session_state["ui_explorador"] = True
        st.rerun(scope="app")


def render() -> None:
    """Panel principal PC, preserva el editor científico existente sin reemplazarlo."""
    st.markdown("### Analizar cambios en el agua")
    st.caption("Elige la zona en el mapa y un periodo de interés. NISAR L se consulta primero; "
               "los resultados de radar no son por sí solos mapas de inundación.")
    zona = flujo.zona_confirmada()
    if zona is None:
        st.info("Primero dibuja o confirma una zona en «1 · Zona».")
        return
    st.caption("Área confirmada en el mapa; no necesitas copiar coordenadas.")
    hoy = datetime.now(timezone.utc).date()
    inicio_def = hoy - timedelta(days=23)
    fin_def = hoy - timedelta(days=16)
    col_a, col_b = st.columns(2)
    inicio = col_a.date_input("Inicio del periodo", value=inicio_def,
                              key="v9_inicio_periodo", format="YYYY-MM-DD")
    fin = col_b.date_input("Fin del periodo", value=fin_def,
                           key="v9_fin_periodo", format="YYYY-MM-DD")
    firma = _firma(zona, inicio, fin)
    preparado_prev = None
    previo_id = st.session_state.get("nisar_auto_job")
    if previo_id:
        preparado_prev = trabajos.leer(previo_id)
    if preparado_prev and _compatible(preparado_prev, zona, inicio, fin):
        if st.button("Usar recortes NISAR ya preparados (sin descargar)", key="v9_reutilizar"):
            st.session_state.update(v9_firma=firma, v9_preparacion=previo_id,
                                    v9_mapa_job=None, v9_publicado=None)
    if st.button("Buscar y analizar cambios", key="v9_analizar", type="primary"):
        st.session_state["v9_error"] = None
        st.session_state.update(v9_firma=None, v9_preparacion=None,
                                v9_mapa_job=None, v9_publicado=None)
        if preparado_prev and _compatible(preparado_prev, zona, inicio, fin):
            st.session_state.update(v9_firma=firma, v9_preparacion=previo_id)
        else:
            with st.spinner("Buscando escenas NISAR comparables en NASA/ASF…"):
                try:
                    job_id = _solicitar(zona, inicio, fin)
                    st.session_state.update(v9_firma=firma, v9_preparacion=job_id,
                                            nisar_auto_job=job_id)
                except (ValueError, nisar_auto.ErrorAutoNISAR) as exc:
                    st.session_state["v9_error"] = str(exc)
                except Exception:
                    st.session_state["v9_error"] = ("No se pudo iniciar la consulta NASA/ASF. "
                                                     "Verifica conectividad y credenciales.")
    if st.session_state.get("v9_error"):
        st.warning(st.session_state["v9_error"])
    _seguimiento(firma)
    st.caption("El producto inicial será ΔdB (cambio SAR real). No genera probabilidades, "
               "clases de inundación ni predicciones de Machine Learning.")
