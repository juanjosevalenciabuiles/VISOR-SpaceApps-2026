"""Cruce SAR × JRC Global Surface Water Occurrence, por AOI y por municipio.

Automatiza el cruce que el equipo hizo a mano en QGIS para Chigorodó. Adaptado
del prototipo «VISOR_automatizacion_regional_2026-11-13» e integrado con los
módulos existentes (procedencia, prefijo_libre, área por píxel, perfiles de
resultado, exportador QGIS).

Qué hace:
- Lee la máscara VV/VH de Sentinel-1 (clases 0/1/2/3, 255 = NoData) y el JRC
  Occurrence ORIGINAL (o un VRT/mosaico), que se reproyecta en memoria
  (WarpedVRT, vecino más cercano) sobre la cuadrícula SAR. No se escribe ningún
  JRC intermedio y no se toca ningún archivo de entrada.
- JRC válido = 0…100. El NoData declarado y cualquier valor > 100 (p. ej. 255)
  son «sin dato JRC»: NUNCA se convierten en 0 («sin agua observada»).
- Recorre la cuadrícula por bloques (memoria acotada) y cuenta, para cada
  umbral de ocurrencia (por defecto 1, 10, 25 y 50 %), las detecciones SAR por
  clase que caen sobre agua histórica, con sus denominadores.
- Por zona (municipio), con máscara propia para cada una (si se solapan, los
  píxeles comunes cuentan en ambas): píxeles de la zona dentro de la
  cuadrícula, cobertura de la zona por la cuadrícula, píxeles SAR válidos y
  cobertura válida. Sin observaciones válidas → N/D, nunca 0 %.

Qué NO hace: no busca ni genera pares SAR, no interpreta las clases VV/VH para
otra banda (NISAR HH/HV se rechaza) y no confirma inundaciones: JRC describe la
frecuencia de agua 1984–2024, no el agua en la fecha del radar.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import RasterioError
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom
from rasterio.windows import Window

from utils import procedencia
from utils.analisis_sar import area_pixel_ha, prefijo_libre
from utils.combinacion_sar import AMBAS, SIN_DISMINUCION, SOLO_VH, SOLO_VV, TIPO_PRODUCTO
from utils.config import DATA_DIR

VERSION = "1.0"
NODATA = 255
CLASES_SAR = (SOLO_VV, SOLO_VH, AMBAS)
NOMBRES_CLASE = {SOLO_VV: "solo_VV", SOLO_VH: "solo_VH", AMBAS: "VV_y_VH"}
UMBRALES_POR_DEFECTO = (1, 10, 25, 50)
BLOQUE = 1024
CARPETA_JRC = DATA_DIR / "jrc"
CARPETA_ANALISIS = DATA_DIR / "analisis"
CARPETA_REGIONAL = DATA_DIR / "analisis" / "regional"
REGISTRO_VALIDACION = "validacion_chigorodo.json"
TIPO_COINCIDENCIA = "sar_jrc_coincidencia"
TIPO_POLARIZACIONES = "sar_jrc_polarizaciones"

CLASES_RASTER_COINCIDENCIA = (
    (0, "Sin detección SAR (área válida)", None),
    (1, "Detección SAR sin agua histórica JRC (ocurrencia 0 %)", "#FF9F0A"),
    (2, "Detección SAR sobre agua histórica JRC (ocurrencia ≥ 1 %)", "#00F0FF"),
)
CLASES_RASTER_POLARIZACIONES = (
    (0, "Sin detección SAR (área válida)", None),
    (1, "Solo VV · JRC 0 %", "#5E5CE6"),
    (2, "Solo VH · JRC 0 %", "#FF9F0A"),
    (3, "VV y VH · JRC 0 %", "#BF5AF2"),
    (11, "Solo VV · JRC ≥ 1 %", "#64D2FF"),
    (12, "Solo VH · JRC ≥ 1 %", "#30D158"),
    (13, "VV y VH · JRC ≥ 1 %", "#00F0FF"),
)
ADVERTENCIA = ("Asociación geográfica con agua HISTÓRICA (JRC 1984–2024). No confirma inundaciones ni valida "
               "la detección SAR de 2026.")
LIMITACIONES = (
    "JRC Occurrence es la frecuencia de agua 1984–2024 sobre las observaciones disponibles; no es agua en la "
    "fecha del radar. Ocurrencia 0 significa «sin agua observada», no «nunca hubo agua».",
    "Los porcentajes y el factor de enriquecimiento son descriptivos: no son precisión, sensibilidad, "
    "exactitud ni causalidad, y hay autocorrelación espacial y sesgos de terreno y cultivo.",
    "Las clases VV/VH usan umbrales distintos y tienen tamaños muy desiguales: sus tasas no son una "
    "sensibilidad comparable entre polarizaciones.",
    "JRC se lleva a la cuadrícula SAR con vecino más cercano; puede desplazar bordes hasta medio píxel.",
    "Un píxel cuenta en una zona si su centro cae dentro del polígono.",
    "Las cifras de un AOI no se extrapolan a otro: cada AOI necesita SAR con cobertura real y JRC propio.",
)


class ErrorJRC(Exception):
    """Problema del cruce SAR × JRC, explicado para el usuario."""


# ---------------------------------------------------------------------------
# Conteo
# ---------------------------------------------------------------------------

@dataclass
class Contador:
    umbrales: tuple[int, ...]
    pixeles_zona: int = 0                 # píxeles de la cuadrícula con centro en la zona
    sar_validos: int = 0                  # SAR 0..3 dentro de la zona
    sar_sin_jrc: int = 0                  # SAR válido, JRC sin dato
    validos: int = 0                      # SAR y JRC válidos (denominador del área)
    sin_deteccion: int = 0
    detecciones_sar: dict[int, int] = field(default_factory=lambda: dict.fromkeys(CLASES_SAR, 0))
    sar: dict[int, int] = field(default_factory=lambda: dict.fromkeys(CLASES_SAR, 0))        # con JRC válido
    agua: dict[int, int] = field(default_factory=dict)
    sar_y_agua: dict[int, dict[int, int]] = field(default_factory=dict)

    def __post_init__(self):
        self.agua = dict.fromkeys(self.umbrales, 0)
        self.sar_y_agua = {t: dict.fromkeys(CLASES_SAR, 0) for t in self.umbrales}

    def sumar(self, sar: np.ndarray, agua: np.ndarray, en_zona: np.ndarray, sar_ok: np.ndarray, jrc_ok: np.ndarray):
        self.pixeles_zona += int(en_zona.sum())
        s = en_zona & sar_ok
        self.sar_validos += int(s.sum())
        self.sar_sin_jrc += int((s & ~jrc_ok).sum())
        for c in CLASES_SAR:
            self.detecciones_sar[c] += int((s & (sar == c)).sum())
        v = s & jrc_ok
        self.validos += int(v.sum())
        self.sin_deteccion += int((v & (sar == SIN_DISMINUCION)).sum())
        por_clase = {c: v & (sar == c) for c in CLASES_SAR}
        for c in CLASES_SAR:
            self.sar[c] += int(por_clase[c].sum())
        for t in self.umbrales:
            mojado = v & (agua >= t)
            self.agua[t] += int(mojado.sum())
            for c in CLASES_SAR:
                self.sar_y_agua[t][c] += int((mojado & por_clase[c]).sum())


def _pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 4) if b else None


def _ha(n: int, ha: float | None) -> float | None:
    return round(n * ha, 4) if ha is not None else None


def estadisticas(c: Contador, area_ha: float | None) -> dict:
    """Cifras de una zona o del total. Cada tasa lleva su denominador; sin datos → None (N/D)."""
    detecciones = sum(c.sar.values())
    salida = {
        "pixeles_zona_en_cuadricula": c.pixeles_zona,
        "pixeles_sar_validos": c.sar_validos,
        "cobertura_sar_valida_pct": _pct(c.sar_validos, c.pixeles_zona),
        "pixeles_sar_validos_sin_jrc": c.sar_sin_jrc,
        "pixeles_validos": c.validos,
        "pixeles_sin_deteccion": c.sin_deteccion,
        "detecciones_sar_totales": sum(c.detecciones_sar.values()),
        "detecciones": detecciones,
        "hectareas_detecciones": _ha(detecciones, area_ha),
        "clases_sar": {NOMBRES_CLASE[k]: {"pixeles": c.sar[k], "hectareas": _ha(c.sar[k], area_ha)} for k in CLASES_SAR},
        "sin_observaciones_validas": c.validos == 0,
        "umbrales_jrc": [],
    }
    for t in c.umbrales:
        coinciden = sum(c.sar_y_agua[t].values())
        tasa = _pct(coinciden, detecciones)
        base = _pct(c.agua[t], c.validos)
        salida["umbrales_jrc"].append({
            "umbral_ocurrencia_pct": t,
            "pixeles_jrc_con_agua": c.agua[t],
            "pixeles_sar_jrc": coinciden,
            "hectareas_sar_jrc": _ha(coinciden, area_ha),
            "pct_jrc_entre_detecciones": tasa, "denominador_detecciones": detecciones,
            "pct_jrc_en_area_valida": base, "denominador_area_valida": c.validos,
            "enriquecimiento_descriptivo": round(tasa / base, 4) if tasa is not None and base else None,
            "por_clase": {NOMBRES_CLASE[k]: {
                "coincidentes": c.sar_y_agua[t][k], "total": c.sar[k],
                "pct_dentro_clase": _pct(c.sar_y_agua[t][k], c.sar[k]),
                "hectareas": _ha(c.sar_y_agua[t][k], area_ha)} for k in CLASES_SAR},
        })
    return salida


# ---------------------------------------------------------------------------
# Entradas
# ---------------------------------------------------------------------------

def _ficha_lateral(ruta: Path) -> dict | None:
    try:
        return json.loads(ruta.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def describir_sar(ruta: Path) -> dict:
    """Comprueba que la entrada es la máscara VV/VH de Sentinel-1 y devuelve su procedencia."""
    from utils.resultados import identificar_perfil
    try:
        with rasterio.open(ruta) as src:
            etiquetas = {k.upper(): v for k, v in src.tags().items()}
            info = {"crs": src.crs, "transform": src.transform, "ancho": src.width, "alto": src.height,
                    "nodata": src.nodata, "bandas": src.count, "tipo": src.dtypes[0]}
    except (RasterioError, OSError) as e:
        raise ErrorJRC(f"`{ruta.name}` no es un GeoTIFF legible.") from e
    if info["bandas"] != 1 or info["tipo"] != "uint8":
        raise ErrorJRC(f"`{ruta.name}` debe ser una banda uint8 de clases 0/1/2/3/255.")
    if info["crs"] is None:
        raise ErrorJRC(f"`{ruta.name}` no tiene CRS.")
    ficha = _ficha_lateral(ruta)
    if identificar_perfil(etiquetas, ficha) != TIPO_PRODUCTO:
        raise ErrorJRC(f"`{ruta.name}` no es una combinación VV/VH (clases solo VV / solo VH / ambas).")
    sensor = (etiquetas.get("SENSOR") or ((ficha or {}).get("procedencia") or {}).get("sensor") or "")
    if "NISAR" in str(sensor).upper() or etiquetas.get("BANDA") == "L":
        raise ErrorJRC("Las clases VV/VH y sus umbrales son de Sentinel-1 (banda C): no se aplican a NISAR HH/HV.")
    sha = procedencia.sha256_archivo(ruta)
    estado = procedencia.evaluar(etiquetas.get("VISOR_DEMO") == "1", ficha, sha)
    return {**info, "etiquetas": etiquetas, "ficha": ficha, "sha256": sha, "procedencia": estado}


def describir_jrc(ruta: Path) -> dict:
    try:
        with rasterio.open(ruta) as src:
            info = {"crs": src.crs, "transform": src.transform, "ancho": src.width, "alto": src.height,
                    "nodata": src.nodata, "bandas": src.count, "tipo": src.dtypes[0], "etiquetas": src.tags()}
    except (RasterioError, OSError) as e:
        raise ErrorJRC(f"`{ruta.name}` no es un ráster legible (GeoTIFF o VRT).") from e
    if info["bandas"] != 1:
        raise ErrorJRC(f"`{ruta.name}` debe tener una sola banda (Occurrence).")
    if info["crs"] is None:
        raise ErrorJRC(f"`{ruta.name}` no tiene CRS.")
    if not np.issubdtype(np.dtype(info["tipo"]), np.integer):
        raise ErrorJRC(f"`{ruta.name}` es {info['tipo']}: JRC Occurrence es entero (0–100).")
    return info


def _zonas_en_crs(zonas, crs) -> list[tuple[str, str, dict]]:
    return [(z.codigo, z.nombre, transform_geom("EPSG:4326", crs, z.geometria.__geo_interface__)) for z in zonas]


def _ventanas(alto: int, ancho: int, bloque: int):
    for f in range(0, alto, bloque):
        for c in range(0, ancho, bloque):
            yield Window(c, f, min(bloque, ancho - c), min(bloque, alto - f))


def _clave_cache(sha_sar: str, sha_jrc: str, aoi, umbrales) -> str:
    texto = json.dumps({"v": VERSION, "sar": sha_sar, "jrc": sha_jrc, "umbrales": list(umbrales),
                        "aoi": aoi.resumen() if aoi is not None else None}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(texto.encode()).hexdigest()


def buscar_en_cache(carpeta: Path, clave: str) -> Path | None:
    for informe in sorted(Path(carpeta).glob("sar_jrc_*_informe.json")):
        try:
            datos = json.loads(informe.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        salidas = [informe.parent / n for n in (datos.get("salidas") or {}).values()]
        if (datos.get("clave_cache") == clave and salidas
                and all(p.is_file() and procedencia.sha256_archivo(p) == datos["huellas_sha256"].get(p.name)
                        for p in salidas)):
            return informe
    return None


# ---------------------------------------------------------------------------
# Cruce
# ---------------------------------------------------------------------------

@dataclass
class ResultadoJRC:
    informe: Path
    datos: dict
    desde_cache: bool = False

    @property
    def coincidencia(self) -> Path:
        return self.informe.parent / self.datos["salidas"]["coincidencia"]

    @property
    def polarizaciones(self) -> Path:
        return self.informe.parent / self.datos["salidas"]["polarizaciones"]

    @property
    def csv(self) -> Path:
        return self.informe.parent / self.datos["salidas_tabla"]["csv"]


def cruzar(ruta_sar: str | Path, ruta_jrc: str | Path, aoi=None, carpeta: str | Path | None = None,
           umbrales=UMBRALES_POR_DEFECTO, bloque: int = BLOQUE, version_jrc: str | None = None,
           usar_cache: bool = True, avance: Callable[[float], None] | None = None) -> ResultadoJRC:
    """Cruza la máscara VV/VH con JRC sobre la cuadrícula SAR, en el AOI (o en toda la cuadrícula)."""
    ruta_sar, ruta_jrc = Path(ruta_sar).resolve(), Path(ruta_jrc).resolve()
    umbrales = tuple(sorted({int(t) for t in umbrales}))
    if not umbrales or umbrales[0] < 1 or umbrales[-1] > 100:
        raise ErrorJRC("Los umbrales de ocurrencia JRC deben ser enteros entre 1 y 100.")
    if not 64 <= int(bloque) <= 8192:
        raise ErrorJRC("El tamaño de bloque debe estar entre 64 y 8192 píxeles.")
    for r in (ruta_sar, ruta_jrc):
        if not r.is_file():
            raise ErrorJRC(f"No se encontró `{r.name}`.")
    if ruta_sar == ruta_jrc:
        raise ErrorJRC("La máscara SAR y el JRC son el mismo archivo.")
    carpeta = Path(carpeta) if carpeta is not None else CARPETA_ANALISIS
    if carpeta.resolve() in (ruta_sar.parent, ruta_jrc.parent) and carpeta.resolve() == CARPETA_JRC.resolve():
        raise ErrorJRC("La carpeta de salida no puede ser la del JRC original.")

    sar = describir_sar(ruta_sar)
    jrc = describir_jrc(ruta_jrc)
    sha_jrc = procedencia.sha256_archivo(ruta_jrc)
    clave = _clave_cache(sar["sha256"], sha_jrc, aoi, umbrales)
    if usar_cache and carpeta.is_dir():
        hit = buscar_en_cache(carpeta, clave)
        if hit is not None:
            return ResultadoJRC(hit, json.loads(hit.read_text(encoding="utf-8")), desde_cache=True)

    area_ha = area_pixel_ha(sar["crs"], sar["transform"])
    avisos = []
    if area_ha is None:
        avisos.append("La cuadrícula SAR no está en un CRS proyectado con unidades conocidas: sin hectáreas.")
    zonas = _zonas_en_crs(aoi.zonas, sar["crs"]) if aoi is not None else []
    union = transform_geom("EPSG:4326", sar["crs"], aoi.geometria.__geo_interface__) if aoi is not None else None
    if aoi is not None:
        avisos.extend(aoi.avisos)

    carpeta.mkdir(parents=True, exist_ok=True)
    from utils.regiones import nombre_archivo
    base = prefijo_libre(carpeta, f"sar_jrc_{nombre_archivo(ruta_sar.stem)}"
                                  + (f"_{nombre_archivo(aoi.nombre)}" if aoi is not None else ""))
    rutas = {"coincidencia": carpeta / f"{base}_coincidencia.tif", "polarizaciones": carpeta / f"{base}_polarizaciones.tif"}
    if any(p.exists() for p in rutas.values()):
        raise ErrorJRC("Ya existen salidas con ese nombre; no se sobrescriben.")

    total = Contador(umbrales)
    por_zona = {codigo: Contador(umbrales) for codigo, _, _ in zonas}
    fuera_aoi = 0
    sar_invalidos = 0
    perfil = {"driver": "GTiff", "height": sar["alto"], "width": sar["ancho"], "count": 1, "dtype": "uint8",
              "crs": sar["crs"], "transform": sar["transform"], "nodata": NODATA, "compress": "deflate",
              "tiled": sar["alto"] >= 256 and sar["ancho"] >= 256}
    ventanas = list(_ventanas(sar["alto"], sar["ancho"], int(bloque)))
    try:
        with rasterio.open(ruta_sar) as src, rasterio.open(ruta_jrc) as fuente, \
                WarpedVRT(fuente, crs=src.crs, transform=src.transform, width=src.width, height=src.height,
                          resampling=Resampling.nearest) as vrt, \
                rasterio.open(rutas["coincidencia"], "w", **perfil) as dc, \
                rasterio.open(rutas["polarizaciones"], "w", **perfil) as dp:
            for i, w in enumerate(ventanas, 1):
                clases = src.read(1, window=w)
                agua = vrt.read(1, window=w)
                sar_ok = (src.read_masks(1, window=w) > 0) & np.isin(clases, (SIN_DISMINUCION, *CLASES_SAR))
                # JRC: NoData declarado, fuera de cobertura o > 100 → sin dato (nunca 0).
                jrc_ok = (vrt.read_masks(1, window=w) > 0) & (agua >= 0) & (agua <= 100)
                t = src.window_transform(w)
                en_aoi = (geometry_mask([union], out_shape=clases.shape, transform=t, invert=True)
                          if union is not None else np.ones(clases.shape, dtype=bool))
                fuera_aoi += int((~en_aoi).sum())
                sar_invalidos += int((en_aoi & ~sar_ok).sum())
                total.sumar(clases, agua, en_aoi, sar_ok, jrc_ok)
                for codigo, _, geo in zonas:
                    m = geometry_mask([geo], out_shape=clases.shape, transform=t, invert=True)
                    if m.any():
                        por_zona[codigo].sumar(clases, agua, m, sar_ok, jrc_ok)
                ok = en_aoi & sar_ok & jrc_ok
                con_agua = agua >= 1
                activo = ok & np.isin(clases, CLASES_SAR)
                c = np.full(clases.shape, NODATA, dtype="uint8")
                p = np.full(clases.shape, NODATA, dtype="uint8")
                c[ok] = 0
                p[ok] = 0
                c[activo] = 1 + con_agua[activo]
                p[activo] = clases[activo] + 10 * con_agua[activo]
                dc.write(c, 1, window=w)
                dp.write(p, 1, window=w)
                if avance:
                    avance(i / len(ventanas))
    except (RasterioError, OSError) as e:
        for r in rutas.values():
            r.unlink(missing_ok=True)
        raise ErrorJRC(f"No se pudo completar el cruce: {e}") from e

    # Las entradas no cambiaron durante el cálculo.
    if procedencia.sha256_archivo(ruta_sar) != sar["sha256"] or procedencia.sha256_archivo(ruta_jrc) != sha_jrc:
        for r in rutas.values():
            r.unlink(missing_ok=True)
        raise ErrorJRC("Una entrada cambió durante el cálculo; se descartaron las salidas.")

    est_total = estadisticas(total, area_ha)
    if est_total["pixeles_sar_validos_sin_jrc"]:
        avisos.append(f"{est_total['pixeles_sar_validos_sin_jrc']:,} píxeles SAR válidos no tienen dato JRC "
                      "(fuera de su cobertura o NoData): quedan fuera de las tasas, no cuentan como «sin agua».")
    zonas_salida = {}
    for codigo, nombre, _ in zonas:
        e = estadisticas(por_zona[codigo], area_ha)
        zona_aoi = next(z for z in aoi.zonas if z.codigo == codigo)
        from utils.regiones import area_geodesica_km2
        area_zona_ha = area_geodesica_km2(zona_aoi.geometria) * 100
        en_cuadricula_ha = _ha(e["pixeles_zona_en_cuadricula"], area_ha)
        e["nombre"] = nombre
        e["area_zona_ha"] = round(area_zona_ha, 2)
        e["cobertura_cuadricula_pct"] = (round(min(100.0, 100 * en_cuadricula_ha / area_zona_ha), 2)
                                         if en_cuadricula_ha is not None and area_zona_ha else None)
        if e["sin_observaciones_validas"]:
            avisos.append(f"{nombre}: sin observaciones SAR y JRC válidas → N/D (no es 0 % de cambio).")
        elif e["cobertura_cuadricula_pct"] is not None and e["cobertura_cuadricula_pct"] < 99:
            avisos.append(f"{nombre}: la cuadrícula SAR solo cubre el {e['cobertura_cuadricula_pct']:.1f} % del municipio.")
        zonas_salida[codigo] = e

    estado_sar = sar["procedencia"].estado
    informe = {
        "producto": "Cruce SAR × JRC Occurrence (asociación con agua histórica)",
        "version": VERSION, "clave_cache": clave,
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "advertencia": ADVERTENCIA,
        "metodo": [
            "Máscara VV/VH de Sentinel-1 (0 sin disminución, 1 solo VV, 2 solo VH, 3 ambas, 255 sin dato).",
            "JRC Global Surface Water Occurrence reproyectado en memoria a la cuadrícula SAR (vecino más cercano).",
            "JRC válido 0–100; NoData y valores > 100 son «sin dato JRC», nunca 0.",
            f"Umbrales de ocurrencia: {', '.join(f'≥ {t} %' for t in umbrales)} (≥ 1 % equivale a «> 0» en datos enteros).",
            "Tasas descriptivas con su denominador; por zona, máscara propia de cada polígono (centro de píxel).",
        ],
        "configuracion": {"umbrales_jrc": list(umbrales), "remuestreo_jrc": "nearest", "bloque": int(bloque)},
        "entradas": {
            "sar": {"archivo": ruta_sar.name, "sha256": sar["sha256"], "procedencia": estado_sar,
                    "fechas": sar["etiquetas"].get("FECHA")},
            "jrc": {"archivo": ruta_jrc.name, "sha256": sha_jrc, "version_declarada": version_jrc or "no declarada",
                    "crs": jrc["crs"].to_string(), "resolucion": [abs(jrc["transform"].a), abs(jrc["transform"].e)],
                    "nodata": jrc["nodata"], "tipo": jrc["tipo"]},
            "entradas_intactas": True,
        },
        "aoi": aoi.resumen() if aoi is not None else None,
        "cuadricula": {"crs": sar["crs"].to_string(), "ancho": sar["ancho"], "alto": sar["alto"],
                       "transform": list(sar["transform"])[:6], "hectareas_por_pixel": area_ha},
        "control": {"pixeles_fuera_aoi": fuera_aoi, "pixeles_sar_sin_dato_en_aoi": sar_invalidos},
        "global": est_total,
        "zonas": zonas_salida,
        "salidas": {k: r.name for k, r in rutas.items()},
        "huellas_sha256": {},
        "avisos": avisos,
        "limitaciones": list(LIMITACIONES),
    }
    _fichas(rutas, informe, sar, estado_sar)
    informe["huellas_sha256"] = {r.name: procedencia.sha256_archivo(r) for r in rutas.values()}   # tras etiquetar
    tabla = carpeta / f"{base}_estadisticas.csv"
    _escribir_csv(tabla, informe)
    informe["salidas_tabla"] = {"csv": tabla.name}
    ruta_informe = carpeta / f"{base}_informe.json"
    with ruta_informe.open("x", encoding="utf-8") as f:
        json.dump(informe, f, ensure_ascii=False, indent=2)
    return ResultadoJRC(ruta_informe, informe)


def _fichas(rutas: dict[str, Path], informe: dict, sar: dict, estado_sar: str) -> None:
    """Etiquetas y ficha de procedencia de cada GeoTIFF (para el explorador y QGIS)."""
    for clave, tipo, clases in (("coincidencia", TIPO_COINCIDENCIA, CLASES_RASTER_COINCIDENCIA),
                                ("polarizaciones", TIPO_POLARIZACIONES, CLASES_RASTER_POLARIZACIONES)):
        ruta = rutas[clave]
        etiquetas = {"TIPO_PRODUCTO": tipo, "UNIDADES": "clase", "FECHA": sar["etiquetas"].get("FECHA", ""),
                     "PRODUCTO": informe["producto"], "ADVERTENCIA": ADVERTENCIA, "FUENTE":
                     f"{sar['etiquetas'].get('FUENTE', 'Máscara VV/VH Sentinel-1')} × JRC Global Surface Water Occurrence",
                     **({"VISOR_DEMO": "1"} if estado_sar == procedencia.DEMO else {})}
        with rasterio.open(ruta, "r+") as dst:
            dst.update_tags(**etiquetas)
        real = estado_sar in (procedencia.REAL_SIN_VALIDAR, procedencia.VALIDADO)
        bloque = {
            "estado": procedencia.REAL_SIN_VALIDAR if real else (procedencia.DEMO if estado_sar == procedencia.DEMO
                                                                 else procedencia.NO_DECLARADA),
            "sensor": "Sentinel-1 (máscara VV/VH) + JRC Global Surface Water Occurrence",
            "fechas": [sar["etiquetas"].get("FECHA") or "no declarada"],
            "polarizaciones": ["VV", "VH"],
            "metodo": " ".join(informe["metodo"]),
            "entradas": [informe["entradas"]["sar"], informe["entradas"]["jrc"]],
            "generado_por": {"funcion": "utils.sar_jrc.cruzar", "version": VERSION},
            "generado_utc": informe["generado_utc"],
            "archivo": {"nombre": ruta.name, "sha256": procedencia.sha256_archivo(ruta)},
            "validacion": None,
        }
        if not real and estado_sar != procedencia.DEMO:
            bloque["motivo"] = "La máscara SAR de entrada no tiene procedencia real declarada."
        ficha = {"esquema": procedencia.ESQUEMA_FICHA, "tipo_producto": tipo, "producto": informe["producto"],
                 "fuente": etiquetas["FUENTE"], "fecha": etiquetas["FECHA"], "unidades": "clase",
                 "advertencia": ADVERTENCIA, "procedencia": bloque,
                 "clases": {str(v): e for v, e, _ in clases} | {str(NODATA): "Sin dato (SAR, JRC o fuera del AOI)"},
                 "informe": f"{ruta.name.rsplit('_', 1)[0]}_informe.json",
                 "limitaciones": list(LIMITACIONES)}
        ruta.with_suffix(".json").write_text(json.dumps(ficha, ensure_ascii=False, indent=2), encoding="utf-8")


def _escribir_csv(ruta: Path, informe: dict) -> None:
    """Una fila por zona y umbral, con denominadores. Vacío = N/D. UTF-8 con BOM (Excel/QGIS en Windows)."""
    filas = [("TOTAL", "Total del AOI", informe["global"])] + [
        (codigo, e["nombre"], e) for codigo, e in informe["zonas"].items()]
    with ruta.open("x", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["codigo", "zona", "cobertura_cuadricula_pct", "cobertura_sar_valida_pct", "pixeles_validos",
                    "detecciones", "umbral_jrc_pct", "coincidencias", "pct_jrc_entre_detecciones",
                    "pct_jrc_en_area_valida", "enriquecimiento", "solo_VV_coinc", "solo_VV_total",
                    "solo_VH_coinc", "solo_VH_total", "VV_y_VH_coinc", "VV_y_VH_total", "hectareas_sar_jrc"])
        for codigo, nombre, e in filas:
            for u in e["umbrales_jrc"]:
                pc = u["por_clase"]
                w.writerow([codigo, nombre, e.get("cobertura_cuadricula_pct", ""),
                            "" if e["cobertura_sar_valida_pct"] is None else e["cobertura_sar_valida_pct"],
                            e["pixeles_validos"], e["detecciones"], u["umbral_ocurrencia_pct"], u["pixeles_sar_jrc"],
                            "" if u["pct_jrc_entre_detecciones"] is None else u["pct_jrc_entre_detecciones"],
                            "" if u["pct_jrc_en_area_valida"] is None else u["pct_jrc_en_area_valida"],
                            "" if u["enriquecimiento_descriptivo"] is None else u["enriquecimiento_descriptivo"],
                            pc["solo_VV"]["coincidentes"], pc["solo_VV"]["total"],
                            pc["solo_VH"]["coincidentes"], pc["solo_VH"]["total"],
                            pc["VV_y_VH"]["coincidentes"], pc["VV_y_VH"]["total"],
                            "" if u["hectareas_sar_jrc"] is None else u["hectareas_sar_jrc"]])


# ---------------------------------------------------------------------------
# Reproducción de Chigorodó: puerta para habilitar el análisis regional
# ---------------------------------------------------------------------------

RUTA_REFERENCIA = Path(__file__).resolve().parent.parent / "tests" / "datos" / "referencia_sar_jrc_chigorodo.json"


def leer_referencia(ruta: Path | None = None) -> dict:
    return json.loads(Path(ruta or RUTA_REFERENCIA).read_text(encoding="utf-8"))


def comparar_con_referencia(informe: dict, ref: dict) -> list[str]:
    """Diferencias entre un cruce (umbral ≥ 1 %) y las cifras de QGIS del equipo. Vacía = reproduce."""
    g = informe["global"]
    c = informe["cuadricula"]
    u1 = next((u for u in g["umbrales_jrc"] if u["umbral_ocurrencia_pct"] == 1), None)
    if u1 is None:
        return ["El cruce no incluye el umbral ≥ 1 % (equivalente a > 0)."]
    claves = {"solo_VV": "solo_VV", "solo_VH": "solo_VH", "VV_y_VH": "VV_y_VH"}
    esperado_obtenido = [
        ("CRS", ref["crs"], c["crs"]), ("ancho", ref["ancho"], c["ancho"]), ("alto", ref["alto"], c["alto"]),
        ("píxeles sin dato SAR", ref["pixeles_nodata"], informe["control"]["pixeles_sar_sin_dato_en_aoi"]),
        ("sin disminución", ref["sin_cambio"], g["pixeles_sin_deteccion"]),
        ("detecciones totales", ref["total_detectado"], g["detecciones"]),
        ("detecciones sobre JRC > 0", ref["total_jrc_con_agua"], u1["pixeles_sar_jrc"]),
        ("hectáreas coincidentes", ref["area_coincidencia_ha"], u1["hectareas_sar_jrc"]),
        ("píxeles SAR válidos sin dato JRC", 0, g["pixeles_sar_validos_sin_jrc"]),
    ]
    for k in claves:
        esperado_obtenido.append((f"{k}: total", ref["clases"][k]["total"], g["clases_sar"][k]["pixeles"]))
        esperado_obtenido.append((f"{k}: con agua JRC", ref["clases"][k]["con_agua"],
                                  u1["por_clase"][k]["coincidentes"]))
    diferencias = []
    for nombre, esperado, obtenido in esperado_obtenido:
        iguales = (math.isclose(esperado, obtenido, abs_tol=0.01) if isinstance(esperado, float) and obtenido is not None
                   else esperado == obtenido)
        if not iguales:
            diferencias.append(f"{nombre}: QGIS {esperado}, V.I.S.O.R. {obtenido}")
    return diferencias


def reproducir_chigorodo(ruta_sar: str | Path, ruta_jrc: str | Path, carpeta_registro: Path | None = None) -> dict:
    """Corre el cruce con los GeoTIFF reales en una carpeta temporal y compara con QGIS.
    Escribe el registro que habilita (o no) el análisis regional. No toca data/analisis/."""
    ref = leer_referencia()
    with tempfile.TemporaryDirectory(prefix="visor_jrc_") as tmp:
        r = cruzar(ruta_sar, ruta_jrc, None, Path(tmp), umbrales=UMBRALES_POR_DEFECTO, usar_cache=False)
        informe = r.datos
    diferencias = comparar_con_referencia(informe, ref)
    registro = {
        "comprobacion": "Reproducción del cruce SAR × JRC de Chigorodó (QGIS del equipo, 13-nov-2026)",
        "resultado": "APROBADA" if not diferencias else "FALLIDA",
        "diferencias": diferencias,
        "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entradas": informe["entradas"],
        "cifras_obtenidas": {"global": informe["global"], "control": informe["control"],
                             "cuadricula": informe["cuadricula"]},
        "referencia": str(RUTA_REFERENCIA.name),
        "nota": "La coincidencia con agua histórica no confirma inundaciones.",
    }
    carpeta = Path(carpeta_registro) if carpeta_registro is not None else CARPETA_REGIONAL
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / REGISTRO_VALIDACION
    if destino.exists():
        destino = carpeta / f"{prefijo_libre(carpeta, 'validacion_chigorodo')}.json"
    destino.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    registro["archivo"] = destino.name
    return registro


def estado_habilitacion(carpeta: Path | None = None, carpeta_sar: Path | None = None) -> tuple[bool, str]:
    """El análisis regional se habilita solo si la última reproducción de Chigorodó fue APROBADA
    y la máscara SAR que se usó sigue teniendo la misma huella."""
    carpeta = Path(carpeta) if carpeta is not None else CARPETA_REGIONAL
    registros = sorted(carpeta.glob("validacion_chigorodo*.json"), key=lambda p: p.stat().st_mtime) \
        if carpeta.is_dir() else []
    if not registros:
        return False, ("Falta reproducir con los GeoTIFF reales el cruce de Chigorodó "
                       "(`python scripts/regional.py reproducir`).")
    try:
        reg = json.loads(registros[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, f"`{registros[-1].name}` no se puede leer."
    if reg.get("resultado") != "APROBADA":
        return False, "La reproducción de Chigorodó NO coincide con QGIS: " + "; ".join(reg.get("diferencias", [])[:3])
    sar = reg.get("entradas", {}).get("sar", {})
    ruta = (Path(carpeta_sar) if carpeta_sar is not None else CARPETA_ANALISIS) / str(sar.get("archivo"))
    if not ruta.is_file() or procedencia.sha256_archivo(ruta) != sar.get("sha256"):
        return False, f"La máscara usada en la reproducción (`{sar.get('archivo')}`) ya no está o cambió."
    return True, f"Reproducción de Chigorodó APROBADA el {reg.get('fecha_utc', '?')[:10]}."
