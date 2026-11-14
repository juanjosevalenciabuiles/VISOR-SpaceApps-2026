"""Compatibilidad con la API del Modo Colombia de la PR #10 (feature/colombia-contexto-ambiental).

Al integrar la PR #10 con la PR #11 se dejó UNA sola política y UNA sola geometría:
`utils/alcance_geografico.py` (MGN 2025 del DANE al nivel `municipal`, 69 polígonos). Este módulo
conserva los nombres que usan el código y las pruebas de la PR #10 y los delega allí, para que
interfaz, servidor y contexto ambiental decidan exactamente igual.

`assets/colombia_departamentos_mgn2025.geojson` (nivel `nacional` de la misma fuente, aportado por
la PR #10) ya no se usa para decidir permisos; se conserva hasta que el equipo decida retirarlo.
"""
from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import shape

from utils import alcance_geografico as _alcance

FUENTE = "DANE MGN 2025; simplificación y distribución: ytolosa/mapas-colombia (CC BY 4.0)"
ARCHIVO = _alcance.CARPETA / _alcance.ARCHIVO_VALIDACION
ARCHIVO_PR10 = Path(__file__).resolve().parents[1] / "assets" / "colombia_departamentos_mgn2025.geojson"
BBOX_COLOMBIA = (-82.7, -4.7, -66.0, 14.1)

FueraDeColombia = _alcance.FueraDeAlcance


def modo() -> str:
    return _alcance.modo()


def geometria_colombia():
    return _alcance.geometria()


def contiene_punto(lon: float, lat: float) -> bool:
    """Orden (longitud, latitud), como en la PR #10."""
    return _alcance.contiene_punto(lat, lon)


def validar_aoi(limites, geometria: dict | None = None):
    """Valida el rectángulo que procesará el motor; devuelve (oeste, sur, este, norte)."""
    try:
        o, s, e, n = (float(v) for v in limites)
    except (TypeError, ValueError) as exc:
        raise FueraDeColombia("La zona no tiene límites válidos.") from exc
    _alcance.validar_limites((o, s, e, n))
    return (o, s, e, n)


def contorno_visual() -> dict:
    capas = _alcance.capas_dibujo()
    if capas is None:
        raise FueraDeColombia("No se pudo cargar el contorno de Colombia.")
    return shape(json.loads(capas[0])["geometry"]).__geo_interface__


def mascara_exterior() -> dict:
    capas = _alcance.capas_dibujo()
    if capas is None:
        raise FueraDeColombia("No se pudo cargar el contorno de Colombia.")
    return json.loads(capas[1])["geometry"]
