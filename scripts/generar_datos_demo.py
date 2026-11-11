"""Genera GeoTIFF SINTÉTICOS de demostración en /data.

NO son datos satelitales: son manchas aleatorias suaves para probar la
interfaz mientras llegan los productos reales de HyP3. Cada archivo lleva la
etiqueta VISOR_DEMO=1, que la app usa para mostrar el aviso de demostración.

Uso:  python scripts/generar_datos_demo.py
"""
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

DATA = Path(__file__).resolve().parent.parent / "data"
LADO = 320
NODATA = -9999.0
# Ventana de prueba dentro del área de referencia (oeste, sur, este, norte).
VENTANA = (-76.3, 5.9, -74.7, 7.5)


def campo_sintetico(semilla: int, manchas: int) -> np.ndarray:
    """Índice 0–1 hecho con manchas gaussianas en posiciones aleatorias."""
    rng = np.random.default_rng(semilla)
    y, x = np.mgrid[0:LADO, 0:LADO]
    campo = np.zeros((LADO, LADO), dtype="float32")
    for _ in range(manchas):
        cx, cy = rng.uniform(20, LADO - 20, 2)
        sx, sy = rng.uniform(6, 26, 2)
        campo += rng.uniform(0.4, 1.0) * np.exp(-(((x - cx) / sx) ** 2 + ((y - cy) / sy) ** 2))
    return np.clip(campo, 0, 1).round(3)


def escribir(nombre: str, datos: np.ndarray, crs: str, descripcion: str) -> None:
    limites = VENTANA if crs == "EPSG:4326" else transform_bounds("EPSG:4326", crs, *VENTANA)
    datos = datos.copy()
    datos[:12, :] = NODATA  # franja sin dato para probar la transparencia
    DATA.mkdir(exist_ok=True)
    with rasterio.open(
        DATA / nombre, "w", driver="GTiff", height=LADO, width=LADO, count=1,
        dtype="float32", crs=CRS.from_string(crs), nodata=NODATA,
        transform=from_bounds(*limites, LADO, LADO), compress="deflate", predictor=3,
    ) as dst:
        dst.write(datos, 1)
        dst.update_tags(
            VISOR_DEMO="1",
            PRODUCTO="Índice sintético 0–1 (sin significado físico)",
            DESCRIPCION=descripcion,
        )
    print(f"  data/{nombre}  ({(DATA / nombre).stat().st_size / 1024:.0f} kB, {crs})")


if __name__ == "__main__":
    print("Generando GeoTIFF sintéticos de demostración:")
    aviso = "DATO SINTÉTICO DE DEMOSTRACIÓN. No es una observación satelital."
    escribir("inundacion.tif", campo_sintetico(1, 14), "EPSG:4326", aviso)
    # En UTM 18N a propósito: así se prueba la reproyección a EPSG:4326.
    escribir("deslizamiento.tif", campo_sintetico(2, 22), "EPSG:32618", aviso)
    escribir("deforestacion.tif", campo_sintetico(3, 18), "EPSG:4326", aviso)
