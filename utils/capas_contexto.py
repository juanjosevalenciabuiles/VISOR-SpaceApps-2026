"""Capas geográficas de contexto (hidrografía, vías) que se dibujan sobre el mapa.

Son datos vectoriales REALES guardados como GeoJSON ligeros en data/contexto/.
Si el archivo de una capa no existe, la capa simplemente no está disponible:
la app no inventa geometrías.

Para sumar una capa (por ejemplo cuencas, o una red de drenaje detallada) se
agrega su GeoJSON a data/contexto/ y una entrada en CAPAS_CONTEXTO con su
fuente y licencia. La precipitación NO es una capa de este tipo: es un dato
ráster con fecha y necesita su propia fuente verificada (ver README).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import streamlit as st

from utils.config import DATA_DIR

CONTEXTO_DIR = DATA_DIR / "contexto"


@dataclass(frozen=True)
class CapaContexto:
    clave: str
    nombre: str
    archivo: str          # GeoJSON dentro de data/contexto/
    color: str
    grosor: float
    fuente: str
    licencia: str
    alcance: str          # qué incluye y qué NO incluye, para no sobreinterpretar

    @property
    def ruta(self) -> Path:
        return CONTEXTO_DIR / self.archivo


CAPAS_CONTEXTO: dict[str, CapaContexto] = {
    "hidrografia": CapaContexto(
        clave="hidrografia",
        nombre="Hidrografía",
        archivo="hidrografia.geojson",
        color="#4FC3F7",
        grosor=2.0,
        fuente="Natural Earth 1:10m · Rivers and lake centerlines (v5.1.2)",
        licencia="Dominio público",
        alcance=(
            "Solo ríos principales a escala general (Cauca, Magdalena, Atrato). "
            "No incluye quebradas, red de drenaje ni cuencas."
        ),
    ),
    "vias": CapaContexto(
        clave="vias",
        nombre="Carreteras",
        archivo="vias.geojson",
        color="#FFD60A",
        grosor=1.4,
        fuente="Natural Earth 1:10m · Roads (v5.1.2)",
        licencia="Dominio público",
        alcance="Solo vías principales a escala general. No incluye vías secundarias ni urbanas.",
    ),
}


@dataclass
class DatosContexto:
    geojson: str          # texto GeoJSON en EPSG:4326, listo para folium.GeoJson
    elementos: int


def _firma(ruta: Path) -> tuple[int, int]:
    try:
        s = ruta.stat()
        return s.st_mtime_ns, s.st_size
    except OSError:
        return 0, 0


def leer_contexto(ruta: str | Path) -> DatosContexto | None:
    """Lee un GeoJSON de contexto. Devuelve None si no existe, está dañado,
    viene vacío o no tiene geometrías: en ese caso la capa no se ofrece."""
    ruta = Path(ruta)
    if not ruta.exists():
        return None
    try:
        gdf = gpd.read_file(ruta)
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
        if gdf.empty:
            return None
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
        return DatosContexto(geojson=gdf.to_json(), elementos=len(gdf))
    except Exception:  # noqa: BLE001 - cualquier fallo de lectura deja la capa sin ofrecer
        return None


@st.cache_data(show_spinner=False, max_entries=8)
def _leer_con_cache(ruta: str, firma: tuple) -> DatosContexto | None:
    return leer_contexto(ruta)


def cargar_contexto(clave: str) -> DatosContexto | None:
    """Versión con caché: relee solo si el archivo cambió."""
    capa = CAPAS_CONTEXTO.get(clave)
    if capa is None:
        return None
    return _leer_con_cache(str(capa.ruta), _firma(capa.ruta))


def disponibles() -> dict[str, bool]:
    """Qué capas de contexto tienen datos utilizables."""
    return {clave: cargar_contexto(clave) is not None for clave in CAPAS_CONTEXTO}
