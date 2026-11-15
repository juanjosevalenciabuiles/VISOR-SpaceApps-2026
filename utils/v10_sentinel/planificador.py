"""Planificación conservadora de OPERA DSWx-S1, sin descarga ni interpretación de píxeles.

Los registros son metadatos normalizados de CMR; no constituyen evidencia de agua.
"""
from __future__ import annotations

from datetime import date
from utils.v10_sentinel.validacion import bbox_valida, fecha_observacion, url_candidata

COLLECTION = "OPERA_L3_DSWX-S1_V1"
MAX_BYTES = 384 * 1024 * 1024


def _fecha(value: str) -> date:
    if isinstance(value, str) and len(value) == 10:
        return date.fromisoformat(value)
    return fecha_observacion(value).date()


def _bbox(value: object) -> tuple[float, float, float, float]:
    return bbox_valida(value)


def _cubre(aoi: tuple[float, ...], footprint: object) -> bool:
    """Solo permite cobertura completa demostrable por bbox; no mosaica teselas."""
    try:
        w, s, e, n = _bbox(footprint)
    except (ValueError, TypeError):
        return False
    return w <= aoi[0] and s <= aoi[1] and e >= aoi[2] and n >= aoi[3]


def planificar(aoi_bbox: object, inicio: str, fin: str, escenas: list[dict],
               *, presupuesto_bytes: int = MAX_BYTES) -> dict:
    """Elige pre y post con cobertura total; NO produce clasificación ni descarga.

    Una fecha pre es anterior a inicio y una post posterior a fin. Las escenas
    dentro del intervalo no reemplazan arbitrariamente al baseline.
    """
    aoi = _bbox(aoi_bbox)
    desde, hasta = _fecha(inicio), _fecha(fin)
    if hasta < desde or not 0 < presupuesto_bytes <= MAX_BYTES:
        raise ValueError("Periodo o presupuesto inválido")
    candidatas = []
    rechazadas = {}
    for item in escenas:
        motivo = None
        try:
            fecha = _fecha(item["observed_at"])
            url = item["wtr_url"]
            nbytes = item["estimated_window_bytes"]
            if item.get("collection") != COLLECTION:
                motivo = "COLECCION"
            elif not url_candidata(url):
                motivo = "URL"
            elif not _cubre(aoi, item.get("bbox")):
                motivo = "COBERTURA"
            elif type(nbytes) is not int or nbytes <= 0 or nbytes > presupuesto_bytes:
                motivo = "PRESUPUESTO"
            elif not item.get("granule_id") or not item.get("source_s1_granule"):
                motivo = "LINAJE"
            elif item.get("qa_metadata") != "APTO":
                motivo = "QA"
            else:
                candidatas.append((fecha, item))
        except (KeyError, ValueError, TypeError):
            motivo = "METADATOS"
        if motivo:
            rechazadas[motivo] = rechazadas.get(motivo, 0) + 1
    anteriores = sorted((x for x in candidatas if x[0] < desde), key=lambda x: x[0], reverse=True)
    posteriores = sorted((x for x in candidatas if x[0] > hasta), key=lambda x: x[0])
    for pre_fecha, pre in anteriores:
        for post_fecha, post in posteriores:
            if pre["estimated_window_bytes"] + post["estimated_window_bytes"] > presupuesto_bytes:
                continue
            return {"estado": "APTA_METADATA", "pre": pre, "post": post,
                    "fechas_reales": [pre_fecha.isoformat(), post_fecha.isoformat()],
                    "presupuesto_bytes": presupuesto_bytes, "rechazos": rechazadas,
                    "advertencia": "Pendiente QA de píxeles WTR; no es mapa de inundación."}
    return {"estado": "NO_APTA" if candidatas or rechazadas else "SIN_DATOS",
            "motivo": "SIN_PAR_COMPLETO", "rechazos": rechazadas,
            "advertencia": "Sin cobertura/par/presupuesto verificable; no generar raster."}
