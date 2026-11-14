#!/usr/bin/env python3
"""Diagnóstico público de OPERA RTC-S1 en ASF para Chigorodó.

Busca metadatos para 2026-09-24 y 2026-10-06. NO descarga GeoTIFF,
no requiere credenciales, no pide procesamientos HyP3 y no toca data/.
Los productos OPERA vienen por ráfagas; no entran directamente al motor HyP3.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

A_O_I = (-76.80, 7.55, -76.55, 7.80)
FECHAS = (date(2026, 9, 24), date(2026, 10, 6))
PATRON_RAFAGA = re.compile(r"T\d{3}[-_]\d{6}[-_]IW[123]", re.IGNORECASE)


def wkt_aoi(limites):
    o, s, e, n = tuple(float(x) for x in limites)
    if not (-180 <= o < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("Extensión AOI inválida")
    if e - o > 5 or n - s > 5:
        raise ValueError("AOI demasiado amplia")
    return f"POLYGON(({o} {s},{e} {s},{e} {n},{o} {n},{o} {s}))"


def nombre_de_url(url):
    return Path(urlparse(url).path).name


def identificar_rafaga(p):
    etiqueta = str(p.get("operaBurstID") or p.get("fileID") or "")
    coincidencia = PATRON_RAFAGA.search(etiqueta)
    return coincidencia.group(0).replace("_", "-").upper() if coincidencia else None


def normalizar_producto(producto):
    p = producto.properties
    adicionales = [str(u) for u in p.get("additionalUrls") or [] if isinstance(u, str)]
    archivos = [nombre_de_url(u) for u in adicionales]
    defecto = p.get("url")
    if isinstance(defecto, str) and defecto:
        archivos.append(nombre_de_url(defecto))
    return {
        "fileID": p.get("fileID"), "startTime": p.get("startTime"),
        "stopTime": p.get("stopTime"), "operaBurstID": identificar_rafaga(p),
        "polarization": p.get("polarization"), "flightDirection": p.get("flightDirection"),
        "pathNumber": p.get("pathNumber"),
        "archivos": sorted(set(n for n in archivos if n)),
        "num_urls_adicionales": len(adicionales),
    }


def consulta(asf, fecha: date, limite=150):
    desde = fecha.isoformat() + "T00:00:00Z"
    hasta = (fecha + timedelta(days=1)).isoformat() + "T00:00:00Z"
    return asf.search(
        dataset="OPERA-S1", processingLevel="RTC",
        intersectsWith=wkt_aoi(A_O_I), start=desde, end=hasta,
        maxResults=limite,
    )


def comparar_por_rafagas(fechas_resultados):
    conjuntos = {
        dia: {p["operaBurstID"] for p in productos if p.get("operaBurstID")}
        for dia, productos in fechas_resultados.items()
    }
    dias = sorted(conjuntos)
    return sorted(set.intersection(*(conjuntos[d] for d in dias))) if dias else []


def ejecutar(asf, fechas=FECHAS, limite=150):
    detalle = {}
    for fecha in fechas:
        detalle[fecha.isoformat()] = [
            normalizar_producto(x) for x in consulta(asf, fecha, limite=limite)
        ]
    pares = comparar_por_rafagas(detalle)
    return {
        "status": "METADATA_ONLY_NOT_DOWNLOAD_TESTED",
        "fuente": "NASA ASF OPERA RTC-S1 / asf_search",
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "aoi_epsg4326": list(A_O_I), "pixel_spacing_expected_m": 30,
        "max_results_per_date": limite,
        "por_fecha": {
            d: {
                "productos": len(v),
                "rafagas_unicas": len({p["operaBurstID"] for p in v if p["operaBurstID"]}),
                "posible_truncamiento": len(v) >= limite,
                "candidatos_vv": sum(1 for p in v if any(n.endswith("_VV.tif") for n in p["archivos"])),
                "candidatos_vh": sum(1 for p in v if any(n.endswith("_VH.tif") for n in p["archivos"])),
                "mascaras": sum(1 for p in v if any(n.endswith("_mask.tif") for n in p["archivos"])),
            } for d, v in detalle.items()
        },
        "rafagas_en_ambas_fechas": pares,
        "advertencias": [
            "La coincidencia por rafaga NO valida un cambio ambiental.",
            "Falta confirmar mosaicos, cobertura real, mascara, CRS y alineacion.",
            "Los OPERA RTC-S1 son por rafaga, no escenas completas RTC de HyP3.",
            "Si hay truncamiento no se confirma cobertura completa.",
            "NO se ha descargado ningun producto SAR.",
        ],
        "detalle": detalle,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--salida", type=Path, help="Informe JSON, fuera de data/")
    parser.add_argument("--limite", type=int, default=150)
    args = parser.parse_args(argv)
    if not 1 <= args.limite <= 1000:
        parser.error("--limite debe estar entre 1 y 1000")
    try:
        import asf_search as asf
    except ImportError:
        sys.exit("Falta asf-search. Instala: python -m pip install asf-search")
    try:
        informe = ejecutar(asf, limite=args.limite)
    except Exception as exc:
        sys.exit(f"Consulta fallida: {type(exc).__name__}. Sin descargas ni datos modificados.")
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(informe, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in informe.items() if k != "detalle"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
