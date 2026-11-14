#!/usr/bin/env python3
"""Crear un mapa de COBERTURA QA NISAR (no agua ni inundación), sin red.

Clases: 0 no utilizable en ninguna, 1 solo fecha inicial,
2 solo fecha final, 3 utilizable en ambas. Una capa UInt8 GTiff
comprimida sin pérdida, misma cuadrícula y resolución (10 m) que GCOV.
Previo: auditoría SHA-256 para ocho COG; no modifica ningún original.

Uso:
  python scripts/nisar_mapa_cobertura_qa.py --informe data/nisar/catalogo/preparacion_UUID.json
Salida: data/nisar/qa/cobertura_<sha>.tif + .json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform_bounds

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.nisar_solape_qa import _abrir_escena, _usables  # noqa: E402
from scripts.verificar_nisar_harmony_pares import ErrorAuditoria, auditar  # noqa: E402

# Los colores representan validez de observación SAR, NUNCA inundaciones.
COLORES = {
    0: (0, 0, 0, 0),
    1: (227, 157, 57, 255),      # solo la fecha anterior
    2: (139, 102, 203, 255),     # solo la fecha posterior
    3: (29, 159, 97, 255),       # intersección de dos observaciones QA
}


def generar(informe: Path, raiz: Path | None = None,
            destino: Path | None = None) -> dict:
    raiz = Path(raiz or RAIZ)
    informe = Path(informe)
    # Verificar de nuevo SHA de todos los insumos y geometría, sin descargar.
    chequeo = auditar(informe, raiz)
    if chequeo["fechas"] != 2 or chequeo["archivos"] != 8:
        raise ErrorAuditoria("Se requieren dos escenas y las ocho capas NISAR.")
    if not chequeo["grillas_temporales_iguales"]:
        raise ErrorAuditoria("No se permite cruzar fechas sin la misma cuadrícula.")
    data = json.loads(informe.read_text(encoding="utf-8"))
    escenas = data["escenas"]
    identificador = hashlib.sha256(informe.read_bytes()).hexdigest()[:14]
    salida = Path(destino or (raiz / "data" / "nisar" / "qa" /
                              f"cobertura_{identificador}.tif"))
    salida.parent.mkdir(parents=True, exist_ok=True)
    meta_path = salida.with_suffix(".json")
    if salida.exists() or meta_path.exists():
        raise ErrorAuditoria("La salida QA ya existe; no sobrescribir imágenes de auditoría.")
    if shutil.disk_usage(salida.parent).free < 64 * 1024**2:
        raise ErrorAuditoria("No hay espacio libre para guardar el mapa de calidad.")
    temp = salida.with_name("." + salida.name + "." + uuid.uuid4().hex[:8] + ".part")
    cuentas = {0: 0, 1: 0, 2: 0, 3: 0}
    minimo_x = minimo_y = maximo_x = maximo_y = None
    try:
        with ExitStack() as stack:
            fuentes = [_abrir_escena(raiz, e, stack) for e in escenas]
            fuente = fuentes[0]["HHHH"]
            perfil = fuente.profile.copy()
            perfil.update(
                driver="GTiff", count=1, dtype="uint8", nodata=0,
                compress="deflate", predictor=1,
                tiled=True, blockxsize=256, blockysize=256,
                interleave="band", BIGTIFF="IF_SAFER",
            )
            with rasterio.open(temp, "w", **perfil) as out:
                out.write_colormap(1, COLORES)
                for _, ventana in fuente.block_windows(1):
                    validos = []
                    for escena in fuentes:
                        datos = {
                            c: escena[c].read(1, window=ventana)
                            for c in ("HHHH", "HVHV", "mask", "numberOfLooks")
                        }
                        validos.append(_usables(datos)[-1])
                    categoria = validos[0].astype(np.uint8)
                    categoria += validos[1].astype(np.uint8) * 2
                    out.write(categoria, 1, window=ventana)
                    valores, cantidades = np.unique(categoria, return_counts=True)
                    for valor, cantidad in zip(valores, cantidades):
                        cuentas[int(valor)] += int(cantidad)
                    comunes = np.argwhere(categoria == 3)
                    if comunes.size:
                        r0 = int(ventana.row_off)
                        c0 = int(ventana.col_off)
                        r_min = r0 + int(comunes[:, 0].min())
                        r_max = r0 + int(comunes[:, 0].max()) + 1
                        c_min = c0 + int(comunes[:, 1].min())
                        c_max = c0 + int(comunes[:, 1].max()) + 1
                        minimo_x = c_min if minimo_x is None else min(minimo_x, c_min)
                        maximo_x = c_max if maximo_x is None else max(maximo_x, c_max)
                        minimo_y = r_min if minimo_y is None else min(minimo_y, r_min)
                        maximo_y = r_max if maximo_y is None else max(maximo_y, r_max)
                out.update_tags(
                    AREA="COBERTURA_QA_NISAR_NO_INUNDACION",
                    CAPAS="HHHH,HVHV,mask,numberOfLooks",
                    FUENTE="NASA NISAR L2 GCOV Harmony",
                    NOTA="3 significa observaciones utilizables en ambas fechas; NO AGUA",
                )
            pixeles = sum(cuentas.values())
            res_m2 = abs(fuente.transform.a * fuente.transform.e -
                         fuente.transform.b * fuente.transform.d)
            if pixeles != fuente.width * fuente.height:
                raise ErrorAuditoria("La cuadrícula resultante tiene tamaño inconsistente.")
            bbox_comun = None
            if minimo_x is not None:
                from rasterio.windows import Window, bounds
                b = bounds(Window(minimo_x, minimo_y, maximo_x - minimo_x,
                                  maximo_y - minimo_y), fuente.transform)
                bbox_comun = list(transform_bounds(fuente.crs, "EPSG:4326", *b,
                                                    densify_pts=21))
        meta = {
            "estado": "MAPA_COBERTURA_QA_NO_INUNDACION",
            "archivo": salida.name,
            "source_informe": informe.name,
            "crs": str(perfil["crs"]),
            "resolucion_m": [abs(float(fuente.transform.a)),
                             abs(float(fuente.transform.e))],
            "clasificacion": {
                "0": "no utilizable en ambas fechas (incluye sin datos)",
                "1": "utilizable solo fecha inicial",
                "2": "utilizable solo fecha final",
                "3": "utilizable en ambas fechas",
            },
            "pixeles_por_clase": {str(k): v for k, v in cuentas.items()},
            "area_comun_qa_km2": round(cuentas[3] * res_m2 / 1e6, 4),
            "bbox_comun_wgs84_aproximado": bbox_comun,
            "advertencia": (
                "Clase 3 indica validez técnica de SAR en dos fechas, NO extensión de "
                "agua/inundación. El bbox contiene zonas no necesariamente válidas."
            ),
        }
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                             encoding="utf-8")
        os.replace(temp, salida)
        return {
            **meta, "archivo": str(salida),
            "tamanio_mib": round(salida.stat().st_size / 1024**2, 3),
            "meta": str(meta_path),
        }
    except Exception:
        temp.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--informe", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        print(json.dumps(generar(args.informe), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, ErrorAuditoria, KeyError,
            rasterio.errors.RasterioError) as exc:
        print("Mapa de calidad no generado:", type(exc).__name__, str(exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
