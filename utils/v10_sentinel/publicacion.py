"""Publicación conservadora de comparación OPERA ya validada; no realiza adquisición."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import os
import tempfile

import numpy as np
import rasterio
from rasterio.transform import Affine

from utils.v10_sentinel.wtr import _grilla_verificada


def publicar_comparacion(
    resultado: dict,
    georef: dict,
    fecha_anterior: str,
    fecha_posterior: str,
    granulo_anterior: str,
    granulo_posterior: str,
    destino: str | Path,
    *,
    qa_verificada: bool = False,
    fuente_verificada: bool = False,
) -> dict:
    """Emite GeoTIFF + ficha solo para matriz apta y linaje verificable.

    Las banderas deben venir de verificaciones reales externas: no se infieren
    de CMR ni de la presencia de enlaces. No confirma una inundación.
    """
    if not (qa_verificada and fuente_verificada):
        return {"estado": "NO_APTA", "motivo": "FUENTE_O_QA_NO_VERIFICADA"}
    if resultado.get("estado") != "APTA" or not resultado.get("cobertura_qa_completa"):
        return {"estado": "NO_APTA", "motivo": "COBERTURA_QA_INCOMPLETA"}
    try:
        crs, valores = _grilla_verificada(georef)
        fechas = [datetime.fromisoformat(x.replace("Z", "+00:00"))
                  for x in (fecha_anterior, fecha_posterior)]
        if any(x.tzinfo is None for x in fechas) or fechas[0] >= fechas[1]:
            raise ValueError("Fechas pre/post inválidas")
        if not all(isinstance(x, str) and x.strip()
                   for x in (granulo_anterior, granulo_posterior)):
            raise ValueError("Granulos sin identificador")
        clases = np.asarray(resultado["clases"])
        if clases.ndim != 2 or not clases.size or not np.isin(
            clases, [0, 1, 2, 255]
        ).all():
            raise ValueError("Matriz de salida inválida")
        if clases.dtype.kind not in "iu":
            raise ValueError("Clases no enteras")
        if int(np.count_nonzero(clases != 255)) != resultado.get("pixeles_totales"):
            raise ValueError("Conteo de cobertura incoherente")
    except (KeyError, ValueError, TypeError, OverflowError):
        return {"estado": "NO_APTA", "motivo": "METADATOS_O_MATRIZ_INVALIDOS"}

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    ficha_path = destino.with_suffix(".visor.ficha.v1.json")
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destino.parent, prefix=".visor-", suffix=".tif", delete=False
        ) as archivo:
            temporal = Path(archivo.name)
        with rasterio.open(
            temporal, "w", driver="GTiff", height=clases.shape[0],
            width=clases.shape[1], count=1, dtype="uint8", nodata=255,
            crs=crs, transform=Affine(*valores), compress="deflate"
        ) as ds:
            ds.write(clases.astype("uint8"), 1)
            ds.set_band_description(1, "Cambio exploratorio de agua observada")
        sha256 = hashlib.sha256(temporal.read_bytes()).hexdigest()
        ficha = {
            "schema": "visor.ficha.v1",
            "estado": "APTA",
            "sensor": "Sentinel-1 / OPERA DSWx-S1 V1",
            "coleccion": "OPERA_L3_DSWX-S1_V1",
            "observacion_anterior": fecha_anterior,
            "observacion_posterior": fecha_posterior,
            "granulo_anterior": granulo_anterior,
            "granulo_posterior": granulo_posterior,
            "qa": "VERIFICADA",
            "cobertura_qa_completa": True,
            "sha256": sha256,
            "crs": crs.to_string(),
            "transform": list(valores),
            "clases_salida": {"0": "no_agua_posterior",
                               "1": "agua_persistente", "2": "agua_nueva",
                               "255": "sin_datos_o_fuera_aoi"},
            "advertencia": "Cambio de agua observada, no inundacion confirmada.",
        }
        # Nunca publicar la ficha antes de haber cerrado el GeoTIFF.
        temporal.replace(destino)
        ficha_temporal = ficha_path.with_suffix(".json.tmp")
        ficha_temporal.write_text(json.dumps(ficha, indent=2), encoding="utf-8")
        os.replace(ficha_temporal, ficha_path)
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
    return {"estado": "APTA", "geotiff": str(destino),
            "ficha": str(ficha_path), "sha256": sha256}
