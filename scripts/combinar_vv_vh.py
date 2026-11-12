"""Combinación VV/VH reproducible desde la línea de comandos.

Combina las máscaras VV y VH que el motor SAR (scripts/analizar_sar.py) dejó
en data/analisis/ para el mismo par de fechas, y escribe el GeoTIFF de
coincidencias con su ficha de procedencia JSON. No descarga nada ni usa HyP3.

Generar (con el entorno del proyecto):

    .venv/bin/python scripts/combinar_vv_vh.py \\
        --vv data/analisis/cambio_VV_20260924_20261006_mascara.tif \\
        --vh data/analisis/cambio_VH_20260924_20261006_mascara.tif \\
        --zona "Chigorodó, Antioquia" \\
        --comparar data/analisis/coincidencia_VV_VH_Chigorodo.tif

Solo describir un GeoTIFF de clases ya existente (no necesita las máscaras):

    .venv/bin/python scripts/combinar_vv_vh.py --describir data/analisis/coincidencia_VV_VH_Chigorodo.tif

El resultado muestra cambios de retrodispersión. No confirma inundaciones.
"""
import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils.analisis_sar import ADVERTENCIA, ErrorSAR  # noqa: E402
from utils.combinacion_sar import comparar_geotiff, combinar_vv_vh, describir_clases  # noqa: E402


def _imprimir_clases(resumen: dict) -> None:
    print(f"  Píxeles totales: {resumen['pixeles_totales']:,} · válidos: {resumen['pixeles_validos']:,} · "
          f"sin dato: {resumen['pixeles_sin_dato']:,}".replace(",", "."))
    for valor, c in resumen["clases"].items():
        ha = f" · {c['area_ha']:.2f} ha" \
            if c["area_ha"] is not None else ""
        print(f"  Clase {valor}: {c['pixeles']:,} px".replace(",", ".")
              + f" · {c['porcentaje_de_validos']:.3f} % de los válidos{ha} · {c['etiqueta']}")
    if resumen.get("pixeles_otros_valores"):
        print(f"  Otros valores: {resumen['pixeles_otros_valores']} px")


def main(argumentos: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Combinación VV/VH de máscaras SAR (V.I.S.O.R.).")
    p.add_argument("--vv", help="máscara VV del motor (…_VV_…_mascara.tif)")
    p.add_argument("--vh", help="máscara VH del motor, del mismo par de fechas")
    p.add_argument("--salida", default=None, help="carpeta de resultados (por defecto, la de la máscara VV)")
    p.add_argument("--prefijo", default=None, help="nombre de salida sin extensión")
    p.add_argument("--zona", default=None, help="etiqueta descriptiva del área (declarada, no medida)")
    p.add_argument("--comparar", default=None, help="GeoTIFF exploratorio con el que verificar equivalencia")
    p.add_argument("--describir", default=None, help="solo describe las clases de un GeoTIFF existente")
    a = p.parse_args(argumentos)

    try:
        if a.describir:
            resumen = describir_clases(a.describir)
            print(f"{a.describir} · {resumen['crs']} · {resumen['dimensiones'][0]}×{resumen['dimensiones'][1]} px")
            _imprimir_clases(resumen)
            return 0
        if not (a.vv and a.vh):
            p.error("indica --vv y --vh, o usa --describir")

        r = combinar_vv_vh(a.vv, a.vh, a.salida, a.prefijo, a.zona)
        print(f"GeoTIFF: {r.geotiff}")
        print(f"Ficha:   {r.ficha_ruta}")
        print(f"Estado de procedencia declarado en la ficha: {r.estado}")
        _imprimir_clases(r.estadisticas)
        for aviso in r.ficha["avisos"]:
            print(f"  AVISO: {aviso}")

        if a.comparar:
            c = comparar_geotiff(r.geotiff, a.comparar)
            print(f"\nComparación con {a.comparar}:")
            print(f"  Misma cuadrícula: {'sí' if c['misma_cuadricula'] else 'NO'} · mismo NoData: "
                  f"{'sí' if c['mismo_nodata'] else 'NO'} · píxeles distintos: {c['pixeles_distintos']}")
            print("  EQUIVALENTES" if c["equivalentes"] else "  NO EQUIVALENTES")
            if not c["equivalentes"]:
                print(json.dumps({"reproducible": c["a"]["clases"], "exploratorio": c["b"]["clases"]},
                                 ensure_ascii=False, indent=2))
                return 2
    except ErrorSAR as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"\n{ADVERTENCIA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
