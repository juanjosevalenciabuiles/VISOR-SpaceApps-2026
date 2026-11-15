"""Caché local de blobs pequeños: sin red ni inferencias científicas."""
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path


def firma_cache(granules, aoi, version, qa, madurez, polarizacion):
    if (not granules or any(not isinstance(g, str) or not g.strip() for g in granules)
            or len(aoi) != 4 or any(type(v) not in (float, int) or not math.isfinite(v) for v in aoi)
            or madurez not in ("BETA", "PROVISIONAL", "VALIDATED")
            or any(not isinstance(v, str) or not v.strip()
                   for v in (version, qa, polarizacion))):
        raise ValueError("Firma incompleta")
    payload = dict(granules=granules, aoi=aoi, version=version, qa=qa,
                   madurez=madurez, polarizacion=polarizacion)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validar(firma, max_bytes):
    if (not isinstance(firma, str) or len(firma) != 64
            or any(c not in "0123456789abcdef" for c in firma)
            or type(max_bytes) is not int or max_bytes < 0):
        raise ValueError("Firma o presupuesto inválido")


def guardar(directorio, firma, contenido, *, max_bytes=200_000_000):
    _validar(firma, max_bytes)
    if not isinstance(contenido, bytes) or len(contenido) > max_bytes:
        return {"estado": "PRESUPUESTO_EXCEDIDO", "bytes": 0}
    carpeta = Path(directorio)
    carpeta.mkdir(parents=True, exist_ok=True)
    fd, temporal = tempfile.mkstemp(prefix=".visor-", dir=carpeta)
    try:
        with os.fdopen(fd, "wb") as archivo:
            archivo.write(contenido)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, carpeta / (firma + ".bin"))
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)
    return {"estado": "GUARDADO", "bytes": len(contenido),
            "sha256": hashlib.sha256(contenido).hexdigest()}


def recuperar(directorio, firma, *, sha256, max_bytes=200_000_000):
    """Un HIT requiere digest externo; no certifica QA ni inundación."""
    _validar(firma, max_bytes)
    _validar(sha256, max_bytes)
    ruta = Path(directorio) / (firma + ".bin")
    if not ruta.is_file() or ruta.is_symlink():
        return {"estado": "MISS", "bytes": 0}
    if ruta.stat().st_size > max_bytes:
        return {"estado": "PRESUPUESTO_EXCEDIDO", "bytes": 0}
    with ruta.open("rb") as archivo:
        contenido = archivo.read(max_bytes + 1)
    if len(contenido) > max_bytes or hashlib.sha256(contenido).hexdigest() != sha256:
        return {"estado": "CACHE_INVALIDA", "bytes": 0}
    return {"estado": "HIT", "bytes": len(contenido), "contenido": contenido}
