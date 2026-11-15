"""Planificación económica de pares SAR desde metadatos de catálogo.

No lee rasters ni afirma validez de píxeles; una huella de catálogo no es QA.
Los pares son del MISMO sensor y banda; nunca se combinan L y C.
"""
from __future__ import annotations

from datetime import date
from itertools import combinations


_BANDAS = {"NISAR": "L", "Sentinel-1": "C"}


def _caja(valores):
    if not isinstance(valores, (tuple, list)) or len(valores) != 4:
        raise ValueError("La caja debe contener oeste, sur, este, norte")
    try:
        o, s, e, n = (float(x) for x in valores)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coordenadas de caja inválidas") from exc
    if not (-180 <= o < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("Caja WGS84 inválida")
    return o, s, e, n


def _solapamiento(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )


def planificar_par(catalogo, aoi, inicio: date, fin: date, presupuesto_bytes: int):
    """Elegir par preliminar por huellas/fechas/tamaño, sin descargarse nada.

    Entrada: registros con granule, sensor, banda, observed_at, bbox y tamano_bytes.
    Salida: solo PLAN_METADATOS; se requiere verificar QA real antes de interpretar.
    NISAR tiene prioridad si dispone de par espacial/temporal compatible.
    """
    area = _caja(aoi)
    if not isinstance(inicio, date) or not isinstance(fin, date) or fin < inicio:
        raise ValueError("Intervalo de fechas inválido")
    if type(presupuesto_bytes) is not int or presupuesto_bytes <= 0:
        raise ValueError("Presupuesto inválido")
    candidatos, descartados, vistos = [], 0, set()
    for item in catalogo:
        try:
            if not isinstance(item, dict):
                raise ValueError("Registro inválido")
            granule = str(item["granule"]).strip()
            sensor = item["sensor"]
            if not granule or sensor not in _BANDAS or item["banda"] != _BANDAS[sensor]:
                raise ValueError("Sensor o banda incompatibles")
            fecha = date.fromisoformat(str(item["observed_at"])[:10])
            huella = _caja(item["bbox"])
            tam = item["tamano_bytes"]
            if type(tam) is not int or tam <= 0 or tam > presupuesto_bytes:
                raise ValueError("Tamaño desconocido o fuera de presupuesto")
            if not inicio <= fecha <= fin or _solapamiento(area, huella) == 0:
                raise ValueError("Sin coincidencia espacio-temporal")
            clave = (sensor, granule)
            if clave in vistos:
                raise ValueError("Granule duplicado")
            vistos.add(clave)
            candidatos.append({"granule": granule, "sensor": sensor, "banda": _BANDAS[sensor],
                               "observed_at": fecha.isoformat(), "bbox": huella,
                               "tamano_bytes": tam})
        except (KeyError, TypeError, ValueError):
            descartados += 1
    pares = []
    for a, b in combinations(candidatos, 2):
        if a["sensor"] != b["sensor"] or a["observed_at"] == b["observed_at"]:
            continue
        total = a["tamano_bytes"] + b["tamano_bytes"]
        if total > presupuesto_bytes or _solapamiento(a["bbox"], b["bbox"]) == 0:
            continue
        prioridad = 0 if a["sensor"] == "NISAR" else 1
        escenas = sorted((a, b), key=lambda x: (x["observed_at"], x["granule"]))
        pares.append((prioridad, total, escenas[0]["granule"], escenas[1]["granule"], escenas))
    sin_par = {"estado": "SIN_PAR_COMPATIBLE" if candidatos else "SIN_COBERTURA_DE_CATALOGO",
               "escenas": [], "sensor": None, "banda": None, "transferencia_estimada_bytes": 0,
               "descartados": descartados,
               "advertencia": "Catálogo sin par válido; no hay observación ni conclusión de inundación."}
    if not pares:
        return sin_par
    _, total, _, _, escenas = min(pares, key=lambda p: p[:4])
    return {"estado": "PLAN_METADATOS", "sensor": escenas[0]["sensor"],
            "banda": escenas[0]["banda"], "escenas": escenas,
            "transferencia_estimada_bytes": total, "descartados": descartados,
            "advertencia": "Huellas CMR aproximadas, NO QA; validar píxeles y fechas antes de analizar."}
