"""Análisis temporal SAR desde la línea de comandos.

Compara dos GeoTIFF RTC de Sentinel-1 (ASF HyP3) de la misma polarización y
escribe en data/analisis/ la diferencia en dB, la máscara de cambios y el
informe de procedencia. No descarga nada ni usa HyP3: trabaja con archivos
que ya están en disco.

Ejemplo (con el entorno del proyecto):

    .venv/bin/python scripts/analizar_sar.py \\
        data/sar/S1C_IW_20260924T..._VV.tif data/sar/S1C_IW_20261006T..._VV.tif \\
        --aoi -76.85 7.50 -76.50 7.85

El resultado muestra cambios de retrodispersión. No confirma inundaciones.
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils.analisis_sar import (  # noqa: E402
    ADVERTENCIA, ESCALAS, POLARIZACIONES, UMBRAL_OSCURO_SUGERIDO, ErrorSAR,
    ParametrosCambio, analizar_par,
)


def main(argumentos: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cambio de retrodispersión SAR entre dos fechas (V.I.S.O.R.).")
    p.add_argument("antes", help="GeoTIFF RTC de la fecha anterior")
    p.add_argument("despues", help="GeoTIFF RTC de la fecha posterior (misma polarización)")
    p.add_argument("--aoi", nargs=4, type=float, metavar=("OESTE", "SUR", "ESTE", "NORTE"),
                   help="recorte en grados lon/lat; recomendado para no cargar la escena completa")
    p.add_argument("--salida", default=str(RAIZ / "data" / "analisis"), help="carpeta de resultados")
    p.add_argument("--umbral-disminucion", type=float, default=3.0, help="dB (por defecto 3)")
    p.add_argument("--umbral-aumento", type=float, default=3.0, help="dB (por defecto 3; 0 = no marcar aumentos)")
    p.add_argument("--ventana", type=int, default=5, help="filtro de speckle en píxeles, impar (1 = sin filtro)")
    p.add_argument("--umbral-oscuro", type=float, default=None,
                   help=f"dB para marcar 'baja en ambas fechas' (orientativo: {UMBRAL_OSCURO_SUGERIDO})")
    p.add_argument("--polarizacion", choices=POLARIZACIONES, help="si no se deduce del nombre del archivo")
    p.add_argument("--fecha-antes", help="AAAA-MM-DD, si no se deduce del nombre")
    p.add_argument("--fecha-despues", help="AAAA-MM-DD, si no se deduce del nombre")
    p.add_argument("--escala", choices=ESCALAS, help="si no se deduce del nombre (HyP3 'power' por defecto)")
    p.add_argument("--prefijo", help="nombre base de los archivos de salida")
    p.add_argument("--guardar-db", action="store_true", help="exportar también cada fecha en dB")
    p.add_argument("--sobrescribir", action="store_true",
                   help="reemplazar resultados existentes con el mismo prefijo (por defecto: nunca)")
    a = p.parse_args(argumentos)

    try:
        parametros = ParametrosCambio(
            umbral_disminucion_db=a.umbral_disminucion,
            umbral_aumento_db=a.umbral_aumento or None,
            ventana_speckle=a.ventana,
            umbral_oscuro_db=a.umbral_oscuro,
        )
        r = analizar_par(
            a.antes, a.despues, a.salida, aoi=tuple(a.aoi) if a.aoi else None, parametros=parametros,
            polarizacion=a.polarizacion, fecha_antes=a.fecha_antes, fecha_despues=a.fecha_despues,
            escala=a.escala, prefijo=a.prefijo, guardar_db=a.guardar_db,
            sobrescribir=a.sobrescribir,
        )
    except ErrorSAR as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    e = r.estadisticas
    c = r.procedencia["cuadricula"]
    print(f"Cuadrícula: {c['ancho']}×{c['alto']} px · {c['crs']} · {e['porcentaje_valido']:.1f}% con dato en ambas fechas")
    print(f"Alineación de la imagen posterior: {r.procedencia['alineacion']['despues']}")
    d = e.get("diferencia_db", {})
    print(f"Diferencia (dB): mediana {d.get('mediana')}, p5 {d.get('p5')}, p95 {d.get('p95')}")
    for clase in e["clases"].values():
        area = f" · {clase['area_ha']:.0f} ha" if clase["area_ha"] is not None else ""
        print(f"  {clase['etiqueta']}: {clase['porcentaje_de_validos']:.2f}%{area}")
    for aviso in r.avisos:
        print(f"Aviso: {aviso}")
    print("Archivos:")
    for ruta in (r.diferencia, r.mascara, *r.extras.values(), r.informe):
        print(f"  {ruta}")
    print(ADVERTENCIA)
    return 0


if __name__ == "__main__":
    sys.exit(main())
