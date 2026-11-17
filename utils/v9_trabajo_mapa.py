"""Trabajo controlado que transforma COG preparados en un cambio SAR del visor."""
from __future__ import annotations

import hashlib
from pathlib import Path

from utils import trabajos
from utils.v9_nisar_puente import leer_preparacion, procesar_preparacion


def iniciar(preparacion: dict) -> dict:
    """Reutilizar trabajo activo sin recalcular ni degradar la preparación existente."""
    if (preparacion.get("estado") != trabajos.APTO
            or preparacion.get("tipo") != "adquisicion_nisar_gcov"
            or preparacion.get("procesador") != "harmony_cog"):
        raise ValueError("No hay dos COG de Harmony preparados para construir un cambio SAR")
    job_id = preparacion["job_id"]
    datos = leer_preparacion(job_id)
    if len(datos.get("escenas") or []) != 2 or (datos.get("plan") or {}).get("tipo") != "PAR":
        raise ValueError("Se necesitan dos fechas NISAR; una escena sola no produce cambio")
    firma = hashlib.sha256(("v9-cambio-cog-v1:" + job_id).encode()).hexdigest()

    def ejecutar(ctx: trabajos.Contexto) -> None:
        ctx.fase("zona", trabajos.APTO, "Usando AOI original de la preparación")
        ctx.fase("escenas", trabajos.APTO, "Dos tomas NISAR preparadas")
        ctx.fase("datos", trabajos.APTO, "COG gamma0, mask y numberOfLooks existentes")
        ctx.fase("preparacion", trabajos.APTO, "Sin volver a descargar HDF5 ni COG")
        ctx.fase("calculo", trabajos.EN_CURSO, "Calculando diferencia dB solo en píxeles QA válidos")
        ctx.comprobar("antes del cálculo")
        salida = procesar_preparacion(job_id)
        ctx.fase("calculo", trabajos.APTO, "Cambio de retrodispersión, sin clasificación de inundación")
        ctx.fase("verificacion", trabajos.EN_CURSO, "Comprobando GeoTIFF y ficha con SHA256")
        raster, ficha = Path(salida["raster"]), Path(salida["ficha"])
        ctx.resultado(raster, ficha, [raster, ficha], [
            "Resultado exploratorio NISAR L, no confirma inundaciones.",
            "Fechas reales de las tomas en ficha; no es predicción ML.",
        ])
        ctx.fase("verificacion", trabajos.APTO, "Resultado SAR con trazabilidad listo para el visor")

    tarea, _ = trabajos.crear_o_reutilizar(
        firma, {"tipo": "cambio_nisar_v9", "sensor": "NISAR", "preparacion_job_id": job_id,
                "aoi": preparacion.get("aoi"), "escenas": preparacion.get("escenas")}, ejecutar)
    return tarea
