"""Alcance geográfico de la plataforma: Modo Colombia (por defecto) o global.

`VISOR_REGION_MODE=CO` (por defecto) restringe la experiencia pública al territorio continental
e insular de Colombia; `GLOBAL` restituye la navegación mundial (solo configuración interna o de
pruebas: no hay control público para cambiarlo). Cualquier otro valor se trata como CO: ante la
duda, la política se cierra, no se abre.

Una sola geometría y una sola regla para la interfaz y el servidor:
- la VALIDACIÓN usa la unión de departamentos del MGN 2025 del DANE al nivel `municipal`
  (69 polígonos, ~63 000 vértices) — ver data/contexto/colombia/FUENTE.json;
- el DIBUJO (contorno y velo) usa la misma geometría simplificada (~300 m);
- una zona es válida solo si el RECTÁNGULO QUE PROCESA EL MOTOR está entero dentro de Colombia
  (no basta el polígono dibujado: el motor recorta por su rectángulo envolvente);
- si el archivo del límite falta o no se puede leer, en modo CO no se admite ninguna zona nueva
  (se explica el motivo) en lugar de quedar sin restricción.

Es un límite de fuente estadística, no una definición jurídica de fronteras; no incluye mar
territorial ni zona económica exclusiva, y la simplificación usada no contiene Gorgona ni Malpelo.
"""
from __future__ import annotations

import gzip
import json
import os
from functools import lru_cache
from pathlib import Path

from shapely import prepare
from shapely.geometry import Point, box, mapping, shape

from utils.config import DATA_DIR

CO, GLOBAL = "CO", "GLOBAL"
CARPETA = DATA_DIR / "contexto" / "colombia"
ARCHIVO_VALIDACION = "colombia_mgn2025_municipal.geojson.gz"
ARCHIVO_DIBUJO = "colombia_dibujo.geojson.gz"
ATRIBUCION = ('Límite de Colombia: <a href="https://www.dane.gov.co" target="_blank">MGN 2025, DANE</a> · '
              'simplificación <a href="https://github.com/ytolosa/mapas-colombia" target="_blank">'
              "ytolosa/mapas-colombia</a>, CC BY 4.0")
INSIGNIA = "COLOMBIA · Área de estudio habilitada"
FUERA = "Zona no disponible en esta versión"
# Vista inicial que abarca Colombia continental y el archipiélago de San Andrés y Providencia.
VISTA_INICIAL = {"centro": (4.6, -74.3), "zoom": 5}
# Paneo permitido: extensión del país con margen (no se puede «perder» el mapa lejos de Colombia).
EXTENSION_NAVEGACION = (-86.0, -8.0, -62.0, 17.0)       # oeste, sur, este, norte
ZOOM_MINIMO = 4


class FueraDeAlcance(ValueError):
    """La zona, el lugar o la operación está fuera del territorio habilitado."""


def modo() -> str:
    valor = os.environ.get("VISOR_REGION_MODE", CO).strip().upper()
    return GLOBAL if valor == GLOBAL else CO


def restringido() -> bool:
    return modo() == CO


def _leer(nombre: str):
    ruta = Path(os.environ.get("VISOR_LIMITE_COLOMBIA_DIR") or CARPETA) / nombre
    datos = json.loads(gzip.decompress(ruta.read_bytes()))
    geometria = shape(datos["features"][0]["geometry"])
    if geometria.is_empty or not geometria.is_valid:
        raise ValueError("geometría vacía o no válida")
    return geometria


@lru_cache(maxsize=4)
def _geometria_cache(directorio: str):
    geometria = _leer(ARCHIVO_VALIDACION)
    prepare(geometria)
    return geometria


def geometria():
    """Geometría de validación (preparada). FueraDeAlcance si no se puede cargar."""
    try:
        return _geometria_cache(os.environ.get("VISOR_LIMITE_COLOMBIA_DIR") or str(CARPETA))
    except (OSError, ValueError, KeyError, IndexError) as e:
        raise FueraDeAlcance(
            "No se pudo cargar el límite nacional de Colombia (data/contexto/colombia/). Por seguridad no se "
            f"admiten zonas nuevas hasta restaurarlo. Detalle: {type(e).__name__}.") from None


def limite_disponible() -> bool:
    try:
        geometria()
        return True
    except FueraDeAlcance:
        return False


