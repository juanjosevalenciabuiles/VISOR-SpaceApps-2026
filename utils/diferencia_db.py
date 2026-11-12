"""Visualización científica de la diferencia de retrodispersión en dB (`…_dif_db.tif`).

El motor escribe, por polarización, Δ = posterior − anterior en dB (float32,
NoData −9999). Es el dato físico del que salen las máscaras al aplicar un
umbral; aquí se muestra SIN umbral:

- Rampa divergente simétrica y FIJA de ±10 dB (comparable entre productos):
  azul = disminución, naranja-rojo = aumento, gris tenue cerca de 0.
  Fuera de ±10 dB el color se satura; el valor no se toca.
- Opacidad que crece con |Δ| desde ALFA_MIN: ningún píxel válido se oculta
  del todo y el mapa base sigue legible donde no hay cambio.
- NoData siempre transparente.
- Estadísticas de la distribución calculadas sobre el archivo original a
  resolución completa (no sobre la imagen remuestreada del mapa).

Una disminución de retrodispersión NO confirma agua ni inundación.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import RasterioError

RANGO_DB = 10.0
ALFA_MIN = 0.15
# (Δ en dB, color) de la rampa; se interpola linealmente entre puntos.
RAMPA: tuple[tuple[float, str], ...] = (
    (-10.0, "#0A84FF"),
    (-5.0, "#64B5FF"),
    (0.0, "#C7C7CC"),
    (5.0, "#FFA45C"),
    (10.0, "#FF453A"),
)
TICKS = (-10, -5, 0, 5, 10)


def _rgb(color: str) -> np.ndarray:
    c = color.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], dtype="float64")


def alfa(delta: np.ndarray) -> np.ndarray:
    """Opacidad (0–1) según |Δ|: ALFA_MIN en 0 dB, 1 a partir de ±RANGO_DB."""
    return ALFA_MIN + (1.0 - ALFA_MIN) * np.clip(np.abs(delta) / RANGO_DB, 0.0, 1.0)


def colorizar_diferencia(datos: np.ma.MaskedArray) -> np.ndarray:
    """Δ (dB, enmascarado) → RGBA uint8. No modifica `datos`."""
    valores = np.clip(np.ma.filled(datos.astype("float64"), 0.0), -RANGO_DB, RANGO_DB)
    xs = np.array([x for x, _ in RAMPA])
    colores = np.stack([_rgb(c) for _, c in RAMPA])
    rgb = np.stack([np.interp(valores, xs, colores[:, k]) for k in range(3)], axis=-1)
    rgba = np.zeros(valores.shape + (4,), dtype="uint8")
    rgba[..., :3] = np.round(rgb).astype("uint8")
    rgba[..., 3] = np.round(alfa(valores) * 255).astype("uint8")
    rgba[np.ma.getmaskarray(datos)] = (0, 0, 0, 0)
    return rgba


def describir_continuo(ruta: str | Path) -> dict:
    """Distribución de Δ a resolución completa, leída del archivo original."""
    ruta = Path(ruta)
    try:
        with rasterio.open(ruta) as src:
            datos = src.read(1, masked=True).astype("float64")
            area_m2 = abs(src.transform.a * src.transform.e) if src.crs and src.crs.is_projected else None
            nodata = src.nodata
    except (RasterioError, OSError, ValueError) as e:
        raise ValueError(f"`{ruta.name}` no es un GeoTIFF válido o está dañado.") from e
    validos = datos.compressed()
    validos = validos[np.isfinite(validos)]
    total = int(datos.size)
    resumen = {"pixeles_totales": total, "pixeles_validos": int(validos.size),
               "pixeles_sin_dato": total - int(validos.size), "nodata": nodata,
               "area_pixel_ha": area_m2 / 10_000 if area_m2 else None, "unidades": "dB"}
    if validos.size:
        p5, p50, p95 = np.percentile(validos, [5, 50, 95])
        resumen.update(minimo=float(validos.min()), p5=float(p5), mediana=float(p50), media=float(validos.mean()),
                       p95=float(p95), maximo=float(validos.max()), desviacion=float(validos.std()),
                       fuera_de_rango=int((np.abs(validos) > RANGO_DB).sum()))
    return resumen


def leyenda_css() -> str:
    """Degradado CSS de la rampa (para la leyenda del panel)."""
    paradas = ", ".join(f"{c} {100 * (x + RANGO_DB) / (2 * RANGO_DB):.0f}%" for x, c in RAMPA)
    return f"linear-gradient(90deg, {paradas})"
