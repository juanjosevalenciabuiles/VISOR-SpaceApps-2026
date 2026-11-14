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


# ---------------------------------------------------------------------------
# Formato común (plan del panel derecho, 14-nov-2026)
# ---------------------------------------------------------------------------
# Cada proveedor devuelve elementos con: source, url, fetched_at, observed_at, published_at, valid_from,
# valid_to, geometry, spatial_relation, value, unit, status, limitations y title. Un campo que la fuente
# no declara queda en None: nunca se rellena con una suposición.

CAMPOS_COMUNES = ("source", "url", "fetched_at", "observed_at", "published_at", "valid_from", "valid_to",
                  "geometry", "spatial_relation", "value", "unit", "status", "limitations", "title")


def comun_eonet(item: dict, fetched_at: str) -> dict:
    """Añade el formato común a un evento ya normalizado por normalizar_eonet (sin quitar sus claves)."""
    return {**item, "fetched_at": fetched_at, "observed_at": item.get("event_start"),
            "published_at": None, "valid_from": None, "valid_to": None,
            "spatial_relation": "la geometría del evento toca la zona", "value": None, "unit": None,
            "status": "evento catalogado"}


# ---------------------------------------------------------------------------
# IDEAM · Alertas Hidrológicas (ArcGIS REST, capa 2)
# ---------------------------------------------------------------------------

IDEAM_CAPA = ("https://visualizador.ideam.gov.co/gisserver/rest/services/StoryMaps_IDA/"
              "Alertas_Hidrologicas/MapServer/2")
IDEAM_ATRIBUCION = "IDEAM — Alertas Hidrológicas (visualizador.ideam.gov.co)"
IDEAM_BOLETIN = ("https://www.ideam.gov.co/sala-de-prensa/boletines/"
                 "Bolet%C3%ADn-de-Alertas-Hidrol%C3%B3gicas-%28BAH%29")
# Candidatos por orden; se eligen entre los campos que la capa DECLARA (no se inventan).
CANDIDATOS_NIVEL = ("NIVEL_A", "NIVEL_ALERTA", "NIVEL", "ALERTA", "COLOR")
CANDIDATOS_NOMBRE = ("NOM_ZH", "NOMZH", "NOM_SZH", "NOMSZH", "ZONA_HIDRO", "SUBZONA", "NOMBRE", "NOM_AH",
                     "NOMAH", "NOM_RIO", "RIO", "NAME")
AGENTE_CONTEXTO = "VISOR-SpaceApps-2026/Contexto-Ambiental (+https://github.com/juanjosevalenciabuiles/VISOR-SpaceApps-2026)"


def _pedir_json(url: str, abrir=None, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE_CONTEXTO, "Accept": "application/json"})
    with (abrir or urllib.request.urlopen)(req, timeout=timeout) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8"))
    if isinstance(datos, dict) and "error" in datos:            # ArcGIS responde 200 con {"error": …}
        raise ErrorContexto(f"ArcGIS: {datos['error'].get('message', 'error')}")
    return datos


def _elegir(campos: list[dict], candidatos: tuple[str, ...]) -> str | None:
    nombres = {c["name"].upper(): c["name"] for c in campos if isinstance(c, dict) and c.get("name")}
    return next((nombres[c] for c in candidatos if c in nombres), None)


