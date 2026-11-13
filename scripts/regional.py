"""Análisis regional SAR × JRC desde la línea de comandos.

1) Reproducir Chigorodó con los GeoTIFF REALES (habilita el análisis regional):
   .venv/bin/python scripts/regional.py reproducir \\
       --sar data/analisis/coincidencia_VV_VH_20260924_20261006.tif --jrc data/jrc/JRC_Occurrence_Chigorodo_30m.tif

2) Extraer Urabá del Marco Geoestadístico Nacional de DANE (el archivo original no se toca):
   .venv/bin/python scripts/regional.py limites --mgn /ruta/MGN_MPIO_POLITICO.geojson

3) Crear un AOI (piloto, Urabá, municipios por código o un GeoJSON propio):
   .venv/bin/python scripts/regional.py aoi --piloto
   .venv/bin/python scripts/regional.py aoi --municipios 05172,05147 --nombre "Chigorodó y Carepa"
   .venv/bin/python scripts/regional.py aoi --geojson mi_area.geojson --nombre "Mi área"

4) Cruzar una máscara VV/VH con JRC en un AOI (exige el paso 1 APROBADO):
   .venv/bin/python scripts/regional.py cruzar --sar data/analisis/coincidencia_….tif \\
       --jrc data/jrc/JRC_….tif --aoi data/aoi/aoi_Piloto….geojson

Nada sobrescribe: cada salida nueva lleva _r2, _r3…
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils import regiones, sar_jrc  # noqa: E402
from utils.procedencia import sha256_archivo  # noqa: E402


def _reproducir(a) -> int:
    try:
        reg = sar_jrc.reproducir_chigorodo(a.sar, a.jrc, a.carpeta)
    except sar_jrc.ErrorJRC as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"Reproducción de Chigorodó: {reg['resultado']}  (registro: {reg['archivo']})")
    for d in reg["diferencias"]:
        print(f"  ✗ {d}")
    g = reg["cifras_obtenidas"]["global"]
    u1 = g["umbrales_jrc"][0]
    print(f"  detecciones {g['detecciones']:,} · sobre JRC ≥ 1 %: {u1['pixeles_sar_jrc']:,} "
          f"({u1['hectareas_sar_jrc']} ha, {u1['pct_jrc_entre_detecciones']} %)")
    print("  Asociación con agua histórica: NO confirma inundaciones.")
    return 0 if reg["resultado"] == "APROBADA" else 2


def _limites(a) -> int:
    try:
        lim = regiones.cargar_limites(Path(a.mgn))
    except regiones.ErrorAOI as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    faltan = [f"{n} ({c})" for c, n in regiones.URABA.items() if c not in lim.zonas]
    if faltan:
        print(f"ERROR: el archivo no trae: {', '.join(faltan)}", file=sys.stderr)
        return 1
    aoi = lim.seleccionar(list(regiones.URABA), "Urabá antioqueño")
    datos = aoi.a_geojson()
    datos["visor_aoi"]["fuente"] = f"{Path(a.mgn).name} (sha256 {sha256_archivo(a.mgn)})"
    carpeta = regiones.CARPETA_LIMITES
    carpeta.mkdir(parents=True, exist_ok=True)
    from utils.analisis_sar import prefijo_libre
    destino = carpeta / f"{prefijo_libre(carpeta, 'uraba_mgn')}.geojson"
    with destino.open("x", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)
    print(f"Límites de los 11 municipios de Urabá: {destino}  ({aoi.area_km2:,.0f} km²)")
    return 0


def _aoi(a) -> int:
    try:
        if a.geojson:
            aoi = regiones.aoi_desde_geojson(Path(a.geojson), a.nombre or Path(a.geojson).stem)
        else:
            archivos = [Path(a.limites)] if a.limites else regiones.archivos_limites()
            if not archivos:
                print("ERROR: no hay límites oficiales en data/limites/ (ver `limites --mgn`).", file=sys.stderr)
                return 1
            lim = regiones.cargar_limites(archivos[0])
            codigos = (list(regiones.PILOTO) if a.piloto else list(regiones.URABA) if a.uraba
                       else [c.strip().zfill(5) for c in (a.municipios or "").split(",") if c.strip()])
            nombre = a.nombre or ("Piloto Urabá" if a.piloto else "Urabá antioqueño" if a.uraba else None)
            aoi = lim.seleccionar(codigos, nombre)
    except regiones.ErrorAOI as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    ruta = aoi.guardar()
    print(f"AOI «{aoi.nombre}»: {len(aoi.zonas)} zona(s), {aoi.area_km2:,.1f} km² → {ruta}")
    for av in aoi.avisos:
        print(f"  AVISO: {av}")
    print("  Un AOI no implica cobertura de escenas: revísala antes de analizar.")
    return 0


def _cruzar(a) -> int:
    ok, motivo = sar_jrc.estado_habilitacion()
    if not ok:
        print(f"BLOQUEADO: {motivo}", file=sys.stderr)
        return 3
    try:
        aoi = regiones.aoi_desde_geojson(Path(a.aoi), Path(a.aoi).stem) if a.aoi else None
        r = sar_jrc.cruzar(a.sar, a.jrc, aoi, umbrales=[int(x) for x in a.umbrales.split(",")],
                           version_jrc=a.version_jrc)
    except (sar_jrc.ErrorJRC, regiones.ErrorAOI, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"{'Desde caché: ' if r.desde_cache else ''}{r.informe}")
    for codigo, z in [("TOTAL", r.datos["global"]), *r.datos["zonas"].items()]:
        u = z["umbrales_jrc"][0]
        tasa = "N/D" if u["pct_jrc_entre_detecciones"] is None else f"{u['pct_jrc_entre_detecciones']} %"
        print(f"  {z.get('nombre', codigo):<22} válidos {z['pixeles_validos']:>9,} · detecciones {z['detecciones']:>7,} "
              f"· JRC ≥ 1 % entre detecciones: {tasa}")
    for av in r.datos["avisos"]:
        print(f"  AVISO: {av}")
    return 0


def main(argumentos=None) -> int:
    p = argparse.ArgumentParser(description="Análisis regional SAR × JRC de V.I.S.O.R.")
    sub = p.add_subparsers(dest="accion", required=True)
    r = sub.add_parser("reproducir", help="reproducir con los GeoTIFF reales el cruce de Chigorodó (QGIS)")
    r.add_argument("--sar", required=True)
    r.add_argument("--jrc", required=True)
    r.add_argument("--carpeta", type=Path, default=None, help="dónde guardar el registro (por defecto data/analisis/regional)")
    m = sub.add_parser("limites", help="extraer los 11 municipios de Urabá de un GeoJSON del MGN de DANE")
    m.add_argument("--mgn", required=True)
    a = sub.add_parser("aoi", help="crear un AOI en data/aoi/")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--piloto", action="store_true", help="Chigorodó, Carepa, Apartadó y Turbo")
    g.add_argument("--uraba", action="store_true", help="los 11 municipios de Urabá")
    g.add_argument("--municipios", help="códigos DIVIPOLA separados por comas")
    g.add_argument("--geojson", help="cualquier polígono GeoJSON en WGS84")
    a.add_argument("--limites", help="GeoJSON de límites oficiales (por defecto el primero de data/limites/)")
    a.add_argument("--nombre")
    c = sub.add_parser("cruzar", help="cruce SAR × JRC en un AOI (exige la reproducción APROBADA)")
    c.add_argument("--sar", required=True)
    c.add_argument("--jrc", required=True)
    c.add_argument("--aoi")
    c.add_argument("--umbrales", default="1,10,25,50")
    c.add_argument("--version-jrc", default=None, help="p. ej. «GSW v1.5 (1984–2024)»")
    a_ = p.parse_args(argumentos)
    return {"reproducir": _reproducir, "limites": _limites, "aoi": _aoi, "cruzar": _cruzar}[a_.accion](a_)


if __name__ == "__main__":
    sys.exit(main())
