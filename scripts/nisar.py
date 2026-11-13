"""NISAR L2 GCOV (banda L) desde la línea de comandos. Nada se descarga sin pedirlo.

    .venv/bin/python scripts/nisar.py buscar --inicio 2026-10-21 --fin 2026-11-13
    .venv/bin/python scripts/nisar.py inspeccionar data/nisar/crudos/NISAR_L2_PR_GCOV_….h5
    .venv/bin/python scripts/nisar.py recortar data/nisar/crudos/NISAR_L2_PR_GCOV_….h5 --termino HHHH --madurez VALIDATED

`buscar` consulta solo metadatos (sin credenciales) y guarda el registro en
data/nisar/catalogo/ sin sobrescribir. `recortar` copia la ventana del área de
interés a data/nisar/ en gamma0 de potencia; el HDF5 no se modifica.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils import nisar_catalogo, nisar_gcov  # noqa: E402
from utils.buscador_sar import ErrorBusqueda  # noqa: E402

CHIGORODO = (-76.80, 7.55, -76.55, 7.80)


def _bbox(p: argparse.ArgumentParser) -> None:
    p.add_argument("--bbox", type=float, nargs=4, default=list(CHIGORODO), metavar=("OESTE", "SUR", "ESTE", "NORTE"),
                   help="recuadro lon/lat (por defecto Chigorodó)")


def _buscar(a) -> int:
    try:
        r = nisar_catalogo.buscar(*a.bbox, a.inicio, a.fin, madurez=a.madurez, max_resultados=a.max)
    except ErrorBusqueda as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    registro = nisar_catalogo.registro_json(r)
    carpeta = nisar_gcov.CARPETA_NISAR / "catalogo"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"busqueda_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{r.madurez}.json"
    with destino.open("x", encoding="utf-8") as f:
        json.dump(registro, f, indent=2, ensure_ascii=False)
    print(f"{r.total_catalogo} resultados del catálogo · {len(r.candidatos)} candidatos · {len(r.pares)} pares")
    for c in r.candidatos:
        n = c.nombre
        tam = f"{c.tamano_bytes / 1e9:.2f} GB" if c.tamano_bytes else "tamaño desconocido"
        print(f"  {n.inicio:%Y-%m-%d %H:%M} T{n.track:03d} F{n.frame:03d} {n.direccion[:3]} "
              f"A={'/'.join(n.pol_a) or '—'} B={'/'.join(n.pol_b) or '—'} {n.crid} cubre {c.cobertura:.0%} · {tam}")
        print(f"    {n.granule}")
    for p in r.pares:
        print(f"  PAR {p.estado}: {p.antes.nombre.inicio:%Y-%m-%d} → {p.despues.nombre.inicio:%Y-%m-%d} "
              f"({p.dias:.0f} días, cubre {p.cobertura_comun:.0%})")
    for b in r.bloqueos[:10]:
        print(f"  sin par: {b}")
    for av in r.avisos:
        print(f"  AVISO: {av}")
    print(f"Registro: {destino}")
    return 0


def _inspeccionar(a) -> int:
    try:
        print(json.dumps(nisar_gcov.inspeccionar(a.hdf5).resumen(), indent=2, ensure_ascii=False, default=str))
    except nisar_gcov.ErrorGCOV as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


def _recortar(a) -> int:
    try:
        salida = nisar_gcov.exportar_recorte(a.hdf5, tuple(a.bbox), a.frecuencia, a.termino, carpeta=a.carpeta,
                                             madurez=a.madurez, sha_origen=a.sha256_origen)
    except nisar_gcov.ErrorGCOV as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"Recorte: {salida}\nFicha:   {salida.with_suffix('.json')}")
    return 0


def main(argumentos=None) -> int:
    p = argparse.ArgumentParser(description="NISAR L2 GCOV para V.I.S.O.R. (banda L, separado de Sentinel-1)")
    sub = p.add_subparsers(dest="accion", required=True)
    b = sub.add_parser("buscar", help="catálogo (solo metadatos, sin credenciales ni descargas)")
    b.add_argument("--inicio", default="2026-10-21")
    b.add_argument("--fin", default=f"{datetime.now(timezone.utc):%Y-%m-%d}")
    b.add_argument("--madurez", default="VALIDATED", choices=list(nisar_catalogo.COLECCIONES))
    b.add_argument("--max", type=int, default=nisar_catalogo.MAX_RESULTADOS)
    _bbox(b)
    i = sub.add_parser("inspeccionar", help="metadatos y capas de un HDF5 local (solo lectura)")
    i.add_argument("hdf5", type=Path)
    r = sub.add_parser("recortar", help="ventana del AOI a GeoTIFF gamma0 en potencia (no sobrescribe)")
    r.add_argument("hdf5", type=Path)
    r.add_argument("--frecuencia", choices=nisar_gcov.FRECUENCIAS, default="A")
    r.add_argument("--termino", choices=nisar_gcov.DIAGONALES, default="HHHH")
    r.add_argument("--madurez", choices=nisar_gcov.MADUREZ_VALIDAS, default=None,
                   help="madurez comprobada en el catálogo (si no se indica: NO_COMPROBADA)")
    r.add_argument("--sha256-origen", action="store_true", help="calcular el SHA-256 del HDF5 (lee el archivo entero)")
    r.add_argument("--carpeta", type=Path, default=None)
    _bbox(r)
    a = p.parse_args(argumentos)
    return {"buscar": _buscar, "inspeccionar": _inspeccionar, "recortar": _recortar}[a.accion](a)


if __name__ == "__main__":
    sys.exit(main())
