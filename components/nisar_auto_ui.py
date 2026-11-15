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

from utils import nisar_auto, nisar_catalogo as cat, nisar_descarga, nisar_gcov, trabajos
from utils.config import DATA_DIR

METODOS = ("Recorte optimizado · NASA Harmony", "HDF5 completo · alternativa")


def _huella(plan, metodo, max_mb):
    contenido = json.dumps({
        "granules": plan.granules, "aoi": list(plan.aoi), "termino": plan.termino,
        "metodo": metodo, "presupuesto_mb": max_mb, "motor": "NISAR GCOV insumos",
    }, sort_keys=True)
    return hashlib.sha256(contenido.encode()).hexdigest()


def _ejecutar_en_cola(resultado, plan, metodo, max_mb):
    registro = cat.registro_json(resultado)
    carpeta = DATA_DIR / "nisar" / "catalogo"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"auto_{uuid.uuid4().hex}.json"
    with ruta.open("x", encoding="utf-8") as archivo:
        json.dump(registro, archivo, indent=2, ensure_ascii=False)
    identificador = _huella(plan, metodo, max_mb)

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
                ctx.fase("preparacion", trabajos.EN_CURSO, "NASA Harmony está preparando los COG")
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
        salida["madurez"] = resultado.madurez  # Procedencia explícita del catálogo validado
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


@st.fragment(run_every=2.0)
def _mostrar_trabajo(job_id: str):
    t = trabajos.leer(job_id)
    if not t:
        st.warning("No se encontró el trabajo de adquisición NISAR.")
        return
    st.markdown(f"**Estado de preparación:** {t['estado']}")
    for f in t.get("fases") or []:
        if f["estado"] != trabajos.PENDIENTE:
            # La cola genérica dice «Resultado publicado», pero aquí solo se publica
            # el manifiesto de INSUMOS, no una capa ambiental dibujable.
            if f["clave"] == "listo" and t["estado"] == trabajos.APTO:
                st.caption("Preparación terminada: APTO · Insumos NISAR guardados, sin clasificación de agua")
            else:
                st.caption(f"{f['nombre']}: {f['estado']} · {f.get('detalle') or ''}")
    if t["estado"] in trabajos.ACTIVOS:
        st.info("Preparando las capas NISAR solicitadas; puedes continuar explorando el mapa.")
        if st.button("Solicitar cancelación", key="nisar_cancelar"):
            trabajos.cancelar(job_id)
    elif t["estado"] == trabajos.APTO:
        st.success("Los insumos NISAR están preparados. Todavía no son un mapa de inundación.")
        st.caption("Datos y manifiestos en data/nisar/; se conserva resolución nativa y procedencia.")
    else:
        st.warning(f"El trabajo no se completó: {t.get('error') or t['estado']}")


def render(region, error: str | None):
    st.markdown("### NISAR · sensor principal para estudiar inundaciones")
    st.caption("NASA/ASF L2 GCOV banda L. Con Harmony descargamos solo tu área y las capas científicas "
               "necesarias, sin traer el HDF5 completo de varios GB.")
    if region is None:
        st.info(error or "Primero dibuja y confirma un área en Colombia.")
        return

    a, b = st.columns(2)
    inicio = a.date_input("Desde", value=cat.INICIO_VALIDATED, key="nisar_auto_inicio")
    fin = b.date_input("Hasta", value=datetime.now(timezone.utc).date(), key="nisar_auto_fin")
    metodo = st.radio("Forma de obtener los datos", METODOS, horizontal=True,
                      key="nisar_auto_metodo", help="Harmony es más eficiente para áreas pequeñas.")
    if metodo == METODOS[0]:
        max_mb = st.slider("Almacenamiento máximo para imágenes recortadas (MB)", 128, 512, 384, 64,
                           key="nisar_max_mb",
                           help="Límite real de transferencia. No se reduce la resolución.")
        max_gb = 15
        st.caption("Solicitud remota: HH/HV (según disponibilidad), máscara y número de observaciones; "
                   "sin reproyección ni interpolación. No puede calcular inundaciones de una fecha única.")
    else:
        max_gb = st.slider("Presupuesto máximo para HDF5 completos (GB)", 1, 10, 5,
                           key="nisar_max_gb",
                           help="Solo como alternativa autorizada. Necesita varios GB de espacio.")
        max_mb = 0
        st.warning("Esta alternativa descarga archivos completos de 1 a varios GB. "
                   "Harmony es preferible cuando está disponible.")

    clave = (tuple(region.limites), str(inicio), str(fin), metodo, max_mb, max_gb)
    if st.button("1. Buscar imágenes NISAR", key="nisar_auto_buscar", type="primary"):
        with st.spinner("Consultando NASA/ASF, sin descargar imágenes…"):
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
        st.markdown(f"**Propuesta:** {plan.tipo.replace('_', ' ').lower()} · "
                    f"{len(plan.candidatos)} fecha(s) · "
                    f"cobertura aproximada **{plan.cobertura:.0%}** de la zona.")
        if metodo == METODOS[0]:
            st.caption(f"El HDF5 original suma {plan.tamano_bytes/1e9:.2f} GB, pero **NO se descargará**. "
                       f"Límite máximo de descarga COG: {max_mb} MB, sujeto a disponibilidad Harmony.")
        else:
            st.caption(f"Tamaño de HDF5 completos: {plan.tamano_bytes/1e9:.2f} GB.")
        for aviso in plan.avisos:
            st.caption(aviso)
        if not os.environ.get(nisar_descarga.VARIABLE_TOKEN, "").strip():
            st.info("Configura EARTHDATA_TOKEN mediante Replit Secrets para autorizar a NASA. "
                    "Nunca escribas el token en el chat ni en GitHub.")
        elif st.button("2. Descargar y preparar las capas automáticamente", key="nisar_auto_descargar",
                       type="primary"):
            try:
                t = _ejecutar_en_cola(guardado["resultado"], plan, metodo, max_mb)
                st.session_state["nisar_auto_job"] = t["job_id"]
            except (OSError, ValueError):
                st.error("No se pudo iniciar el trabajo; revisa el espacio disponible.")
    elif guardado:
        st.info("Has cambiado el área, las fechas o el presupuesto. Busca de nuevo antes de descargar.")
    if st.session_state.get("nisar_auto_job"):
        _mostrar_trabajo(st.session_state["nisar_auto_job"])
    st.caption("Los COG son datos calibrados de radar. Su contenido NO es una clasificación "
               "automática de agua ni una confirmación de inundaciones.")
