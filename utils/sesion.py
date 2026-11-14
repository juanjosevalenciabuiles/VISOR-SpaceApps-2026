"""Estado del recorrido de análisis: zona confirmada, ejecución y resultado activo.

Reglas que este módulo hace cumplir (sin Streamlit, para poder probarlas):

- Un resultado solo está en el mapa si lo autoriza una acción explícita: una
  ejecución correcta de «Analizar» o «Ver» en el historial. Un archivo que
  existe en disco no autoriza nada.
- Cada ejecución tiene un `run_id` estable: zona + escenas + parámetros +
  versión del motor. Si cambia cualquiera de ellos, el resultado activo deja
  de corresponder a lo que hay en pantalla y se retira (el archivo no se toca).
- La zona se valida antes de cargar datos: geometría, orden de coordenadas y
  tamaño estimado frente al límite de píxeles del motor.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from utils.analisis_sar import MAX_PIXELES, VERSION_MOTOR

ANALISIS, HISTORICO = "analisis", "historico"
RESOLUCION_ESTIMADA_M = 30.0          # solo para estimar el tamaño antes de leer los RTC
MAX_LADO_GRADOS = 5.0


class ErrorZona(ValueError):
    """La zona no se puede usar; el mensaje dice por qué y cómo corregirla."""


def zona_canonica(limites) -> tuple[float, float, float, float]:
    """(oeste, sur, este, norte) con 5 decimales (~1 m): la misma zona da siempre la misma clave."""
    return tuple(round(float(v), 5) for v in limites)


def dimensiones_km(limites) -> tuple[float, float]:
    oeste, sur, este, norte = limites
    alto = (norte - sur) * 111.32
    ancho = (este - oeste) * 111.32 * math.cos(math.radians((norte + sur) / 2))
    return ancho, alto


def pixeles_estimados(limites, resolucion_m: float = RESOLUCION_ESTIMADA_M) -> int:
    ancho, alto = dimensiones_km(limites)
    return int(round(ancho * 1000 / resolucion_m) * round(alto * 1000 / resolucion_m))


def validar_zona(limites) -> tuple[float, float, float, float]:
    """Devuelve la zona canónica o lanza ErrorZona antes de tocar ningún dato pesado."""
    try:
        oeste, sur, este, norte = (float(v) for v in limites)
    except (TypeError, ValueError):
        raise ErrorZona("La zona necesita cuatro números: oeste, sur, este y norte.") from None
    if not all(math.isfinite(v) for v in (oeste, sur, este, norte)):
        raise ErrorZona("La zona tiene coordenadas que no son números.")
    if not (-180 <= oeste <= 180 and -180 <= este <= 180 and -90 <= sur <= 90 and -90 <= norte <= 90):
        raise ErrorZona("Las coordenadas están fuera del mundo: longitud entre −180 y 180, latitud entre −90 y 90. "
                        "Si cargaste un GeoJSON, comprueba que esté en WGS84 (EPSG:4326) y en orden longitud, latitud.")
    if oeste >= este:
        raise ErrorZona("El oeste debe ser menor que el este. No se admiten zonas que crucen el meridiano 180: "
                        "divídela en dos.")
    if sur >= norte:
        raise ErrorZona("El sur debe ser menor que el norte.")
    if este - oeste < 0.001 or norte - sur < 0.001:
        raise ErrorZona("La zona es demasiado pequeña: dibuja al menos unos 100 m de lado.")
    if este - oeste > MAX_LADO_GRADOS or norte - sur > MAX_LADO_GRADOS:
        raise ErrorZona(f"La zona es demasiado amplia ({este - oeste:.1f}° × {norte - sur:.1f}°). "
                        f"El máximo es {MAX_LADO_GRADOS:g}° por lado: acércate y dibuja una zona más pequeña.")
    zona = zona_canonica((oeste, sur, este, norte))
    px = pixeles_estimados(zona)
    if px > MAX_PIXELES:
        ancho, alto = dimensiones_km(zona)
        raise ErrorZona(
            f"La zona mide {ancho:.0f} × {alto:.0f} km: a 30 m serían unos {px / 1e6:.0f} millones de píxeles y el "
            f"motor admite {MAX_PIXELES / 1e6:.0f} millones. Reduce la zona (por ejemplo a menos de "
            f"{math.sqrt(MAX_PIXELES) * RESOLUCION_ESTIMADA_M / 1000:.0f} km por lado) antes de analizar.")
    return zona


def zona_de_geojson(objeto) -> tuple[tuple[float, float, float, float], dict]:
    """Recuadro envolvente y geometría de un GeoJSON (Feature, FeatureCollection o geometría).

    Solo polígonos, en WGS84 y orden longitud-latitud (el del estándar GeoJSON)."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    if isinstance(objeto, (str, bytes)):
        try:
            objeto = json.loads(objeto)
        except ValueError:
            raise ErrorZona("El archivo no es un GeoJSON válido (no se pudo leer como JSON).") from None
    if not isinstance(objeto, dict):
        raise ErrorZona("El GeoJSON debe ser un objeto con una geometría de polígono.")
    if objeto.get("type") == "FeatureCollection":
        geometrias = [f.get("geometry") for f in objeto.get("features") or [] if isinstance(f, dict)]
    elif objeto.get("type") == "Feature":
        geometrias = [objeto.get("geometry")]
    else:
        geometrias = [objeto]
    formas = []
    for g in geometrias:
        if not isinstance(g, dict) or g.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        try:
            formas.append(shape(g))
        except Exception:  # noqa: BLE001 — coordenadas mal formadas
            raise ErrorZona("La geometría del GeoJSON está mal formada.") from None
    if not formas:
        raise ErrorZona("El GeoJSON no contiene ningún polígono. Un punto o una línea no delimitan una zona.")
    union = unary_union(formas)
    if union.is_empty or not union.is_valid or union.area == 0:
        raise ErrorZona("El polígono está vacío o se cruza a sí mismo. Vuelve a dibujarlo.")
    return validar_zona(union.bounds), union.__geo_interface__


