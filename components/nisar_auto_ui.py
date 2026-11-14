"""NISAR PRINCIPAL: adquisición automática de insumos GCOV para inundaciones.

El usuario solo confirma AOI y fechas; ningún HDF5 se copia a mano.
La descarga requiere click explícito tras mostrar presupuesto de GB y el
token Earthdata configurado en Secrets. Se ejecuta con cola existente.
Los recortes NO se publican como mapas de inundación.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, datetime, timezone

import streamlit as st

from utils import nisar_auto, nisar_catalogo as cat, nisar_descarga, nisar_gcov, trabajos
from utils.config import DATA_DIR


def _huella(plan) -> str:
    contenido = json.dumps({"granules": plan.granules, "aoi": list(plan.aoi),
                            "termino": plan.termino, "motor": "NISAR GCOV"}, sort_keys=True)
    return hashlib.sha256(contenido.encode()).hexdigest()


def _ejecutar_en_cola(resultado, plan):
    registro = cat.registro_json(resultado)
    carpeta = DATA_DIR / "nisar" / "catalogo"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"auto_{uuid.uuid4().hex}.json"
    with ruta.open("x", encoding="utf-8") as archivo:
        json.dump(registro, archivo, indent=2, ensure_ascii=False)
    identificador = _huella(plan)

    def tarea(ctx: trabajos.Contexto):
        ctx.fase("zona", trabajos.APTO, "AOI dentro de Colombia")
        ctx.fase("escenas", trabajos.APTO, f"{len(plan.candidatos)} GCOV del catálogo NASA/ASF")
        ctx.fase("datos", trabajos.EN_CURSO, "Descargando NISAR auténtico, sin sobrescribir")
        ctx.comprobar("antes de descargar")

        def notificar(etapa, _granule):
            ctx.comprobar(etapa)
            ctx.fase("datos" if etapa == "descarga" else "preparacion", trabajos.EN_CURSO, etapa)

        salida = nisar_auto.preparar(plan, ruta, notificar=notificar)
        ctx.fase("datos", trabajos.APTO, "HDF5 descargados/reutilizados con tamaño comprobado")
        ctx.fase("preparacion", trabajos.APTO, "Señal gamma0 recortada, sin interpretación de inundación")
        ctx.comprobar("verificación")
        ctx.fase("verificacion", trabajos.EN_CURSO, "Registrando procedencia de insumos GCOV")
        resumen = carpeta / f"resultado_{ctx.job_id}.json"
        with resumen.open("x", encoding="utf-8") as archivo:
            json.dump(salida, archivo, indent=2, ensure_ascii=False)
        geotiffs = [nisar_gcov.CARPETA_NISAR / x["geotiff"] for x in salida["escenas"]]
        ctx.resultado(geotiffs[-1], resumen, geotiffs, list(plan.avisos))
        ctx.fase("verificacion", trabajos.APTO, "Insumos preparados; no es un mapa de inundación")
    t, _ = trabajos.crear_o_reutilizar(
        identificador, {
            "tipo": "adquisicion_nisar_gcov",
            "sensor": "NISAR", "procesador": "nisar_gcov",
            "aoi": {"limites": list(plan.aoi)}, "escenas": list(plan.granules),
        }, tarea,
    )
    return t


@st.fragment(run_every=2.0)
def _mostrar_trabajo(job_id: str):
    t = trabajos.leer(job_id)
    if not t:
        st.warning("No se encontró el trabajo de adquisición NISAR.")
        return
    st.markdown(f"**Estado de preparación:** {t['estado']}")
    for f in t.get("fases") or []:
        if f["estado"] != trabajos.PENDIENTE:
            st.caption(f"{f['nombre']}: {f['estado']} · {f.get('detalle') or ''}")
    if t["estado"] in trabajos.ACTIVOS:
        st.info("Preparando archivos NISAR. Puedes seguir explorando el mapa; la aplicación supervisa el proceso.")
        if st.button("Solicitar cancelación", key="nisar_cancelar"):
            trabajos.cancelar(job_id)
    elif t["estado"] == trabajos.APTO:
        st.success("Los insumos NISAR están preparados. Todavía no son un mapa de inundación.")
        st.caption("Recortes GCOV en data/nisar/; consulta el registro de procedencia antes del análisis.")
    else:
        st.warning(f"El trabajo no se completó: {t.get('error') or t['estado']}")


def render(region, error: str | None):
    st.markdown("### NISAR · radar principal para estudiar inundaciones")
    st.caption("NISAR L2 GCOV · banda L · NASA/ASF. "
               "Al buscar, V.I.S.O.R. propone archivos para la zona; "
               "al autorizar, los descarga y prepara sin copiar GeoTIFF manualmente.")
    if region is None:
        st.info(error or "Primero dibuja y confirma un área dentro de Colombia en el paso Área.")
        return
    inicio_defecto = cat.INICIO_VALIDATED
    fecha_hoy = datetime.now(timezone.utc).date()
    a, b = st.columns(2)
    inicio = a.date_input("Desde", value=inicio_defecto, key="nisar_auto_inicio")
    fin = b.date_input("Hasta", value=fecha_hoy, key="nisar_auto_fin")
    max_gb = st.slider("Límite de descarga (GB)", 1, 10, 5, key="nisar_max_gb",
                       help="La descarga se impide si no hay espacio suficiente. Un par puede ocupar varios GB.")
    clave = (tuple(region.limites), str(inicio), str(fin), max_gb)
    if st.button("1. Buscar NISAR disponible", key="nisar_auto_buscar", type="primary"):
        with st.spinner("Consultando el catálogo NASA/ASF (sin descargar)…"):
            try:
                if inicio > fin:
                    raise nisar_auto.ErrorAutoNISAR("La fecha inicial debe ser anterior a la final.")
                resultado = cat.buscar(*region.limites, inicio, fin, madurez="VALIDATED")
                plan = nisar_auto.planear(resultado, max_gb=float(max_gb))
                st.session_state["nisar_auto_plan"] = {"clave": clave, "resultado": resultado, "plan": plan}
                st.session_state["nisar_auto_error"] = None
            except Exception as exc:
                st.session_state["nisar_auto_error"] = str(exc) if isinstance(exc, nisar_auto.ErrorAutoNISAR) else (
                    "No se pudieron consultar o preparar candidatos NISAR. Revisa la conexión y las fechas.")
                st.session_state.pop("nisar_auto_plan", None)
    if st.session_state.get("nisar_auto_error"):
        st.warning(st.session_state["nisar_auto_error"])
    guardado = st.session_state.get("nisar_auto_plan")
    if guardado and guardado["clave"] == clave:
        plan = guardado["plan"]
        st.markdown(f"**Propuesta:** {plan.tipo.replace('_', ' ').lower()} · "
                    f"{len(plan.candidatos)} archivo(s) · **{plan.tamano_bytes/1e9:.2f} GB** · "
                    f"cubre aproximadamente **{plan.cobertura:.0%}** del área.")
        for aviso in plan.avisos:
            st.caption(aviso)
        if not os.environ.get(nisar_descarga.VARIABLE_TOKEN, "").strip():
            st.info("Para descargar, configura EARTHDATA_TOKEN en los Secrets de Replit. "
                    "No escribas la credencial aquí ni en el repositorio.")
        else:
            if st.button("2. Descargar y preparar NISAR automáticamente", key="nisar_auto_descargar",
                         type="primary", help="Descarga hasta el límite mostrado. No sobrescribe archivos."):
                try:
                    t = _ejecutar_en_cola(guardado["resultado"], plan)
                    st.session_state["nisar_auto_job"] = t["job_id"]
                except (OSError, ValueError) as exc:
                    st.error("No se pudo iniciar el trabajo NISAR; verifica el disco y vuelve a intentarlo.")
    elif guardado:
        st.info("La zona o las fechas cambiaron. Busca de nuevo antes de descargar.")
    job_id = st.session_state.get("nisar_auto_job")
    if job_id:
        _mostrar_trabajo(job_id)
    st.caption("Estos archivos son insumos de radar reales, no detecciones automáticas de inundación. "
               "Si no hay un par temporal compatible, no se publicará un mapa de cambio.")
