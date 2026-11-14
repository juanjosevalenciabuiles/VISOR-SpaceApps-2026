"""Auditoría de solo lectura de un GeoTIFF de clases SAR (informe JSON).

    .venv/bin/python scripts/auditar_geotiff.py data/analisis/coincidencia_VV_VH_20260924_20261006.tif \\
        --comparar data/analisis/coincidencia_VV_VH_Chigorodo.tif \\
        --vv data/analisis/cambio_VV_20260924_20261006_mascara.tif \\
        --vh data/analisis/cambio_VH_20260924_20261006_mascara.tif \\
        --salida auditoria_chigorodo.json

No modifica ningún archivo de entrada. Sin --salida, solo imprime.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.analisis_sar import ErrorSAR  # noqa: E402
from utils.auditoria import auditar  # noqa: E402


def main(argumentos=None) -> int:
    p = argparse.ArgumentParser(description="Auditoría de GeoTIFF de clases SAR (V.I.S.O.R.)")
    p.add_argument("geotiff", type=Path)
    p.add_argument("--comparar", type=Path)
    p.add_argument("--vv", type=Path)
    p.add_argument("--vh", type=Path)
    p.add_argument("--salida", type=Path, help="informe JSON nuevo (no puede ser uno de los insumos)")
    a = p.parse_args(argumentos)
    insumos = [x for x in (a.geotiff, a.comparar, a.vv, a.vh) if x]
    if a.salida and any(a.salida.resolve() == x.resolve() for x in insumos):
        p.error("--salida no puede sobrescribir un insumo")
    if a.salida and a.salida.suffix.lower() in (".tif", ".tiff"):
        p.error("--salida debe ser un .json")
    try:
        texto = json.dumps(auditar(a.geotiff, a.comparar, a.vv, a.vh), ensure_ascii=False, indent=2)
    except ErrorSAR as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(texto)
    if a.salida:
        a.salida.write_text(texto + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
