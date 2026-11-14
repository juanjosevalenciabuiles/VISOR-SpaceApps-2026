"""Restricción geoespacial del Modo Colombia.

La geometría procede de límites departamentales derivados del MGN DANE 2025,
distribuidos con atribución CC BY 4.0. Las islas son parte del multipolígono.
El modo GLOBAL permanece disponible solo como configuración del despliegue.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

FUENTE = "DANE MGN 2025; simplificación y distribución: ytolosa/mapas-colombia (CC BY 4.0)"
ARCHIVO = Path(__file__).resolve().parents[1] / "assets" / "colombia_departamentos_mgn2025.geojson"
BBOX_COLOMBIA = (-82.7, -4.7, -66.0, 14.1)


class FueraDeColombia(ValueError):
    """La región solicitada no puede analizarse en la edición Colombia."""


def modo() -> str:
    return "GLOBAL" if os.environ.get("VISOR_REGION_MODE", "CO").strip().upper() == "GLOBAL" else "CO"


@lru_cache(maxsize=1)
def geometria_colombia():
    with ARCHIVO.open("r", encoding="utf-8") as archivo:
        raw = json.load(archivo)
    partes = [shape(f["geometry"]) for f in raw["features"] if f.get("geometry")]
    if len(partes) < 30:
        raise RuntimeError("Los límites de Colombia están ausentes o incompletos; análisis bloqueado.")
    geom = unary_union(partes)
    if geom.is_empty or not geom.is_valid:
        raise RuntimeError("La geometría colombiana no es válida; análisis bloqueado.")
    return geom


def contiene_punto(lon: float, lat: float) -> bool:
    if modo() == "GLOBAL":
        return True
    from shapely.geometry import Point
    return geometria_colombia().covers(Point(float(lon), float(lat)))


def validar_aoi(limites, geometria: dict | None = None):
    """Valida *la región que se procesará*, no solo el centro del lugar buscado.

    El motor actual procesa el rectángulo envolvente incluso para un polígono
    dibujado; por eso siempre validamos ese rectángulo completo. El polígono
    será una herramienta de selección, no una vía para analizar fuera del país.
    """
    if modo() == "GLOBAL":
        return tuple(limites)
    try:
        o, s, e, n = (float(v) for v in limites)
        region = box(o, s, e, n)
    except (ValueError, TypeError) as exc:
        raise FueraDeColombia("La zona no tiene límites válidos.") from exc
    if region.is_empty or not region.is_valid or not geometria_colombia().covers(region):
        raise FueraDeColombia(
            "Esta versión de V.I.S.O.R. solo analiza zonas completamente dentro de Colombia. "
            "Reduce o desplaza el rectángulo para que no cruce fronteras o el mar. "
            "Si dibujaste un polígono, recuerda que el motor procesa su rectángulo envolvente."
        )
    return (o, s, e, n)


@lru_cache(maxsize=1)
def contorno_visual() -> dict:
    """Polígono simplificado para sombrear exterior, no para decidir permisos."""
    # El sombreado usa el territorio simplificado; la validación usa la fuente original.
    geo = geometria_colombia().simplify(0.012, preserve_topology=True)
    return mapping(geo)


@lru_cache(maxsize=1)
def mascara_exterior() -> dict:
    # Cobertura mundial visible; no se transfiere un mapa de países entero.
    mundo = box(-179.9, -85, 179.9, 85)
    return mapping(mundo.difference(shape(contorno_visual())))
