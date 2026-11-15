"""V.I.S.O.R. · evidencia multifuente cualitativa, independiente del motor SAR.

No descarga imágenes, no escribe en data/, no produce mapas de inundación.
Aísla fechas, alcance espacial y linaje de los productos observacionales.
"""
from __future__ import annotations

import unicodedata
from datetime import date


DAGRAN_05 = (
    "https://www.antioquia.gov.co/index.php/antioquiacuenta/"
    "gobernacion-de-antioquia-acompana-a-cuatro-municipios-de-uraba-afectados-"
    "por-las-lluvias-del-fin-de-semana"
)
DAGRAN_07 = (
    "https://www.antioquia.gov.co/index.php/antioquiacuenta/"
    "gobernacion-de-antioquia-entrega-ayuda-humanitaria-a-familias-afectadas-"
    "por-las-lluvias-en-uraba"
)
IDEAM_11 = (
    "https://ideam.gov.co/sites/default/files/prensa/boletines/"
    "2026-10-11/284_itd_octubre_11_2026.pdf"
)


def _normalizar(nombre: str) -> str:
    texto = unicodedata.normalize("NFKD", str(nombre))
    return "".join(x for x in texto if not unicodedata.combining(x)).casefold().strip()


def _superpone(desde: date, hasta: date, inicio: date, fin: date) -> bool:
    return inicio <= hasta and fin >= desde


def casos_documentados(municipios, inicio: date, fin: date) -> list[dict]:
    """Devuelve solo el caso documentado si la AOI toca Chigorodó y su ventana.

    La escala es MUNICIPAL; jamás indica que el AOI concreto se inundó.
    El 7-oct es seguimiento de la misma emergencia, NO otro evento.
    """
    if fin < inicio:
        raise ValueError("Fechas invertidas")
    toca = any(
        _normalizar(getattr(m, "nombre", m)) == "chigorodo"
        and _normalizar(getattr(m, "departamento", "antioquia")) == "antioquia"
        for m in municipios
    )
    if not toca or not _superpone(inicio, fin, date(2026, 10, 3), date(2026, 10, 7)):
        return []
    return [{
        "id": "CHIGORODO-2026-10-INUNDACIONES-DAGRAN",
        "resumen": (
            "DAGRAN/Gobernación de Antioquia documentó inundaciones en sectores "
            "de Chigorodó y desbordamiento de los ríos León y Guapá. "
            "Se registraron preliminarmente 397 familias afectadas."
        ),
        "alcance": (
            "Alcance municipal y sectores Barranquillita, La India, Guapá León y "
            "Unión Las Parcelas; NO hay polígono exacto ni confirmación para "
            "cada punto del área seleccionada."
        ),
        "ventana_documental": ["2026-10-03", "2026-10-07"],
        "fuentes": [
            {"organismo": "IDEAM · creciente reportada el 03-oct",
             "publicado": "11-oct-2026", "url": IDEAM_11},
            {"organismo": "DAGRAN · inundaciones reportadas",
             "publicado": "05-oct-2026", "url": DAGRAN_05},
            {"organismo": "DAGRAN · atención de la misma emergencia",
             "publicado": "07-oct-2026", "url": DAGRAN_07},
        ],
    }]


def evaluar_evidencias(registros: list[dict], inicio: date, fin: date) -> dict:
    """Evalúa evidencias normalizadas; sin puntajes probabilísticos.

    Cada registro necesita: tipo, observed_at (YYYY-MM-DD), valid=True,
    relacion_espacial ('aoi' o 'municipio') y origen (granule/evento fuente).
    Un producto GFM y otro DSWx del mismo Sentinel-1 deben compartir origen.
    Cambios de agua con lluvia/caudal SOLO producen 'posible inundación'.
    """
    if fin < inicio:
        raise ValueError("Fechas invertidas")
    aceptados, descartados, claves = [], 0, set()
    for r in registros:
        try:
            fecha = date.fromisoformat(str(r.get("observed_at", ""))[:10])
        except (TypeError, ValueError):
            descartados += 1
            continue
        if not (inicio <= fecha <= fin) or r.get("valid") is not True:
            descartados += 1
            continue
        if r.get("relacion_espacial") not in ("aoi", "municipio"):
            descartados += 1
            continue
        tipo = r.get("tipo")
        if tipo not in ("reporte_oficial", "agua_satelital", "cambio_agua", "lluvia", "hidrologia", "qa_sar"):
            descartados += 1
            continue
        origen = str(r.get("origen") or "").strip()
        if not origen:
            descartados += 1
            continue
        clave = (tipo if tipo in ("lluvia", "hidrologia", "reporte_oficial") else "satelite", origen)
        if clave in claves:
            continue
        claves.add(clave)
        aceptados.append(r)
    reportes = [x for x in aceptados if x["tipo"] == "reporte_oficial"]
    agua = [x for x in aceptados if x["tipo"] in ("agua_satelital", "cambio_agua")
            and x["relacion_espacial"] == "aoi"]
    cambio = [x for x in agua if x["tipo"] == "cambio_agua"]
    condiciones = [x for x in aceptados if x["tipo"] in ("lluvia", "hidrologia")]
    estados = []
    if reportes:
        estados.append("INUNDACION_DOCUMENTADA_POR_AUTORIDAD")
    if agua:
        estados.append("AGUA_OBSERVADA_POR_SATELITE")
    # La lluvia es apoyo contextual independiente, no una detección.
    if cambio and condiciones:
        estados.append("POSIBLE_INUNDACION")
    if condiciones:
        estados.append("CONDICIONES_METEOROLOGICAS_O_HIDROLOGICAS")
    if not estados:
        estados.append("INFORMACION_INSUFICIENTE")
    return {
        "estados": estados,
        "registros_utilizables": len(aceptados),
        "registros_descartados": descartados,
        "grupos_de_origen": len(claves),
        "limitaciones": (
            "Un reporte municipal no verifica píxeles de un AOI; "
            "el agua detectada no demuestra por sí sola inundación; "
            "sin cobertura SAR/óptica válida no se infiere ausencia de inundación."
        ),
    }
