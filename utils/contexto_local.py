"""Contexto LOCAL de una zona: lo que se sabe sin consultar ningún servicio externo.

- Ubicación administrativa: municipios y departamentos del MGN 2025 del DANE que cubre la zona
  (nivel `departamental` de la fuente; se nombran solo los que ocupan al menos el 1 % de la zona).
- Superficie en km², calculada en MAGNA-SIRGAS / Origen Nacional (EPSG:9377), el sistema oficial de
  Colombia para áreas.
- Ríos, lagos y vías de la cartografía de referencia ya incluida (Natural Earth 1:10m): solo ríos y
  vías principales. Que no aparezca un río NO significa que no exista; la cercanía no es un riesgo.

Nada aquí consulta la red ni toca data/sar, data/analisis o los trabajos.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from functools import lru_cache

from shapely import STRtree
from shapely.geometry import box, mapping, shape

from utils import alcance_geografico, capas_contexto

ARCHIVO_MUNICIPIOS = "municipios_mgn2025_departamental.geojson.gz"
FRACCION_MINIMA = 0.01
ATRIBUCION_MUNICIPIOS = "Municipios: MGN 2025, DANE · ytolosa/mapas-colombia, CC BY 4.0"
ATRIBUCION_CARTOGRAFIA = "Ríos, lagos y vías: Natural Earth 1:10m (dominio público), solo elementos principales"


@dataclass
class Municipio:
    nombre: str
    departamento: str
    divipola: str
    fraccion: float          # parte de la zona que cae en este municipio (0–1)


@dataclass
class ContextoLocal:
    municipios: list[Municipio] = field(default_factory=list)
    area_km2: float | None = None
    rios: list[str] = field(default_factory=list)
    lagos: list[str] = field(default_factory=list)
    rios_sin_nombre: int = 0
    vias: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def lugar(self) -> str | None:
        """«Chigorodó, Antioquia» o «Chigorodó y Carepa, Antioquia» o None si no se pudo comprobar."""
        if not self.municipios:
            return None
        principales = self.municipios[:3]
        deptos = list(dict.fromkeys(m.departamento for m in principales))
        nombres = [m.nombre for m in principales]
        texto = nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]
        resto = len(self.municipios) - len(principales)
        return f"{texto}{f' (y {resto} más)' if resto > 0 else ''}, {' / '.join(deptos)}"


def _titulo(texto: str) -> str:
    """«CHIGORODÓ» → «Chigorodó» respetando conectores («San Juan de Urabá»)."""
    menores = {"de", "del", "la", "las", "el", "los", "y"}
    palabras = str(texto).lower().split()
    siglas = {"d.c.": "D.C.", "d.c": "D.C."}
    return " ".join(siglas.get(p) or (p if (i and p in menores) else p[:1].upper() + p[1:])
                    for i, p in enumerate(palabras))


@lru_cache(maxsize=1)
def _municipios():
    ruta = alcance_geografico.CARPETA / ARCHIVO_MUNICIPIOS
    datos = json.loads(gzip.decompress(ruta.read_bytes()))
    geoms, props = [], []
    for f in datos["features"]:
        g = shape(f["geometry"]).buffer(0)
        if not g.is_empty:
            geoms.append(g)
            props.append(f["properties"])
    return STRtree(geoms), geoms, props


def municipios(geometria) -> list[Municipio]:
    arbol, geoms, props = _municipios()
    total = geometria.area
    if total <= 0:
        return []
    salida = []
    for i in arbol.query(geometria, predicate="intersects"):
        fraccion = geoms[i].intersection(geometria).area / total
        if fraccion >= FRACCION_MINIMA:
            p = props[i]
            salida.append(Municipio(_titulo(p["mpio_nombre"]), _titulo(p["dpto_nombre"]), p["divipola_mun"],
                                    round(fraccion, 4)))
    return sorted(salida, key=lambda m: -m.fraccion)


def area_km2(geometria) -> float:
    from rasterio.warp import transform_geom
    plana = shape(transform_geom("EPSG:4326", "EPSG:9377", mapping(geometria)))
    return plana.area / 1e6


def _nombres(datos) -> tuple[list[str], int]:
    if not datos or not datos.geojson:
        return [], 0
    nombres, sin_nombre = [], 0
    for f in json.loads(datos.geojson).get("features", []):
        nombre = (f.get("properties") or {}).get("name")
        if nombre:
            nombres.append(str(nombre))
        else:
            sin_nombre += 1
    return sorted(dict.fromkeys(nombres)), sin_nombre


def contexto(geometria_geojson: dict) -> ContextoLocal:
    """Contexto local de la zona (geometría real: polígono dibujado o rectángulo)."""
    geometria = shape(geometria_geojson)
    salida = ContextoLocal()
    try:
        salida.municipios = municipios(geometria)
    except (OSError, ValueError, KeyError) as e:
        salida.avisos.append(f"No se pudo comprobar el municipio ({type(e).__name__}).")
    try:
        salida.area_km2 = round(area_km2(geometria), 1)
    except Exception as e:  # noqa: BLE001 — un fallo de PROJ no debe vaciar el panel
        salida.avisos.append(f"No se pudo calcular la superficie ({type(e).__name__}).")
    limites = geometria.bounds
    hidro = capas_contexto.recortar("hidrografia", limites, None)
    if hidro is not None and hidro.geojson:
        todos = json.loads(hidro.geojson).get("features", [])
        for f in todos:
            nombre = (f.get("properties") or {}).get("name")
            if not shape(f["geometry"]).intersects(geometria):
                continue
            destino = salida.lagos if (f.get("properties") or {}).get("featurecla", "").lower().startswith("lake") \
                else salida.rios
            if nombre:
                destino.append(str(nombre))
            else:
                salida.rios_sin_nombre += 1
        salida.rios = sorted(dict.fromkeys(salida.rios))
        salida.lagos = sorted(dict.fromkeys(salida.lagos))
    vias = capas_contexto.recortar("vias", limites, None)
    if vias is not None and vias.geojson:
        salida.vias = sum(1 for f in json.loads(vias.geojson).get("features", [])
                          if shape(f["geometry"]).intersects(geometria))
    return salida


def geometria_de_zona(zona: dict) -> dict:
    """La geometría real de la zona confirmada (polígono dibujado si existe; si no, su rectángulo)."""
    return zona.get("geometria") or mapping(box(*zona["limites"]))
