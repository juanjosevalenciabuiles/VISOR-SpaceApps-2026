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

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import RasterioError

from utils.analisis_sar import area_pixel_ha

RANGO_DB = 10.0
# Por encima de esta cantidad de píxeles, las estadísticas se calculan sobre una lectura
# reducida (y se marcan como aproximadas) para no agotar la memoria de Replit.
MAX_PIXELES_EXACTOS = 25_000_000
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


@dataclass(frozen=True)
class EscalaContinua:
    """Rampa fija de un producto continuo en dB (la misma en el mapa, la leyenda y QGIS)."""
    clave: str
    minimo: float
    maximo: float
    rampa: tuple[tuple[float, str], ...]
    ticks: tuple[int, ...]
    alfa_fija: float | None          # None: opacidad creciente con |valor| (diferencias)
    texto_leyenda: str
    texto_qgis: str                  # ASCII: va al LEEME del paquete


ESCALA_DIFERENCIA = EscalaContinua(
    "diferencia_db", -RANGO_DB, RANGO_DB, RAMPA, TICKS, None, "dB · ← disminución · aumento →",
    "Diferencia continua en dB (posterior - anterior), sin umbral: pseudocolor fijo de -10 a +10 dB "
    "(azul disminucion, rojo aumento), NoData transparente.")
# gamma0 de UNA fecha (NISAR, escena única): oscuro = señal baja. No es un cambio.
ESCALA_GAMMA0 = EscalaContinua(
    "retrodispersion_db", -30.0, 0.0,
    ((-30.0, "#1C1C1E"), (-20.0, "#3A4A5C"), (-12.0, "#5AC8FA"), (-5.0, "#BFF4FF"), (0.0, "#FFFFFF")),
    (-30, -20, -10, 0), 0.85, "dB · gamma0 de una fecha (oscuro = señal baja)",
    "Retrodispersion gamma0 de UNA fecha en dB, sin umbral ni cambio: escala fija de -30 a 0 dB "
    "(oscuro = senal baja), NoData transparente.")
ESCALAS = {e.clave: e for e in (ESCALA_DIFERENCIA, ESCALA_GAMMA0)}


def escala_de(clave: str | None) -> EscalaContinua:
    return ESCALAS.get(clave or "", ESCALA_DIFERENCIA)


def _rgb(color: str) -> np.ndarray:
    c = color.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], dtype="float64")


def alfa(delta: np.ndarray, escala: EscalaContinua = ESCALA_DIFERENCIA) -> np.ndarray:
    """Opacidad (0–1). Diferencias: ALFA_MIN en 0 dB, 1 a partir de ±RANGO_DB.
    Escalas con `alfa_fija`: la misma para todo píxel válido."""
    if escala.alfa_fija is not None:
        return np.full_like(np.asarray(delta, dtype="float64"), escala.alfa_fija)
    return ALFA_MIN + (1.0 - ALFA_MIN) * np.clip(np.abs(delta) / RANGO_DB, 0.0, 1.0)


def colorizar_diferencia(datos: np.ma.MaskedArray, escala: EscalaContinua = ESCALA_DIFERENCIA) -> np.ndarray:
    """Valores en dB (enmascarados) → RGBA uint8 con la rampa de `escala`. No modifica `datos`."""
    valores = np.clip(np.ma.filled(datos.astype("float64"), escala.minimo), escala.minimo, escala.maximo)
    xs = np.array([x for x, _ in escala.rampa])
    colores = np.stack([_rgb(c) for _, c in escala.rampa])
    rgb = np.stack([np.interp(valores, xs, colores[:, k]) for k in range(3)], axis=-1)
    rgba = np.zeros(valores.shape + (4,), dtype="uint8")
    rgba[..., :3] = np.round(rgb).astype("uint8")
    rgba[..., 3] = np.round(alfa(valores, escala) * 255).astype("uint8")
    rgba[np.ma.getmaskarray(datos)] = (0, 0, 0, 0)
    return rgba


def describir_continuo(ruta: str | Path, escala: EscalaContinua = ESCALA_DIFERENCIA) -> dict:
    """Distribución de los valores en dB a resolución completa, leída del archivo original."""
    ruta = Path(ruta)
    try:
        with rasterio.open(ruta) as src:
            total = src.width * src.height
            reduccion = min(1.0, (MAX_PIXELES_EXACTOS / total) ** 0.5)
            forma = (max(1, int(src.height * reduccion)), max(1, int(src.width * reduccion)))
            datos = src.read(1, masked=True, out_shape=forma) if reduccion < 1 else src.read(1, masked=True)
            area_ha = area_pixel_ha(src.crs, src.transform)
            nodata = src.nodata
    except (RasterioError, OSError, ValueError) as e:
        raise ValueError(f"`{ruta.name}` no es un GeoTIFF válido o está dañado.") from e
    validos = datos.compressed().astype("float32", copy=False)
    validos = validos[np.isfinite(validos)]
    aproximado = reduccion < 1
    if aproximado:  # conteos extrapolados a la resolución completa
        factor = total / datos.size
        n_validos = int(round(validos.size * factor))
    else:
        n_validos = int(validos.size)
    resumen = {"pixeles_totales": int(total), "pixeles_validos": n_validos,
               "pixeles_sin_dato": int(total) - n_validos, "nodata": nodata,
               "area_pixel_ha": area_ha, "unidades": "dB",
               "aproximado": aproximado}
    if validos.size:
        p5, p50, p95 = np.percentile(validos, [5, 50, 95])
        fuera = int(((validos < escala.minimo) | (validos > escala.maximo)).sum())
        resumen.update(minimo=float(validos.min()), p5=float(p5), mediana=float(p50),
                       media=float(validos.mean(dtype="float64")), p95=float(p95), maximo=float(validos.max()),
                       desviacion=float(validos.std(dtype="float64")),
                       fuera_de_rango=int(round(fuera * total / datos.size)) if aproximado else fuera)
    return resumen


def leyenda_css(escala: EscalaContinua = ESCALA_DIFERENCIA) -> str:
    """Degradado CSS de la rampa (para la leyenda del panel)."""
    ancho = escala.maximo - escala.minimo
    paradas = ", ".join(f"{c} {100 * (x - escala.minimo) / ancho:.0f}%" for x, c in escala.rampa)
    return f"linear-gradient(90deg, {paradas})"
