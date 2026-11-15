"""Validaciones conservadoras de entradas CMR antes de solicitar bytes remotos."""
from __future__ import annotations

import ipaddress
import math
from datetime import datetime
from urllib.parse import urlsplit


def fecha_observacion(valor: str) -> datetime:
    """Exige fecha y hora ISO con zona; no acepta fechas truncadas."""
    if not isinstance(valor, str):
        raise ValueError("Fecha de observación inválida")
    try:
        instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Fecha de observación inválida") from exc
    if instante.tzinfo is None or instante.utcoffset() is None:
        raise ValueError("Fecha de observación sin zona horaria")
    return instante


def bbox_valida(valores: object) -> tuple[float, float, float, float]:
    if not isinstance(valores, (tuple, list)) or len(valores) != 4:
        raise ValueError("BBox inválida")
    try:
        oeste, sur, este, norte = (float(v) for v in valores)
    except (TypeError, ValueError) as exc:
        raise ValueError("BBox inválida") from exc
    if not all(math.isfinite(v) for v in (oeste, sur, este, norte)):
        raise ValueError("BBox no finita")
    if not (-180 <= oeste < este <= 180 and -90 <= sur < norte <= 90):
        raise ValueError("BBox fuera de rango o antimeridiano")
    return oeste, sur, este, norte


def url_candidata(url: object) -> bool:
    """Filtro previo, NO autorización Earthdata ni garantía de COG/range."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 443) or parsed.fragment:
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        if host.lower() in {"localhost", "localhost.localdomain"} or "." not in host:
            return False
        return True
    except ValueError:
        return False
