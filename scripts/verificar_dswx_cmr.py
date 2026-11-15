#!/usr/bin/env python3
"""Busca OPERA DSWx-S1 (agua superficial) para Chigorodó, SOLO metadatos.

DSWx-S1 es Nivel 3 y se distribuye por NASA PO.DAAC (CMR), NO es el
mismo archivo que OPERA RTC-S1 de ASF. Ni cero coincidencias ni agua
clasificada implican por sí solos que exista o no inundación.
No descarga GeoTIFF, no usa credenciales y no modifica data/.
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
SHORT_NAME = "OPERA_L3_DSWX-S1_V1"
AOI = (-76.80, 7.55, -76.55, 7.80)
FECHAS = (date(2026, 9, 24), date(2026, 10, 6))


def crear_url(fecha: date, limites=AOI, max_resultados=150):
    if not 1 <= max_resultados <= 2000:
        raise ValueError("Límite de resultados inválido")
    o, s, e, n = (float(v) for v in limites)
    if o >= e or s >= n:
        raise ValueError("AOI inválida")
    parametros = {
        "short_name": SHORT_NAME,
        "bounding_box": ",".join(f"{v:.5f}" for v in (o, s, e, n)),
        "temporal": (fecha.isoformat() + "T00:00:00Z," +
                     (fecha + timedelta(days=1)).isoformat() + "T00:00:00Z"),
        "page_size": str(max_resultados),
        "sort_key": "-start_date",
    }
    return CMR + "?" + urllib.parse.urlencode(parametros)


def normalizar(respuesta):
    feed = respuesta.get("feed")
    if not isinstance(feed, dict) or not isinstance(feed.get("entry"), list):
        raise ValueError("CMR no devolvió la estructura feed.entry esperada")
    resultado = []
    for item in feed["entry"]:
        if not isinstance(item, dict):
            continue
        links = item.get("links") or []
        salida = []
        for enlace in links:
            if not isinstance(enlace, dict) or enlace.get("inherited"):
                continue
            href = enlace.get("href")
            if isinstance(href, str) and href.startswith("https://") and href.lower().split("?")[0].endswith(".tif"):
                salida.append(Path(urllib.parse.urlparse(href).path).name)
        resultado.append({
            "granule_ur": item.get("granule_ur"),
            "time_start": item.get("time_start"),
            "time_end": item.get("time_end"),
            "concept_id": item.get("id"),
            "archivos_tif_listados": sorted(set(salida)),
        })
    return resultado


def ejecutar(fechas=FECHAS, opener=None, limite=150):
    pedir = opener or urllib.request.urlopen
    resumen = {}
    detalle = {}
    for fecha in fechas:
        req = urllib.request.Request(crear_url(fecha, max_resultados=limite),
                                     headers={"User-Agent": "VISOR-SpaceApps-2026/DSWx-Metadata-Only",
                                              "Accept": "application/json"})
        with pedir(req, timeout=25) as respuesta:
            payload = json.loads(respuesta.read().decode("utf-8"))
        productos = normalizar(payload)
        detalle[fecha.isoformat()] = productos
        resumen[fecha.isoformat()] = {"total_en_pagina": len(productos),
                                     "posible_truncamiento": len(productos) >= limite,
                                     "con_archivos_tif_listados": sum(bool(p["archivos_tif_listados"]) for p in productos)}
    return {
        "estado": "METADATOS_ONLY_NO_DESCARGADOS",
        "fuente": "NASA PO.DAAC / Earthdata CMR",
        "coleccion": SHORT_NAME,
        "aoi_epsg4326": list(AOI),
        "consultado_utc": datetime.now(timezone.utc).isoformat(),
        "pixeles_estimados_m": 30,
        "por_fecha": resumen,
        "advertencias": [
            "DSWx-S1 clasifica agua superficial, no confirma una inundacion.",
            "Para evaluar posible inundacion hace falta referencia historica y control de calidad.",
            "El bbox es solo un filtro de catalogo: verificar interseccion espacial y cobertura de COG antes de usar.",
            "El producto incluye limitaciones de deteccion de agua bajo vegetacion, cuerpos angostos y otros escenarios.",
            "No se han descargado datos ni usado tokens de Earthdata.",
        ],
        "detalle": detalle,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--salida", type=Path, help="Informe opcional, FUERA de data/")
    ap.add_argument("--limite", type=int, default=150)
    args = ap.parse_args(argv)
    try:
        resultados = ejecutar(limite=args.limite)
    except (ValueError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        ap.exit(2, f"CMR no verificado: {type(exc).__name__}. No se descargó nada.\n")
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(json.dumps({k: v for k, v in resultados.items() if k != "detalle"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
