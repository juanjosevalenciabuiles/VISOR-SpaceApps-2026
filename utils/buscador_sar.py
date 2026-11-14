"""Buscador de escenas Sentinel-1 en el catálogo de Alaska Satellite Facility (ASF).

Consulta de SOLO LECTURA al SearchAPI público de ASF: no descarga imágenes,
no envía trabajos a HyP3, no usa credenciales ni consume créditos.

El módulo está separado en cuatro pasos independientes:

    1. Validación    validar_region, region_desde_punto, validar_fechas, wkt_region, bbox_region
    2. Consulta      construir_consulta, consultar_asf        (única parte con red)
                     La región viaja como recuadro `bbox`.
    3. Filtrado      interpretar_respuesta → Escena           (descarta lo incompatible)
    4. Emparejado    emparejar → ParEscenas                   (pares antes/después)

y una salida pensada para el futuro enlace con el motor de análisis:
`ParEscenas.para_motor()`.

IMPORTANTE: un par "recomendado" es el mejor candidato según geometría,
polarización, cobertura y fechas. No es un par científicamente validado: no se
ha comprobado la calidad de las imágenes ni qué ocurrió en el terreno.

No depende de Streamlit ni añade dependencias (usa urllib y Shapely, que ya
llega con GeoPandas).
"""
from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry

URL_BUSQUEDA = "https://api.daac.asf.alaska.edu/services/search/param"
URL_VERTEX = "https://search.asf.alaska.edu/#/"
AGENTE = "VISOR-SpaceApps-2026 (buscador de solo lectura)"

PRIMER_DATO_S1 = date(2014, 4, 3)        # lanzamiento de Sentinel-1A
MAX_DIAS = 366                           # período máximo por consulta
MAX_LADO_GRADOS = 5.0                    # lado máximo del recuadro
MAX_RESULTADOS = 250                     # tope pedido al catálogo
TIEMPO_ESPERA_S = 30                     # el SearchAPI corta las consultas a los 30 s
CICLO_DIAS = 12                          # ciclo de repetición de cada satélite Sentinel-1

# Productos aptos para análisis de amplitud: GRD de alta resolución en modo IW.
NIVELES_ACEPTADOS = ("GRD_HD",)
MODO_ACEPTADO = "IW"
_CODIGOS_POL = {"SDV": ("VV", "VH"), "SDH": ("HH", "HV"), "SSV": ("VV",), "SSH": ("HH",)}

# Ejemplo: S1A_IW_GRDH_1SDV_20190809T001336_20190809T001401_028485_033839_78A1
_NOMBRE_ESCENA = re.compile(
    r"^(?P<plataforma>S1[A-D])_(?P<modo>[A-Z0-9]{2})_(?P<tipo>[A-Z]{3})(?P<res>[A-Z_])_"
    r"(?P<nivel>\d)(?P<clase>[A-Z])(?P<pol>[A-Z]{2})_"
    r"(?P<inicio>\d{8}T\d{6})_(?P<fin>\d{8}T\d{6})_(?P<orbita>\d{6})_(?P<toma>[0-9A-F]{6})_(?P<id>[0-9A-F]{4})$"
)
# Órbita relativa a partir de la absoluta (solo para satélites con fórmula publicada).
_DESFASE_ORBITA = {"S1A": 73, "S1B": 27}

ADVERTENCIA_PAR = (
    "Par recomendado, no validado: se eligió por órbita, polarización, cobertura y fechas. "
    "Falta revisar la calidad de las imágenes y contrastar el resultado con otras fuentes."
)


class ErrorBusqueda(Exception):
    """Entrada inválida: coordenadas, fechas o tamaño de la consulta."""


class ErrorConexion(ErrorBusqueda):
    """No se pudo hablar con ASF (red caída, tiempo agotado, servicio no disponible)."""


class ErrorServicio(ErrorBusqueda):
    """ASF respondió, pero con un error o con algo que no se puede interpretar."""


# ---------------------------------------------------------------------------
# 1. Validación de la región y del período
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Region:
    oeste: float
    sur: float
    este: float
    norte: float

    @property
    def limites(self) -> tuple[float, float, float, float]:
        return self.oeste, self.sur, self.este, self.norte

    @property
    def poligono(self) -> BaseGeometry:
        return box(*self.limites)

    @property
    def centro(self) -> tuple[float, float]:
        """(latitud, longitud)."""
        return (self.sur + self.norte) / 2, (self.oeste + self.este) / 2


