#!/usr/bin/env python3
"""Auditoría complementaria de solape temporal QA de NISAR GCOV, sin red ni descargas.

Compara píxel a píxel SOLO las dos fechas del informe Harmony:
- máscara 1..254 (subswath válida; 0 parcialmente enfocado; 255 fuera),
- numberOfLooks positivo/finito,
- HHHH y HVHV ambos positivos/finito.
Los resultados son superficies de COBERTURA USABLE, nunca inundaciones.
Antes de trabajar valida SHA-256 y cuadriculas con verificar_nisar_harmony_pares.
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import rasterio

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.verificar_nisar_harmony_pares import (  # noqa: E402
    ErrorAuditoria,
    _ruta_segura,
    auditar,
)

CAPAS = ("HHHH", "HVHV", "mask", "numberOfLooks")


def _abrir_escena(p: Path, escena: dict, stack: ExitStack):
    carpeta = _ruta_segura(p / "data" / "nisar" / "harmony", escena["carpeta_relativa"])
    manifiesto = json.loads((carpeta / "manifest.json").read_text(encoding="utf-8"))
    if set(x["capa"] for x in manifiesto.get("archivos") or []) != set(CAPAS):
        raise ErrorAuditoria("Se requieren las cuatro capas HH, HV, máscara y looks por escena.")
    return {
        c["capa"]: stack.enter_context(rasterio.open(_ruta_segura(carpeta, c["archivo"])))
        for c in manifiesto["archivos"]
    }


def _usables(datos):
    hh, hv, mascara, looks = [np.asarray(datos[c]) for c in CAPAS]
    m = (mascara >= 1) & (mascara <= 254)
    l = np.isfinite(looks) & (looks > 0)
    h = np.isfinite(hh) & (hh > 0)
    v = np.isfinite(hv) & (hv > 0)
    return m, l, h, v, m & l & h & v


def calcular(informe: Path, raiz: Path | None = None) -> dict:
    raiz = Path(raiz or RAIZ)
    evaluacion = auditar(informe, raiz)
    if evaluacion["fechas"] != 2 or evaluacion["archivos"] != 8:
        raise ErrorAuditoria("Se requieren dos fechas y las ocho capas GCOV.")
    if not evaluacion["grillas_temporales_iguales"]:
        raise ErrorAuditoria("Las fechas no comparten cuadrícula: no comparar píxeles.")
    data = json.loads(Path(informe).read_text(encoding="utf-8"))
    escenas = data["escenas"]
    globales = [
        {"mask_valida": 0, "mask_cero": 0, "mask_fuera_255": 0,
         "looks_positivos": 0, "hh_positiva": 0, "hv_positiva": 0, "usable": 0}
        for _ in escenas
    ]
    ambos = 0
    pixeles = 0
    with ExitStack() as stack:
        fuentes = [_abrir_escena(raiz, escena, stack) for escena in escenas]
        hh0 = fuentes[0]["HHHH"]
        transform = hh0.transform
        area_km2_por_pixel = abs(transform.a * transform.e - transform.b * transform.d) / 1e6
        for _, ventana in hh0.block_windows(1):
            validos = []
            for i, source in enumerate(fuentes):
                datos = {c: source[c].read(1, window=ventana) for c in CAPAS}
                m, l, h, v, usable = _usables(datos)
                stats = globales[i]
                stats["mask_valida"] += int(np.count_nonzero(m))
                stats["mask_cero"] += int(np.count_nonzero(datos["mask"] == 0))
                stats["mask_fuera_255"] += int(np.count_nonzero(datos["mask"] == 255))
                stats["looks_positivos"] += int(np.count_nonzero(l))
                stats["hh_positiva"] += int(np.count_nonzero(h))
                stats["hv_positiva"] += int(np.count_nonzero(v))
                stats["usable"] += int(np.count_nonzero(usable))
                validos.append(usable)
            ambos += int(np.count_nonzero(validos[0] & validos[1]))
            pixeles += validos[0].size

    if pixeles <= 0:
        raise ErrorAuditoria("No se encontraron píxeles para auditar.")
    for estadistica in globales:
        estadistica["fraccion_usable"] = round(estadistica["usable"] / pixeles, 6)
        estadistica["area_usable_km2"] = round(estadistica["usable"] * area_km2_por_pixel, 4)
    return {
        "estado": "SOLAPE_GCOV_QA_NO_INUNDACION",
        "fechas": [escena["granule"] for escena in escenas],
        "pixeles_en_cuadricula": pixeles,
        "area_cuadricula_km2": round(pixeles * area_km2_por_pixel, 4),
        "criterio_mask": "1..254 subswath válida; 0 inválido; 255 fuera de cobertura",
        "criterio_looks": "numberOfLooks finito y > 0",
        "criterio_intensidad": "HHHH y HVHV finitos y > 0, ambas fechas",
        "por_fecha": globales,
        "pixeles_validos_comunes": ambos,
        "fraccion_valida_comun": round(ambos / pixeles, 6),
        "area_valida_comun_km2": round(ambos * area_km2_por_pixel, 4),
        "advertencia": (
            "Métrica de solape técnico/QA, NO extensión de agua ni inundación. "
            "Hay que validar semántica específica del producto, comparabilidad radiométrica "
            "y fuentes de referencia antes de clasificar cambios."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--informe", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.informe:
            informe = args.informe
        else:
            base = RAIZ / "data" / "nisar" / "catalogo"
            informes = sorted(base.glob("preparacion_*.json"),
                              key=lambda p: p.stat().st_mtime, reverse=True)
            if not informes:
                raise ErrorAuditoria("No existe un informe de preparación Harmony.")
            informe = informes[0]
        print(json.dumps(calcular(informe), indent=2, ensure_ascii=False))
        return 0
    except (ErrorAuditoria, ValueError, KeyError, OSError, rasterio.errors.RasterioError) as exc:
        print("Auditoría de solape interrumpida:", type(exc).__name__, str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
