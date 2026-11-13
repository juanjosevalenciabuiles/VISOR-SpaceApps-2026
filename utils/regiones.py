"""Áreas de interés (AOI) regionales: municipios oficiales, uniones y GeoJSON.

V.I.S.O.R. deja de estar atado a Chigorodó: el análisis puede hacerse sobre un
municipio, la unión de varios (piloto: Chigorodó, Carepa, Apartadó y Turbo),
toda la subregión de Urabá o cualquier polígono GeoJSON.

Límites oficiales: la app NO trae polígonos administrativos inventados. Lee el
GeoJSON del Marco Geoestadístico Nacional (DANE) o de IGAC que el equipo copie
en `data/limites/` (fuera de Git) y guarda su SHA-256 en cada AOI. Sin ese
archivo, solo se puede usar un recuadro o un GeoJSON propio.

Códigos DIVIPOLA de Urabá: Anuario Estadístico de Antioquia (Gobernación de
Antioquia), subregión R09.

Un AOI es solo un área de trabajo: no implica que haya escenas Sentinel-1 o
NISAR que la cubran. La cobertura se mide aparte (`utils/cobertura.py`).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from utils.config import DATA_DIR

CARPETA_LIMITES = DATA_DIR / "limites"
CARPETA_AOI = DATA_DIR / "aoi"
MAX_BYTES_GEOJSON = 50 * 1024 * 1024
MAX_VERTICES = 2_000_000
TOLERANCIA_SOLAPE = 1e-4          # fracción del área de la zona menor

# Subregión Urabá (R09), DIVIPOLA. Fuente: Anuario Estadístico de Antioquia.
URABA: dict[str, str] = {
    "05045": "Apartadó", "05051": "Arboletes", "05147": "Carepa", "05172": "Chigorodó",
    "05475": "Murindó", "05480": "Mutatá", "05490": "Necoclí", "05659": "San Juan de Urabá",
    "05665": "San Pedro de Urabá", "05837": "Turbo", "05873": "Vigía del Fuerte",
}
PILOTO = ("05172", "05147", "05045", "05837")        # Chigorodó, Carepa, Apartadó, Turbo
GRUPOS = {
    "Piloto: Chigorodó, Carepa, Apartadó y Turbo": PILOTO,
    "Urabá antioqueño (11 municipios)": tuple(URABA),
}
# Campos de código y nombre en los GeoJSON oficiales más comunes (DANE MGN, IGAC) y genéricos.
CAMPOS_CODIGO = ("MPIO_CDPMP", "MPIO_CCNCT", "COD_MPIO", "CODIGO_DANE", "COD_DANE", "MpCodigo", "codigo", "code")
CAMPOS_NOMBRE = ("MPIO_CNMBR", "MPIO_NOMBRE", "NOM_MPIO", "MpNombre", "nombre", "name", "NOMBRE")


class ErrorAOI(Exception):
    """Problema con un área de interés, explicado para el usuario."""


@dataclass(frozen=True)
class Zona:
    codigo: str
    nombre: str
    geometria: BaseGeometry        # WGS84 (lon, lat)


@dataclass
class AOI:
    nombre: str
    geometria: BaseGeometry        # WGS84; unión de las zonas
    zonas: tuple[Zona, ...]
    origen: str                    # "limites_oficiales" | "geojson" | "recuadro"
    fuente: str
    sha256_fuente: str | None
    avisos: list[str] = field(default_factory=list)

    @property
    def limites(self) -> tuple[float, float, float, float]:
        return tuple(round(v, 6) for v in self.geometria.bounds)

    @property
    def area_km2(self) -> float:
        return area_geodesica_km2(self.geometria)

    @property
    def codigos(self) -> tuple[str, ...]:
        return tuple(z.codigo for z in self.zonas)

    def resumen(self) -> dict:
        return {
            "nombre": self.nombre, "origen": self.origen, "fuente": self.fuente, "sha256_fuente": self.sha256_fuente,
            "zonas": [{"codigo": z.codigo, "nombre": z.nombre, "area_km2": round(area_geodesica_km2(z.geometria), 3)}
                      for z in self.zonas],
            "area_km2": round(self.area_km2, 3), "limites_lonlat": list(self.limites), "avisos": self.avisos,
        }

    def a_geojson(self) -> dict:
        """FeatureCollection RFC 7946: una Feature por zona y la descripción del AOI."""
        return {
            "type": "FeatureCollection", "name": self.nombre,
            "visor_aoi": {k: v for k, v in self.resumen().items() if k != "zonas"},
            "features": [{"type": "Feature", "properties": {"codigo": z.codigo, "nombre": z.nombre},
                          "geometry": mapping(z.geometria)} for z in self.zonas],
        }

    def guardar(self, carpeta: Path | None = None) -> Path:
        """Escribe `aoi_<nombre>.geojson` sin sobrescribir (usa _r2, _r3…)."""
        from utils.analisis_sar import prefijo_libre
        carpeta = Path(carpeta) if carpeta is not None else CARPETA_AOI
        carpeta.mkdir(parents=True, exist_ok=True)
        base = prefijo_libre(carpeta, f"aoi_{nombre_archivo(self.nombre)}")
        ruta = carpeta / f"{base}.geojson"
        with ruta.open("x", encoding="utf-8") as f:
            json.dump(self.a_geojson(), f, ensure_ascii=False)
        return ruta


def nombre_archivo(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return (re.sub(r"[^A-Za-z0-9]+", "_", sin_tildes).strip("_") or "aoi")[:60]


def area_geodesica_km2(geometria: BaseGeometry) -> float:
    """Área sobre el elipsoide WGS84 (no depende de una proyección)."""
    from pyproj import Geod
    return abs(Geod(ellps="WGS84").geometry_area_perimeter(geometria)[0]) / 1e6


def _sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def _poligonal(geo: BaseGeometry, quien: str) -> BaseGeometry:
    if geo.is_empty:
        raise ErrorAOI(f"{quien}: geometría vacía.")
    if not geo.is_valid:
        geo = make_valid(geo)
    poligonos = [g for g in getattr(geo, "geoms", [geo]) if g.geom_type in ("Polygon", "MultiPolygon")]
    geo = unary_union(poligonos) if poligonos else None
    if geo is None or geo.is_empty or geo.area == 0:
        raise ErrorAOI(f"{quien}: no contiene un polígono con área.")
    o, s, e, n = geo.bounds
    if not (-180 <= o <= e <= 180 and -90 <= s <= n <= 90):
        raise ErrorAOI(f"{quien}: coordenadas fuera de longitud/latitud. GeoJSON debe estar en WGS84 (EPSG:4326).")
    return geo


def _vertices(geo: BaseGeometry) -> int:
    partes = getattr(geo, "geoms", [geo])
    return sum(len(p.exterior.coords) + sum(len(i.coords) for i in p.interiors) for p in partes)


def leer_geojson(datos: bytes | str | Path, nombre: str = "GeoJSON") -> tuple[list[tuple[dict, BaseGeometry]], str]:
    """(propiedades, geometría WGS84) de cada polígono y el SHA-256 del contenido.

    Solo Polygon/MultiPolygon en WGS84 (RFC 7946). Rechaza otros CRS declarados,
    archivos enormes y geometrías sin área; repara geometrías inválidas."""
    es_ruta = isinstance(datos, Path)        # una cadena es contenido GeoJSON; una ruta, Path
    if es_ruta:
        ruta = Path(datos)
        if not ruta.is_file():
            raise ErrorAOI(f"No se encontró `{ruta.name}`.")
        if ruta.stat().st_size > MAX_BYTES_GEOJSON:
            raise ErrorAOI(f"{ruta.name} supera {MAX_BYTES_GEOJSON // 2**20} MB; simplifícalo o recórtalo.")
        nombre, datos = ruta.name, ruta.read_bytes()
    if isinstance(datos, str):
        datos = datos.encode("utf-8")
    if len(datos) > MAX_BYTES_GEOJSON:
        raise ErrorAOI(f"{nombre} supera {MAX_BYTES_GEOJSON // 2**20} MB.")
    try:
        crudo = json.loads(datos.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ErrorAOI(f"{nombre} no es un JSON válido.") from e
    if not isinstance(crudo, dict):
        raise ErrorAOI(f"{nombre} no es un GeoJSON.")
    crs = ((crudo.get("crs") or {}).get("properties") or {}).get("name", "")
    if crs and not re.search(r"(CRS84|EPSG::?4326)$", str(crs)):
        raise ErrorAOI(f"{nombre} declara el CRS {crs}. Exporta el GeoJSON en WGS84 (EPSG:4326).")
    tipo = crudo.get("type")
    if tipo == "FeatureCollection":
        elementos = crudo.get("features") or []
    elif tipo == "Feature":
        elementos = [crudo]
    elif tipo in ("Polygon", "MultiPolygon", "GeometryCollection"):
        elementos = [{"type": "Feature", "properties": {}, "geometry": crudo}]
    else:
        raise ErrorAOI(f"{nombre}: tipo GeoJSON '{tipo}' no admitido.")
    salida = []
    for i, f in enumerate(elementos, 1):
        g = (f or {}).get("geometry")
        if not g:
            continue
        try:
            geo = shape(g)
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            raise ErrorAOI(f"{nombre}: la geometría {i} no es válida.") from e
        if geo.geom_type not in ("Polygon", "MultiPolygon", "GeometryCollection"):
            raise ErrorAOI(f"{nombre}: la geometría {i} es {geo.geom_type}; solo se admiten polígonos.")
        salida.append(((f.get("properties") or {}), _poligonal(geo, f"{nombre}, geometría {i}")))
    if not salida:
        raise ErrorAOI(f"{nombre} no contiene polígonos.")
    if sum(_vertices(g) for _, g in salida) > MAX_VERTICES:
        raise ErrorAOI(f"{nombre} tiene más de {MAX_VERTICES:,} vértices; simplifícalo.")
    return salida, _sha256(datos)


def _campo(propiedades: dict, opciones: tuple[str, ...]) -> str | None:
    claves = {k.lower(): k for k in propiedades}
    for o in opciones:
        if o.lower() in claves and propiedades[claves[o.lower()]] not in (None, ""):
            return str(propiedades[claves[o.lower()]]).strip()
    return None


def _codigo_divipola(valor: str | None) -> str | None:
    if valor is None:
        return None
    digitos = re.sub(r"\D", "", valor)
    return digitos.zfill(5) if 1 <= len(digitos) <= 5 else None


@dataclass
class Limites:
    zonas: dict[str, Zona]
    fuente: str
    sha256: str

    def seleccionar(self, codigos: list[str] | tuple[str, ...], nombre: str | None = None) -> AOI:
        """Unión de los municipios pedidos (códigos DIVIPOLA)."""
        if not codigos:
            raise ErrorAOI("Elige al menos un municipio.")
        faltan = [c for c in codigos if c not in self.zonas]
        if faltan:
            nombres = ", ".join(f"{URABA.get(c, c)} ({c})" for c in faltan)
            raise ErrorAOI(f"El archivo de límites no trae: {nombres}.")
        zonas = tuple(self.zonas[c] for c in dict.fromkeys(codigos))
        nombre = nombre or (zonas[0].nombre if len(zonas) == 1 else ", ".join(z.nombre for z in zonas))
        return _aoi(nombre, zonas, "limites_oficiales", self.fuente, self.sha256)


def cargar_limites(ruta: str | Path) -> Limites:
    """Municipios de un GeoJSON oficial (DANE MGN / IGAC), por código DIVIPOLA."""
    ruta = Path(ruta)
    elementos, sha = leer_geojson(ruta)
    zonas: dict[str, Zona] = {}
    for propiedades, geo in elementos:
        codigo = _codigo_divipola(_campo(propiedades, CAMPOS_CODIGO))
        if codigo is None:
            raise ErrorAOI(f"{ruta.name}: falta el código DIVIPOLA de municipio "
                           f"(campos admitidos: {', '.join(CAMPOS_CODIGO)}).")
        nombre = _campo(propiedades, CAMPOS_NOMBRE) or URABA.get(codigo, codigo)
        if codigo in zonas:            # municipio partido en varias Features: se unen
            geo = unary_union([zonas[codigo].geometria, geo])
        zonas[codigo] = Zona(codigo, nombre.title() if nombre.isupper() else nombre, geo)
    return Limites(zonas, ruta.name, sha)


def archivos_limites(carpeta: Path | None = None) -> list[Path]:
    carpeta = Path(carpeta) if carpeta is not None else CARPETA_LIMITES
    return sorted(p for p in carpeta.glob("*.geojson")) + sorted(carpeta.glob("*.json")) if carpeta.is_dir() else []


def aoi_desde_geojson(datos: bytes | str | Path, nombre: str = "AOI cargada") -> AOI:
    """Cualquier AOI GeoJSON. Cada Feature es una zona (para estadísticas por zona)."""
    etiqueta = Path(datos).name if isinstance(datos, Path) else nombre
    elementos, sha = leer_geojson(datos, etiqueta)
    zonas = []
    for i, (propiedades, geo) in enumerate(elementos, 1):
        codigo = _codigo_divipola(_campo(propiedades, CAMPOS_CODIGO)) or f"zona_{i}"
        zonas.append(Zona(codigo, _campo(propiedades, CAMPOS_NOMBRE) or f"Zona {i}", geo))
    if len({z.codigo for z in zonas}) != len(zonas):
        zonas = [Zona(f"{z.codigo}_{i}", z.nombre, z.geometria) for i, z in enumerate(zonas, 1)]
    return _aoi(nombre, tuple(zonas), "geojson", etiqueta, sha)


def aoi_recuadro(oeste: float, sur: float, este: float, norte: float, nombre: str = "Recuadro") -> AOI:
    from shapely.geometry import box
    from utils.buscador_sar import validar_region
    r = validar_region(oeste, sur, este, norte)
    geo = box(*r.limites)
    return _aoi(nombre, (Zona("recuadro", nombre, geo),), "recuadro", "coordenadas escritas a mano", None,
                ["Un recuadro no es un límite administrativo: no sirve para estadísticas municipales."])


def solapes(zonas: tuple[Zona, ...]) -> list[str]:
    avisos = []
    for i, a in enumerate(zonas):
        for b in zonas[i + 1:]:
            if a.geometria.intersects(b.geometria):
                comun = a.geometria.intersection(b.geometria).area
                menor = min(a.geometria.area, b.geometria.area)
                if menor and comun / menor > TOLERANCIA_SOLAPE:
                    avisos.append(f"{a.nombre} y {b.nombre} se solapan ({comun / menor:.2%} de la menor): "
                                  "los píxeles comunes cuentan en ambas zonas, no en el total dos veces.")
    return avisos


def _aoi(nombre: str, zonas: tuple[Zona, ...], origen: str, fuente: str, sha: str | None,
         avisos: list[str] | None = None) -> AOI:
    union = unary_union([z.geometria for z in zonas])
    avisos = [*(avisos or []), *solapes(zonas)]
    if not math.isfinite(union.area) or union.is_empty:
        raise ErrorAOI("La unión de las zonas está vacía.")
    if union.geom_type == "MultiPolygon":
        avisos.append(f"El AOI tiene {len(union.geoms)} partes separadas.")
    if area_geodesica_km2(union) > 1_200_000:
        avisos.append("AOI mayor que Colombia continental: revisa el archivo.")
    return AOI(nombre, union, zonas, origen, fuente, sha, avisos)


def registro(aoi: AOI) -> dict:
    """Ficha del AOI para guardar junto a un análisis (qué área, de qué fuente, cuándo)."""
    return {**aoi.resumen(), "creado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