def _numero(valor, nombre: str) -> float:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        raise ErrorBusqueda(f"{nombre} debe ser un número.") from None
    if not math.isfinite(n):
        raise ErrorBusqueda(f"{nombre} debe ser un número finito.")
    return n


def validar_region(oeste, sur, este, norte, max_lado: float = MAX_LADO_GRADOS) -> Region:
    """Recuadro en grados decimales (longitud oeste/este, latitud sur/norte)."""
    oeste, sur = _numero(oeste, "Oeste"), _numero(sur, "Sur")
    este, norte = _numero(este, "Este"), _numero(norte, "Norte")
    if not (-180 <= oeste <= 180 and -180 <= este <= 180):
        raise ErrorBusqueda("Las longitudes (oeste y este) deben estar entre −180 y 180.")
    if not (-90 <= sur <= 90 and -90 <= norte <= 90):
        raise ErrorBusqueda("Las latitudes (sur y norte) deben estar entre −90 y 90.")
    if oeste >= este:
        raise ErrorBusqueda("El oeste debe ser menor que el este (no se admiten recuadros que crucen el meridiano 180).")
    if sur >= norte:
        raise ErrorBusqueda("El sur debe ser menor que el norte.")
    if este - oeste < 0.001 or norte - sur < 0.001:
        raise ErrorBusqueda("La región es demasiado pequeña: usa al menos 0.001° de lado (unos 100 m).")
    if este - oeste > max_lado or norte - sur > max_lado:
        raise ErrorBusqueda(
            f"La región es demasiado amplia ({este - oeste:.1f}° × {norte - sur:.1f}°). "
            f"El máximo es {max_lado:g}° por lado: divide la búsqueda en zonas más pequeñas."
        )
    return Region(oeste, sur, este, norte)


def region_desde_punto(latitud, longitud, radio_km: float = 10.0) -> Region:
    """Recuadro centrado en un punto, con el radio dado en kilómetros."""
    lat, lon, radio = _numero(latitud, "La latitud"), _numero(longitud, "La longitud"), _numero(radio_km, "El radio")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ErrorBusqueda("El punto debe tener latitud entre −90 y 90 y longitud entre −180 y 180.")
    if radio <= 0:
        raise ErrorBusqueda("El radio debe ser mayor que cero.")
    d_lat = radio / 110.574
    d_lon = radio / (111.320 * max(math.cos(math.radians(lat)), 0.01))
    return validar_region(max(lon - d_lon, -180), max(lat - d_lat, -90), min(lon + d_lon, 180), min(lat + d_lat, 90))


def _a_dia(valor, nombre: str) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ErrorBusqueda(f"{nombre} no es una fecha válida. Usa el formato AAAA-MM-DD.") from None


def validar_fechas(inicio, fin, hoy: date | None = None, max_dias: int = MAX_DIAS) -> tuple[date, date]:
    inicio, fin = _a_dia(inicio, "La fecha inicial"), _a_dia(fin, "La fecha final")
    hoy = hoy or datetime.now(timezone.utc).date()
    if inicio > fin:
        raise ErrorBusqueda("La fecha inicial es posterior a la fecha final.")
    if inicio > hoy:
        raise ErrorBusqueda("La fecha inicial está en el futuro: todavía no hay imágenes.")
    if fin < PRIMER_DATO_S1:
        raise ErrorBusqueda(f"Sentinel-1 no tiene datos anteriores al {PRIMER_DATO_S1:%Y-%m-%d}.")
    if (fin - inicio).days > max_dias:
        raise ErrorBusqueda(
            f"El período es demasiado largo ({(fin - inicio).days} días). "
            f"El máximo es {max_dias} días por consulta."
        )
    return inicio, fin


def _coordenadas(region: Region) -> tuple[str, str, str, str]:
    return tuple(f"{v:.6f}".rstrip("0").rstrip(".") for v in region.limites)


def wkt_region(region: Region) -> str:
    """Polígono WKT cerrado y en sentido antihorario (para enlaces, exportación
    o herramientas que pidan la región como geometría)."""
    o, s, e, n = _coordenadas(region)
    return f"POLYGON(({o} {s},{e} {s},{e} {n},{o} {n},{o} {s}))"