TOLERANCIA_LUGAR_KM = 1.0     # solo para LUGARES (navegar): un geocódigo costero puede caer metros mar adentro


def contiene_punto(latitud: float, longitud: float, tolerancia_km: float = 0.0) -> bool:
    """True si el punto está en Colombia (o si el modo es GLOBAL). La tolerancia solo se usa para
    ubicar lugares en el mapa; las zonas de análisis se validan sin tolerancia."""
    if not restringido():
        return True
    punto = Point(float(longitud), float(latitud))
    geo = geometria()
    return bool(geo.covers(punto) or (tolerancia_km > 0 and geo.distance(punto) * 111.0 <= tolerancia_km))


def validar_punto(latitud: float, longitud: float, que: str = "El lugar") -> None:
    if not contiene_punto(latitud, longitud, TOLERANCIA_LUGAR_KM):
        raise FueraDeAlcance(f"{que} ({latitud:.4f}, {longitud:.4f}) está fuera de Colombia. {FUERA}: V.I.S.O.R. "
                             "solo permite explorar y analizar el territorio colombiano.")


def validar_limites(limites: tuple[float, float, float, float], que: str = "La zona") -> None:
    """Exige que el rectángulo (oeste, sur, este, norte) que procesará el motor esté entero en Colombia.

    No recorta: si una parte sale del país (frontera o mar), se rechaza y se pide reducirla."""
    if not restringido():
        return
    o, s, e, n = (float(v) for v in limites)
    validar_geometria(box(o, s, e, n), que)


def validar_geometria(rect, que: str = "La zona") -> None:
    """Igual que validar_limites para cualquier polígono en EPSG:4326 (p. ej. la cuadrícula UTM del motor
    transformada a longitud/latitud)."""
    if not restringido():
        return
    geo = geometria()
    if geo.covers(rect):
        return
    dentro = rect.intersection(geo).area / rect.area if rect.area else 0.0
    if dentro <= 0:
        raise FueraDeAlcance(f"{que} está fuera de Colombia. {FUERA}: solo se analiza territorio colombiano.")
    raise FueraDeAlcance(
        f"{que} sale del territorio colombiano: el rectángulo que se analizaría tiene un {100 * (1 - dentro):.1f} % "
        "fuera del país (otro país o mar). Redúcela para que quede entera dentro de Colombia; no se recorta en "
        "silencio. Si dibujaste un polígono, cuenta su rectángulo envolvente, que es lo que procesa el motor.")


def admitida(limites) -> bool:
    try:
        validar_limites(limites)
        return True
    except FueraDeAlcance:
        return False


@lru_cache(maxsize=2)
def _dibujo_cache(directorio: str) -> tuple[str, str]:
    colombia = _leer(ARCHIVO_DIBUJO)
    o, s, e, n = EXTENSION_NAVEGACION
    margen = 30.0      # el velo cubre más que la extensión navegable: nunca se ve su borde
    velo = box(o - margen, s - margen, e + margen, n + margen).difference(colombia)
    contorno = {"type": "Feature", "properties": {"nombre": "Colombia"}, "geometry": mapping(colombia)}
    exterior = {"type": "Feature", "properties": {"nombre": FUERA}, "geometry": mapping(velo)}
    return (json.dumps(contorno, separators=(",", ":")), json.dumps(exterior, separators=(",", ":")))


def capas_dibujo() -> tuple[str, str] | None:
    """(contorno de Colombia, velo exterior) como GeoJSON; None si el archivo de dibujo falta."""
    try:
        return _dibujo_cache(os.environ.get("VISOR_LIMITE_COLOMBIA_DIR") or str(CARPETA))
    except (OSError, ValueError, KeyError, IndexError):
        return None


def ficha_fuente() -> dict:
    try:
        return json.loads((CARPETA / "FUENTE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def filtrar_resultados(resultados: list) -> tuple[list, int]:
    """(resultados que se pueden mostrar, cuántos se ocultan por estar fuera de Colombia).

    Un resultado guardado de otro país no se puede abrir, exportar ni recuperar como actual en Modo
    Colombia. Los archivos no se tocan. Los que no se pueden leer se conservan (muestran su error)."""
    if not restringido():
        return list(resultados), 0
    visibles, ocultos = [], 0
    for r in resultados:
        capa = getattr(r, "capa", None)
        if capa is not None and not admitida(capa.limites):
            ocultos += 1
            continue
        visibles.append(r)
    return visibles, ocultos
