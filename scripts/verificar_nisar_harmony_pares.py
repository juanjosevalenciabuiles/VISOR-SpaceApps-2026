#!/usr/bin/env python3
"""Auditar un par NISAR Harmony ya preparado, SIN red ni descargas.

Uso:
  python scripts/verificar_nisar_harmony_pares.py
  python scripts/verificar_nisar_harmony_pares.py --informe data/nisar/catalogo/preparacion_XXXX.json

Lee resumen + manifiestos, comprueba SHA-256, tamaño, GeoTIFF, cuadrículas
de capas en cada fecha y compatibilidad temporal. No clasifica inundaciones,
no modifica los datos y no imprime secretos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils import nisar_harmony as harmony  # noqa: E402


class ErrorAuditoria(RuntimeError):
    pass


def _ruta_segura(carpeta: Path, nombre: str) -> Path:
    parte = Path(nombre)
    if parte.is_absolute() or len(parte.parts) != 1 or parte.name in ("", ".", ".."):
        raise ErrorAuditoria("Nombre de archivo o carpeta fuera del directorio permitido.")
    return carpeta / parte


def _sha256(ruta: Path) -> str:
    hasher = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(2 * 1024**2), b""):
            hasher.update(bloque)
    return hasher.hexdigest()


def _estadisticas_hh(ruta: Path) -> dict:
    """Cuenta potencia HH positiva/finita SIN confundirla con inundaciones."""
    import numpy as np
    import rasterio

    validos, total = 0, 0
    try:
        with rasterio.open(ruta) as src:
            for _, ventana in src.block_windows(1):
                muestra = src.read(1, window=ventana, masked=True)
                datos = np.asarray(muestra.data)
                mascara = np.ma.getmaskarray(muestra)
                total += datos.size
                validos += int(np.count_nonzero(~mascara & np.isfinite(datos) & (datos > 0)))
    except (OSError, rasterio.errors.RasterioError) as exc:
        raise ErrorAuditoria("No se pudo calcular la validez de intensidad HH.") from exc
    return {"pixeles_total": total, "pixeles_hh_positivos_finitos": validos,
            "fraccion_hh_positiva_finita": round(validos / total, 6) if total else 0}


def auditar(informe: Path, raiz: Path | None = None) -> dict:
    raiz = Path(raiz or RAIZ)
    informe = Path(informe)
    if not informe.is_file():
        raise ErrorAuditoria("No se encontró el informe indicado.")
    data = json.loads(informe.read_text(encoding="utf-8"))
    if data.get("estado") != "NISAR_COG_PREPARADO_SIN_CLASIFICAR" or data.get("metodo") != "NASA_HARMONY":
        raise ErrorAuditoria("El informe no corresponde a insumos NISAR Harmony preparados.")
    escenas = data.get("escenas") or []
    if len(escenas) != 2:
        raise ErrorAuditoria("Se esperaban exactamente dos escenas para verificar el par temporal.")
    resumen = []
    grillas = []
    total_bytes = 0
    directorio = raiz / "data" / "nisar" / "harmony"
    for escena in escenas:
        carpeta = _ruta_segura(directorio, escena["carpeta_relativa"])
        manifiesto = json.loads((carpeta / "manifest.json").read_text(encoding="utf-8"))
        if manifiesto.get("estado") != "INSUMOS_GCOV_SIN_CLASIFICAR" or manifiesto.get("granule") != escena["granule"]:
            raise ErrorAuditoria("El manifiesto no corresponde a la escena solicitada.")
        capas = {}
        bytes_escena = 0
        cuadricula_escena = None
        for item in manifiesto.get("archivos") or []:
            capa = item["capa"]
            if capa in capas:
                raise ErrorAuditoria("Hay capas científicas repetidas en el manifiesto.")
            ruta = _ruta_segura(carpeta, item["archivo"])
            if not ruta.is_file():
                raise ErrorAuditoria("Falta un archivo científico de la escena.")
            if ruta.stat().st_size != item["bytes"] or _sha256(ruta) != item["sha256"]:
                raise ErrorAuditoria("Tamaño o huella SHA-256 no coincide con el manifiesto.")
            info = harmony._validar_cog(ruta, manifiesto["aoi"], capa)
            cuadricula = (info["crs"], tuple(info["dimensiones"]), tuple(info["transform"]))
            if cuadricula_escena is not None and cuadricula != cuadricula_escena:
                raise ErrorAuditoria("Las capas de una misma escena no comparten la misma cuadrícula.")
            cuadricula_escena = cuadricula
            capas[capa] = {
                "mib": round(item["bytes"] / 1024**2, 3),
                "dtype": info["dtype"],
                "crs": info["crs"],
                "resolucion_m": info["resolucion_m"],
            }
            if capa in ("HHHH", "VVVV"):
                capas[capa].update(_estadisticas_hh(ruta))
            bytes_escena += item["bytes"]
        if set(escena["archivos"]) != set(item["archivo"] for item in manifiesto["archivos"]):
            raise ErrorAuditoria("Lista de archivos y manifiesto no coinciden.")
        if not {"mask", "numberOfLooks"}.issubset(capas) or not ({"HHHH", "VVVV"} & capas.keys()):
            raise ErrorAuditoria("Faltan máscara/looks o intensidad copolar para analizar calidad.")
        if bytes_escena != manifiesto["bytes_totales"] or bytes_escena != escena["bytes_totales"]:
            raise ErrorAuditoria("Totales de bytes inconsistentes para esta escena.")
        total_bytes += bytes_escena
        grillas.append(cuadricula_escena)
        resumen.append({"granule": escena["granule"],
                        "mib": round(bytes_escena / 1024**2, 3),
                        "capas": capas})
    if total_bytes != data["bytes_totales"]:
        raise ErrorAuditoria("Total del plan no coincide con los archivos guardados.")
    iguales = grillas[0] == grillas[1]
    return {
        "estado": "ARCHIVOS_GCOV_AUDITADOS_SIN_CLASIFICAR",
        "fechas": 2,
        "archivos": sum(len(e["capas"]) for e in resumen),
        "total_bytes": total_bytes,
        "total_mib": round(total_bytes / 1024**2, 3),
        "grillas_temporales_iguales": iguales,
        "advertencia_grillas": (
            "Las dos fechas tienen la misma cuadrícula geométrica; falta evaluar comparabilidad radiométrica."
            if iguales else
            "Las cuadrículas de ambas fechas DIFEREN: registrar/reproyectar explícitamente antes de comparar."
        ),
        "escenas": resumen,
        "advertencia": (
            "Fracciones HH son solo potencia positiva/finita, NO máscara QA decodificada "
            "ni superficie inundada; el solape temporal útil requiere más evaluación."
        ),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--informe", type=Path)
    a = ap.parse_args(argv)
    try:
        ruta = a.informe
        if ruta is None:
            base = RAIZ / "data" / "nisar" / "catalogo"
            candidatos = sorted(base.glob("preparacion_*.json"),
                                key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidatos:
                raise ErrorAuditoria("No hay informes de preparación en la carpeta experimental.")
            ruta = candidatos[0]
        salida = auditar(ruta)
        print(json.dumps(salida, ensure_ascii=False, indent=2))
        return 0
    except (ErrorAuditoria, OSError, KeyError, ValueError, TypeError) as exc:
        print("Auditoría NISAR detenida:", type(exc).__name__, str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