def bbox_region(region: Region) -> str:
    """Recuadro "oeste,sur,este,norte", la forma en que se envía la región a ASF."""
    return ",".join(_coordenadas(region))


# ---------------------------------------------------------------------------
# 2. Consulta al catálogo
# ---------------------------------------------------------------------------

def construir_consulta(region: Region, inicio: date, fin: date, max_resultados: int = MAX_RESULTADOS) -> dict[str, str]:
    """Parámetros del SearchAPI de ASF para escenas Sentinel-1 GRD en modo IW.

    La región se envía con `bbox`. Comprobado contra el servicio real el
    2026-11-12: para el recuadro de Chigorodó, `bbox` devolvió las 13 escenas
    que lo tocan, mientras que `intersectsWith=POLYGON(...)` con el mismo
    recuadro omitió 6 que solo lo cubren parcialmente.
    """
    return {
        "platform": "Sentinel-1",
        "processingLevel": ",".join(NIVELES_ACEPTADOS),
        "beamMode": MODO_ACEPTADO,
        "bbox": bbox_region(region),
        "start": f"{inicio:%Y-%m-%d}T00:00:00Z",
        "end": f"{fin:%Y-%m-%d}T23:59:59Z",
        "output": "geojson",
        "maxResults": str(int(max_resultados)),
    }


def url_consulta(parametros: dict[str, str]) -> str:
    return f"{URL_BUSQUEDA}?{urllib.parse.urlencode(parametros)}"


