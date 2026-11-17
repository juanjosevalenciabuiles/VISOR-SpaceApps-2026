#!/usr/bin/env python3
"""Diagnóstico de pares NISAR Harmony YA preparados (solo lectura, sin red).

Uso: .venv/bin/python scripts/diagnosticar_nisar_v9.py
No descarga, convierte ni modifica los datos. El resultado muestra metadatos
de la cuadrícula; no certifica radiometría ni píxeles QA válidos.
"""
from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import rasterio  # noqa: E402
from utils.config import DATA_DIR  # noqa: E402
from utils.v9_nisar_puente import escenas_preparadas, leer_preparacion  # noqa: E402

CAMPOS = ("cog", "qa_mask", "looks")


def revisar_trabajo(job: dict) -> None:
    job_id = job.get("job_id") or "(sin ID)"
    print(f"\nTrabajo {job_id} · {job.get('estado', 'desconocido')} · "
          f"{job.get('procesador', 'desconocido')}")
    print("  AOI:", (job.get("aoi") or {}).get("limites", "(sin AOI)"))
    try:
        manifiesto = leer_preparacion(job_id)
        escenas = escenas_preparadas(manifiesto)
        print("  Fechas NISAR:", escenas[0]["observed_at"][:10],
              "→", escenas[1]["observed_at"][:10])
        print("  Órbita:", escenas[0]["orbita"], "· Polarización:", escenas[0]["polarizacion"])
        with ExitStack() as stack:
            rasters = [stack.enter_context(rasterio.open(escena[k]))
                       for escena in escenas for k in CAMPOS]
            referencia = rasters[0]
            compatibles = referencia.crs is not None and referencia.crs.is_projected and all(
                ds.crs == referencia.crs and ds.transform == referencia.transform
                and ds.width == referencia.width and ds.height == referencia.height
                and ds.count == 1 for ds in rasters
            )
            print("  Cuadrículas 6 capas:", "COMPATIBLES" if compatibles else "INCOMPATIBLES")
            for indice, ds in enumerate(rasters):
                print(f"    {'pre' if indice < 3 else 'post'}:{CAMPOS[indice % 3]}: "
                      f"{ds.width}×{ds.height}, {ds.dtypes[0]}, {ds.crs}")
            if compatibles:
                print("  SIGUIENTE: comprobar píxeles válidos y procesar ΔdB (aún no certificado).")
            else:
                print("  BLOQUEO: no remuestrear ni combinar cuadrículas diferentes sin QA.")
    except (OSError, ValueError, TypeError, KeyError, rasterio.errors.RasterioError) as exc:
        print("  BLOQUEO:", type(exc).__name__ + ":", str(exc)[:220])


def main() -> None:
    carpeta = DATA_DIR / "trabajos"
    trabajos = []
    for archivo in carpeta.glob("*.json") if carpeta.is_dir() else []:
        try:
            job = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if (job.get("tipo") == "adquisicion_nisar_gcov"
                and job.get("procesador") == "harmony_cog"
                and job.get("estado") == "APTO"):
            trabajos.append((archivo.stat().st_mtime, job))
    trabajos.sort(reverse=True, key=lambda x: x[0])
    print(f"Preparaciones NISAR Harmony APTO encontradas: {len(trabajos)}")
    for _, job in trabajos[:20]:
        revisar_trabajo(job)
    resultados = list((DATA_DIR / "analisis").glob("nisar_v9_*_dif_db.tif"))
    print(f"\nGeoTIFF de cambio NISAR V9 existentes: {len(resultados)}")
    for ruta in resultados:
        print(" ", ruta.name)
    print("\nSolo lectura: no se descargó, calculó ni modificó ningún archivo.")


if __name__ == "__main__":
    main()
