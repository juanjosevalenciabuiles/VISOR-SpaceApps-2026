"""Cronología V10: solo observaciones verificables por metadatos del GeoTIFF.

No crea fechas intermedias, no atribuye clases de inundación a cambios dB y
nunca activa una capa por el mero hecho de que un archivo exista.
"""
from __future__ import annotations

from datetime import date, datetime
import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProductoTemporal:
    identificador: str
    sensor: str
    antes: date
    despues: date
    tipo: str
    estado: str


def _fecha(valor: Any) -> date | None:
    """Aceptar ISO-8601 verdadero, nunca fechas del nombre del archivo."""
    if not isinstance(valor, str) or not valor.strip():
        return None
    try:
        return datetime.fromisoformat(valor.strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _sensor(valor: Any) -> str | None:
    texto = str(valor or "").upper()
    if "NISAR" in texto:
        return "NISAR"
    if "SENTINEL-1" in texto or "S1C" in texto or "S1A" in texto or "S1B" in texto:
        return "Sentinel-1"
    return None


def producto_de_resultado(resultado: Any) -> ProductoTemporal | None:
    """Los productos sin dos fechas y procedencia real no aparecen como comparables."""
    if not getattr(resultado, "dibujable", False):
        return None
    capa = getattr(resultado, "capa", None)
    if capa is None or not getattr(getattr(capa, "procedencia", None), "es_real", False):
        return None
    ficha = getattr(resultado, "ficha", None) or {}
    if not isinstance(ficha, dict):
        return None
    bloque = ficha.get("procedencia") or {}
    if not isinstance(bloque, dict):
        return None
    fechas = bloque.get("fechas") or []
    if not isinstance(fechas, (list, tuple)) or len(fechas) != 2:
        return None
    antes, despues = _fecha(fechas[0]), _fecha(fechas[1])
    sensor = _sensor(bloque.get("sensor"))
    if antes is None or despues is None or antes >= despues or sensor is None:
        return None
    return ProductoTemporal(
        identificador=str(resultado.id), sensor=sensor, antes=antes, despues=despues,
        tipo=str(ficha.get("tipo_producto") or "producto_no_declarado"),
        estado=str(bloque.get("estado") or "real_sin_validar"),
    )


def dentro_de_zona(resultado: Any, zona: tuple[float, float, float, float] | None) -> bool:
    """Comparación territorial exige que el resultado cubra gran parte del AOI."""
    if zona is None:
        return False
    limites = getattr(getattr(resultado, "capa", None), "limites", None)
    if not limites:
        return False
    try:
        o, s, e, n = (float(v) for v in zona)
        a, b, c, d = (float(v) for v in limites)
    except (TypeError, ValueError):
        return False
    # NaN/inf y límites invertidos nunca deben pasar el filtro de cobertura.
    if not all(math.isfinite(v) for v in (o, s, e, n, a, b, c, d)):
        return False
    if not (-180 <= o < e <= 180 and -90 <= s < n <= 90):
        return False
    if not (-180 <= a < c <= 180 and -90 <= b < d <= 90):
        return False
    area = (e - o) * (n - s)
    cubierta = max(0, min(e, c) - max(o, a)) * max(0, min(n, d) - max(s, b))
    return area > 0 and cubierta / area >= 0.8


def productos_disponibles(resultados: list, zona=None, inicio: date | None = None,
                          fin: date | None = None) -> list[ProductoTemporal]:
    """Comparar por zona y rango de interés, sin asumir fechas idénticas entre sensores."""
    datos = []
    for r in resultados:
        p = producto_de_resultado(r)
        if p is None or not dentro_de_zona(r, zona):
            continue
        if inicio is not None and p.despues < inicio:
            continue
        if fin is not None and p.antes > fin:
            continue
        datos.append(p)
    return sorted(datos, key=lambda p: (p.despues, p.antes, p.identificador), reverse=True)


def capas_visibles(resultados: list, zona, inicio: date, fin: date, modo: str,
                   seleccion: dict[str, str] | None = None) -> dict[str, float]:
    """Activa un máximo de dos GeoTIFF reales, uno por sensor, sin crear una capa sintética."""
    if modo not in ("Ambos", "NISAR", "Sentinel-1"):
        return {}
    # Un periodo inválido nunca debe reactivar capas de una consulta anterior.
    if (not isinstance(inicio, date) or not isinstance(fin, date)
            or inicio > fin):
        return {}
    productos = productos_disponibles(resultados, zona, inicio, fin)
    preferidos = seleccion or {}
    salida = {}
    for sensor in ("NISAR", "Sentinel-1"):
        if modo not in ("Ambos", sensor):
            continue
        elegidos = [p for p in productos if p.sensor == sensor]
        p = next((v for v in elegidos if v.identificador == preferidos.get(sensor)), None)
        if p is None:
            p = elegidos[0] if elegidos else None
        if p is not None:
            salida[p.identificador] = 0.70 if modo == "Ambos" else 0.85
    return salida


def puntos_observados(productos: list[ProductoTemporal]) -> list[tuple[date, str]]:
    """Marcas discretas: puede haber múltiples sensores en el mismo día."""
    return sorted({(fecha, p.sensor) for p in productos for fecha in (p.antes, p.despues)})
