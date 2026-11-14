"""Catálogo NISAR L2 GCOV (banda L): búsqueda de solo metadatos y candidatos a par.

Proveedor SEPARADO del de Sentinel-1 (banda C, `utils/buscador_sar.py`). Nada
de aquí se mezcla con escenas Sentinel-1 ni etiqueta HH/HV como VV/VH.

Fuentes (comprobadas el 13-nov-2026):
- Colecciones por madurez: `asf_search` (ASF), `CMR/datasets.py`. VALIDATED =
  `NISAR_L2_GCOV_V1`; PROVISIONAL y BETA llevan el sufijo en el nombre.
- Consulta: el CMR de NASA (`cmr.earthdata.nasa.gov`), como hace `asf_search`;
  rutas UMM-G de cada campo según `asf_search/Products/NISARProduct.py`.
- Nombre de granule: convención de ISCE3
  (`nisar/products/writers/BaseWriterSingleInput.py`) y del NISAR Cookbook de
  ASF (`HDF5_intro.md`):
  NISAR_IL_PT_PROD_CYL_REL_P_FRM_MODE_POLE_S_Inicio_Fin_CRID_A_C_LOC_CTR,
  con S = A (un solo modo) o M (modos de adquisición mixtos), A = exactitud
  de órbita y apuntamiento, C = F (frame completo) o P (parcial).
- Comprobado con el catálogo real el 13-nov-2026 (GitHub Actions): 11 GCOV
  VALIDATED sobre Chigorodó, con productos S=M y C=P entre ellos.
- VALIDATED cubre adquisiciones desde el 21-oct-2026 (nisar-docs.asf.alaska.edu).

Consultar el catálogo no requiere credenciales ni descarga nada. Un par que
sale de aquí es siempre «CANDIDATO NO VALIDADO»: solo los metadatos del
catálogo lo respaldan hasta inspeccionar los HDF5.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from utils.buscador_sar import ErrorConexion, ErrorServicio, Region, validar_fechas, validar_region

URL_CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
PROVEEDOR = "ASF"
AGENTE = "VISOR-SpaceApps-2026 (catalogo NISAR de solo lectura)"
TIEMPO_ESPERA_S = 30
MAX_RESULTADOS = 200
COLECCIONES = {
    "VALIDATED": "NISAR_L2_GCOV_V1",
    "PROVISIONAL": "NISAR_L2_GCOV_PROVISIONAL_V1",
    "BETA": "NISAR_L2_GCOV_BETA_V1",
}
INICIO_VALIDATED = date(2026, 10, 21)
ESTADO_PAR = "CANDIDATO NO VALIDADO"
SENSOR = "NISAR"
BANDA = "L"

# POLE: dos letras por banda (primaria A, secundaria B). ISCE3, BaseWriterSingleInput.
CODIGOS_POL = {
    "SH": ("HH",), "SV": ("VV",), "DH": ("HH", "HV"), "DV": ("VV", "VH"),
    "CL": ("LH", "LV"), "CR": ("RH", "RV"), "QP": ("HH", "HV", "VV", "VH"), "NA": (),
}
_NOMBRE = re.compile(
    r"NISAR_(?P<nivel>L2)_(?P<configuracion>[A-Z]{2})_(?P<producto>GCOV)_(?P<ciclo>\d{3})_"
    r"(?P<track>\d{3})_(?P<direccion>[AD])_(?P<frame>\d{3})_(?P<modo_a>\d{2})(?P<modo_b>\d{2})_"
    r"(?P<pol_a>[A-Z]{2})(?P<pol_b>[A-Z]{2})_(?P<fuente>[AM])_(?P<inicio>\d{8}T\d{6})_(?P<fin>\d{8}T\d{6})_"
    r"(?P<crid>[A-Z]\d{5})_(?P<a>[A-Z])_(?P<c>[A-Z])_(?P<loc>[A-Z])_(?P<contador>\d{3})"
)


@dataclass(frozen=True)
class NombreGCOV:
    granule: str
    configuracion: str          # PR = producción, UR = respuesta urgente
    ciclo: int
    track: int
    direccion: str              # ASCENDING / DESCENDING
    frame: int
    modo_a: str                 # ancho de banda de rango en MHz (00 = sin banda)
    modo_b: str
    pol_a: tuple[str, ...]
    pol_b: tuple[str, ...]
    inicio: datetime
    fin: datetime
    crid: str
    contador: int
    fuente_datos: str = "A"     # A = un solo modo de adquisición; M = modos mixtos
    exactitud: str = ""         # indicador de exactitud de órbita y apuntamiento
    cobertura: str = ""         # F = frame completo; P = parcial

    @property
    def clave_adquisicion(self) -> tuple:
        """Misma toma, distinto procesamiento (CRID o contador)."""
        return (self.track, self.direccion, self.frame, self.modo_a, self.modo_b,
                self.pol_a, self.pol_b, self.fuente_datos, self.inicio)

    @property
    def geometria(self) -> tuple:
        """Lo que debe coincidir para que dos fechas se puedan comparar."""
        return (self.track, self.direccion, self.frame, self.modo_a, self.modo_b,
                self.pol_a, self.pol_b, self.fuente_datos, self.configuracion)


def _utc(texto: str) -> datetime:
    return datetime.strptime(texto, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)


def leer_nombre(granule: str) -> NombreGCOV | None:
    """Interpreta un nombre de granule GCOV; None si no sigue la convención."""
    m = _NOMBRE.search(granule or "")
    if not m or m["pol_a"] not in CODIGOS_POL or m["pol_b"] not in CODIGOS_POL:
        return None
    return NombreGCOV(
        granule=m.group(0), configuracion=m["configuracion"], ciclo=int(m["ciclo"]), track=int(m["track"]),
        direccion="ASCENDING" if m["direccion"] == "A" else "DESCENDING", frame=int(m["frame"]),
        modo_a=m["modo_a"], modo_b=m["modo_b"], pol_a=CODIGOS_POL[m["pol_a"]], pol_b=CODIGOS_POL[m["pol_b"]],
        inicio=_utc(m["inicio"]), fin=_utc(m["fin"]), crid=m["crid"], contador=int(m["contador"]),
        fuente_datos=m["fuente"], exactitud=m["a"], cobertura=m["c"],
    )


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------

def construir_consulta(region: Region, inicio: date, fin: date, madurez: str = "VALIDATED",
                       max_resultados: int = MAX_RESULTADOS) -> list[tuple[str, str]]:
    """Parámetros del CMR (lista: el CMR usa claves repetidas)."""
    madurez = madurez.upper()
    if madurez not in COLECCIONES:
        raise ErrorServicio(f"Madurez '{madurez}' no reconocida. Opciones: {', '.join(COLECCIONES)}.")
    if not 1 <= int(max_resultados) <= 2000:
        raise ErrorServicio("El número de resultados debe estar entre 1 y 2000.")
    o, s, e, n = region.limites
    return [
        ("short_name", COLECCIONES[madurez]),
        ("provider", PROVEEDOR),
        ("bounding_box", f"{o:.6f},{s:.6f},{e:.6f},{n:.6f}"),
        ("temporal", f"{inicio:%Y-%m-%d}T00:00:00Z,{fin:%Y-%m-%d}T23:59:59Z"),
        ("page_size", str(int(max_resultados))),
        ("sort_key[]", "start_date"),
    ]


def url_consulta(parametros: list[tuple[str, str]]) -> str:
    return f"{URL_CMR}?{urllib.parse.urlencode(parametros)}"


def consultar_cmr(parametros: list[tuple[str, str]], tiempo_espera: float = TIEMPO_ESPERA_S,
                  abrir: Callable | None = None) -> dict:
    """GET sin autenticación al CMR. `abrir` sustituye la red en las pruebas."""
    abrir = abrir or urllib.request.urlopen
    peticion = urllib.request.Request(url_consulta(parametros),
                                      headers={"User-Agent": AGENTE, "Accept": "application/json"})
    try:
        with abrir(peticion, timeout=tiempo_espera) as respuesta:
            cuerpo = respuesta.read()
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            raise ErrorConexion(f"El catálogo CMR no está disponible (HTTP {e.code}). Intenta más tarde.") from e
        raise ErrorServicio(f"El CMR rechazó la consulta (HTTP {e.code}).") from e
    except TimeoutError as e:
        raise ErrorConexion("El catálogo tardó demasiado en responder. Reduce la región o el período.") from e
    except (urllib.error.URLError, OSError) as e:
        if isinstance(getattr(e, "reason", None), TimeoutError):
            raise ErrorConexion("El catálogo tardó demasiado en responder. Reduce la región o el período.") from e
        raise ErrorConexion("No se pudo conectar con el catálogo de NASA (CMR). Revisa la conexión.") from e
    try:
        datos = json.loads(cuerpo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ErrorServicio("El catálogo devolvió una respuesta que no es JSON.") from e
    if isinstance(datos, dict) and datos.get("errors"):
        raise ErrorServicio(f"El catálogo informó un error: {'; '.join(map(str, datos['errors']))[:300]}")
    if not isinstance(datos, dict) or not isinstance(datos.get("items"), list):
        raise ErrorServicio("La respuesta del catálogo no tiene el formato esperado (UMM-G con 'items').")
    return datos


# ---------------------------------------------------------------------------
# Interpretación
# ---------------------------------------------------------------------------

@dataclass
class CandidatoGCOV:
    nombre: NombreGCOV
    madurez: str
    coleccion: str
    huella: BaseGeometry | None
    cobertura: float                        # fracción del AOI cubierta por la huella
    tamano_bytes: int | None
    url_h5: str | None
    cobertura_frame: str | None = None      # FULL / PARTIAL según el catálogo
    otras_versiones: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def granule(self) -> str:
        return self.nombre.granule

    def resumen(self) -> dict:
        n = self.nombre
        return {
            "granule": n.granule, "sensor": SENSOR, "banda": BANDA, "madurez": self.madurez,
            "track": n.track, "frame": n.frame, "direccion": n.direccion, "ciclo": n.ciclo,
            "inicio": n.inicio.isoformat(), "fin": n.fin.isoformat(), "crid": n.crid, "contador": n.contador,
            "frecuencia_A": {"polarizaciones": list(n.pol_a), "ancho_banda_MHz": n.modo_a},
            "frecuencia_B": {"polarizaciones": list(n.pol_b), "ancho_banda_MHz": n.modo_b},
            "modos_de_adquisicion": "mixtos" if n.fuente_datos == "M" else "uno solo",
            "frame_nombre": {"cobertura": "parcial" if n.cobertura == "P" else "completa" if n.cobertura == "F" else n.cobertura,
                      "exactitud_orbita": n.exactitud},
            "cobertura_aoi": round(self.cobertura, 4), "cobertura_frame": self.cobertura_frame,
            "tamano_bytes": self.tamano_bytes, "url_h5": self.url_h5,
            "otras_versiones": self.otras_versiones, "avisos": self.avisos,
        }


def _atributo(umm: dict, nombre: str):
    for a in umm.get("AdditionalAttributes") or []:
        if a.get("Name") == nombre:
            valores = a.get("Values") or []
            return valores[0] if valores else None
    return None


def _huella(umm: dict) -> BaseGeometry | None:
    try:
        poligonos = umm["SpatialExtent"]["HorizontalSpatialDomain"]["Geometry"]["GPolygons"]
        puntos = poligonos[0]["Boundary"]["Points"]
        geo = Polygon([(float(p["Longitude"]), float(p["Latitude"])) for p in puntos])
        return geo if geo.is_valid and not geo.is_empty else geo.buffer(0)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _archivo_h5(umm: dict) -> tuple[str | None, int | None]:
    url = next((u.get("URL") for u in umm.get("RelatedUrls") or []
                if u.get("Type") == "GET DATA" and str(u.get("URL", "")).endswith(".h5")
                and "QA_STATS" not in str(u.get("URL", ""))), None)
    tamano = None
    for a in (umm.get("DataGranule") or {}).get("ArchiveAndDistributionInformation") or []:
        nombre = str(a.get("Name", ""))
        if nombre.endswith(".h5") and "QA_STATS" not in nombre and a.get("SizeInBytes") is not None:
            tamano = int(a["SizeInBytes"])
    return url, tamano


def _candidato(item: dict, region: Region, madurez: str) -> CandidatoGCOV | str:
    """Un candidato, o el motivo por el que se descarta (texto)."""
    umm = item.get("umm") or {}
    identificador = umm.get("GranuleUR") or "(sin nombre)"
    productor = next((i.get("Identifier") for i in (umm.get("DataGranule") or {}).get("Identifiers") or []
                      if i.get("IdentifierType") == "ProducerGranuleId"), None)
    nombre = leer_nombre(productor or identificador)
    if nombre is None:
        return f"{identificador}: el nombre no sigue la convención NISAR L2 GCOV."
    avisos = []
    # Los metadatos del catálogo deben coincidir con el nombre; si no, no se usa.
    for atributo, esperado in (("TRACK_NUMBER", nombre.track), ("FRAME_NUMBER", nombre.frame)):
        valor = _atributo(umm, atributo)
        if valor is not None and str(valor).strip().lstrip("0") != str(esperado):
            return f"{nombre.granule}: {atributo}={valor} no coincide con el nombre ({esperado})."
    direccion = _atributo(umm, "ASCENDING_DESCENDING")
    if direccion and str(direccion).upper() != nombre.direccion:
        return f"{nombre.granule}: dirección {direccion} no coincide con el nombre ({nombre.direccion})."
    crid = next((i.get("Identifier") for i in (umm.get("DataGranule") or {}).get("Identifiers") or []
                 if i.get("IdentifierType") == "CRID"), None)
    if crid and crid != nombre.crid:
        return f"{nombre.granule}: CRID {crid} del catálogo no coincide con el nombre ({nombre.crid})."
    tipo = _atributo(umm, "PRODUCT_TYPE")
    if tipo and str(tipo).upper() != "GCOV":
        return f"{nombre.granule}: el catálogo lo declara {tipo}, no GCOV."

    huella = _huella(umm)
    if huella is None:
        avisos.append("El catálogo no trae huella: no se pudo calcular la cobertura del área.")
        cobertura = 0.0
    else:
        zona = region.poligono
        cobertura = float(huella.intersection(zona).area / zona.area) if zona.area else 0.0
        if cobertura <= 0:
            return f"{nombre.granule}: su huella no toca el área de interés."
    url, tamano = _archivo_h5(umm)
    if url is None:
        avisos.append("El catálogo no trae un enlace .h5 de descarga.")
    if nombre.fuente_datos == "M":
        avisos.append("Producto de modos de adquisición MIXTOS (S=M): el modo cambia dentro del frame.")
    if nombre.cobertura == "P":
        avisos.append("Frame de cobertura PARCIAL (C=P).")
    if madurez == "VALIDATED" and nombre.inicio.date() < INICIO_VALIDATED:
        avisos.append("Fecha anterior al inicio de VALIDATED (21-oct-2026): revisa la madurez.")
    return CandidatoGCOV(nombre=nombre, madurez=madurez, coleccion=COLECCIONES[madurez], huella=huella,
                         cobertura=cobertura, tamano_bytes=tamano, url_h5=url,
                         cobertura_frame=_atributo(umm, "FULL_FRAME"), avisos=avisos)


def _orden_version(c: CandidatoGCOV) -> tuple:
    return (c.nombre.crid, c.nombre.contador)


def interpretar(datos: dict, region: Region, madurez: str = "VALIDATED") -> tuple[list[CandidatoGCOV], list[str]]:
    """Candidatos (una sola versión por toma: la de CRID y contador mayores) y descartes."""
    candidatos, descartes = [], []
    for item in datos.get("items") or []:
        r = _candidato(item, region, madurez.upper())
        (descartes if isinstance(r, str) else candidatos).append(r)
    por_toma: dict[tuple, list[CandidatoGCOV]] = {}
    for c in candidatos:
        por_toma.setdefault(c.nombre.clave_adquisicion, []).append(c)
    elegidos = []
    for versiones in por_toma.values():
        versiones.sort(key=_orden_version, reverse=True)
        mejor = versiones[0]
        mejor.otras_versiones = [v.granule for v in versiones[1:]]
        if mejor.otras_versiones:
            mejor.avisos.append(f"Hay {len(mejor.otras_versiones)} versión(es) más de esta toma; se usa la de "
                                f"CRID {mejor.nombre.crid} y contador {mejor.nombre.contador:03d}.")
        elegidos.append(mejor)
    elegidos.sort(key=lambda c: c.nombre.inicio)
    return elegidos, descartes


# ---------------------------------------------------------------------------
# Candidatos a par temporal
# ---------------------------------------------------------------------------

@dataclass
class ParNISAR:
    antes: CandidatoGCOV
    despues: CandidatoGCOV
    dias: float
    cobertura_comun: float
    polarizaciones_A: tuple[str, ...]
    motivos: list[str]
    avisos: list[str]
    estado: str = ESTADO_PAR

    def resumen(self) -> dict:
        return {"estado": self.estado, "antes": self.antes.granule, "despues": self.despues.granule,
                "dias": round(self.dias, 2), "cobertura_comun": round(self.cobertura_comun, 4),
                "polarizaciones_frecuencia_A": list(self.polarizaciones_A),
                "motivos": self.motivos, "avisos": self.avisos}


def evaluar_par(a: CandidatoGCOV, b: CandidatoGCOV, region: Region) -> ParNISAR | list[str]:
    """Par candidato, o la lista de motivos que lo bloquean."""
    na, nb = a.nombre, b.nombre
    bloqueos = []
    if na.track != nb.track:
        bloqueos.append(f"track distinto ({na.track} y {nb.track})")
    if na.direccion != nb.direccion:
        bloqueos.append(f"dirección distinta ({na.direccion} y {nb.direccion})")
    if na.frame != nb.frame:
        bloqueos.append(f"frame distinto ({na.frame} y {nb.frame})")
    if (na.modo_a, na.modo_b) != (nb.modo_a, nb.modo_b):
        bloqueos.append(f"modo de ancho de banda distinto ({na.modo_a}{na.modo_b} y {nb.modo_a}{nb.modo_b})")
    if (na.pol_a, na.pol_b) != (nb.pol_a, nb.pol_b):
        bloqueos.append("polarizaciones distintas")
    if na.fuente_datos != nb.fuente_datos:
        bloqueos.append("uno es de un solo modo de adquisición y el otro de modos mixtos")
    if na.crid != nb.crid:
        bloqueos.append(f"CRID distinto ({na.crid} y {nb.crid}): versiones de procesamiento diferentes")
    if na.configuracion != nb.configuracion:
        bloqueos.append(f"configuración distinta ({na.configuracion} y {nb.configuracion})")
    if a.madurez != b.madurez:
        bloqueos.append(f"madurez distinta ({a.madurez} y {b.madurez})")
    dias = (nb.inicio - na.inicio).total_seconds() / 86_400
    if dias < 0.5:
        bloqueos.append("misma toma o mismo día: no es un par temporal")
    comun = 0.0
    if a.huella is not None and b.huella is not None:
        zona = region.poligono
        comun = float(a.huella.intersection(b.huella).intersection(zona).area / zona.area) if zona.area else 0.0
        if comun <= 0:
            bloqueos.append("sus huellas no comparten área dentro de la región")
    else:
        bloqueos.append("falta la huella de alguna escena: no se puede comprobar la superposición")
    if bloqueos:
        return bloqueos
    avisos = ["Par CANDIDATO NO VALIDADO: solo lo respaldan los metadatos del catálogo. Hay que inspeccionar "
              "los dos HDF5 (cuadrícula, CRS, máscara) antes de calcular el cambio."]
    if comun < 0.999:
        avisos.append(f"El par no cubre toda la región (cubre el {comun:.0%}).")
    if dias > 36:
        avisos.append(f"{dias:.0f} días entre fechas: pueden acumularse cambios ajenos al evento.")
    if na.fuente_datos == "M":
        avisos.append("Ambos productos son de modos de adquisición mixtos: comprobar en los HDF5 que el modo "
                      "es el mismo sobre el área antes de comparar.")
    if "P" in (na.cobertura, nb.cobertura):
        avisos.append("Algún frame es de cobertura parcial: la zona común puede ser menor que la huella.")
    motivos = [f"Mismo track {na.track}, frame {na.frame} y dirección {na.direccion.lower()}",
               f"Mismo modo ({na.modo_a}{na.modo_b} MHz), polarizaciones y CRID {na.crid}",
               f"{dias:.0f} días entre fechas"]
    return ParNISAR(a, b, dias, comun, na.pol_a, motivos, avisos)


@dataclass
class ResultadoNISAR:
    region: Region
    inicio: date
    fin: date
    madurez: str
    url: str
    total_catalogo: int
    candidatos: list[CandidatoGCOV]
    descartes: list[str]
    pares: list[ParNISAR]
    bloqueos: list[str]               # por qué no hay pares (si no los hay)
    avisos: list[str]


def emparejar(candidatos: list[CandidatoGCOV], region: Region) -> tuple[list[ParNISAR], list[str]]:
    pares, bloqueos = [], []
    for i, a in enumerate(candidatos):
        for b in candidatos[i + 1:]:
            r = evaluar_par(a, b, region)
            if isinstance(r, ParNISAR):
                pares.append(r)
            else:
                bloqueos.append(f"{a.nombre.inicio:%Y-%m-%d} T{a.nombre.track} F{a.nombre.frame} ↔ "
                                f"{b.nombre.inicio:%Y-%m-%d} T{b.nombre.track} F{b.nombre.frame}: {'; '.join(r)}")
    pares.sort(key=lambda p: (-p.cobertura_comun, p.dias))
    return pares, ([] if pares else bloqueos)


def buscar(oeste, sur, este, norte, inicio, fin, madurez: str = "VALIDATED",
           max_resultados: int = MAX_RESULTADOS, abrir: Callable | None = None,
           hoy: date | None = None) -> ResultadoNISAR:
    """Consulta el catálogo y propone candidatos. Solo metadatos; nada se descarga."""
    region = validar_region(oeste, sur, este, norte)
    d0, d1 = validar_fechas(inicio, fin, hoy=hoy)
    parametros = construir_consulta(region, d0, d1, madurez, max_resultados)
    datos = consultar_cmr(parametros, abrir=abrir)
    candidatos, descartes = interpretar(datos, region, madurez)
    pares, bloqueos = emparejar(candidatos, region)
    avisos = []
    if madurez.upper() == "VALIDATED" and d0 < INICIO_VALIDATED:
        avisos.append("VALIDATED solo cubre adquisiciones desde el 21-oct-2026; antes de esa fecha no habrá resultados.")
    if len(datos["items"]) >= int(max_resultados):
        avisos.append("Se alcanzó el máximo de resultados: puede haber más escenas. Reduce el período.")
    if not candidatos:
        avisos.append("El catálogo no devolvió escenas GCOV utilizables para esta región y período.")
    elif not pares:
        avisos.append("No hay ningún par compatible: se puede inspeccionar una escena única, sin cálculo de cambio.")
    return ResultadoNISAR(region, d0, d1, madurez.upper(), url_consulta(parametros), len(datos["items"]),
                          candidatos, descartes, pares, bloqueos, avisos)


def registro_json(r: ResultadoNISAR) -> dict:
    """Registro auditable de la búsqueda (para guardar junto a los datos)."""
    return {
        "consulta": {"url": r.url, "madurez": r.madurez, "coleccion": COLECCIONES[r.madurez],
                     "region": list(r.region.limites), "inicio": r.inicio.isoformat(), "fin": r.fin.isoformat(),
                     "fecha_consulta_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "total_catalogo": r.total_catalogo,
        "candidatos": [c.resumen() for c in r.candidatos],
        "descartes": r.descartes,
        "pares": [p.resumen() for p in r.pares],
        "bloqueos": r.bloqueos,
        "avisos": r.avisos,
        "nota": "Solo metadatos. Ningún par está validado y no se descargó nada.",
    }
