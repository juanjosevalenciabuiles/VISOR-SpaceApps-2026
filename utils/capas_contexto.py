"""Capas geográficas de contexto (ríos y lagos, carreteras), de alcance MUNDIAL.

Son datos vectoriales REALES de Natural Earth 1:10m (dominio público), simplificados y
comprimidos en data/contexto/mundo/ (≈4,5 MB en total). Nunca se envía el mundo entero al
navegador: en cada vista se recorta lo que cae dentro del encuadre del mapa, se simplifica
según el zoom y se limita el número de elementos. Si un archivo no existe, la capa no se
ofrece; la app no inventa geometrías.

Natural Earth es cartografía a escala general: solo ríos, lagos y carreteras PRINCIPALES. Las
calles, quebradas, puentes y vías secundarias están en los mapas base de calles (OpenStreetMap).
Un río ausente en esta capa no significa que no exista. Ninguna de estas capas es un resultado
SAR ni muestra agua actual o inundaciones.

Regenerar los archivos: python scripts/preparar_contexto.py <carpeta de natural-earth-vector>
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import streamlit as st
from shapely.geometry import box

from utils.config import DATA_DIR

CONTEXTO_DIR = DATA_DIR / "contexto"
MAX_ELEMENTOS = 4000
FUENTE_NE = "Natural Earth 1:10m (natural-earth-vector, versión 5.2.0-pre, descargada el 14-nov-2026)"


@dataclass(frozen=True)
class CapaContexto:
    clave: str
    nombre: str
    archivo: str          # dentro de data/contexto/ (.geojson o .geojson.gz)
    color: str
    grosor: float
    fuente: str
    licencia: str
    alcance: str          # qué incluye y qué NO incluye, para no sobreinterpretar
    zoom_minimo: int = 0  # por debajo, la capa no se dibuja (demasiados elementos)
    relleno: bool = False
    extra: str | None = None   # segundo archivo de la misma capa (lagos junto a los ríos)

    @property
    def ruta(self) -> Path:
        return CONTEXTO_DIR / self.archivo

    @property
    def rutas(self) -> list[Path]:
        return [self.ruta] + ([CONTEXTO_DIR / self.extra] if self.extra else [])


CAPAS_CONTEXTO: dict[str, CapaContexto] = {
    "hidrografia": CapaContexto(
        clave="hidrografia",
        nombre="Ríos y lagos (mundo)",
        archivo="mundo/rios.geojson.gz",
        extra="mundo/lagos.geojson.gz",
        color="#4FC3F7",
        grosor=1.6,
        fuente=FUENTE_NE + " · Rivers and lake centerlines + Lakes",
        licencia="Dominio público",
        alcance=("Ríos y lagos principales de todo el mundo a escala general (Natural Earth). No incluye "
                 "quebradas ni la red de drenaje detallada: el mapa base «Calles» muestra más. Es cartografía, "
                 "no agua actual ni inundación."),
    ),
    "vias": CapaContexto(
        clave="vias",
        nombre="Carreteras principales (mundo)",
        archivo="mundo/carreteras.geojson.gz",
        color="#FFD60A",
        grosor=1.2,
        fuente=FUENTE_NE + " · Roads",
        licencia="Dominio público",
        alcance=("Carreteras principales de todo el mundo a escala general (Natural Earth). Calles, vías "
                 "secundarias y puentes están en el mapa base «Calles» (OpenStreetMap)."),
        zoom_minimo=5,
    ),
}


@dataclass
class DatosContexto:
    geojson: str          # texto GeoJSON en EPSG:4326, listo para folium.GeoJson
    elementos: int
    aviso: str | None = None


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
        gdf = gpd.read_file(f"/vsigzip/{ruta}" if ruta.suffix == ".gz" else ruta)
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
        if gdf.empty:
            return None
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
        return DatosContexto(geojson=gdf.to_json(), elementos=len(gdf))
    except Exception:  # noqa: BLE001 - cualquier fallo de lectura deja la capa sin ofrecer
        return None


@st.cache_resource(show_spinner=False, max_entries=6)
def _tabla(ruta: str, firma: tuple):
    """La capa completa, leída una sola vez por proceso (compartida entre sesiones: son datos públicos)."""
    lectura = f"/vsigzip/{ruta}" if ruta.endswith(".gz") else ruta
    try:
        gdf = gpd.read_file(lectura)
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
    except Exception:  # noqa: BLE001 - cualquier fallo de lectura deja la capa sin ofrecer
        return None
    if gdf.empty:
        return None
    _ = gdf.sindex  # índice espacial: el recorte por vista no recorre todo el mundo
    return gdf


def _tablas(capa: CapaContexto) -> list:
    return [t for t in (_tabla(str(r), _firma(r)) for r in capa.rutas if r.exists()) if t is not None]


def limites_validos(limites) -> tuple[float, float, float, float] | None:
    """Encuadre en grados, recortado al mundo. Si cruza el meridiano 180 se usa el mundo entero en
    longitud (no se generan rectángulos invertidos)."""
    try:
        oeste, sur, este, norte = (float(v) for v in limites)
    except (TypeError, ValueError):
        return None
    sur, norte = max(-90.0, sur), min(90.0, norte)
    if este - oeste >= 360 or oeste >= este:
        oeste, este = -180.0, 180.0
    oeste, este = max(-180.0, oeste), min(180.0, este)
    return (oeste, sur, este, norte) if sur < norte and oeste < este else None


def recortar(clave: str, limites, zoom: float | None) -> DatosContexto | None:
    """Elementos de la capa dentro del encuadre, simplificados para el zoom. None si no hay datos;
    `elementos == 0` si en esa zona la capa no tiene nada; `omitido` explica si no se dibuja."""
    capa = CAPAS_CONTEXTO.get(clave)
    tablas = _tablas(capa) if capa else []
    caja = limites_validos(limites)
    if not tablas or caja is None:
        return None
    if zoom is not None and zoom < capa.zoom_minimo:
        return DatosContexto("", 0, f"Acércate para ver {capa.nombre.lower()} (desde el zoom {capa.zoom_minimo}).")
    ventana = box(*caja)
    partes = [t.iloc[t.sindex.query(ventana, predicate="intersects")] for t in tablas]
    total = sum(len(x) for x in partes)
    aviso = None
    if total > MAX_ELEMENTOS:
        # Los más importantes primero (scalerank bajo), repartiendo el cupo entre los archivos de la capa.
        cupo = MAX_ELEMENTOS // len(partes)
        partes = [x.sort_values("scalerank").head(cupo) if "scalerank" in x.columns else x.head(cupo) for x in partes]
        aviso = f"Vista muy amplia: solo los {MAX_ELEMENTOS} elementos más importantes. Acércate para ver el resto."
    tolerancia = 0.0 if zoom is None or zoom >= 9 else (360 / 2 ** zoom) / 1500
    rasgos = []
    for x in partes:
        if x.empty:
            continue
        if tolerancia:
            x = x.assign(geometry=x.geometry.simplify(tolerancia, preserve_topology=False))
            x = x[~x.geometry.is_empty]
        columnas = [c for c in ("name", "featurecla", "type") if c in x.columns]
        rasgos += json.loads(x[columnas + ["geometry"]].to_json())["features"]
    return DatosContexto(json.dumps({"type": "FeatureCollection", "features": rasgos}), len(rasgos), aviso)


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
    return {clave: bool(_tablas(capa)) for clave, capa in CAPAS_CONTEXTO.items()}
