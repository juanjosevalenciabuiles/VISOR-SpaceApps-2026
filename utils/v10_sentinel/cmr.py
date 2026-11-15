"""Consulta acotada de metadatos CMR; nunca descarga productos ni certifica QA."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from urllib.parse import urlencode, urlsplit, parse_qsl, urlunsplit
from urllib.request import Request, urlopen

CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
SHORT_NAME = "OPERA_L3_DSWX-S1_V1"


def parametros_cmr(aoi_bbox: tuple[float, float, float, float], inicio: str, fin: str) -> str:
    """URL CMR de metadatos; la búsqueda no implica cobertura completa del AOI."""
    from utils.v10_sentinel.validacion import bbox_valida

    bbox = bbox_valida(aoi_bbox)
    desde = datetime.fromisoformat(inicio.replace("Z", "+00:00"))
    hasta = datetime.fromisoformat(fin.replace("Z", "+00:00"))
    if desde.tzinfo is None or hasta.tzinfo is None or hasta < desde:
        raise ValueError("Fechas UTC con zona horaria y orden válido requeridas")
    args = {
        "short_name": SHORT_NAME,
        "bounding_box": ",".join(str(v) for v in bbox),
        "temporal": f"{desde.astimezone(timezone.utc).isoformat()},{hasta.astimezone(timezone.utc).isoformat()}",
        "page_size": "100",
        "sort_key": "-start_date",
    }
    return CMR_URL + "?" + urlencode(args)


def extraer_granulos(payload: dict, *, pagina_final: bool = True) -> list[dict]:
    """Extrae linaje y enlaces candidatos, sin inventar WTR/CONF ni QA."""
    entries = payload.get("feed", {}).get("entry", [])
    if not isinstance(entries, list):
        raise ValueError("Respuesta CMR inválida")
    # CMR page_size=100: una página llena no demuestra que el catálogo esté completo.
    # Nunca seleccionar pre/post sobre un conjunto potencialmente truncado.
    if pagina_final and len(entries) >= 100:
        raise ValueError("CMR_PAGINACION_PENDIENTE: página completa de 100 granulos")
    salida = []
    for item in entries:
        if not isinstance(item, dict) or not item.get("id") or not item.get("time_start"):
            raise ValueError("CMR granulo incompleto: catalogo no verificable")
        enlaces = []
        for link in item.get("links", []):
            if not isinstance(link, dict):
                continue
            href = link.get("href")
            if isinstance(href, str) and href.startswith("https://") and not link.get("inherited"):
                enlaces.append(href)
        salida.append({
            "granule_id": item["id"],
            "observed_at": item["time_start"],
            "collection": SHORT_NAME,
            "links_candidatos": enlaces,
            "qa_metadata": "NO_VERIFICADO",
            "estado": "PENDIENTE_ASSETS_QA",
        })
    return salida


def consultar_cmr(aoi_bbox: tuple[float, float, float, float], inicio: str, fin: str,
                  *, timeout: float = 12.0) -> dict:
    """Solo tras acción explícita del usuario. Fallo de red => SIN_DATOS, nunca mapa."""
    url = parametros_cmr(aoi_bbox, inicio, fin)
    try:
        # Paginación CMR acotada: no se permite publicar un catálogo truncado.
        partes = urlsplit(url)
        base = dict(parse_qsl(partes.query))
        acumulados = []
        ids = set()
        for pagina in range(1, 11):
            args = {**base, "page_num": str(pagina)}
            pagina_url = urlunsplit((partes.scheme, partes.netloc, partes.path,
                                     urlencode(args), ""))
            request = Request(pagina_url, headers={
                "Accept": "application/json", "User-Agent": "VISOR-metadata/1"})
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise OSError("CMR HTTP no exitoso")
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("Respuesta CMR excede presupuesto")
            payload = json.loads(raw)
            entries = payload.get("feed", {}).get("entry")
            if not isinstance(entries, list) or len(entries) > 100:
                raise ValueError("CMR página inválida")
            for item in extraer_granulos(payload, pagina_final=False):
                if item["granule_id"] in ids:
                    raise ValueError("CMR paginación repetida")
                ids.add(item["granule_id"])
                acumulados.append(item)
            if len(entries) < 100:
                break
        else:
            raise ValueError("CMR límite de 1000 registros alcanzado")
        items = acumulados
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"estado": "SIN_DATOS", "granulos": [], "motivo": "CMR_NO_VERIFICABLE"}
    return {"estado": "METADATOS_SIN_QA" if items else "SIN_DATOS",
            "granulos": items, "motivo": "ASSETS_Y_QA_PENDIENTES" if items else "SIN_ESCENAS"}