def consultar_asf(
    parametros: dict[str, str],
    tiempo_espera: float = TIEMPO_ESPERA_S,
    abrir: Callable | None = None,
) -> dict:
    """Hace la consulta HTTP (GET, sin autenticación) y devuelve el GeoJSON.

    `abrir` permite sustituir la red en las pruebas.
    """
    abrir = abrir or urllib.request.urlopen
    peticion = urllib.request.Request(url_consulta(parametros), headers={"User-Agent": AGENTE, "Accept": "application/json"})
    try:
        with abrir(peticion, timeout=tiempo_espera) as respuesta:
            cuerpo = respuesta.read()
    except urllib.error.HTTPError as e:
        detalle = ""
        try:
            detalle = json.loads(e.read().decode("utf-8", "replace")).get("error", {}).get("report", "")
        except Exception:  # noqa: BLE001 - el cuerpo del error es opcional
            pass
        if e.code >= 500:
            raise ErrorConexion(f"El catálogo de ASF no está disponible en este momento (HTTP {e.code}). Intenta más tarde.") from e
        raise ErrorServicio(f"ASF rechazó la consulta (HTTP {e.code}). {detalle}".strip()) from e
    except TimeoutError as e:
        raise ErrorConexion("ASF tardó demasiado en responder. Reduce la región o el período e intenta de nuevo.") from e
    except (urllib.error.URLError, OSError) as e:
        if isinstance(getattr(e, "reason", None), TimeoutError):
            raise ErrorConexion("ASF tardó demasiado en responder. Reduce la región o el período e intenta de nuevo.") from e
        raise ErrorConexion("No se pudo conectar con el catálogo de ASF. Revisa la conexión a internet.") from e

    try:
        datos = json.loads(cuerpo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ErrorServicio("ASF devolvió una respuesta que no es JSON.") from e
    if isinstance(datos, dict) and "error" in datos:
        informe = datos["error"].get("report", "") if isinstance(datos["error"], dict) else str(datos["error"])
        raise ErrorServicio(f"ASF informó un error en la consulta. {informe}".strip())
    if not isinstance(datos, dict) or not isinstance(datos.get("features"), list):
        raise ErrorServicio("La respuesta de ASF no tiene el formato esperado (GeoJSON con 'features').")
    return datos


# ---------------------------------------------------------------------------
# 3. Filtrado: de la respuesta a escenas utilizables
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Escena:
    nombre: str
    plataforma: str                        # S1A, S1B, S1C…
    inicio: datetime                       # UTC
    fin: datetime
    orbita_absoluta: int
    orbita_relativa: int
    direccion: str                         # "ASCENDING" o "DESCENDING"
    modo: str
    nivel: str
    polarizaciones: tuple[str, ...]
    huella: BaseGeometry = field(compare=False, repr=False)
    cobertura: float = 0.0                 # fracción de la región que cubre (0–1)
    url: str | None = None                 # enlace oficial al producto en ASF
    tamano_bytes: int | None = None
    cuadro: int | None = None
    otras_versiones: tuple[str, ...] = ()  # mismo paso del satélite, publicado más de una vez en ASF

    @property
    def direccion_es(self) -> str:
        return "Ascendente" if self.direccion == "ASCENDING" else "Descendente"

    @property
    def enlace_vertex(self) -> str:
        """Búsqueda de esta escena en ASF Vertex."""
        return f"{URL_VERTEX}?searchType=List%20Search&searchList={self.nombre}"

    def metadatos(self) -> dict:
        return {
            "nombre": self.nombre,
            "plataforma": self.plataforma,
            "inicio_utc": self.inicio.isoformat(),
            "fin_utc": self.fin.isoformat(),
            "orbita_absoluta": self.orbita_absoluta,
            "orbita_relativa": self.orbita_relativa,
            "direccion": self.direccion,
            "modo": self.modo,
            "nivel": self.nivel,
            "polarizaciones": list(self.polarizaciones),
            "cobertura_region": round(self.cobertura, 4),
            "huella_wkt": self.huella.wkt,
            "url": self.url,
            "tamano_bytes": self.tamano_bytes,
            "otras_versiones": list(self.otras_versiones),
        }


def _fecha_utc(texto) -> datetime | None:
    if not texto:
        return None
    limpio = str(texto).strip().replace("Z", "")
    for formato in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y%m%dT%H%M%S"):
        try:
            return datetime.strptime(limpio[:26], formato).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _entero(valor) -> int | None:
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def _polarizaciones(texto, codigo: str | None) -> tuple[str, ...]:
    partes = [p for p in re.split(r"[+,/\s]+", str(texto or "").upper()) if p in ("VV", "VH", "HH", "HV")]
    if not partes and codigo:
        partes = list(_CODIGOS_POL.get("S" + codigo, ()))
    return tuple(dict.fromkeys(partes))


def _cobertura(huella: BaseGeometry, region: Region) -> float:
    zona = region.poligono
    return float(huella.intersection(zona).area / zona.area) if zona.area else 0.0


def _escena_de(elemento: dict, region: Region) -> Escena | str:
    """Convierte un elemento del GeoJSON en Escena, o devuelve el motivo del descarte."""
    p = elemento.get("properties") or {}
    nombre = str(p.get("sceneName") or p.get("fileID") or "").replace("-GRD_HD", "").strip()
    if not nombre:
        return "sin nombre de escena"
    nivel = str(p.get("processingLevel") or "").upper()
    if nivel.startswith("METADATA"):
        return "solo metadatos"
    partes = _NOMBRE_ESCENA.match(nombre)
    if not nivel and partes and partes["tipo"] == "GRD":
        nivel = "GRD_HD" if partes["res"] == "H" else f"GRD_{partes['res']}"
    if nivel not in NIVELES_ACEPTADOS:
        return f"producto {nivel or 'desconocido'}, no GRD de alta resolución"
    modo = str(p.get("beamModeType") or (partes and partes["modo"]) or "").upper()
    if modo != MODO_ACEPTADO:
        return f"modo {modo or 'desconocido'}, no IW"
    plataforma_larga = str(p.get("platform") or "")
    plataforma = (partes and partes["plataforma"]) or ("S1" + plataforma_larga[-1:].upper() if "entinel-1" in plataforma_larga else "")
    if not re.fullmatch(r"S1[A-D]", plataforma or ""):
        return "no es Sentinel-1"

    inicio = _fecha_utc(p.get("startTime")) or (partes and _fecha_utc(partes["inicio"]))
    fin = _fecha_utc(p.get("stopTime")) or (partes and _fecha_utc(partes["fin"])) or inicio
    if not inicio:
        return "sin fecha de adquisición"
    absoluta = _entero(p.get("orbit")) or (partes and int(partes["orbita"]))
    relativa = _entero(p.get("pathNumber"))
    if relativa is None and absoluta and plataforma in _DESFASE_ORBITA:
        relativa = (absoluta - _DESFASE_ORBITA[plataforma]) % 175 + 1
    if not absoluta or relativa is None:
        return "sin órbita"
    direccion = str(p.get("flightDirection") or "").upper()
    if direccion not in ("ASCENDING", "DESCENDING"):
        return "sin dirección de vuelo"
    pols = _polarizaciones(p.get("polarization"), partes and partes["pol"])
    if not pols:
        return "sin polarización reconocible"

    try:
        huella = shape(elemento.get("geometry"))
        if huella.is_empty or huella.geom_type not in ("Polygon", "MultiPolygon"):
            return "sin huella geográfica"
        if not huella.is_valid:
            huella = huella.buffer(0)
    except Exception:  # noqa: BLE001 - geometría ausente o mal formada
        return "sin huella geográfica"
    cobertura = _cobertura(huella, region)
    if cobertura <= 0:
        return "no cubre la región"

    url = str(p.get("url") or "")
    return Escena(
        nombre=nombre, plataforma=plataforma, inicio=inicio, fin=fin, orbita_absoluta=absoluta,
        orbita_relativa=relativa, direccion=direccion, modo=modo, nivel=nivel, polarizaciones=pols,
        huella=huella, cobertura=cobertura, url=url if url.startswith("https://") else None,
        tamano_bytes=_entero(p.get("bytes")), cuadro=_entero(p.get("frameNumber")),
    )


@dataclass
class ResultadoFiltrado:
    escenas: list[Escena]
    descartes: dict[str, int]              # motivo → cantidad
    duplicados: int                        # mismo producto repetido en la respuesta
    recibidos: int
    versiones: int = 0                     # misma adquisición publicada con otro identificador


def _adquisicion(e: Escena) -> tuple:
    """Dos productos con esta misma clave son la misma toma del satélite."""
    return e.plataforma, e.inicio, e.fin, e.orbita_absoluta, e.nivel


def interpretar_respuesta(geojson: dict, region: Region) -> ResultadoFiltrado:
    """Filtra la respuesta de ASF: deja solo escenas Sentinel-1 GRD IW con
    órbita, polarización y huella, sin duplicados, ordenadas por fecha."""
    elementos = geojson.get("features") or []
    por_nombre: dict[str, Escena] = {}
    descartes: dict[str, int] = {}
    duplicados = 0
    for elemento in elementos:
        resultado = _escena_de(elemento, region) if isinstance(elemento, dict) else "elemento ilegible"
        if isinstance(resultado, str):
            descartes[resultado] = descartes.get(resultado, 0) + 1
        elif resultado.nombre in por_nombre:
            duplicados += 1
        else:
            por_nombre[resultado.nombre] = resultado

    # ASF publica a veces la misma adquisición con dos identificadores (reprocesos).
    # Se conserva una sola, elegida de forma estable (orden alfabético), y se
    # anotan las demás para que el usuario pueda consultarlas.
    por_toma: dict[tuple, list[Escena]] = {}
    for escena in por_nombre.values():
        por_toma.setdefault(_adquisicion(escena), []).append(escena)
    escenas, versiones = [], 0
    for grupo in por_toma.values():
        grupo.sort(key=lambda e: e.nombre)
        versiones += len(grupo) - 1
        escenas.append(replace(grupo[0], otras_versiones=tuple(e.nombre for e in grupo[1:])))
    escenas.sort(key=lambda e: (e.inicio, e.nombre))
    return ResultadoFiltrado(escenas, descartes, duplicados, len(elementos), versiones)


# ---------------------------------------------------------------------------
# 4. Emparejado antes / después
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParEscenas:
    antes: Escena
    despues: Escena
    dias: float
    polarizaciones_comunes: tuple[str, ...]
    cobertura_comun: float                 # fracción de la región cubierta por AMBAS escenas
    misma_plataforma: bool
    puntuacion: float
    motivos: tuple[str, ...]
    avisos: tuple[str, ...]
    recomendado: bool = False
    validado: bool = False                 # este módulo nunca valida científicamente un par

    @property
    def estado(self) -> str:
        return "Recomendado (sin validar)" if self.recomendado else "Compatible (sin validar)"

    @property
    def enlace_vertex(self) -> str:
        return f"{URL_VERTEX}?searchType=List%20Search&searchList={self.antes.nombre},{self.despues.nombre}"

    def para_motor(self) -> dict:
        """Identificadores y metadatos del par, en la forma que podrá recibir
        el motor de análisis (utils/analisis_sar.py) cuando ambos se integren."""
        return {
            "estado": self.estado,
            "validado_cientificamente": False,
            "advertencia": ADVERTENCIA_PAR,
            "polarizaciones_comunes": list(self.polarizaciones_comunes),
            "orbita_relativa": self.antes.orbita_relativa,
            "direccion": self.antes.direccion,
            "dias_entre_escenas": round(self.dias, 2),
            "cobertura_comun_region": round(self.cobertura_comun, 4),
            "antes": self.antes.metadatos(),
            "despues": self.despues.metadatos(),
        }


def polarizaciones_comunes(a: Escena, b: Escena) -> tuple[str, ...]:
    return tuple(p for p in a.polarizaciones if p in b.polarizaciones)


def geometria_compatible(a: Escena, b: Escena) -> bool:
    """Misma órbita relativa y misma dirección: el radar mira el terreno igual."""
    return a.orbita_relativa == b.orbita_relativa and a.direccion == b.direccion


def cobertura_comun(a: Escena, b: Escena, region: Region) -> float:
    zona = region.poligono
    return float(a.huella.intersection(b.huella).intersection(zona).area / zona.area) if zona.area else 0.0


def _evaluar(a: Escena, b: Escena, region: Region, evento: date | None) -> ParEscenas | None:
    if not geometria_compatible(a, b):
        return None
    comunes = polarizaciones_comunes(a, b)
    if not comunes:
        return None
    dias = (b.inicio - a.inicio).total_seconds() / 86_400
    if dias < 0.5:                          # misma pasada o mismo día: no es un par temporal
        return None
    comun = cobertura_comun(a, b, region)
    misma = a.plataforma == b.plataforma

    motivos = [f"Misma órbita relativa ({a.orbita_relativa}) y dirección ({a.direccion_es.lower()})",
               f"Polarizaciones en común: {', '.join(comunes)}",
               f"Ambas cubren el {comun:.0%} de la región"]
    avisos = []
    puntos = 60.0 * comun
    if misma:
        puntos += 15
        motivos.append(f"Mismo satélite ({a.plataforma})")
    else:
        avisos.append(f"Satélites distintos ({a.plataforma} y {b.plataforma}): puede haber pequeñas diferencias de calibración.")
    puntos += 5 * min(len(comunes), 2)
    puntos += 15 * max(0.0, 1 - max(dias - CICLO_DIAS, 0) / 60)     # cuanto más cerca en el tiempo, mejor
    motivos.append(f"{dias:.0f} días entre escenas")
    if dias > 36:
        avisos.append(f"Hay {dias:.0f} días entre escenas: pueden acumularse cambios ajenos al evento (vegetación, cultivos).")
    if comun < 0.999:
        avisos.append(f"El par no cubre toda la región (cubre el {comun:.0%}).")
    for escena in (a, b):
        if escena.otras_versiones:
            avisos.append(
                f"ASF tiene otra versión de la escena del {escena.inicio:%Y-%m-%d}: "
                f"{', '.join(escena.otras_versiones)}. Usa la misma que se procese en HyP3."
            )
    if evento is not None:
        antes_ok, despues_ok = a.inicio.date() < evento, b.inicio.date() >= evento
        if antes_ok and despues_ok:
            puntos += 10
            motivos.append(f"Encierra la fecha de interés ({evento:%Y-%m-%d})")
            puntos -= min((b.inicio.date() - evento).days, 30) / 6
        else:
            puntos -= 40
            avisos.append(f"No encierra la fecha de interés ({evento:%Y-%m-%d}).")
    return ParEscenas(a, b, dias, comunes, comun, misma, round(puntos, 2), tuple(motivos), tuple(avisos))


def emparejar(
    escenas: list[Escena],
    region: Region,
    fecha_evento=None,
    min_cobertura: float = 0.5,
    max_pares: int = 50,
) -> list[ParEscenas]:
    """Pares antes/después compatibles, del mejor al peor.

    Compatibles: misma órbita relativa y dirección, al menos una polarización en
    común, fechas distintas y cobertura conjunta de la región ≥ `min_cobertura`.
    Se priorizan el mismo satélite, la mayor cobertura y la cercanía temporal.
    Solo el primero queda marcado como recomendado, y ninguno como validado.
    """
    evento = _a_dia(fecha_evento, "La fecha de interés") if fecha_evento else None
    ordenadas = sorted(escenas, key=lambda e: (e.inicio, e.nombre))
    pares = []
    for i, a in enumerate(ordenadas):
        for b in ordenadas[i + 1:]:
            par = _evaluar(a, b, region, evento)
            if par is not None and par.cobertura_comun >= min_cobertura:
                pares.append(par)
    pares.sort(key=lambda p: (-p.puntuacion, p.dias, p.antes.inicio, p.antes.nombre))
    pares = pares[:max_pares]
    if pares:
        primero = pares[0]
        pares[0] = replace(primero, recomendado=True)
    return pares


# ---------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------

@dataclass
class ResultadoBusqueda:
    region: Region
    inicio: date
    fin: date
    escenas: list[Escena]
    pares: list[ParEscenas]
    descartes: dict[str, int]
    duplicados: int
    recibidos: int
    versiones: int                         # adquisiciones que ASF publica con más de un identificador
    truncado: bool                         # ASF devolvió el máximo pedido: puede haber más
    url: str                               # consulta exacta que se hizo

    @property
    def recomendado(self) -> ParEscenas | None:
        return self.pares[0] if self.pares else None


def buscar(
    oeste, sur, este, norte, inicio, fin,
    fecha_evento=None,
    min_cobertura: float = 0.5,
    max_resultados: int = MAX_RESULTADOS,
    abrir: Callable | None = None,
    hoy: date | None = None,
) -> ResultadoBusqueda:
    """Valida, consulta ASF, filtra y empareja. Lanza ErrorBusqueda (o sus
    subclases ErrorConexion / ErrorServicio) con un mensaje legible."""
    region = validar_region(oeste, sur, este, norte)
    inicio, fin = validar_fechas(inicio, fin, hoy)
    if fecha_evento:
        evento = _a_dia(fecha_evento, "La fecha de interés")
        if not inicio <= evento <= fin + timedelta(days=1):
            raise ErrorBusqueda("La fecha de interés debe estar dentro del período de búsqueda.")
    parametros = construir_consulta(region, inicio, fin, max_resultados)
    filtrado = interpretar_respuesta(consultar_asf(parametros, abrir=abrir), region)
    return ResultadoBusqueda(
        region=region, inicio=inicio, fin=fin, escenas=filtrado.escenas,
        pares=emparejar(filtrado.escenas, region, fecha_evento, min_cobertura),
        descartes=filtrado.descartes, duplicados=filtrado.duplicados, recibidos=filtrado.recibidos,
        versiones=filtrado.versiones, truncado=filtrado.recibidos >= max_resultados, url=url_consulta(parametros),
    )


# ---------------------------------------------------------------------------
# Presentación (tablas sin formato de interfaz)
# ---------------------------------------------------------------------------

def filas_escenas(escenas: list[Escena]) -> list[dict]:
    return [{
        "Fecha (UTC)": f"{e.inicio:%Y-%m-%d %H:%M}",
        "Satélite": e.plataforma,
        "Órbita rel.": e.orbita_relativa,
        "Dirección": e.direccion_es,
        "Modo": e.modo,
        "Polarizaciones": "+".join(e.polarizaciones),
        "Cubre la región": round(100 * e.cobertura),
        "Escena": e.nombre,
        "Otras versiones": len(e.otras_versiones),
        "ASF": e.enlace_vertex,
    } for e in escenas]


def filas_pares(pares: list[ParEscenas]) -> list[dict]:
    return [{
        "Estado": p.estado,
        "Antes": f"{p.antes.inicio:%Y-%m-%d}",
        "Después": f"{p.despues.inicio:%Y-%m-%d}",
        "Días": round(p.dias),
        "Satélites": p.antes.plataforma if p.misma_plataforma else f"{p.antes.plataforma} / {p.despues.plataforma}",
        "Órbita rel.": p.antes.orbita_relativa,
        "Dirección": p.antes.direccion_es,
        "Polarizaciones": "+".join(p.polarizaciones_comunes),
        "Cobertura común": round(100 * p.cobertura_comun),
        "Puntuación": p.puntuacion,
        "ASF": p.enlace_vertex,
    } for p in pares]