def clave_par(antes: str, despues: str) -> str:
    return f"{antes}|{despues}"


def _huella(datos) -> str:
    return hashlib.sha256(json.dumps(datos, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def run_id(zona, antes: str, despues: str, parametros: dict[str, dict]) -> str:
    """Identificador de una ejecución: misma zona, mismas escenas, mismos parámetros y
    misma versión del motor ⇒ mismo `run_id`. `parametros`: polarización → valores."""
    return _huella({"zona": zona_canonica(zona), "antes": antes, "despues": despues,
                    "parametros": {p: {k: float(v) for k, v in sorted(d.items())}
                                   for p, d in sorted(parametros.items())},
                    "motor": VERSION_MOTOR})


def contexto(zona, par: str | None, parametros: dict | None) -> str:
    """Clave de lo que hay elegido ahora. Un resultado se muestra mientras esta clave sea la
    que había cuando se autorizó; si cambia, ya no corresponde y se retira."""
    return _huella({"zona": zona_canonica(zona) if zona else None, "par": par,
                    "parametros": {p: {k: float(v) for k, v in sorted(d.items())}
                                   for p, d in sorted((parametros or {}).items())}})


def registros(carpeta: Path) -> list[dict]:
    """Registros de ejecuciones (`*_registro.json`) legibles, del más reciente al más antiguo.
    Cada uno lleva además `_archivo` con su nombre."""
    salida = []
    if not Path(carpeta).is_dir():
        return salida
    for ruta in Path(carpeta).glob("*_registro.json"):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(datos, dict):
            salida.append({**datos, "_archivo": ruta.name})
    return sorted(salida, key=lambda d: str(d.get("generado_utc", "")), reverse=True)


def _mismo_par(registro: dict, antes: str, despues: str) -> bool:
    par = registro.get("par_catalogo_asf") or {}
    nombres = [str((par.get(k) or {}).get("nombre") or (par.get(k) or {}).get("escena") or "")
               for k in ("antes", "despues")]
    return nombres == [antes, despues] or registro.get("par") == clave_par(antes, despues)


def ejecuciones_del_par(carpeta: Path, zona, antes: str, despues: str) -> list[dict]:
    """Ejecuciones correctas anteriores de este par sobre esta misma zona (con cualquier parámetro)
    cuyas salidas siguen existiendo."""
    zona = list(zona_canonica(zona))
    salida = []
    for r in registros(carpeta):
        try:
            misma_zona = list(zona_canonica(r.get("aoi_lonlat") or ())) == zona
        except (TypeError, ValueError):
            misma_zona = False
        if misma_zona and _mismo_par(r, antes, despues) and salidas_existentes(carpeta, r):
            salida.append(r)
    return salida


def salidas_existentes(carpeta: Path, registro: dict) -> list[str]:
    nombres = [str(n) for n in registro.get("salidas") or []]
    return nombres if nombres and all((Path(carpeta) / n).is_file() for n in nombres) else []


def ejecucion_con_id(carpeta: Path, identificador: str) -> dict | None:
    for r in registros(carpeta):
        if r.get("run_id") == identificador and salidas_existentes(carpeta, r):
            return r
    return None


def resultado_principal(registro: dict) -> str | None:
    """Archivo que representa la ejecución: la coincidencia VV/VH si existe; si no, la primera máscara."""
    salidas = [str(n) for n in registro.get("salidas") or []]
    for n in salidas:
        if n.startswith("coincidencia_"):
            return n
    return salidas[0] if salidas else None
