"""Motor de análisis temporal SAR de V.I.S.O.R.

Compara dos productos RTC de Sentinel-1 (ASF HyP3) de fechas distintas y
produce la diferencia de retrodispersión en dB y una máscara de cambios
significativos. No depende de Streamlit: se usa desde la página de análisis,
desde `scripts/analizar_sar.py` o desde cualquier otro código.

Flujo (`analizar_par`):
    1. describir_escena   valida cada GeoTIFF (CRS, transformación, tamaño, NoData, polarización)
    2. validar_par        misma polarización/escala, fechas distintas y en orden
    3. cuadricula_comun   cuadrícula de la imagen anterior, recortada a la zona común y al AOI
    4. leer_en_cuadricula lectura directa si ya coincide; si no, remuestreo a esa cuadrícula
    5. a_potencia + filtrar_speckle (media móvil en potencia)
    6. potencia_a_db      10·log10(potencia); nulos y no positivos quedan sin dato
    7. diferencia_db      posterior − anterior, solo donde ambas fechas tienen dato
    8. mascara_cambios    umbrales configurables
    9. exportar           GeoTIFF georreferenciados + informe JSON de procedencia

IMPORTANTE: el resultado describe cambios de la señal de radar. Una disminución
de retrodispersión NO es una inundación confirmada (ver LIMITACIONES).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.errors import RasterioError
from rasterio.transform import Affine, array_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds

from utils.procedencia import sha256_archivo

VERSION_MOTOR = "1.0"
NODATA_DB = -9999.0
NODATA_MASCARA = 255
_SUFIJOS_SALIDA = {f"{n}.{e}" for n in ("dif_db", "mascara", "antes_db", "despues_db") for e in ("tif", "json")} \
    | {"analisis.json"}
# Tope de píxeles de la cuadrícula de trabajo. Una escena RTC completa a 30 m
# supera los 60 millones: hay que recortar con un AOI.
MAX_PIXELES = 16_000_000

ESCALAS = ("power", "amplitude", "db")
POLARIZACIONES = ("VV", "VH", "HH", "HV", "RH", "RV")   # RH/RV: polarimetría compacta (NISAR)

# Clases de la máscara: (valor, etiqueta, color). Las etiquetas describen la
# señal medida, nunca un fenómeno confirmado.
SIN_CAMBIO, DISMINUCION, AUMENTO, BAJA_EN_AMBAS = 0, 1, 2, 3
CLASES_MASCARA: tuple[tuple[int, str, str | None], ...] = (
    (SIN_CAMBIO, "Sin cambio significativo", None),
    (DISMINUCION, "Disminución significativa de retrodispersión", "#00F0FF"),
    (AUMENTO, "Aumento significativo de retrodispersión", "#FF9F0A"),
    (BAJA_EN_AMBAS, "Retrodispersión baja en ambas fechas", "#7D7AFF"),
)

# Valores orientativos para marcar "baja en ambas fechas" (posible agua
# permanente, sombra o superficie lisa). Son heurísticos: ajustarlos por zona.
UMBRAL_OSCURO_SUGERIDO = {"VV": -18.0, "HH": -18.0, "VH": -24.0, "HV": -24.0}

ADVERTENCIA = (
    "Resultado exploratorio: muestra cambios de retrodispersión SAR entre dos fechas. "
    "No confirma inundaciones ni ningún otro fenómeno; requiere validación independiente."
)
LIMITACIONES: tuple[str, ...] = (
    "Una disminución de retrodispersión puede deberse a agua en superficie, pero también a "
    "cambios de humedad del suelo, cosechas, quemas, labores agrícolas o viento sobre el agua.",
    "Vegetación: bajo dosel denso o cultivos altos el agua puede no oscurecer la señal en banda C; "
    "la vegetación inundada puede incluso aumentarla (doble rebote).",
    "Humedad: lluvia reciente o suelo más seco o más húmedo cambia la retrodispersión sin que "
    "exista inundación.",
    "Relieve: en zonas de sombra y layover el radar no observa bien el terreno; los productos RTC "
    "corrigen la radiometría, no recuperan esas zonas.",
    "Speckle: el ruido propio del radar produce falsos cambios píxel a píxel; el filtro de media "
    "móvil lo reduce a costa de detalle espacial.",
    "Agua permanente: ríos, ciénagas y embalses son oscuros en ambas fechas y no aparecen como "
    "cambio; superficies lisas (pistas, vías) se comportan igual.",
    "Solo se comparan dos fechas: no hay referencia estacional ni se sabe qué ocurrió entre ellas.",
    "Los umbrales son configurables y no están calibrados para la zona.",
)
# Solo para NISAR (banda L). Sustituyen la línea de vegetación en banda C.
LIMITACIONES_BANDA_L: tuple[str, ...] = (
    "Banda L (NISAR): penetra más el dosel que la banda C; el agua bajo vegetación suele AUMENTAR la "
    "señal (doble rebote) y no disminuirla. Un cambio en banda L no se interpreta igual que en Sentinel-1.",
    "Umbrales EXPERIMENTALES para banda L: no se copian los de Sentinel-1 (VV −7,5 / VH −3 dB) y no "
    "están calibrados por canal ni por cobertura; deben evaluarse con datos de campo.",
    "El producto GCOV ya trae corrección radiométrica del terreno (RTC); no se vuelve a aplicar.",
    "Que el producto GCOV sea VALIDATED significa que el dato está calibrado, no que este mapa derivado "
    "esté validado.",
)
# Campos de NISAR que deben coincidir entre las dos fechas (etiquetas del recorte GCOV).
CAMPOS_GEOMETRIA_NISAR = ("TRACK", "FRAME", "DIRECCION", "FRECUENCIA", "TERMINO", "CRID")


class ErrorSAR(Exception):
    """Error legible: la escena o el par no se pueden analizar."""


# ---------------------------------------------------------------------------
# Escenas
# ---------------------------------------------------------------------------

# Nombre de un producto RTC de HyP3, por ejemplo:
#   S1C_IW_20260924T231502_DVP_RTC30_G_gpuned_1A2B_VV.tif
_NOMBRE_HYP3 = re.compile(
    r"(?P<plataforma>S1[A-D])_(?P<modo>[A-Z0-9]{2})_(?P<fecha>\d{8}T\d{6})_"
    r"(?P<pols>[DS][VH])(?P<orbita>[PRO])_RTC(?P<resolucion>\d+)_[A-Z]_"
    r"(?P<radiometria>[gs])(?P<escala>[pda])[a-z]{4}_(?P<id>[0-9A-F]{4})_"
    r"(?P<banda>VV|VH|HH|HV)(?=[._])"
)
_RADIOMETRIAS = {"g": "gamma0", "s": "sigma0"}
_ESCALAS_HYP3 = {"p": "power", "d": "db", "a": "amplitude"}


@dataclass
class EscenaRTC:
    ruta: Path
    polarizacion: str
    escala: str                       # "power", "amplitude" o "db"
    crs: CRS
    transform: Affine
    ancho: int
    alto: int
    nodata: float | None
    fecha: datetime | None = None
    plataforma: str | None = None
    radiometria: str | None = None
    es_hyp3: bool = False             # el nombre sigue la convención de HyP3 RTC
    avisos: list[str] = field(default_factory=list)
    sensor: str | None = None         # "Sentinel-1" (banda C) o "NISAR" (banda L); None = desconocido
    banda: str | None = None
    geometria: dict[str, str] = field(default_factory=dict)   # NISAR: track, frame, dirección, CRID…
    es_demo: bool = False             # etiqueta VISOR_DEMO=1 en el archivo de entrada

    @property
    def es_nisar(self) -> bool:
        return self.sensor == "NISAR"

    @property
    def limites(self) -> tuple[float, float, float, float]:
        """(oeste, sur, este, norte) en el CRS de la escena."""
        return array_bounds(self.alto, self.ancho, self.transform)

    @property
    def resolucion(self) -> tuple[float, float]:
        return abs(self.transform.a), abs(self.transform.e)

    def resumen(self) -> dict:
        return {
            "archivo": self.ruta.name,
            "fecha": self.fecha.isoformat() if self.fecha else None,
            "plataforma": self.plataforma,
            "polarizacion": self.polarizacion,
            "radiometria": self.radiometria,
            "escala": self.escala,
            "producto_hyp3_rtc": self.es_hyp3,
            "sensor": self.sensor,
            "banda": self.banda,
            **({"geometria_nisar": self.geometria} if self.geometria else {}),
            "demo": self.es_demo,
            "crs": self.crs.to_string(),
            "resolucion": list(self.resolucion),
            "dimensiones": [self.ancho, self.alto],
            "nodata": self.nodata,
            "bytes": self.ruta.stat().st_size,
        }


def _a_fecha(valor) -> datetime | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day)
    texto = str(valor).strip()
    for formato in ("%Y-%m-%dT%H:%M:%S", "%Y%m%dT%H%M%S", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    raise ErrorSAR(f"Fecha no reconocida: '{texto}'. Usa el formato AAAA-MM-DD.")


def describir_escena(
    ruta: str | Path,
    polarizacion: str | None = None,
    fecha=None,
    escala: str | None = None,
) -> EscenaRTC:
    """Abre un GeoTIFF RTC y valida que se pueda usar. Lo que no se deduce del
    nombre (convención HyP3) se puede indicar con los argumentos."""
    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorSAR(f"No se encontró el archivo `{ruta.name}`.")
    try:
        with rasterio.open(ruta) as src:
            crs, transform = src.crs, src.transform
            ancho, alto, nodata, bandas = src.width, src.height, src.nodata, src.count
            tipo = src.dtypes[0]
            etiquetas = {k.upper(): str(v) for k, v in src.tags().items()}
    except (RasterioError, OSError, ValueError) as e:
        raise ErrorSAR(f"`{ruta.name}` no es un GeoTIFF válido o está dañado.") from e

    if crs is None:
        raise ErrorSAR(f"`{ruta.name}` no tiene sistema de coordenadas (CRS).")
    if transform.is_identity or transform.a == 0 or transform.e == 0:
        raise ErrorSAR(f"`{ruta.name}` no tiene georreferenciación (transformación afín).")
    if transform.b != 0 or transform.d != 0:
        raise ErrorSAR(f"`{ruta.name}` tiene una cuadrícula rotada; no está soportada.")
    if ancho < 2 or alto < 2:
        raise ErrorSAR(f"`{ruta.name}` es demasiado pequeño ({ancho}×{alto} px).")

    avisos: list[str] = []
    if bandas > 1:
        avisos.append(f"{ruta.name}: tiene {bandas} bandas; se usa la banda 1.")
    if not np.issubdtype(np.dtype(tipo), np.floating):
        avisos.append(f"{ruta.name}: los valores son {tipo}, no de punto flotante; revisa que sea un RTC.")
    if nodata is None:
        avisos.append(f"{ruta.name}: no declara NoData; se descartan valores no finitos y no positivos.")

    nombre = _NOMBRE_HYP3.search(ruta.name)
    if nombre is None:
        avisos.append(f"{ruta.name}: el nombre no sigue la convención de HyP3 RTC; revisa los metadatos indicados.")

    pol = (polarizacion or (nombre and nombre["banda"]) or etiquetas.get("POLARIZACION") or "").upper()
    if pol not in POLARIZACIONES:
        raise ErrorSAR(
            f"No se pudo determinar la polarización de `{ruta.name}`. "
            f"Indícala ({', '.join(POLARIZACIONES)})."
        )
    if nombre and polarizacion and nombre["banda"] != pol:
        raise ErrorSAR(f"`{ruta.name}` es {nombre['banda']} según su nombre, pero se indicó {pol}.")

    esc = (escala or (nombre and _ESCALAS_HYP3[nombre["escala"]]) or etiquetas.get("ESCALA") or "").lower()
    if not esc:
        esc = "power"
        avisos.append(f"{ruta.name}: escala no indicada; se asume potencia (power).")
    if esc not in ESCALAS:
        raise ErrorSAR(f"Escala '{esc}' no reconocida. Opciones: {', '.join(ESCALAS)}.")

    sensor = "Sentinel-1" if nombre else (etiquetas.get("SENSOR") or None)
    banda = "C" if nombre else (etiquetas.get("BANDA") or None)
    if nombre and etiquetas.get("SENSOR") not in (None, "", "Sentinel-1"):
        raise ErrorSAR(f"`{ruta.name}` tiene nombre de Sentinel-1 pero declara SENSOR={etiquetas['SENSOR']}.")
    geometria = {k.lower(): etiquetas.get(k, "") for k in (*CAMPOS_GEOMETRIA_NISAR, "MADUREZ", "GRANULE", "MISION")} \
        if sensor == "NISAR" else {}
    return EscenaRTC(
        ruta=ruta, polarizacion=pol, escala=esc, crs=crs, transform=transform,
        ancho=ancho, alto=alto, nodata=nodata,
        fecha=_a_fecha(fecha or (nombre and nombre["fecha"]) or etiquetas.get("FECHA_ADQUISICION")),
        plataforma=nombre["plataforma"] if nombre else ("NISAR" if sensor == "NISAR" else None),
        radiometria=_RADIOMETRIAS[nombre["radiometria"]] if nombre else (etiquetas.get("RADIOMETRIA") or None),
        es_hyp3=nombre is not None, avisos=avisos, sensor=sensor, banda=banda, geometria=geometria,
        es_demo=etiquetas.get("VISOR_DEMO") == "1",
    )


def bloqueos_nisar(antes: EscenaRTC, despues: EscenaRTC) -> list[str]:
    """Motivos por los que dos recortes NISAR no son comparables (lista vacía = compatibles)."""
    motivos = []
    for campo in CAMPOS_GEOMETRIA_NISAR:
        a, d = antes.geometria.get(campo.lower(), ""), despues.geometria.get(campo.lower(), "")
        if not a or not d:
            motivos.append(f"falta {campo} en {antes.ruta.name if not a else despues.ruta.name}")
        elif a != d:
            motivos.append(f"{campo} distinto ({a} y {d})")
    ma, md = antes.geometria.get("madurez", ""), despues.geometria.get("madurez", "")
    if ma and md and "NO_COMPROBADA" not in (ma, md) and ma != md:
        motivos.append(f"madurez distinta ({ma} y {md})")
    return motivos


def validar_par(antes: EscenaRTC, despues: EscenaRTC) -> list[str]:
    """Comprueba que las dos escenas son comparables. Devuelve avisos; lanza
    ErrorSAR si compararlas no tendría sentido."""
    if antes.ruta.resolve() == despues.ruta.resolve():
        raise ErrorSAR("La imagen anterior y la posterior son el mismo archivo.")
    # Banda C (Sentinel-1) y banda L (NISAR) no son el mismo canal: nunca se comparan entre sí.
    if (antes.sensor != despues.sensor or antes.banda != despues.banda) and "NISAR" in (antes.sensor, despues.sensor):
        raise ErrorSAR(
            f"No se comparan sensores o bandas distintos: {antes.ruta.name} es "
            f"{antes.sensor or 'de sensor desconocido'} (banda {antes.banda or '?'}) y {despues.ruta.name} es "
            f"{despues.sensor or 'de sensor desconocido'} (banda {despues.banda or '?'})."
        )
    if antes.es_nisar:
        motivos = bloqueos_nisar(antes, despues)
        if motivos:
            raise ErrorSAR("Los dos recortes NISAR no son comparables: " + "; ".join(motivos) + ".")
    if antes.polarizacion != despues.polarizacion:
        raise ErrorSAR(
            f"Polarizaciones distintas ({antes.polarizacion} y {despues.polarizacion}): "
            "solo se comparan imágenes de la misma polarización."
        )
    if antes.escala != despues.escala:
        raise ErrorSAR(f"Escalas distintas ({antes.escala} y {despues.escala}).")
    if antes.radiometria and despues.radiometria and antes.radiometria != despues.radiometria:
        raise ErrorSAR(f"Radiometrías distintas ({antes.radiometria} y {despues.radiometria}).")

    avisos = [*antes.avisos, *despues.avisos]
    if antes.fecha and despues.fecha:
        if antes.fecha.date() == despues.fecha.date():
            raise ErrorSAR("Las dos imágenes son de la misma fecha; no hay cambio temporal que medir.")
        if antes.fecha > despues.fecha:
            raise ErrorSAR(
                f"El orden está invertido: la imagen 'anterior' ({antes.fecha:%Y-%m-%d}) es "
                f"posterior a la 'posterior' ({despues.fecha:%Y-%m-%d})."
            )
    else:
        avisos.append("No se conoce la fecha de alguna imagen: no se pudo comprobar el orden temporal.")
    if antes.plataforma and despues.plataforma and antes.plataforma != despues.plataforma:
        avisos.append(f"Satélites distintos ({antes.plataforma} y {despues.plataforma}).")
    if antes.crs != despues.crs:
        avisos.append(f"CRS distintos ({antes.crs.to_string()} y {despues.crs.to_string()}): la imagen posterior se reproyecta.")
    if not all(math.isclose(a, b, rel_tol=1e-6) for a, b in zip(antes.resolucion, despues.resolucion, strict=True)):
        avisos.append("Resoluciones distintas: la imagen posterior se remuestrea a la cuadrícula de la anterior.")
    return avisos


# ---------------------------------------------------------------------------
# Cuadrícula común y lectura alineada
# ---------------------------------------------------------------------------

@dataclass
class Cuadricula:
    crs: CRS
    transform: Affine
    ancho: int
    alto: int

    @property
    def limites(self) -> tuple[float, float, float, float]:
        return array_bounds(self.alto, self.ancho, self.transform)

    @property
    def limites_lonlat(self) -> tuple[float, float, float, float]:
        return transform_bounds(self.crs, "EPSG:4326", *self.limites, densify_pts=21)

    @property
    def area_pixel_ha(self) -> float | None:
        return area_pixel_ha(self.crs, self.transform)


def prefijo_libre(carpeta: Path, base: str) -> str:
    """`base`, o `base_r2`, `base_r3`… si ya hay archivos con ese prefijo."""
    carpeta = Path(carpeta)

    def ocupado(p: str) -> bool:
        return any(carpeta.glob(f"{p}.*")) or any(carpeta.glob(f"{p}_*"))
    if not ocupado(base):
        return base
    n = 2
    while ocupado(f"{base}_r{n}"):
        n += 1
    return f"{base}_r{n}"


def area_pixel_ha(crs: CRS | None, transform: Affine) -> float | None:
    """Área de un píxel en hectáreas. None si el CRS no es proyectado o sus
    unidades lineales no se conocen (no se inventan hectáreas). Las unidades
    distintas del metro (p. ej. pies) se convierten con su factor."""
    if crs is None or not crs.is_projected:
        return None
    try:
        _, factor = crs.linear_units_factor
    except Exception:  # noqa: BLE001 — CRS sin unidades lineales declaradas
        return None
    if not factor or not math.isfinite(factor):
        return None
    return abs(transform.a * transform.e) * factor * factor / 10_000.0


def _interseccion(a, b):
    oeste, sur, este, norte = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (oeste, sur, este, norte) if oeste < este and sur < norte else None


def cuadricula_comun(
    antes: EscenaRTC,
    despues: EscenaRTC,
    aoi: tuple[float, float, float, float] | None = None,
    max_pixeles: int = MAX_PIXELES,
) -> Cuadricula:
    """Cuadrícula de trabajo: la de la imagen anterior, limitada a la zona que
    cubren ambas imágenes y, si se indica, al AOI (oeste, sur, este, norte en
    grados lon/lat). Siempre queda ajustada a píxeles enteros de la anterior."""
    limites_despues = despues.limites
    if despues.crs != antes.crs:
        limites_despues = transform_bounds(despues.crs, antes.crs, *limites_despues, densify_pts=21)
    zona = _interseccion(antes.limites, limites_despues)
    if zona is None:
        raise ErrorSAR("Las dos imágenes no se superponen: no hay zona común que comparar.")

    if aoi is not None:
        oeste, sur, este, norte = (float(v) for v in aoi)
        if not (-180 <= oeste < este <= 180 and -90 <= sur < norte <= 90):
            raise ErrorSAR("AOI inválido: debe ser (oeste, sur, este, norte) en grados, con oeste < este y sur < norte.")
        zona = _interseccion(zona, transform_bounds("EPSG:4326", antes.crs, oeste, sur, este, norte, densify_pts=21))
        if zona is None:
            raise ErrorSAR("El AOI queda fuera de la zona cubierta por las dos imágenes.")

    # De coordenadas a índices de píxel de la imagen anterior (hacia afuera, sin salirse).
    t = antes.transform                      # sin rotación (validado en describir_escena)
    c0, c1 = (zona[0] - t.c) / t.a, (zona[2] - t.c) / t.a
    f0, f1 = (zona[3] - t.f) / t.e, (zona[1] - t.f) / t.e
    col0, col1 = sorted((c0, c1))
    fil0, fil1 = sorted((f0, f1))
    eps = 1e-6
    col0, fil0 = max(0, math.floor(col0 + eps)), max(0, math.floor(fil0 + eps))
    col1, fil1 = min(antes.ancho, math.ceil(col1 - eps)), min(antes.alto, math.ceil(fil1 - eps))
    ancho, alto = col1 - col0, fil1 - fil0
    if ancho < 2 or alto < 2:
        raise ErrorSAR("La zona común es menor que dos píxeles; amplía el AOI.")
    if ancho * alto > max_pixeles:
        raise ErrorSAR(
            f"La zona a analizar tiene {ancho}×{alto} px ({ancho * alto / 1e6:.1f} millones), más que el "
            f"máximo de {max_pixeles / 1e6:.0f} millones. Indica un AOI más pequeño."
        )
    origen = Affine(t.a, 0.0, t.c + col0 * t.a, 0.0, t.e, t.f + fil0 * t.e)
    return Cuadricula(antes.crs, origen, ancho, alto)


def _desfase_entero(escena: EscenaRTC, cuad: Cuadricula) -> tuple[int, int] | None:
    """(columna, fila) de la esquina de la cuadrícula dentro de la escena, si
    ambas comparten CRS, tamaño de píxel y están desplazadas un número entero
    de píxeles. None si hace falta remuestrear."""
    t, g = escena.transform, cuad.transform
    if escena.crs != cuad.crs:
        return None
    if not (math.isclose(t.a, g.a, rel_tol=1e-9) and math.isclose(t.e, g.e, rel_tol=1e-9)):
        return None
    col, fil = (g.c - t.c) / t.a, (g.f - t.f) / t.e
    if abs(col - round(col)) > 1e-4 or abs(fil - round(fil)) > 1e-4:
        return None
    return round(col), round(fil)


def leer_en_cuadricula(escena: EscenaRTC, cuad: Cuadricula) -> tuple[np.ma.MaskedArray, str]:
    """Lee la escena sobre la cuadrícula común. Devuelve (datos, método).

    - Si la escena ya está en esa cuadrícula: lectura directa de la ventana,
      sin tocar los valores.
    - Si no: remuestreo bilinear a la cuadrícula (en las unidades del archivo),
      con el NoData excluido para que no contamine los bordes.
    """
    sin_dato_implicito = 0.0 if escena.escala in ("power", "amplitude") else None
    nodata = escena.nodata if escena.nodata is not None else sin_dato_implicito
    try:
        with rasterio.open(escena.ruta) as src:
            desfase = _desfase_entero(escena, cuad)
            if desfase is not None:
                col, fil = desfase
                datos = np.full((cuad.alto, cuad.ancho), np.nan, dtype="float32")
                c0, f0 = max(col, 0), max(fil, 0)
                c1, f1 = min(col + cuad.ancho, src.width), min(fil + cuad.alto, src.height)
                if c1 > c0 and f1 > f0:
                    bloque = src.read(1, window=((f0, f1), (c0, c1))).astype("float32")
                    datos[f0 - fil:f1 - fil, c0 - col:c1 - col] = bloque
                metodo = "lectura directa (misma cuadrícula)"
            else:
                with WarpedVRT(
                    src, crs=cuad.crs, transform=cuad.transform, width=cuad.ancho, height=cuad.alto,
                    resampling=Resampling.bilinear, src_nodata=nodata, nodata=nodata,
                ) as vrt:
                    datos = vrt.read(1).astype("float32")
                metodo = "remuestreo bilinear a la cuadrícula de la imagen anterior"
    except (RasterioError, OSError, ValueError) as e:
        raise ErrorSAR(f"No se pudo leer `{escena.ruta.name}`.") from e

    mascara = ~np.isfinite(datos)
    if nodata is not None and not math.isnan(nodata):
        mascara |= datos == np.float32(nodata)
    return np.ma.MaskedArray(datos, mask=mascara), metodo


# ---------------------------------------------------------------------------
# Radiometría
# ---------------------------------------------------------------------------

def a_potencia(datos: np.ma.MaskedArray, escala: str) -> np.ma.MaskedArray:
    """Lleva los valores a potencia lineal. En potencia y amplitud, los valores
    no positivos no son físicos y quedan sin dato."""
    if escala not in ESCALAS:
        raise ErrorSAR(f"Escala '{escala}' no reconocida.")
    valores = np.ma.getdata(datos).astype("float64")
    mascara = np.ma.getmaskarray(datos) | ~np.isfinite(valores)
    if escala == "db":
        potencia = np.power(10.0, np.where(mascara, 0.0, valores) / 10.0)
    else:
        mascara = mascara | (valores <= 0)
        base = np.where(mascara, 1.0, valores)
        potencia = base * base if escala == "amplitude" else base
    return np.ma.MaskedArray(potencia.astype("float32"), mask=mascara)


def potencia_a_db(potencia: np.ma.MaskedArray) -> np.ma.MaskedArray:
    """dB = 10 · log10(potencia). Nulos, no finitos y no positivos → sin dato."""
    valores = np.ma.getdata(potencia).astype("float64")
    mascara = np.ma.getmaskarray(potencia) | ~np.isfinite(valores) | (valores <= 0)
    db = 10.0 * np.log10(np.where(mascara, 1.0, valores))
    return np.ma.MaskedArray(db.astype("float32"), mask=mascara)


def _suma_ventana(a: np.ndarray, k: int) -> np.ndarray:
    r = k // 2
    s = np.pad(a.astype("float64"), ((r + 1, r), (r + 1, r))).cumsum(0).cumsum(1)
    return s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]


def filtrar_speckle(potencia: np.ma.MaskedArray, ventana: int) -> np.ma.MaskedArray:
    """Media móvil de `ventana`×`ventana` píxeles EN POTENCIA (no en dB), usando
    solo los píxeles con dato. Los píxeles sin dato siguen sin dato."""
    if ventana < 1 or ventana % 2 == 0:
        raise ErrorSAR("La ventana del filtro debe ser un entero impar (1 = sin filtro).")
    if ventana == 1:
        return potencia
    mascara = np.ma.getmaskarray(potencia)
    suma = _suma_ventana(np.where(mascara, 0.0, np.ma.getdata(potencia)), ventana)
    cuenta = _suma_ventana(~mascara, ventana)
    media = suma / np.maximum(cuenta, 1)
    return np.ma.MaskedArray(media.astype("float32"), mask=mascara)


def diferencia_db(db_antes: np.ma.MaskedArray, db_despues: np.ma.MaskedArray) -> np.ma.MaskedArray:
    """posterior − anterior, en dB. Negativo = la retrodispersión disminuyó.
    Solo hay resultado donde las DOS fechas tienen dato."""
    if db_antes.shape != db_despues.shape:
        raise ErrorSAR("Las imágenes no están en la misma cuadrícula; no se pueden restar.")
    mascara = np.ma.getmaskarray(db_antes) | np.ma.getmaskarray(db_despues)
    dif = np.ma.getdata(db_despues).astype("float32") - np.ma.getdata(db_antes).astype("float32")
    return np.ma.MaskedArray(np.where(mascara, 0.0, dif).astype("float32"), mask=mascara)


# ---------------------------------------------------------------------------
# Cambios significativos
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParametrosCambio:
    umbral_disminucion_db: float = 3.0       # magnitud: cambio ≤ −umbral
    umbral_aumento_db: float | None = 3.0    # magnitud: cambio ≥ +umbral; None = no marcar aumentos
    ventana_speckle: int = 5                 # píxeles; 1 = sin filtro
    umbral_oscuro_db: float | None = None    # dB; None = no marcar "baja en ambas fechas"

    def __post_init__(self) -> None:
        if not self.umbral_disminucion_db > 0:
            raise ErrorSAR("El umbral de disminución debe ser un número positivo de dB.")
        if self.umbral_aumento_db is not None and not self.umbral_aumento_db > 0:
            raise ErrorSAR("El umbral de aumento debe ser un número positivo de dB.")
        if self.ventana_speckle < 1 or self.ventana_speckle % 2 == 0:
            raise ErrorSAR("La ventana del filtro debe ser un entero impar (1 = sin filtro).")


def mascara_cambios(
    dif_db: np.ma.MaskedArray,
    parametros: ParametrosCambio | None = None,
    db_antes: np.ma.MaskedArray | None = None,
    db_despues: np.ma.MaskedArray | None = None,
) -> np.ndarray:
    """Clasifica cada píxel (uint8): ver CLASES_MASCARA. Sin dato = 255."""
    parametros = parametros or ParametrosCambio()
    valores = np.ma.getdata(dif_db)
    sin_dato = np.ma.getmaskarray(dif_db)
    clases = np.full(dif_db.shape, SIN_CAMBIO, dtype="uint8")
    clases[valores <= -parametros.umbral_disminucion_db] = DISMINUCION
    if parametros.umbral_aumento_db is not None:
        clases[valores >= parametros.umbral_aumento_db] = AUMENTO
    if parametros.umbral_oscuro_db is not None and db_antes is not None and db_despues is not None:
        oscuro = (np.ma.getdata(db_antes) < parametros.umbral_oscuro_db) & \
                 (np.ma.getdata(db_despues) < parametros.umbral_oscuro_db)
        clases[oscuro & (clases == SIN_CAMBIO)] = BAJA_EN_AMBAS
    clases[sin_dato] = NODATA_MASCARA
    return clases


def estadisticas(dif_db: np.ma.MaskedArray, mascara: np.ndarray, cuad: Cuadricula) -> dict:
    validos = dif_db.compressed().astype("float64")
    total = int(mascara.size)
    n = int(validos.size)
    area = cuad.area_pixel_ha
    clases = {}
    for valor, etiqueta, _ in CLASES_MASCARA:
        cuenta = int((mascara == valor).sum())
        clases[str(valor)] = {
            "etiqueta": etiqueta,
            "pixeles": cuenta,
            "porcentaje_de_validos": round(100.0 * cuenta / n, 3) if n else 0.0,
            "area_ha": round(cuenta * area, 2) if area is not None else None,
        }
    resumen = {"pixeles_totales": total, "pixeles_validos": n,
               "porcentaje_valido": round(100.0 * n / total, 3) if total else 0.0, "clases": clases}
    if n:
        p5, p50, p95 = np.percentile(validos, [5, 50, 95])
        resumen["diferencia_db"] = {
            "media": round(float(validos.mean()), 3), "mediana": round(float(p50), 3),
            "desviacion": round(float(validos.std()), 3), "p5": round(float(p5), 3),
            "p95": round(float(p95), 3), "minimo": round(float(validos.min()), 3),
            "maximo": round(float(validos.max()), 3),
        }
    return resumen


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------

def exportar_geotiff(
    ruta: str | Path,
    datos: np.ndarray | np.ma.MaskedArray,
    cuad: Cuadricula,
    nodata: float,
    etiquetas: dict[str, str] | None = None,
    lateral: dict[str, str] | None = None,
) -> Path:
    """Escribe un GeoTIFF comprimido y georreferenciado en la cuadrícula dada.
    `lateral` se guarda como `<nombre>.json`: son los metadatos que muestra el visor."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    matriz = datos.filled(nodata) if isinstance(datos, np.ma.MaskedArray) else np.asarray(datos)
    flotante = np.issubdtype(matriz.dtype, np.floating)
    with rasterio.open(
        ruta, "w", driver="GTiff", height=cuad.alto, width=cuad.ancho, count=1,
        dtype=matriz.dtype, crs=cuad.crs, transform=cuad.transform, nodata=nodata,
        compress="deflate", predictor=3 if flotante else 1,
    ) as dst:
        dst.write(matriz, 1)
        if etiquetas:
            dst.update_tags(**{k: str(v) for k, v in etiquetas.items()})
    if lateral:
        ruta.with_suffix(".json").write_text(json.dumps(lateral, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


@dataclass
class ResultadoAnalisis:
    diferencia: Path                  # GeoTIFF float32, dB (posterior − anterior)
    mascara: Path                     # GeoTIFF uint8, clases de CLASES_MASCARA
    informe: Path                     # JSON de procedencia, parámetros y estadísticas
    procedencia: dict
    extras: dict[str, Path] = field(default_factory=dict)

    @property
    def estadisticas(self) -> dict:
        return self.procedencia["estadisticas"]

    @property
    def avisos(self) -> list[str]:
        return self.procedencia["avisos"]


def analizar_par(
    ruta_antes: str | Path,
    ruta_despues: str | Path,
    carpeta_salida: str | Path,
    aoi: tuple[float, float, float, float] | None = None,
    parametros: ParametrosCambio | None = None,
    polarizacion: str | None = None,
    fecha_antes=None,
    fecha_despues=None,
    escala: str | None = None,
    prefijo: str | None = None,
    guardar_db: bool = False,
    max_pixeles: int = MAX_PIXELES,
    sobrescribir: bool = False,
) -> ResultadoAnalisis:
    """Análisis completo de un par de escenas. Escribe en `carpeta_salida`:

    - `<prefijo>_dif_db.tif`    diferencia de retrodispersión en dB
    - `<prefijo>_mascara.tif`   máscara de cambios significativos
    - `<prefijo>_analisis.json` procedencia, parámetros, estadísticas y limitaciones
    - con `guardar_db=True`, además `<prefijo>_antes_db.tif` y `<prefijo>_despues_db.tif`

    Nunca reemplaza resultados anteriores sin pedirlo: con el prefijo
    automático se usa `_r2`, `_r3`…; con un prefijo explícito ya ocupado se
    detiene, salvo `sobrescribir=True`.
    """
    antes = describir_escena(ruta_antes, polarizacion, fecha_antes, escala)
    despues = describir_escena(ruta_despues, polarizacion, fecha_despues, escala)
    avisos = validar_par(antes, despues)
    if antes.es_nisar and parametros is None:
        raise ErrorSAR("NISAR (banda L) no tiene umbrales por defecto: indica umbrales experimentales "
                       "explícitos (los de Sentinel-1 no se aplican).")
    parametros = parametros or ParametrosCambio()
    if antes.es_nisar:
        avisos.append("Umbrales EXPERIMENTALES para banda L, no calibrados: el resultado es exploratorio.")
        madureces = {antes.geometria.get("madurez"), despues.geometria.get("madurez")}
        if "NO_COMPROBADA" in madureces or "" in madureces:
            avisos.append("La madurez de algún producto GCOV no se comprobó en el catálogo.")
    cuad = cuadricula_comun(antes, despues, aoi, max_pixeles)

    datos_antes, metodo_antes = leer_en_cuadricula(antes, cuad)
    datos_despues, metodo_despues = leer_en_cuadricula(despues, cuad)
    if "remuestreo" in metodo_despues:
        avisos.append("La imagen posterior no estaba en la cuadrícula de la anterior: se remuestreó para alinear los píxeles.")
        if despues.escala == "db":
            avisos.append("El remuestreo se hizo sobre valores en dB; es preferible partir de productos en potencia.")

    db_antes = potencia_a_db(filtrar_speckle(a_potencia(datos_antes, antes.escala), parametros.ventana_speckle))
    db_despues = potencia_a_db(filtrar_speckle(a_potencia(datos_despues, despues.escala), parametros.ventana_speckle))
    dif = diferencia_db(db_antes, db_despues)
    if dif.count() == 0:
        raise ErrorSAR("No hay ningún píxel con dato en las dos fechas dentro de la zona elegida.")
    mascara = mascara_cambios(dif, parametros, db_antes, db_despues)
    resumen = estadisticas(dif, mascara, cuad)
    if resumen["porcentaje_valido"] < 50:
        avisos.append(f"Solo el {resumen['porcentaje_valido']:.0f}% de la zona tiene dato en ambas fechas.")

    def dia(e: EscenaRTC) -> str:
        return f"{e.fecha:%Y-%m-%d}" if e.fecha else "fecha desconocida"

    pol = antes.polarizacion
    carpeta = Path(carpeta_salida)
    if prefijo is None:
        sello = lambda e: f"{e.fecha:%Y%m%d}" if e.fecha else "sinfecha"  # noqa: E731
        prefijo = (f"nisar_cambio_{antes.geometria['frecuencia']}{antes.geometria['termino']}_{sello(antes)}_{sello(despues)}"
                   if antes.es_nisar else f"cambio_{pol}_{sello(antes)}_{sello(despues)}")
        if not sobrescribir:
            prefijo = prefijo_libre(carpeta, prefijo)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", prefijo):
        raise ErrorSAR("El prefijo de salida solo puede tener letras, números, guiones y puntos.")
    previos = sorted(q.name for q in carpeta.glob(f"{prefijo}_*")
                     if q.name.removeprefix(f"{prefijo}_") in _SUFIJOS_SALIDA)
    if previos and not sobrescribir:
        raise ErrorSAR(f"Ya existen resultados con el prefijo `{prefijo}` ({', '.join(previos)}). "
                       "Elige otro prefijo o pide sobrescribirlos expresamente.")

    if antes.es_hyp3 and despues.es_hyp3:
        plataformas = " y ".join(sorted({antes.plataforma, despues.plataforma}))
        fuente = f"Sentinel-1 ({plataformas}), ASF HyP3 RTC {antes.radiometria} · derivado por V.I.S.O.R."
    elif antes.es_nisar:
        g = antes.geometria
        fuente = (f"NISAR L2 GCOV banda L, frecuencia {g['frecuencia']}, {g['termino']} gamma0 · track {g['track']}, "
                  f"frame {g['frame']}, CRID {g['crid']} · ASF · derivado por V.I.S.O.R.")
    else:
        fuente = f"Archivos locales: {antes.ruta.name} y {despues.ruta.name} · derivado por V.I.S.O.R."
    fechas = f"{dia(antes)} / {dia(despues)}"
    comunes = {
        "VISOR_ANALISIS": "1", "MOTOR_VERSION": VERSION_MOTOR, "FUENTE": fuente, "FECHA": fechas,
        "POLARIZACION": pol, "ENTRADA_ANTES": antes.ruta.name, "ENTRADA_DESPUES": despues.ruta.name,
        "PARAMETROS": json.dumps(asdict(parametros)), "ADVERTENCIA": ADVERTENCIA,
        **({"SENSOR": antes.sensor, "BANDA": antes.banda or ""} if antes.sensor else {}),
        **({"UMBRALES": "experimentales banda L, no calibrados"} if antes.es_nisar else {}),
        # Si una entrada es sintética, lo derivado también lo es: la marca DEMO se propaga.
        **({"VISOR_DEMO": "1"} if antes.es_demo or despues.es_demo else {}),
    }

    def lateral(producto: str, unidades: str) -> dict[str, str]:
        return {"fuente": fuente, "fecha": fechas, "producto": producto, "unidades": unidades}

    producto_dif = f"Cambio de retrodispersión {pol} (posterior − anterior)"
    producto_masc = f"Cambios SAR significativos {pol} (indicios, sin validar)"
    ruta_dif = exportar_geotiff(
        carpeta / f"{prefijo}_dif_db.tif", dif, cuad, NODATA_DB,
        {**comunes, "PRODUCTO": producto_dif, "UNIDADES": "dB"}, lateral(producto_dif, "dB"),
    )
    ruta_masc = exportar_geotiff(
        carpeta / f"{prefijo}_mascara.tif", mascara, cuad, NODATA_MASCARA,
        {**comunes, "PRODUCTO": producto_masc, "UNIDADES": "clase",
         "CLASES": json.dumps({str(v): e for v, e, _ in CLASES_MASCARA}, ensure_ascii=False)},
        lateral(producto_masc, "clase"),
    )
    extras: dict[str, Path] = {}
    if guardar_db:
        for clave, escena, db in (("antes_db", antes, db_antes), ("despues_db", despues, db_despues)):
            producto = f"Retrodispersión {pol} {dia(escena)}"
            extras[clave] = exportar_geotiff(
                carpeta / f"{prefijo}_{clave}.tif", db, cuad, NODATA_DB,
                {**comunes, "PRODUCTO": producto, "UNIDADES": "dB", "FECHA": dia(escena)},
                {**lateral(producto, "dB"), "fecha": dia(escena)},
            )

    procedencia = {
        "motor": "V.I.S.O.R. · utils/analisis_sar.py",
        "version_motor": VERSION_MOTOR,
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "advertencia": ADVERTENCIA,
        "entradas": {"antes": {**antes.resumen(), "sha256": sha256_archivo(antes.ruta)},
                     "despues": {**despues.resumen(), "sha256": sha256_archivo(despues.ruta)}},
        "aoi_lonlat": list(aoi) if aoi is not None else None,
        "cuadricula": {
            "crs": cuad.crs.to_string(), "transform": list(cuad.transform)[:6],
            "ancho": cuad.ancho, "alto": cuad.alto, "limites": list(cuad.limites),
            "limites_lonlat": list(cuad.limites_lonlat), "area_pixel_ha": cuad.area_pixel_ha,
        },
        "alineacion": {"antes": metodo_antes, "despues": metodo_despues},
        "parametros": asdict(parametros),
        "metodo": [
            "Lectura de ambas escenas sobre la cuadrícula de la imagen anterior.",
            f"Media móvil de {parametros.ventana_speckle}×{parametros.ventana_speckle} px en potencia."
            if parametros.ventana_speckle > 1 else "Sin filtro de speckle.",
            "Conversión a decibelios: 10·log10(potencia); nulos y no positivos quedan sin dato.",
            "Diferencia = posterior − anterior, solo donde ambas fechas tienen dato.",
            f"Disminución significativa: diferencia ≤ −{parametros.umbral_disminucion_db:g} dB."
            + (f" Aumento significativo: diferencia ≥ +{parametros.umbral_aumento_db:g} dB."
               if parametros.umbral_aumento_db is not None else ""),
            *([f"Señal baja en ambas fechas (sin cambio significativo): < {parametros.umbral_oscuro_db:g} dB "
               "antes y después."] if parametros.umbral_oscuro_db is not None else []),
        ],
        "salidas": {"diferencia_db": ruta_dif.name, "mascara": ruta_masc.name,
                    **{k: v.name for k, v in extras.items()}},
        "huellas_sha256": {q.name: sha256_archivo(q) for q in (ruta_dif, ruta_masc, *extras.values())},
        "clases_mascara": {str(v): e for v, e, _ in CLASES_MASCARA},
        "estadisticas": resumen,
        "avisos": avisos,
        "sensor": antes.sensor, "banda": antes.banda,
        "limitaciones": ([lim for lim in LIMITACIONES if not lim.startswith("Vegetación")] + list(LIMITACIONES_BANDA_L)
                         if antes.es_nisar else list(LIMITACIONES)),
    }
    ruta_informe = carpeta / f"{prefijo}_analisis.json"
    ruta_informe.write_text(json.dumps(procedencia, ensure_ascii=False, indent=2), encoding="utf-8")
    return ResultadoAnalisis(ruta_dif, ruta_masc, ruta_informe, procedencia, extras)
