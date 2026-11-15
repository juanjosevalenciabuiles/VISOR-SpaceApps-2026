"""Adaptadores opt-in para OPERA DSWx-S1 e IMERG previamente verificados.

No consultan red ni convierten catálogo en observación. El integrador debe
inspeccionar los píxeles, la QA, el AOI y el linaje antes de activar evidencia.
"""
from __future__ import annotations

import math
from datetime import date
from urllib.parse import urlsplit

PRODUCTOS = {"DSWx-S1": "agua_satelital", "IMERG": "lluvia"}


def _fecha(valor: object) -> str:
    if not isinstance(valor, str):
        raise ValueError("Fecha de observación ausente")
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError as exc:
        raise ValueError("Fecha de observación inválida") from exc


def _url_https(valor: object) -> str:
    if not isinstance(valor, str):
        raise ValueError("URL de procedencia ausente")
    p = urlsplit(valor)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("La URL de procedencia debe ser HTTPS")
    return valor


def adaptar_observacion(producto: str, metadatos: dict, *, pixeles_verificados: bool = False) -> dict:
    """Normaliza una observación al contrato de verificacion_multifuente de V8.

    pixeles_verificados es una afirmación del llamador: NO se deduce del catálogo.
    La QA y la cobertura en AOI deben haber sido comprobadas independientemente.
    """
    if producto not in PRODUCTOS:
        raise ValueError("Producto no soportado")
    if not isinstance(metadatos, dict):
        raise ValueError("Metadatos inválidos")
    fecha = _fecha(metadatos.get("observed_at"))
    url = _url_https(metadatos.get("url"))
    fuente = "NASA OPERA" if producto == "DSWx-S1" else "NASA GPM"
    linaje = str(metadatos.get("granule_origen") or "").strip()
    qa = metadatos.get("qa")
    relacion = metadatos.get("relacion_espacial")
    apto = (pixeles_verificados is True and qa == "APTO"
            and relacion == "aoi" and bool(linaje))
    if producto == "DSWx-S1":
        apto = apto and metadatos.get("agua_observada") is True
        origen = "S1:" + linaje if linaje else ""
    else:
        valor = metadatos.get("precipitacion_mm")
        apto = (apto and type(valor) in (int, float)
                and math.isfinite(valor) and 0 <= valor < 100000)
        origen = "GPM:" + linaje if linaje else ""
    return {
        "tipo": PRODUCTOS[producto],
        "observed_at": fecha,
        "valid": bool(apto),
        "relacion_espacial": relacion if relacion == "aoi" else "sin_verificar",
        "origen": origen,
        "fuente": fuente,
        "producto": producto,
        "url": url,
        "qa": qa if isinstance(qa, str) else "NO_VERIFICADO",
        "limitaciones": (
            "Clasificación DSWx-S1 de agua observada; no demuestra inundación. "
            "Comparte origen con productos derivados del mismo Sentinel-1."
            if producto == "DSWx-S1" else
            "Precipitación IMERG contextual; no demuestra presencia de agua ni inundación."
        ),
    }
