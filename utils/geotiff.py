"""Lectura segura de GeoTIFF ligeros desde /data.

- Valida que el archivo exista, se pueda abrir y tenga CRS.
- Reproyecta a EPSG:4326 (lo que necesita Folium) si viene en otro CRS.
- Enmascara NoData y valores no finitos (quedan transparentes en el mapa).
- Reduce la resolución si el ráster supera MAX_LADO_PX.
- Convierte los valores en una imagen RGBA con la rampa del fenómeno.

`leer_geotiff` no depende de Streamlit (se puede probar con pytest).
`cargar_capa` es la versión con caché que usa la app.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rasterio
import streamlit as st
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError
from rasterio.vrt import WarpedVRT

from utils.config import MAX_LADO_PX
from utils.geo import intersecta_antioquia

CRS_MAPA = "EPSG:4326"


class ErrorCapa(Exception):
    """Error legible para mostrar al usuario cuando una capa no se puede usar."""


@dataclass
class Capa:
    datos: np.ma.MaskedArray                    # float32, en EPSG:4326
    limites: tuple[float, float, float, float]  # oeste, sur, este, norte
    crs_original: str
    reproyectada: bool
    forma_original: tuple[int, int]             # (alto, ancho) del archivo
    es_demo: bool
    metadatos: dict[str, str] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)

    @property
    def rango(self) -> tuple[float, float]:
        return float(self.datos.min()), float(self.datos.max())


def _metadatos(src: rasterio.DatasetReader, ruta: Path) -> dict[str, str]:
    """Etiquetas del GeoTIFF + archivo lateral opcional `<nombre>.json`."""
    meta = {k.upper(): str(v) for k, v in src.tags().items()}
    lateral = ruta.with_suffix(".json")
    if lateral.exists():
        try:
            extra = json.loads(lateral.read_text(encoding="utf-8"))
            meta.update({str(k).upper(): str(v) for k, v in extra.items()})
        except (json.JSONDecodeError, OSError):
            pass  # un .json dañado no debe tumbar la capa
    return meta


def leer_geotiff(ruta: str | Path, max_lado: int = MAX_LADO_PX) -> Capa:
    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorCapa(f"No se encontró el archivo `data/{ruta.name}`.")

    avisos: list[str] = []
    try:
        with rasterio.open(ruta) as src:
            if src.crs is None:
                raise ErrorCapa(
                    f"`{ruta.name}` no tiene sistema de coordenadas (CRS); "
                    "no se puede ubicar en el mapa."
                )
            if src.count > 1:
                avisos.append(f"El archivo tiene {src.count} bandas; se muestra la banda 1.")

            crs_original = src.crs.to_string()
            reproyectada = src.crs != rasterio.crs.CRS.from_string(CRS_MAPA)
            meta = _metadatos(src, ruta)
            forma_original = (src.height, src.width)

            with WarpedVRT(src, crs=CRS_MAPA, resampling=Resampling.bilinear) as vrt:
                escala = min(1.0, max_lado / max(vrt.height, vrt.width))
                alto = max(1, round(vrt.height * escala))
                ancho = max(1, round(vrt.width * escala))
                if escala < 1.0:
                    avisos.append(
                        f"Ráster reducido a {ancho}×{alto} px para visualización."
                    )
                datos = vrt.read(
                    1, out_shape=(alto, ancho), masked=True,
                    resampling=Resampling.bilinear,
                ).astype("float32")
                b = vrt.bounds
    except RasterioIOError as e:
        raise ErrorCapa(f"`{ruta.name}` no es un GeoTIFF válido o está dañado.") from e

    datos = np.ma.masked_invalid(datos)  # NaN / inf también son "sin dato"
    if datos.count() == 0:
        raise ErrorCapa(f"`{ruta.name}` no contiene píxeles válidos (todo es NoData).")

    limites = (b.left, b.bottom, b.right, b.top)
    if not (-180 <= b.left < b.right <= 180 and -90 <= b.bottom < b.top <= 90):
        raise ErrorCapa(f"`{ruta.name}` tiene una extensión geográfica inválida.")
    if not intersecta_antioquia(limites):
        avisos.append("La capa queda fuera del área de referencia de Antioquia.")

    return Capa(
        datos=datos,
        limites=limites,
        crs_original=crs_original,
        reproyectada=reproyectada,
        forma_original=forma_original,
        es_demo=meta.get("VISOR_DEMO") == "1",
        metadatos=meta,
        avisos=avisos,
    )


@st.cache_data(show_spinner=False)
def _cargar_con_cache(ruta: str, mtime: float) -> Capa:
    return leer_geotiff(ruta)


def cargar_capa(ruta: Path) -> Capa:
    """Versión con caché: solo relee si el archivo cambió en disco."""
    mtime = ruta.stat().st_mtime if ruta.exists() else 0.0
    return _cargar_con_cache(str(ruta), mtime)


def _hex_a_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def colorizar(
    datos: np.ma.MaskedArray,
    colores: tuple[str, ...],
    vmin: float | None = None,
    vmax: float | None = None,
    invertir: bool = False,
) -> np.ndarray:
    """Convierte valores en RGBA uint8. NoData → transparente; a mayor indicio,
    más color y más opacidad (así el mapa oscuro se sigue viendo debajo)."""
    validos = datos.compressed()
    if vmin is None or vmax is None:
        p2, p98 = np.percentile(validos, [2, 98])
        vmin = p2 if vmin is None else vmin
        vmax = p98 if vmax is None else vmax
    if vmax <= vmin:
        vmax = vmin + 1e-6

    norm = np.clip((datos.filled(vmin) - vmin) / (vmax - vmin), 0.0, 1.0)
    if invertir:
        norm = 1.0 - norm

    paradas = np.linspace(0.0, 1.0, len(colores))
    rgb = np.array([_hex_a_rgb(c) for c in colores], dtype="float32")
    rgba = np.empty(datos.shape + (4,), dtype="uint8")
    for canal in range(3):
        rgba[..., canal] = np.interp(norm, paradas, rgb[:, canal]).astype("uint8")
    alfa = np.clip(norm * 1.5, 0.0, 1.0) * 255
    alfa[np.ma.getmaskarray(datos)] = 0
    rgba[..., 3] = alfa.astype("uint8")
    return rgba


def a_web_mercator(rgba: np.ndarray, sur: float, norte: float) -> np.ndarray:
    """Reacomoda las filas de una imagen en lat/lon (EPSG:4326) para que encaje
    en el mapa web (Web Mercator). Se hace aquí, y no con `mercator_project` de
    Folium, porque esa opción reescala cada canal y altera los colores."""
    alto = rgba.shape[0]

    def merc(lat: float) -> float:
        return float(np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)))

    y = np.linspace(merc(norte), merc(sur), alto * 2 + 1)[1::2]  # centros de fila
    lat = np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)
    filas = np.clip(((norte - lat) / (norte - sur) * alto).astype(int), 0, alto - 1)
    return rgba[filas]
