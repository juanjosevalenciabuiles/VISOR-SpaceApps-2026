"""Funciones geoespaciales pequeñas (GeoPandas / Shapely)."""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import box

from utils.config import ANTIOQUIA_BBOX

Limites = tuple[float, float, float, float]  # oeste, sur, este, norte


def intersecta_antioquia(limites: Limites) -> bool:
    return box(*limites).intersects(box(*ANTIOQUIA_BBOX))


def huella(limites: Limites, nombre: str) -> gpd.GeoDataFrame:
    """Rectángulo de cobertura de una capa, listo para folium.GeoJson."""
    return gpd.GeoDataFrame({"nombre": [nombre]}, geometry=[box(*limites)], crs="EPSG:4326")


def area_referencia() -> gpd.GeoDataFrame:
    return huella(ANTIOQUIA_BBOX, "Área de referencia (rectángulo aproximado, no es el límite oficial)")
