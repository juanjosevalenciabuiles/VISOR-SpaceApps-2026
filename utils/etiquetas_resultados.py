"""Etiquetas legibles del historial SAR a partir de metadatos declarados.

No se infieren municipios sin una fuente. Cuando no existe topónimo
documentado, se usan las coordenadas del centro del GeoTIFF (AOI).
"""
from __future__ import annotations

from datetime import date
import re


def _texto_seguro(valor: str) -> str:
    """Texto breve de metadatos no fiables sin marcado HTML ni control."""
    sin_html = re.sub(r"<[^>]*>", "", valor)
    return " ".join(sin_html.replace("<", "").replace(">", "").split())[:65]


def _zona(res) -> str:
    ficha = getattr(res, "ficha", None) or {}
    procedencia = ficha.get("procedencia") if isinstance(ficha, dict) else {}
    procedencia = procedencia if isinstance(procedencia, dict) else {}
    for candidato in (ficha.get("zona") if isinstance(ficha, dict) else None,
                      ficha.get("municipio") if isinstance(ficha, dict) else None,
                      procedencia.get("zona"), procedencia.get("municipio"),
                      ficha.get("aoi") if isinstance(ficha, dict) else None):
        if isinstance(candidato, str) and candidato.strip():
            return _texto_seguro(candidato) or "AOI"
        if isinstance(candidato, dict):
            nombre = candidato.get("municipio") or candidato.get("nombre") or candidato.get("etiqueta")
            if isinstance(nombre, str) and nombre.strip():
                return _texto_seguro(nombre) or "AOI"
    capa = getattr(res, "capa", None)
    limites = getattr(capa, "limites", None)
    if limites is not None and len(limites) == 4:
        try:
            oeste, sur, este, norte = map(float, limites)
            lat, lon = (sur + norte) / 2, (oeste + este) / 2
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return f"AOI {abs(lat):.3f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.3f}°{'E' if lon >= 0 else 'W'}"
        except (TypeError, ValueError):
            pass
    return "AOI"


def _fechas(res) -> str:
    ficha = getattr(res, "ficha", None) or {}
    procedencia = ficha.get("procedencia") if isinstance(ficha, dict) else {}
    procedencia = procedencia if isinstance(procedencia, dict) else {}
    fechas = procedencia.get("fechas") or ficha.get("fechas")
    if isinstance(fechas, (tuple, list)) and len(fechas) >= 2:
        # Las fechas proceden de JSON/GeoTIFF no fiables. Solo aceptamos
        # ISO YYYY-MM-DD reales y evitamos inyección de marcado por historial.
        try:
            primero, segundo = str(fechas[0])[:10], str(fechas[1])[:10]
            if (date.fromisoformat(primero).isoformat() == primero and
                    date.fromisoformat(segundo).isoformat() == segundo):
                return f"{primero} → {segundo}"
        except (TypeError, ValueError):
            pass
    return "date unknown"


def nombre_resultado(res, idioma_codigo: str = "en") -> str:
    """Zona · par de fechas · producto; no confundir fecha de generación y adquisición."""
    producto = getattr(getattr(res, "perfil", None), "clave", None)
    tipos = {
        "diferencia_db": ("ΔdB", "ΔdB"),
        "coincidencia_vv_vh": ("VV/VH", "VV/VH"),
        "mascara_cambios": ("Máscara SAR", "SAR mask"),
    }
    es, en = tipos.get(producto, (getattr(res, "nombre", "SAR"), getattr(res, "nombre", "SAR")))
    fecha = _fechas(res)
    if fecha == "date unknown":
        fecha = "fecha no disponible" if idioma_codigo == "es" else "date unknown"
    return f"{_zona(res)} · {fecha} · {es if idioma_codigo == 'es' else en}"
