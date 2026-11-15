#!/usr/bin/env python3
"""Comprobar si un punto está cubierto por el mapa QA temporal NISAR.

Solo lectura local; sin Earthdata ni descargas. No infiere agua o inundaciones.

Ejemplo piloto del centro urbano Chigorodó (Minvivienda Colombia):
  python scripts/nisar_verificar_punto_qa.py \
    --raster data/nisar/qa/cobertura_XXXX.tif \
    --lon -76.6774845 --lat 7.6645455

Fuente centro urbano: https://www.minvivienda.gov.co/node/38689
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import rasterio
from rasterio.warp import transform

CLASES = {
    0: "SIN OBSERVACIÓN UTILIZABLE EN AMBAS FECHAS",
    1: "SOLO FECHA INICIAL",
    2: "SOLO FECHA FINAL",
    3: "UTILIZABLE EN AMBAS FECHAS",
}


def verificar(ruta: Path, lon: float, lat: float) -> dict:
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("Coordenadas WGS84 fuera de rango.")
    with rasterio.open(ruta) as src:
        if src.driver != "GTiff" or src.crs is None or src.count != 1:
            raise ValueError("Se necesita una capa QA GeoTIFF de banda única con CRS.")
        if src.tags().get("AREA") != "COBERTURA_QA_NISAR_NO_INUNDACION":
            raise ValueError("El raster seleccionado no declara ser cobertura QA NISAR.")
        x, y = transform("EPSG:4326", src.crs, [lon], [lat])
        x, y = x[0], y[0]
        # Rasterio puede devolver 0 (nodata) para observaciones fuera del raster,
        # por eso comprobamos geometría antes de pedir la celda.
        en_cuadricula = src.bounds.left <= x < src.bounds.right and src.bounds.bottom < y <= src.bounds.top
        if en_cuadricula:
            fila, columna = src.index(x, y)
            en_cuadricula = (0 <= fila < src.height and 0 <= columna < src.width)
        clase = None
        if en_cuadricula:
            valor = src.read(1, window=((fila, fila + 1), (columna, columna + 1)))
            clase = int(valor[0, 0])
            if clase not in CLASES:
                raise ValueError("El raster no contiene únicamente clases QA 0, 1, 2 o 3.")
        return {
            "estado": "VERIFICACION_PUNTO_QA_NO_INUNDACION",
            "punto_wgs84": {"longitud": lon, "latitud": lat},
            "en_cuadricula": bool(en_cuadricula),
            "clase_qa": clase,
            "descripcion": CLASES.get(clase, "FUERA DE CUADRÍCULA"),
            "puede_comparar_ambas_fechas": clase == 3,
            "raster": ruta.name,
            "advertencia": "La cobertura QA no identifica agua ni inundación.",
        }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raster", type=Path, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--lat", type=float, required=True)
    a = p.parse_args(argv)
    try:
        resultado = verificar(a.raster, a.lon, a.lat)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, rasterio.errors.RasterioError) as e:
        print("Verificación no disponible:", type(e).__name__, str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
