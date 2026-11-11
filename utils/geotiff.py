"""Lectura segura de GeoTIFF ligeros desde /data.

- Valida que el archivo exista, se pueda abrir, tenga CRS y píxeles válidos.
- Reproyecta a EPSG:4326 (lo que necesita Folium) solo si viene en otro CRS.
- Remuestrea con `bilinear` los productos continuos y con `nearest` las
  máscaras categóricas (para no inventar clases intermedias).
- Enmascara NoData y valores no finitos: es lo ÚNICO que se oculta siempre.
- Reduce la resolución si el ráster supera MAX_LADO_PX.
- Convierte los valores en una imagen RGBA según la configuración del fenómeno.

`leer_geotiff` no depende de la sesión de Streamlit (se prueba con pytest).
`cargar_capa` es la versión con caché que usa la app.
"""
from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

import numpy as np
import rasterio
import streamlit as st
from rasterio.enums import Resampling
from rasterio.errors import RasterioError
from rasterio.vrt import WarpedVRT

from utils.config import MAX_LADO_PX
from utils.geo import intersecta_antioquia

if TYPE_CHECKING:
    from utils.config import Fenomeno

CRS_MAPA = "EPSG:4326"
COLOR_CLASE_DESCONOCIDA = "#8E8E93"


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
    categorico: bool = False

    @property
    def rango(self) -> tuple[float, float]:
        return float(self.datos.min()), float(self.datos.max())


def _metadatos(src: rasterio.DatasetReader, ruta: Path) -> tuple[dict[str, str], list[str]]:
    """Etiquetas del GeoTIFF + archivo lateral opcional `<nombre>.json`.

    Un JSON dañado no tumba la capa, pero se avisa. La marca de demostración
    (VISOR_DEMO) solo se toma del propio GeoTIFF: un JSON no puede quitarla.
    """
    meta = {k.upper(): str(v) for k, v in src.tags().items()}
    avisos: list[str] = []
    lateral = ruta.with_suffix(".json")
    if lateral.exists():
        try:
            extra = json.loads(lateral.read_text(encoding="utf-8"))
            if not isinstance(extra, dict):
                raise ValueError("el JSON debe ser un objeto {clave: valor}")
            for clave, valor in extra.items():
                clave = str(clave).upper()
                if clave != "VISOR_DEMO" and isinstance(valor, (str, int, float)):
                    meta[clave] = str(valor)
        except (ValueError, OSError):  # incluye JSON mal formado y mala codificación
            avisos.append(
                f"No se pudieron leer los metadatos de `data/{lateral.name}`; se ignoraron."
            )
    return meta, avisos


def leer_geotiff(
    ruta: str | Path,
    max_lado: int = MAX_LADO_PX,
    categorico: bool = False,
) -> Capa:
    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorCapa(f"No se encontró el archivo `data/{ruta.name}`.")

    remuestreo = Resampling.nearest if categorico else Resampling.bilinear
    try:
        with rasterio.open(ruta) as src:
            if src.crs is None:
                raise ErrorCapa(
                    f"`{ruta.name}` no tiene sistema de coordenadas (CRS); "
                    "no se puede ubicar en el mapa."
                )
            meta, avisos = _metadatos(src, ruta)
            if src.count > 1:
                avisos.append(f"El archivo tiene {src.count} bandas; se muestra la banda 1.")

            crs_original = src.crs.to_string()
            reproyectada = src.crs != rasterio.crs.CRS.from_string(CRS_MAPA)
            forma_original = (src.height, src.width)

            # Solo se crea el VRT de reproyección cuando hace falta.
            contexto = (
                WarpedVRT(src, crs=CRS_MAPA, resampling=remuestreo)
                if reproyectada else nullcontext(src)
            )
            with contexto as fuente:
                escala = min(1.0, max_lado / max(fuente.height, fuente.width))
                alto = max(1, round(fuente.height * escala))
                ancho = max(1, round(fuente.width * escala))
                if escala < 1.0:
                    avisos.append(f"Ráster reducido a {ancho}×{alto} px para visualización.")
                # Una sola lectura, ya a la resolución de pantalla.
                datos = fuente.read(
                    1, out_shape=(alto, ancho), masked=True, resampling=remuestreo,
                ).astype("float32")
                b = fuente.bounds
    except ErrorCapa:
        raise
    except (RasterioError, OSError, ValueError) as e:
        raise ErrorCapa(f"`{ruta.name}` no es un GeoTIFF válido o está dañado.") from e

    datos = np.ma.masked_invalid(datos)  # NaN / inf también son "sin dato"
    if datos.count() == 0:
        raise ErrorCapa(f"`{ruta.name}` no contiene píxeles válidos (todo es NoData).")

    limites = (b.left, b.bottom, b.right, b.top)
    if not (-180 <= b.left < b.right <= 180 and -90 <= b.bottom < b.top <= 90):
        raise ErrorCapa(f"`{ruta.name}` tiene una extensión geográfica inválida.")
    if not intersecta_antioquia(limites):
        avisos.append("La capa queda fuera del área de referencia de Antioquia.")
    if not categorico and float(datos.min()) == float(datos.max()):
        avisos.append(
            "Todos los píxeles válidos tienen el mismo valor; la capa no tiene contraste."
        )

    return Capa(
        datos=datos,
        limites=limites,
        crs_original=crs_original,
        reproyectada=reproyectada,
        forma_original=forma_original,
        es_demo=meta.get("VISOR_DEMO") == "1",
        metadatos=meta,
        avisos=avisos,
        categorico=categorico,
    )


