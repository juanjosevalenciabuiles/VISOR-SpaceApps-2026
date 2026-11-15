"""GeoJSON de contexto territorial para el mapa, sin datos inventados.

Los polígonos IDEAM se recortan al área confirmada. El recorte NO significa
que toda la AOI esté inundada: es la intersección con una *zona de alerta*.
Las proporciones municipales reutilizan el cálculo DANE del panel derecho.
"""
from __future__ import annotations

from html import escape

from shapely.geometry import mapping, shape

from utils import contexto_local

MAX_ELEMENTOS = 15
# Paleta consistente con el panel de municipios, independiente de color de alerta.
COLORES_MUNICIPIOS = ("#47B5FF", "#A78BFA", "#35D0AC", "#FBBF67", "#F472B6",
                      "#38BDF8", "#84CC16", "#FCA5A5")
COLORES_ALERTA = {1: "#FACC15", 2: "#FB923C", 3: "#EF4444"}


def _coleccion(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def _recorte_poligonal(geometria, aoi):
    """No dibujar contactos lineales ni ampliar la alerta fuera de la AOI."""
    try:
        poligono = shape(geometria)
        clipped = poligono.intersection(aoi)
        if clipped.is_empty or clipped.area <= 0:
            return None
        # Simplificación solo visual en ~25-55 m; la fuente no se modifica.
        recorte = clipped.simplify(0.00035, preserve_topology=True).intersection(aoi)
        return mapping(recorte) if not recorte.is_empty and recorte.area > 0 else None
    except (ValueError, TypeError, AttributeError):
        return None


def municipios_del_area(aoi_geojson: dict, local: contexto_local.ContextoLocal,
                        max_elementos: int = MAX_ELEMENTOS) -> dict:
    """Distribución geográfica DANE: fracciones ya calculadas del área seleccionada.

    Lee el índice MGN local (caché) y devuelve solo partes que intersectan la AOI;
    no usa centroides municipales ni dibujos aproximados.
    """
    if max_elementos <= 0:
        return _coleccion([])
    aoi = shape(aoi_geojson)
    if aoi.is_empty or not aoi.is_valid:
        return _coleccion([])
    mostrar = {m.divipola: m for m in local.municipios[:max_elementos]}
    if not mostrar:
        return _coleccion([])
    arbol, geoms, props = contexto_local._municipios()
    elementos = []
    for i in arbol.query(aoi, predicate="intersects"):
        p = props[i]
        municipio = mostrar.get(str(p.get("divipola_mun") or ""))
        if municipio is None:
            continue
        geo = _recorte_poligonal(mapping(geoms[i]), aoi)
        if geo is None:
            continue
        posicion = next((j for j, m in enumerate(local.municipios) if m.divipola == municipio.divipola), 0)
        elementos.append({
            "type": "Feature", "geometry": geo,
            "properties": {
                "nombre": escape(municipio.nombre),
                "departamento": escape(municipio.departamento),
                "porcentaje": f"{municipio.fraccion * 100:.1f} %",
                "fraccion": municipio.fraccion,
                "color": COLORES_MUNICIPIOS[posicion % len(COLORES_MUNICIPIOS)],
                "fuente": "DANE · MGN 2025 · intersección con el área seleccionada",
                "divipola": municipio.divipola,
            },
        })
    elementos.sort(key=lambda feature: -feature["properties"]["fraccion"])
    return _coleccion(elementos[:max_elementos])


def alertas_ideam_del_area(aoi_geojson: dict, consulta: dict,
                          max_elementos: int = MAX_ELEMENTOS) -> dict:
    """Únicamente polígonos que la API devolvió con geometría auténtica.

    JAMÁS inventa un marcador en el centro de la AOI si el servicio no trae
    geometría. Recortar a la AOI es visual, no una medición local de inundación.
    """
    if consulta.get("estado") != "CON_RESULTADOS":
        return _coleccion([])
    aoi = shape(aoi_geojson)
    if aoi.is_empty or not aoi.is_valid:
        return _coleccion([])
    features = []
    for item in consulta.get("items") or []:
        if len(features) >= max_elementos:
            break
        nivel = item.get("gravedad")
        if nivel not in COLORES_ALERTA or not item.get("geometry"):
            continue
        geo = _recorte_poligonal(item["geometry"], aoi)
        if geo is None:
            continue
        features.append({
            "type": "Feature", "geometry": geo,
            "properties": {
                "nombre": escape(str(item.get("title") or "Subzona hidrológica")),
                "nivel": {1: "Amarilla", 2: "Naranja", 3: "Roja"}[nivel],
                "gravedad": nivel,
                "color": COLORES_ALERTA[nivel],
                "zona": escape(str(item.get("zona_hidrografica") or "No indicada")),
                "fuente": "IDEAM · alerta hidrológica consultada hoy",
                "limitacion": "Zona hidrográfica de alerta; no es mapa de inundación.",
                "consulta": str(consulta.get("retrieved_at") or "Fecha de consulta no disponible"),
            },
        })
    return _coleccion(features)


def eventos_eonet_del_area(aoi_geojson: dict, consulta: dict,
                           max_elementos: int = MAX_ELEMENTOS) -> dict:
    """Geometrías NASA EONET reportadas: posiciones, NO huellas del impacto."""
    if consulta.get("estado") != "CON_RESULTADOS":
        return _coleccion([])
    aoi = shape(aoi_geojson)
    if aoi.is_empty or not aoi.is_valid:
        return _coleccion([])
    features = []
    for item in consulta.get("items") or []:
        if len(features) >= max_elementos:
            break
        raw = item.get("geometry")
        if not raw:
            continue
        try:
            geom = shape(raw)
            if geom.is_empty or not geom.is_valid or not geom.intersects(aoi):
                continue
            # EONET ofrece puntos y eventualmente polígonos de evento.
            geometry = mapping(geom if geom.geom_type in ("Point", "MultiPoint")
                               else geom.intersection(aoi))
        except (ValueError, TypeError, AttributeError):
            continue
        features.append({
            "type": "Feature", "geometry": geometry,
            "properties": {
                "nombre": escape(str(item.get("title") or "Evento catalogado")),
                "tipo": escape(str(item.get("phenomenon") or "Sin categoría")),
                "fecha": escape(str(item.get("event_start") or "Fecha no indicada")),
                "fuente": "NASA EONET · posición del catálogo, no extensión real del impacto",
            },
        })
    return _coleccion(features)
