"""Paquete ZIP para QGIS Desktop a partir de un resultado de data/analisis/.

    .venv/bin/python scripts/exportar_qgis.py data/analisis/coincidencia_VV_VH_20260924_20261006.tif

Escribe el ZIP en exportaciones/ (fuera de Git). El GeoTIFF original no se modifica.
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils.qgis import ErrorExportacion, exportar  # noqa: E402
from utils.resultados import leer_resultado  # noqa: E402


def main(argumentos=None) -> int:
    p = argparse.ArgumentParser(description="Exportar un resultado SAR para QGIS (V.I.S.O.R.)")
    p.add_argument("geotiff", type=Path)
    p.add_argument("--carpeta", type=Path, default=RAIZ / "exportaciones")
    a = p.parse_args(argumentos)
    res = leer_resultado(a.geotiff)
    if not res.dibujable:
        print(f"ERROR: {res.error or 'resultado no reconocido'}", file=sys.stderr)
        return 1
    try:
        nombre, datos = exportar(a.geotiff, res.perfil.clases, res.nombre, continuo=res.perfil.continuo)
    except ErrorExportacion as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    a.carpeta.mkdir(parents=True, exist_ok=True)
    destino = a.carpeta / nombre
    destino.write_bytes(datos)
    print(f"Paquete QGIS: {destino} ({len(datos) / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
