"""Lectura acotada de ventanas COG; no certifica códigos ni QA OPERA.

No se llama durante render. El orquestador debe invocarla solo tras
la acción explícita del usuario y verificar la fuente y sus clases.
"""
from __future__ import annotations

from urllib.parse import urlsplit
import numpy as np
import rasterio
from rasterio.windows import from_bounds, Window, transform as window_transform
from rasterio.warp import transform_bounds

MAX_AOI_BYTES = 384 * 1024 * 1024


def _url_cog_confiable(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError("URL COG inválida")
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
            or not (host.endswith(".earthdata.nasa.gov")
                    or host == "earthdata.nasa.gov"
                    or host.endswith(".nasa.gov") or host == "nasa.gov")):
        raise ValueError("COG_URL_NO_CONFIABLE")
    return url


def leer_ventana_cog(url: str, bbox_wgs84: tuple[float, float, float, float],
                     *, presupuesto_bytes: int = MAX_AOI_BYTES) -> dict:
    """Lee solo AOI con Rasterio; el límite es de memoria estimada, no tráfico HTTP.

    El servidor debe soportar acceso aleatorio COG; si no, fallar cerrado.
    No descargar archivos completos ni interpretar clases WTR/CONF aquí.
    """
    _url_cog_confiable(url)
    if not isinstance(presupuesto_bytes, int) or not 0 < presupuesto_bytes <= MAX_AOI_BYTES:
        raise ValueError("PRESUPUESTO_INVALIDO")
    if len(bbox_wgs84) != 4 or not all(np.isfinite(bbox_wgs84)):
        raise ValueError("AOI_INVALIDA")
    west, south, east, north = bbox_wgs84
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("AOI_INVALIDA")
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                      VSI_CACHE="FALSE", GDAL_HTTP_MAX_RETRY="0"):
        with rasterio.open(url) as ds:
            if ds.crs is None or ds.transform.is_identity or ds.count < 1:
                raise ValueError("COG_SIN_GEOREFERENCIA")
            bounds = transform_bounds("EPSG:4326", ds.crs, *bbox_wgs84,
                                      densify_pts=21)
            win = from_bounds(*bounds, transform=ds.transform)
            col0 = max(0, int(np.floor(win.col_off)))
            row0 = max(0, int(np.floor(win.row_off)))
            col1 = min(ds.width, int(np.ceil(win.col_off + win.width)))
            row1 = min(ds.height, int(np.ceil(win.row_off + win.height)))
            if col1 <= col0 or row1 <= row0:
                raise ValueError("AOI_SIN_INTERSECCION")
            window = Window(col0, row0, col1-col0, row1-row0)
            estimate = int(window.width * window.height * np.dtype(ds.dtypes[0]).itemsize)
            if estimate > presupuesto_bytes:
                raise ValueError("AOI_EXCEDE_PRESUPUESTO")
            values = ds.read(1, window=window, masked=True)
            transform = window_transform(window, ds.transform)
            return {"valores": values, "georef": {"crs": ds.crs.to_string(),
                    "transform": tuple(transform)[:6]}, "nodata": ds.nodata,
                    "window": (row0, row1, col0, col1),
                    "cobertura_aoi_no_verificada": True,
                    "bytes_estimados": estimate}
