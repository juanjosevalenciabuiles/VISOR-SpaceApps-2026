"""Puente V9: insumos NISAR/Harmony ya preparados -> cambio SAR georreferenciado.

La salida es Δ gamma0 (dB), NO una clasificación ni predicción de inundaciones.
No consulta la red, no modifica los COG originales y no inventa máscaras QA.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from utils import nisar_catalogo
from utils.config import DATA_DIR
from utils.procedencia import sha256_archivo
from utils.resultados import MAX_BYTES_RESULTADO, leer_resultado
from utils.v9_datos.cambio_cog import QAInsuficiente, procesar_par

CATALOGO = DATA_DIR / "nisar" / "catalogo"
HARMONY = DATA_DIR / "nisar" / "harmony"
DESTINO = DATA_DIR / "analisis"
LAYERS = ("HHHH", "VVVV")
ARCHIVOS_QA = ("mask.tif", "numberOfLooks.tif")


def _ruta_segura(carpeta: Path, nombre: str) -> Path:
    if (not isinstance(nombre, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", nombre)
            or nombre in (".", "..")):
        raise QAInsuficiente("SIN_QA: nombre de archivo o carpeta no seguro")
    ruta = (carpeta / nombre).resolve()
    if ruta.parent != carpeta.resolve():
        raise QAInsuficiente("SIN_QA: ruta fuera del área de datos")
    return ruta


def leer_preparacion(job_id: str) -> dict:
    """Solo manifiesto autenticado por trabajo NISAR; nunca nombres arbitrarios."""
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{16}", job_id):
        raise QAInsuficiente("Identificador de trabajo NISAR inválido")
    ruta = CATALOGO / f"resultado_{job_id}.json"
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise QAInsuficiente("No se encuentra el manifiesto NISAR ya preparado") from exc
    if (datos.get("estado") != "NISAR_COG_PREPARADO_SIN_CLASIFICAR"
            or datos.get("metodo") != "NASA_HARMONY"):
        raise QAInsuficiente("La preparación no contiene un par Harmony COG verificable")
    return datos


def escenas_preparadas(manifiesto: dict) -> list[dict]:
    """Conservar la fuente real y exigir correspondencia exacta de ambas tomas."""
    plan = manifiesto.get("plan") or {}
    escenas = manifiesto.get("escenas") or []
    granules = plan.get("granules") or []
    termino = plan.get("termino")
    if (plan.get("tipo") != "PAR" or len(escenas) != 2 or len(granules) != 2
            or termino not in LAYERS):
        raise QAInsuficiente("SIN_PAR: faltan dos escenas con copolarización válida")
    if set(g.get("granule") for g in escenas) != set(granules):
        raise QAInsuficiente("SIN_QA: escenas ajenas al plan original")
    nombres = [nisar_catalogo.leer_nombre(g["granule"]) for g in escenas]
    if any(n is None for n in nombres):
        raise QAInsuficiente("SIN_QA: granules NISAR sin nombre verificable")
    a, b = nombres
    if (a.geometria != b.geometria or a.crid != b.crid
            or a.inicio >= b.inicio):
        raise QAInsuficiente("SIN_PAR: órbita, stack, versión o fechas incompatibles")
    if (termino == "HHHH" and "HH" not in a.pol_a) or (termino == "VVVV" and "VV" not in a.pol_a):
        raise QAInsuficiente("SIN_PAR: polarización incompatible con granules")
    madurez = manifiesto.get("madurez") or "VALIDATED"
    # El productor V8 legacy solo busca en la colección VALIDATED; no procesamos
    # un manifiesto que declare otra madurez que el puente no sabe comprobar.
    if madurez != "VALIDATED":
        raise QAInsuficiente("SIN_QA: fuente no validada por este pipeline")
    meta = []
    for escena, nombre in zip(escenas, nombres, strict=True):
        carpeta = _ruta_segura(HARMONY, escena.get("carpeta_relativa"))
        declarados = escena.get("archivos") or []
        requeridos = [f"{termino}.tif", *ARCHIVOS_QA]
        if not set(requeridos).issubset(declarados):
            raise QAInsuficiente("SIN_QA: falta máscara, looks o gamma0 en Harmony")
        archivos = [_ruta_segura(carpeta, v) for v in requeridos]
        if not all(r.is_file() for r in archivos):
            raise QAInsuficiente("SIN_QA: faltan archivos COG de la preparación")
        meta.append({
            "sensor": "NISAR", "banda": "L", "orbita": f"{nombre.track}:{nombre.direccion}",
            "stack": f"{nombre.frame}:{nombre.modo_a}:{nombre.modo_b}:{nombre.crid}",
            "madurez": madurez, "polarizacion": termino,
            "observed_at": nombre.inicio.isoformat(), "granule": nombre.granule,
            "cog": str(archivos[0]), "qa_mask": str(archivos[1]), "looks": str(archivos[2]),
        })
    return meta


def procesar_preparacion(job_id: str) -> dict:
    """Calcular SOLO si hay 2 fechas con QA, mismas celdas y COG originales íntegros."""
    manifiesto = leer_preparacion(job_id)
    escenas = escenas_preparadas(manifiesto)
    DESTINO.mkdir(parents=True, exist_ok=True)
    firma = hashlib.sha256((job_id + "|" + "|".join(e["granule"] for e in escenas)).encode()).hexdigest()[:20]
    ruta = DESTINO / f"nisar_v9_{firma}_dif_db.tif"
    ficha = ruta.with_suffix(".json")
    if ruta.exists() or ficha.exists():
        if not ruta.is_file() or not ficha.is_file():
            raise QAInsuficiente("Salida parcialmente escrita: no se sobrescribe")
        estado = leer_resultado(ruta)
        if (not estado.dibujable or not estado.capa or not estado.capa.procedencia.es_real
                or estado.perfil.clave != "diferencia_db"):
            raise QAInsuficiente("El archivo previo no superó la verificación de procedencia")
        return {"estado": "CAMBIO_DB_EXPLORATORIO", "raster": str(ruta), "ficha": str(ficha),
                "reutilizado": True, "advertencia": "Cambio SAR, no mapa de inundación"}
    resultado = procesar_par(escenas[0], escenas[1], ruta, minimo_looks=1.0, minimo_validos=1)
    if ruta.stat().st_size > MAX_BYTES_RESULTADO:
        raise QAInsuficiente("Mapa de cambio demasiado grande para el visor (max. 200 MB)")
    verificado = leer_resultado(ruta)
    if (not verificado.dibujable or not verificado.capa
            or verificado.capa.procedencia.estado != "real_sin_validar"
            or verificado.perfil.clave != "diferencia_db"):
        raise QAInsuficiente("El mapa nuevo no pasó la verificación de capa y trazabilidad")
    if sha256_archivo(ruta) != resultado["sha256"]:
        raise QAInsuficiente("El resultado no coincide con su SHA-256")
    return {**resultado, "reutilizado": False,
            "advertencia": "Cambio de señal de radar NISAR L. NO es inundación confirmada."}