def _esri_a_shapely(geometria: dict):
    """Polígono Esri JSON (anillos) → geometría shapely, sin suponer orden de anillos."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    anillos = (geometria or {}).get("rings") or []
    partes = [Polygon(a).buffer(0) for a in anillos if len(a) >= 4]
    return unary_union(partes) if partes else None


def _fecha_esri(valor) -> str | None:
    if isinstance(valor, (int, float)) and valor > 0:      # milisegundos desde 1970 (UTC)
        return datetime.fromtimestamp(valor / 1000, tz=timezone.utc).isoformat(timespec="minutes")
    return None


def consultar_ideam(aoi_geojson: dict, abrir=None) -> dict:
    """Alertas hidrológicas VIGENTES del IDEAM que tocan la zona (relación geométrica real).

    1. Lee la definición de la capa (campos y tipos) para no suponer nombres.
    2. Pide los polígonos que cruzan el rectángulo de la zona (outSR=4326).
    3. Conserva solo los que intersecan la geometría real de la zona.
    Una consulta correcta sin polígonos es «SIN_COINCIDENCIAS»; un fallo de red o formato es «ERROR_FUENTE»."""
    poligono = shape(aoi_geojson)
    if not poligono.is_valid or poligono.is_empty:
        raise ValueError("AOI inválida")
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    base = {"fuente": IDEAM_ATRIBUCION, "retrieved_at": ahora, "items": [], "url_consulta": IDEAM_CAPA}
    try:
        meta = _pedir_json(IDEAM_CAPA + "?f=json", abrir)
        campos = meta.get("fields") or []
        nivel = _elegir(campos, CANDIDATOS_NIVEL)
        nombre = _elegir(campos, CANDIDATOS_NOMBRE) or meta.get("displayField")
        fechas = [c["name"] for c in campos if c.get("type") == "esriFieldTypeDate"]
        o, s, e, n = poligono.bounds
        q = urllib.parse.urlencode({
            "where": "1=1", "geometry": f"{o},{s},{e},{n}", "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
            "returnGeometry": "true", "outSR": "4326", "f": "json"})
        datos = _pedir_json(IDEAM_CAPA + "/query?" + q, abrir)
        if not isinstance(datos.get("features"), list):
            raise ErrorContexto("IDEAM devolvió un formato inesperado.")
        items = []
        for f in datos["features"]:
            atributos = f.get("attributes") or {}
            geom = _esri_a_shapely(f.get("geometry"))
            if geom is None or geom.is_empty or not geom.intersects(poligono):
                continue
            relacion = ("la zona está dentro del área de alerta" if geom.covers(poligono)
                        else "el área de alerta cruza la zona")
            valor = atributos.get(nivel) if nivel else None
            fechas_val = {c: _fecha_esri(atributos.get(c)) for c in fechas}
            items.append({
                "id": f"IDEAM:{atributos.get(meta.get('objectIdField') or 'OBJECTID', '')}",
                "source": IDEAM_ATRIBUCION, "source_type": "alerta_oficial",
                "title": str(atributos.get(nombre) or "Área de alerta hidrológica")[:200],
                "url": IDEAM_BOLETIN, "fetched_at": ahora, "observed_at": None,
                "published_at": next((v for v in fechas_val.values() if v), None),
                "valid_from": None, "valid_to": None,
                "geometry": None, "spatial_relation": relacion,
                "value": str(valor) if valor not in (None, "") else None, "unit": "nivel de alerta" if nivel else None,
                "status": "alerta vigente según el servicio", "campo_nivel": nivel, "campo_nombre": nombre,
                "fechas_declaradas": fechas_val,
                "limitations": ["Alerta por zona hidrográfica publicada por el IDEAM; no es una medición en la "
                                "zona ni confirma una inundación.",
                                "Vigencia: la que tenga el servicio al momento de la consulta."],
            })
        return {**base, "items": items, "estado": "CON_RESULTADOS" if items else "SIN_COINCIDENCIAS",
                "campos": {"nivel": nivel, "nombre": nombre, "fechas": fechas}}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ErrorContexto,
            KeyError, TypeError) as exc:
        return {**base, "estado": "ERROR_FUENTE", "error": type(exc).__name__}


# ---------------------------------------------------------------------------
# Consultas en segundo plano con caché por zona + período + fuente
# ---------------------------------------------------------------------------

import threading as _threading  # noqa: E402
import time as _time  # noqa: E402

TTL_S = {"eonet": 3600, "ideam": 900}
_consultas: dict[tuple[str, str], dict] = {}
_cerrojo_consultas = _threading.Lock()


def pedir(fuente: str, clave: str, funcion, sincrono: bool = False) -> dict:
    """Lanza (una sola vez por clave y TTL) la consulta en un hilo y devuelve su estado actual:
    {"estado": "CONSULTANDO" | "CON_RESULTADOS" | "SIN_COINCIDENCIAS" | "ERROR_FUENTE", ...}.
    Nunca bloquea la interfaz; nunca mezcla claves (zona/período) distintas."""
    k = (fuente, clave)
    with _cerrojo_consultas:
        actual = _consultas.get(k)
        vigente = actual and (actual["estado"] == "CONSULTANDO" or
                              _time.monotonic() - actual["_t"] < TTL_S.get(fuente, 900))
        if vigente:
            return actual
        _consultas[k] = {"estado": "CONSULTANDO", "_t": _time.monotonic()}

    def correr():
        try:
            resultado = funcion()
        except Exception as exc:  # noqa: BLE001 — una fuente caída nunca rompe la app
            resultado = {"estado": "ERROR_FUENTE", "items": [], "error": type(exc).__name__}
        with _cerrojo_consultas:
            _consultas[k] = {**resultado, "_t": _time.monotonic()}

    if sincrono:
        correr()
    else:
        _threading.Thread(target=correr, name=f"visor-contexto-{fuente}", daemon=True).start()
    with _cerrojo_consultas:
        return _consultas[k]


def estado(fuente: str, clave: str) -> dict | None:
    with _cerrojo_consultas:
        return _consultas.get((fuente, clave))


def olvidar() -> None:
    """Solo pruebas."""
    with _cerrojo_consultas:
        _consultas.clear()