def _firma(ruta: Path) -> tuple[int, int, int, int]:
    """Huella del GeoTIFF y de su JSON lateral: si cambia, la caché se invalida."""
    def una(p: Path) -> tuple[int, int]:
        try:
            s = p.stat()
            return s.st_mtime_ns, s.st_size
        except OSError:
            return 0, 0
    return una(ruta) + una(ruta.with_suffix(".json"))


@st.cache_data(show_spinner=False, max_entries=12)
def _cargar_con_cache(ruta: str, firma: tuple, categorico: bool) -> Capa:
    return leer_geotiff(ruta, categorico=categorico)


def cargar_capa(ruta: Path, categorico: bool = False) -> Capa:
    """Versión con caché: relee solo si cambió el GeoTIFF o su JSON de metadatos."""
    ruta = Path(ruta)
    return _cargar_con_cache(str(ruta), _firma(ruta), categorico)


# --------------------------------------------------------------------------
# De valores a colores
# --------------------------------------------------------------------------

def _hex_a_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rango_visual(
    datos: np.ma.MaskedArray,
    vmin: float | None = None,
    vmax: float | None = None,
    percentiles: tuple[float, float] = (2, 98),
) -> tuple[float, float]:
    """Rango usado para estirar los colores: fijo si se configura, si no por percentiles."""
    if vmin is None or vmax is None:
        p_bajo, p_alto = np.percentile(datos.compressed(), percentiles)
        vmin = float(p_bajo) if vmin is None else vmin
        vmax = float(p_alto) if vmax is None else vmax
    return float(vmin), float(vmax)


def colorizar(
    datos: np.ma.MaskedArray,
    colores: tuple[str, ...],
    vmin: float | None = None,
    vmax: float | None = None,
    invertir: bool = False,
    transparencia: str = "gradual",
    alfa_min: float = 0.25,
    percentiles: tuple[float, float] = (2, 98),
) -> np.ndarray:
    """Convierte valores continuos en RGBA uint8.

    NoData es siempre transparente. Los valores válidos NUNCA se ocultan:
    - transparencia="nodata":  todos los píxeles válidos son opacos.
    - transparencia="gradual": la opacidad va de `alfa_min` (extremo tenue de
      la rampa) a 1 (extremo intenso), para dejar ver el mapa base.
    `invertir=True` asigna el extremo intenso de la rampa a los valores BAJOS.
    """
    if transparencia not in ("gradual", "nodata"):
        raise ValueError(f"transparencia desconocida: {transparencia!r}")

    vmin, vmax = rango_visual(datos, vmin, vmax, percentiles)
    if vmax > vmin:
        norm = np.clip((datos.filled(vmin) - vmin) / (vmax - vmin), 0.0, 1.0)
        if invertir:
            norm = 1.0 - norm
    else:  # valores constantes o rango degenerado: color medio, sin contraste
        norm = np.full(datos.shape, 0.5, dtype="float32")

    paradas = np.linspace(0.0, 1.0, len(colores))
    rgb = np.array([_hex_a_rgb(c) for c in colores], dtype="float32")
    rgba = np.empty(datos.shape + (4,), dtype="uint8")
    for canal in range(3):
        rgba[..., canal] = np.interp(norm, paradas, rgb[:, canal]).astype("uint8")

    if transparencia == "nodata":
        alfa = np.full(datos.shape, 255.0)
    else:
        alfa_min = float(np.clip(alfa_min, 0.0, 1.0))
        alfa = (alfa_min + (1.0 - alfa_min) * norm) * 255.0
    alfa[np.ma.getmaskarray(datos)] = 0
    rgba[..., 3] = np.round(alfa).astype("uint8")
    return rgba


def colorizar_categorico(
    datos: np.ma.MaskedArray,
    clases: Iterable[tuple[float, str, str | None]],
) -> np.ndarray:
    """Convierte una máscara de clases en RGBA uint8.

    `clases` son tuplas (valor, etiqueta, color). Un color `None` deja esa
    clase transparente por decisión explícita de configuración. Los valores
    válidos que no estén en la lista se pintan en gris: no se ocultan.
    """
    valores = datos.filled(np.nan)
    rgba = np.zeros(datos.shape + (4,), dtype="uint8")
    rgba[...] = _hex_a_rgb(COLOR_CLASE_DESCONOCIDA) + (255,)
    for valor, _etiqueta, color in clases:
        donde = valores == valor
        rgba[donde] = (0, 0, 0, 0) if color is None else _hex_a_rgb(color) + (255,)
    rgba[np.ma.getmaskarray(datos)] = (0, 0, 0, 0)
    return rgba


def colorizar_capa(capa: Capa, fenomeno: "Fenomeno") -> np.ndarray:
    """Aplica a una capa la configuración de visualización de su fenómeno."""
    if fenomeno.categorico:
        return colorizar_categorico(capa.datos, fenomeno.clases)
    return colorizar(
        capa.datos, fenomeno.colores, fenomeno.vmin, fenomeno.vmax, fenomeno.invertir,
        fenomeno.transparencia, fenomeno.alfa_min, fenomeno.percentiles,
    )


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
