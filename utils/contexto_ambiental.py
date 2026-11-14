"""Contexto ambiental independiente del motor SAR.

Primera fuente: NASA EONET v3, API pública oficial.
Un evento EONET no constituye una validación temática de cambios SAR.
NUNCA escribe en data/sar, data/analisis o en la cola de trabajos.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from shapely.geometry import shape

ENDPOINT = "https://eonet.gsfc.nasa.gov/api/v3/events"
ATRIBUCION = "NASA EONET v3 — Earth Observatory Natural Event Tracker"


class ErrorContexto(RuntimeError):
    pass


def ventana(inicio: date, fin: date, margen_dias: int = 15):
    if fin < inicio or margen_dias < 0 or margen_dias > 60:
        raise ValueError("Intervalo ambiental inválido.")
    return inicio - timedelta(days=margen_dias), fin + timedelta(days=margen_dias)


def url_eonet(limites, inicio: date, fin: date) -> str:
    """EONET bbox = oeste,norte,este,sur (NO oeste,sur,este,norte)."""
    o, s, e, n = (float(x) for x in limites)
    params = {"status": "all", "start": inicio.isoformat(), "end": fin.isoformat(),
              "bbox": ",".join(f"{x:.5f}" for x in (o, n, e, s)), "limit": "250"}
    return ENDPOINT + "?" + urllib.parse.urlencode(params)


def _fecha_geometria(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def normalizar_eonet(respuesta: dict, aoi_geojson: dict, inicio: date, fin: date) -> list[dict]:
    """No inventa posiciones: solo permite 'intersects_aoi' con geometría verificable."""
    if not isinstance(respuesta, dict) or not isinstance(respuesta.get("events"), list):
        raise ErrorContexto("EONET devolvió un formato inesperado.")
    poligono = shape(aoi_geojson)
    if poligono.is_empty or not poligono.is_valid:
        raise ValueError("AOI inválida.")
    out = []
    for evento in respuesta["events"]:
        if not isinstance(evento, dict):
            continue
        coincidencias = []
        for g in evento.get("geometry") or []:
            try:
                geom = shape({"type": g["type"], "coordinates": g["coordinates"]})
                fecha = _fecha_geometria(g.get("date"))
                if fecha is not None and not (inicio <= fecha <= fin):
                    continue
                if not geom.is_empty and geom.is_valid and poligono.intersects(geom):
                    coincidencias.append((g, fecha))
            except (ValueError, TypeError, KeyError):
                continue
        if not coincidencias:
            continue
        geom, fecha = coincidencias[-1]
        fuentes = [s.get("url") for s in evento.get("sources") or [] if isinstance(s, dict) and
                   str(s.get("url") or "").startswith("https://")]
        enlace = fuentes[0] if fuentes else evento.get("link")
        categorias = [x.get("title") for x in evento.get("categories") or [] if isinstance(x, dict)]
        out.append({
            "id": "EONET:" + str(evento.get("id") or ""),
            "source": ATRIBUCION,
            "source_type": "evento_catalogado",
            "title": str(evento.get("title") or "Evento sin título")[:320],
            "url": enlace if str(enlace).startswith("https://") else None,
            "event_start": fecha.isoformat() if fecha else None,
            "published_at": None,
            "geo_relation": "intersects_aoi",
            "location_name": None,
            "geometry": {"type": geom.get("type"), "coordinates": geom.get("coordinates")},
            "phenomenon": ", ".join(c for c in categorias if c) or "Categoría no indicada",
            "limitations": ["Evento catalogado; no verifica por sí solo ningún cambio SAR."]
        })
    return out


def consultar_eonet(aoi_geojson: dict, inicio: date, fin: date, abrir=None) -> dict:
    """Consulta limitada y explícita (invocar solo tras pulsar 'Consultar contexto').

    Las caídas de red se reflejan en el resultado; el usuario puede seguir usando SAR.
    """
    poligono = shape(aoi_geojson)
    if not poligono.is_valid or poligono.is_empty:
        raise ValueError("AOI inválida")
    o, s, e, n = poligono.bounds
    url = url_eonet((o, s, e, n), inicio, fin)
    req = urllib.request.Request(url, headers={"User-Agent": "VISOR-SpaceApps-2026/Contexto-Ambiental",
                                              "Accept": "application/json"})
    try:
        with (abrir or urllib.request.urlopen)(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = normalizar_eonet(payload, aoi_geojson, inicio, fin)
        return {"items": items, "fuentes_consultadas": [ATRIBUCION],
                "fuentes_con_error": [], "ventana_temporal": [inicio.isoformat(), fin.isoformat()],
                "retrieved_at": datetime.now(timezone.utc).isoformat(), "estado": "CON_RESULTADOS" if items else "SIN_COINCIDENCIAS"}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ErrorContexto) as exc:
        return {"items": [], "fuentes_consultadas": [], "fuentes_con_error": [ATRIBUCION],
                "ventana_temporal": [inicio.isoformat(), fin.isoformat()],
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "estado": "ERROR_FUENTE", "error": type(exc).__name__}
