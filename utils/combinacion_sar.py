"""Combinación VV/VH de las máscaras del motor SAR, con ficha de procedencia.

Toma dos máscaras de cambios producidas por `utils/analisis_sar.py` para el
MISMO par de fechas, una en VV y otra en VH, y clasifica cada píxel según en
qué polarización hubo una disminución significativa de retrodispersión:

    0   sin disminución significativa en VV ni en VH
        (incluye aumentos y señal baja en ambas fechas)
    1   disminución significativa solo en VV
    2   disminución significativa solo en VH
    3   disminución significativa en VV y en VH (coincidencia)
    255 sin dato en alguna de las dos máscaras

La regla es exactamente la del script exploratorio con que se generó
`coincidencia_VV_VH_Chigorodo.tif` (ver `clasificar`); `comparar_geotiff`
comprueba píxel a píxel que dos productos son equivalentes.

Además del GeoTIFF escribe `<nombre>.json`, una ficha de procedencia
(`utils/procedencia.py`) con entradas y sus huellas SHA-256, fechas, sensor,
polarizaciones, parámetros, método, estadísticas por clase y limitaciones.
La ficha solo declara REAL SIN VALIDAR si todos los datos de trazabilidad se
pueden leer de las máscaras de entrada; si falta alguno, la declara como
procedencia no declarada y enumera lo que falta.

No modifica el motor: solo usa sus constantes y su cuadrícula. No depende de
Streamlit. IMPORTANTE: ninguna clase confirma una inundación.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import RasterioError

from utils import procedencia
from utils.analisis_sar import (
    ADVERTENCIA,
    DISMINUCION,
    LIMITACIONES,
    NODATA_MASCARA,
    VERSION_MOTOR,
    Cuadricula,
    ErrorSAR,
)

VERSION_COMBINACION = "1.0"
TIPO_PRODUCTO = "coincidencia_vv_vh"
SIN_DISMINUCION, SOLO_VV, SOLO_VH, AMBAS = 0, 1, 2, 3

# (valor, etiqueta, color). Clase 0 transparente: no es un cambio.
CLASES_COINCIDENCIA: tuple[tuple[int, str, str | None], ...] = (
    (SIN_DISMINUCION, "Sin disminución significativa en VV ni en VH", None),
    (SOLO_VV, "Disminución significativa solo en VV", "#00F0FF"),
    (SOLO_VH, "Disminución significativa solo en VH", "#FF9F0A"),
    (AMBAS, "Disminución significativa en VV y VH (coincidencia)", "#7D7AFF"),
)
NOTA_CLASE_0 = (
    "La clase 0 no significa «sin cambios»: incluye píxeles con aumento significativo y píxeles "
    "con señal baja en ambas fechas. Solo indica que no hubo disminución significativa en ninguna "
    "de las dos polarizaciones."
)
LIMITACIONES_COMBINACION: tuple[str, ...] = (
    "La coincidencia entre VV y VH indica que la disminución es consistente en las dos "
    "polarizaciones, pero no la confirma: ambas responden también a humedad del suelo, cosechas, "
    "labores agrícolas o viento sobre el agua.",
    "Las dos máscaras deben venir del mismo par de fechas, con los mismos parámetros y en la misma "
    "cuadrícula; la combinación no remuestrea.",
    "Conteos y hectáreas se calculan sobre la cuadrícula proyectada del archivo, a resolución completa.",
    NOTA_CLASE_0,
)
METODO_COMBINACION = (
    "Combinación píxel a píxel de las máscaras VV y VH (clase 1 del motor = disminución "
    "significativa): 1 si solo VV, 2 si solo VH, 3 si ambas, 0 si ninguna; 255 si falta dato en "
    "alguna de las dos."
)
_PLATAFORMAS = {"S1A": "Sentinel-1A", "S1B": "Sentinel-1B", "S1C": "Sentinel-1C", "S1D": "Sentinel-1D"}


def clasificar(vv: np.ndarray, vh: np.ndarray) -> np.ndarray:
    """Regla de combinación (idéntica a la del script exploratorio)."""
    vv, vh = np.asarray(vv), np.asarray(vh)
    if vv.shape != vh.shape:
        raise ErrorSAR("Las máscaras VV y VH no tienen el mismo tamaño.")
    validos = (vv != NODATA_MASCARA) & (vh != NODATA_MASCARA)
    dis_vv, dis_vh = vv == DISMINUCION, vh == DISMINUCION
    resultado = np.zeros(vv.shape, dtype="uint8")
    resultado[~validos] = NODATA_MASCARA
    resultado[validos & dis_vv & ~dis_vh] = SOLO_VV
    resultado[validos & ~dis_vv & dis_vh] = SOLO_VH
    resultado[validos & dis_vv & dis_vh] = AMBAS
    return resultado


def estadisticas_clases(
    clases: np.ndarray,
    area_pixel_ha: float | None,
    definicion=CLASES_COINCIDENCIA,
    nodata: int = NODATA_MASCARA,
) -> dict:
    """Píxeles, porcentaje del área válida y hectáreas por clase."""
    clases = np.asarray(clases)
    total = int(clases.size)
    sin_dato = int((clases == nodata).sum())
    validos = total - sin_dato
    resumen = {
        "pixeles_totales": total, "pixeles_validos": validos, "pixeles_sin_dato": sin_dato,
        "area_pixel_ha": area_pixel_ha, "clases": {},
    }
    conocidas = 0
    for valor, etiqueta, _ in definicion:
        n = int((clases == valor).sum())
        conocidas += n
        resumen["clases"][str(valor)] = {
            "etiqueta": etiqueta, "pixeles": n,
            "porcentaje_de_validos": round(100.0 * n / validos, 3) if validos else 0.0,
            "area_ha": round(n * area_pixel_ha, 2) if area_pixel_ha is not None else None,
        }
    resumen["pixeles_otros_valores"] = validos - conocidas
    return resumen


# ---------------------------------------------------------------------------
# Entradas
# ---------------------------------------------------------------------------

@dataclass
class MascaraEntrada:
    ruta: Path
    polarizacion: str | None
    fechas: list[str]
    fuente: str | None
    parametros: dict | None
    rtc: dict[str, str | None]
    motor_version: str | None
    sha256: str
    cuadricula: Cuadricula
    datos: np.ndarray
    informe: dict | None = None
    avisos: list[str] = field(default_factory=list)

    def resumen(self) -> dict:
        return {
            "archivo": self.ruta.name, "sha256": self.sha256, "polarizacion": self.polarizacion,
            "fechas": self.fechas, "motor_version": self.motor_version, "parametros": self.parametros,
            "rtc_antes": self.rtc.get("antes"), "rtc_despues": self.rtc.get("despues"),
            "informe": self.informe_ruta.name if self.informe is not None else None,
        }

    @property
    def informe_ruta(self) -> Path:
        return self.ruta.with_name(self.ruta.name.replace("_mascara.tif", "_analisis.json"))


def _fechas(texto: str | None) -> list[str]:
    return re.findall(r"\d{4}-\d{2}-\d{2}", texto or "")


def leer_mascara(ruta: str | Path, polarizacion: str) -> MascaraEntrada:
    """Lee una máscara del motor y lo que declara sobre su origen."""
    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorSAR(f"No se encontró la máscara `{ruta.name}`.")
    try:
        with rasterio.open(ruta) as src:
            if src.crs is None:
                raise ErrorSAR(f"`{ruta.name}` no tiene sistema de coordenadas (CRS).")
            if src.dtypes[0] != "uint8":
                raise ErrorSAR(f"`{ruta.name}` no es una máscara de clases (uint8).")
            datos = src.read(1)
            cuad = Cuadricula(src.crs, src.transform, src.width, src.height)
            tags = {k.upper(): str(v) for k, v in src.tags().items()}
            nodata = src.nodata
    except ErrorSAR:
        raise
    except (RasterioError, OSError, ValueError) as e:
        raise ErrorSAR(f"`{ruta.name}` no es un GeoTIFF válido o está dañado.") from e

    avisos: list[str] = []
    if nodata is not None and int(nodata) != NODATA_MASCARA:
        raise ErrorSAR(f"`{ruta.name}` usa NoData {nodata:g}; las máscaras del motor usan {NODATA_MASCARA}.")
    if tags.get("VISOR_ANALISIS") != "1":
        avisos.append(f"{ruta.name}: no lleva la marca VISOR_ANALISIS del motor; su origen no se puede verificar.")
    declarada = tags.get("POLARIZACION", "").upper() or None
    if declarada and declarada != polarizacion:
        raise ErrorSAR(f"`{ruta.name}` es una máscara {declarada}, pero se indicó como {polarizacion}.")
    if declarada is None:
        avisos.append(f"{ruta.name}: no declara su polarización.")
    try:
        parametros = json.loads(tags["PARAMETROS"]) if "PARAMETROS" in tags else None
    except ValueError:
        parametros = None
        avisos.append(f"{ruta.name}: los parámetros guardados no se pudieron leer.")

    entrada = MascaraEntrada(
        ruta=ruta, polarizacion=declarada, fechas=_fechas(tags.get("FECHA")), fuente=tags.get("FUENTE"),
        parametros=parametros, rtc={"antes": tags.get("ENTRADA_ANTES"), "despues": tags.get("ENTRADA_DESPUES")},
        motor_version=tags.get("MOTOR_VERSION"), sha256=procedencia.sha256_archivo(ruta),
        cuadricula=cuad, datos=datos, avisos=avisos,
    )
    if entrada.informe_ruta.exists():
        try:
            entrada.informe = json.loads(entrada.informe_ruta.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            avisos.append(f"{entrada.informe_ruta.name}: el informe del motor no se pudo leer.")
    return entrada


def _misma_cuadricula(a: Cuadricula, b: Cuadricula) -> bool:
    return a.crs == b.crs and (a.ancho, a.alto) == (b.ancho, b.alto) and a.transform.almost_equals(b.transform)


def _plataformas(*entradas: MascaraEntrada) -> list[str]:
    encontradas: set[str] = set()
    for e in entradas:
        if isinstance(e.informe, dict):
            for escena in (e.informe.get("entradas") or {}).values():
                if isinstance(escena, dict) and escena.get("plataforma"):
                    encontradas.add(str(escena["plataforma"]))
        encontradas.update(re.findall(r"S1[A-D]", e.fuente or ""))
    return sorted(encontradas)


def _radiometria(*entradas: MascaraEntrada) -> str | None:
    for e in entradas:
        if isinstance(e.informe, dict):
            for escena in (e.informe.get("entradas") or {}).values():
                if isinstance(escena, dict) and escena.get("radiometria"):
                    return str(escena["radiometria"])
    return None


# ---------------------------------------------------------------------------
# Combinación
# ---------------------------------------------------------------------------

@dataclass
class ResultadoCombinacion:
    geotiff: Path
    ficha_ruta: Path
    ficha: dict

    @property
    def estado(self) -> str:
        return self.ficha["procedencia"]["estado"]

    @property
    def estadisticas(self) -> dict:
        return self.ficha["estadisticas"]


def combinar_vv_vh(
    ruta_vv: str | Path,
    ruta_vh: str | Path,
    carpeta_salida: str | Path | None = None,
    prefijo: str | None = None,
    zona: str | None = None,
) -> ResultadoCombinacion:
    """Combina las máscaras VV y VH del mismo par y escribe GeoTIFF + ficha JSON.

    `zona` es solo una etiqueta descriptiva (por ejemplo, "Chigorodó, Antioquia");
    se guarda como declarada por quien ejecuta, no como dato medido.
    """
    if Path(ruta_vv).resolve() == Path(ruta_vh).resolve():
        raise ErrorSAR("La máscara VV y la VH son el mismo archivo.")
    vv = leer_mascara(ruta_vv, "VV")
    vh = leer_mascara(ruta_vh, "VH")
    if not _misma_cuadricula(vv.cuadricula, vh.cuadricula):
        raise ErrorSAR("Las cuadrículas VV y VH son incompatibles (CRS, tamaño o transformación distintos).")
    if vv.fechas and vh.fechas and vv.fechas != vh.fechas:
        raise ErrorSAR(f"Las máscaras no son del mismo par de fechas ({' / '.join(vv.fechas)} y "
                       f"{' / '.join(vh.fechas)}).")

    avisos = [*vv.avisos, *vh.avisos]
    if vv.parametros and vh.parametros and vv.parametros != vh.parametros:
        avisos.append("Las máscaras VV y VH se generaron con parámetros distintos; revisa los umbrales.")

    clases = clasificar(vv.datos, vh.datos)
    cuad = vv.cuadricula
    resumen = estadisticas_clases(clases, cuad.area_pixel_ha)
    if cuad.area_pixel_ha is None:
        avisos.append("El CRS no es proyectado: no se calculan hectáreas.")

    fechas = vv.fechas or vh.fechas
    plataformas = _plataformas(vv, vh)
    sensor = (" y ".join(_PLATAFORMAS.get(p, p) for p in plataformas) + " (ESA/Copernicus) · SAR banda C"
              if plataformas else None)
    radiometria = _radiometria(vv, vh)
    if prefijo is None:
        sello = "_".join(f.replace("-", "") for f in fechas) or "sinfecha"
        prefijo = f"coincidencia_VV_VH_{sello}"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", prefijo):
        raise ErrorSAR("El prefijo de salida solo puede tener letras, números, guiones y puntos.")
    carpeta = Path(carpeta_salida) if carpeta_salida is not None else vv.ruta.parent
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_tif = carpeta / f"{prefijo}.tif"
    if ruta_tif.resolve() in (vv.ruta.resolve(), vh.ruta.resolve()):
        raise ErrorSAR("La salida no puede sobrescribir una de las máscaras de entrada.")

    fuente = (f"{' y '.join(_PLATAFORMAS.get(p, p) for p in plataformas)}, ASF HyP3 RTC"
              f"{' ' + radiometria if radiometria else ''} · combinación VV/VH de V.I.S.O.R."
              if plataformas else "Máscaras del motor SAR de V.I.S.O.R. · combinación VV/VH")
    producto = "Coincidencia de disminuciones de retrodispersión VV/VH (indicios, sin validar)"
    etiquetas = {
        "TIPO_PRODUCTO": TIPO_PRODUCTO, "PRODUCTO": producto, "UNIDADES": "clase", "FUENTE": fuente,
        "FECHA": " / ".join(fechas) if fechas else "fecha desconocida", "POLARIZACION": "VV+VH",
        "MOTOR_VERSION": vv.motor_version or VERSION_MOTOR, "COMBINACION_VERSION": VERSION_COMBINACION,
        "ENTRADA_VV": vv.ruta.name, "ENTRADA_VH": vh.ruta.name, "ADVERTENCIA": ADVERTENCIA,
        "CLASES": json.dumps({str(v): e for v, e, _ in CLASES_COINCIDENCIA}, ensure_ascii=False),
        **{f"CLASE_{v}": e for v, e, _ in CLASES_COINCIDENCIA}, f"CLASE_{NODATA_MASCARA}": "Sin dato",
    }
    with rasterio.open(
        ruta_tif, "w", driver="GTiff", height=cuad.alto, width=cuad.ancho, count=1, dtype="uint8",
        crs=cuad.crs, transform=cuad.transform, nodata=NODATA_MASCARA, compress="deflate",
    ) as dst:
        dst.write(clases, 1)
        dst.update_tags(**etiquetas)

    umbral = (vv.parametros or {}).get("umbral_disminucion_db")
    ventana = (vv.parametros or {}).get("ventana_speckle")
    metodo = [
        "Motor SAR de V.I.S.O.R. (utils/analisis_sar.py), por separado en VV y en VH: productos RTC "
        "en potencia, lectura en una cuadrícula común"
        + (f", media móvil de {ventana}×{ventana} px en potencia" if ventana and ventana > 1
           else ", sin filtro de speckle" if ventana == 1 else ", filtro de speckle no declarado")
        + ", conversión a dB y diferencia posterior − anterior.",
        f"Disminución significativa: diferencia ≤ −{umbral:g} dB." if umbral is not None
        else "Umbral de disminución: no declarado en las máscaras.",
        METODO_COMBINACION,
    ]
    aoi = next((e.informe.get("aoi_lonlat") for e in (vv, vh)
                if isinstance(e.informe, dict) and e.informe.get("aoi_lonlat")), None)

    bloque = {
        "estado": procedencia.REAL_SIN_VALIDAR,
        "sensor": sensor,
        "producto_base": f"ASF HyP3 RTC{' ' + radiometria if radiometria else ''}" if plataformas else None,
        "fechas": fechas,
        "polarizaciones": ["VV", "VH"] if vv.polarizacion == "VV" and vh.polarizacion == "VH" else [],
        "metodo": " ".join(metodo),
        "entradas": [vv.resumen(), vh.resumen()],
        "generado_por": {
            "funcion": "utils.combinacion_sar.combinar_vv_vh", "version_combinacion": VERSION_COMBINACION,
            "motor": "utils/analisis_sar.py", "version_motor": vv.motor_version or VERSION_MOTOR,
        },
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "archivo": {"nombre": ruta_tif.name, "sha256": procedencia.sha256_archivo(ruta_tif)},
        "validacion": None,
    }
    faltantes = [c for c in procedencia.CAMPOS_TRAZABILIDAD if procedencia.campo_vacio(bloque.get(c))]
    if vv.motor_version is None or vh.motor_version is None:
        faltantes.append("marca del motor en las máscaras")
    if faltantes:
        bloque["estado"] = procedencia.NO_DECLARADA
        bloque["faltantes"] = faltantes
        avisos.append("Trazabilidad incompleta (" + ", ".join(faltantes) + "): la ficha NO declara "
                      "el producto como real.")

    ficha = {
        "esquema": procedencia.ESQUEMA_FICHA,
        "tipo_producto": TIPO_PRODUCTO,
        "producto": producto,
        "fuente": fuente,
        "fecha": etiquetas["FECHA"],
        "unidades": "clase",
        "advertencia": ADVERTENCIA,
        "zona_declarada": zona,
        "procedencia": bloque,
        "parametros": {"VV": vv.parametros, "VH": vh.parametros},
        "aoi_lonlat": aoi,
        "cuadricula": {
            "crs": cuad.crs.to_string(), "transform": list(cuad.transform)[:6], "ancho": cuad.ancho,
            "alto": cuad.alto, "resolucion": [abs(cuad.transform.a), abs(cuad.transform.e)],
            "limites": list(cuad.limites), "limites_lonlat": list(cuad.limites_lonlat),
        },
        "clases": {str(v): e for v, e, _ in CLASES_COINCIDENCIA} | {str(NODATA_MASCARA): "Sin dato"},
        "nota_clase_0": NOTA_CLASE_0,
        "estadisticas": resumen,
        "avisos": avisos,
        "limitaciones": [*LIMITACIONES_COMBINACION, *LIMITACIONES],
    }
    ruta_ficha = ruta_tif.with_suffix(".json")
    ruta_ficha.write_text(json.dumps(ficha, ensure_ascii=False, indent=2), encoding="utf-8")
    return ResultadoCombinacion(ruta_tif, ruta_ficha, ficha)


# ---------------------------------------------------------------------------
# Equivalencia y descripción
# ---------------------------------------------------------------------------

def describir_clases(ruta: str | Path, definicion=CLASES_COINCIDENCIA) -> dict:
    """Estadísticas por clase de un GeoTIFF de clases ya existente, a resolución completa."""
    ruta = Path(ruta)
    try:
        with rasterio.open(ruta) as src:
            datos = src.read(1)
            cuad = Cuadricula(src.crs, src.transform, src.width, src.height) if src.crs else None
            nodata = int(src.nodata) if src.nodata is not None else NODATA_MASCARA
    except (RasterioError, OSError, ValueError) as e:
        raise ErrorSAR(f"`{ruta.name}` no es un GeoTIFF válido o está dañado.") from e
    resumen = estadisticas_clases(datos, cuad.area_pixel_ha if cuad else None, definicion, nodata)
    resumen["crs"] = cuad.crs.to_string() if cuad else None
    resumen["dimensiones"] = [datos.shape[1], datos.shape[0]]
    return resumen


def comparar_geotiff(ruta_a: str | Path, ruta_b: str | Path) -> dict:
    """Compara dos GeoTIFF de clases: cuadrícula y cada píxel (NoData incluido)."""
    with rasterio.open(ruta_a) as a, rasterio.open(ruta_b) as b:
        cuadricula = (a.crs == b.crs and a.shape == b.shape and a.transform.almost_equals(b.transform))
        nodata = a.nodata == b.nodata
        distintos = int((a.read(1) != b.read(1)).sum()) if a.shape == b.shape else None
    return {
        "equivalentes": bool(cuadricula and nodata and distintos == 0),
        "misma_cuadricula": bool(cuadricula), "mismo_nodata": bool(nodata), "pixeles_distintos": distintos,
        "a": describir_clases(ruta_a), "b": describir_clases(ruta_b),
    }
