"""Planificador conservador pre/post SAR: metadatos, nunca evidencia observacional."""
from datetime import date


def _fecha(valor):
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def planificar_stack(escenas, aoi, objetivo, dias_antes=30, dias_despues=30,
                    presupuesto_bytes=200_000_000):
    """Devuelve PLAN_METADATOS o SIN_DATOS/SIN_PAR/SIN_QA sin descargar.

    Cada escena exige sensor, banda, orbita, stack, polarizaciones, madurez,
    observed_at, bbox, granule, tamano_bytes y qa_apto (True/False/None).
    qa_apto=True solo si proviene de inspección QA externa real.
    """
    fecha = _fecha(objetivo)
    if dias_antes < 0 or dias_despues < 0 or presupuesto_bytes <= 0:
        raise ValueError("Ventana/presupuesto inválidos")
    oeste, sur, este, norte = map(float, aoi)
    if not (-180 <= oeste < este <= 180 and -90 <= sur < norte <= 90):
        raise ValueError("AOI inválida")
    filtradas = []
    qa_pendiente = False
    for e in escenas:
        try:
            f = _fecha(e["observed_at"])
            sensor = e["sensor"]
            if (sensor, e["banda"]) not in (("NISAR", "L"), ("Sentinel-1", "C")):
                continue
            x1, y1, x2, y2 = map(float, e["bbox"])
            if min(este, x2) <= max(oeste, x1) or min(norte, y2) <= max(sur, y1):
                continue
            if not (-dias_antes <= (f - fecha).days <= dias_despues):
                continue
            if not e.get("granule") or not e.get("stack") or e.get("orbita") is None:
                continue
            if not e.get("polarizaciones") or not e.get("madurez"):
                continue
            if type(e.get("tamano_bytes")) is not int or e["tamano_bytes"] <= 0:
                continue
            if e.get("qa_apto") is False:
                continue
            if e.get("qa_apto") is not True:
                qa_pendiente = True
            filtradas.append((f, e))
        except (KeyError, TypeError, ValueError):
            continue
    base = {"escenas": [], "transferencia_estimada_bytes": 0,
            "advertencia": "Sin observación verificada; no afirmar inundación."}
    if not filtradas:
        return {**base, "estado": "SIN_DATOS"}
    pares = []
    for f1, a in filtradas:
        if f1 > fecha:
            continue
        for f2, b in filtradas:
            if f2 <= fecha or f1 >= f2:
                continue
            if any(a[k] != b[k] for k in ("sensor", "banda", "orbita", "stack", "madurez")):
                continue
            if not set(a["polarizaciones"]).intersection(b["polarizaciones"]):
                continue
            if a["tamano_bytes"] + b["tamano_bytes"] > presupuesto_bytes:
                continue
            if min(a["bbox"][2], b["bbox"][2], este) <= max(a["bbox"][0], b["bbox"][0], oeste):
                continue
            if min(a["bbox"][3], b["bbox"][3], norte) <= max(a["bbox"][1], b["bbox"][1], sur):
                continue
            pares.append((0 if a["sensor"] == "NISAR" else 1,
                          (fecha - f1).days + (f2 - fecha).days, f1, f2, a, b))
    if not pares:
        return {**base, "estado": "SIN_PAR"}
    _, _, f1, f2, a, b = min(pares, key=lambda p: (p[0], p[1], p[2], p[3]))
    if a.get("qa_apto") is not True or b.get("qa_apto") is not True:
        return {**base, "estado": "SIN_QA", "granules_candidatos": [a["granule"], b["granule"]],
                "advertencia": "Par de catálogo sin QA de píxeles; no producir raster."}
    return {**base, "estado": "PLAN_METADATOS", "escenas": [a, b],
            "fechas": [f1.isoformat(), f2.isoformat()],
            "polarizaciones": sorted(set(a["polarizaciones"]) & set(b["polarizaciones"])),
            "transferencia_estimada_bytes": a["tamano_bytes"] + b["tamano_bytes"],
            "advertencia": "QA externa declarada; verificar raster, nodata y looks antes de producir mapa."}
