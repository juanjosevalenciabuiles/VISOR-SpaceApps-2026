"""Mosaico de RTC Sentinel-1 de UNA pasada (cuadros consecutivos), por bloques y con caché.

Para AOI regionales que no caben en un cuadro. Solo se unen productos que son
la misma observación cortada en cuadros:

- mismo satélite, misma polarización, escala y radiometría;
- adquiridos seguidos (pocos segundos entre un cuadro y el siguiente);
- mismo CRS, mismo tamaño de píxel y cuadrículas alineadas (no se remuestrea).

No se mezclan fechas, órbitas ni sensores. En el solape entre cuadros gana el
primero (orden temporal) y se mide la diferencia entre ambos: si es grande, se
avisa. Se escribe por bloques (memoria acotada) en `data/sar/mosaicos/`, sin
tocar los RTC ni sobrescribir; un mosaico ya hecho con las mismas entradas
(por SHA-256) se reutiliza.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import RasterioError
from rasterio.transform import Affine
from rasterio.windows import Window

from utils.analisis_sar import ErrorSAR, EscenaRTC, describir_escena, prefijo_libre
from utils.config import DATA_DIR
from utils.procedencia import sha256_archivo

CARPETA_MOSAICOS = DATA_DIR / "sar" / "mosaicos"
MAX_SEGUNDOS_ENTRE_CUADROS = 90
MAX_PIXELES = 1_500_000_000
BLOQUE = 1024
AVISO_DIFERENCIA_DB = 0.5
VERSION = "1.0"


@dataclass
class Mosaico:
    ruta: Path
    ficha: dict
    desde_cache: bool = False


def _alineadas(a: EscenaRTC, b: EscenaRTC) -> bool:
    ta, tb = a.transform, b.transform
    if not (math.isclose(ta.a, tb.a, rel_tol=1e-9) and math.isclose(ta.e, tb.e, rel_tol=1e-9)):
        return False
    dx, dy = (tb.c - ta.c) / ta.a, (tb.f - ta.f) / ta.e
    return abs(dx - round(dx)) < 1e-4 and abs(dy - round(dy)) < 1e-4


def validar(escenas: list[EscenaRTC]) -> list[EscenaRTC]:
    """Ordena por hora y comprueba que los cuadros son de una misma pasada. Lanza ErrorSAR si no."""
    if len(escenas) < 2:
        raise ErrorSAR("Un mosaico necesita al menos dos cuadros.")
    if any(e.fecha is None for e in escenas):
        raise ErrorSAR("Algún RTC no tiene hora de adquisición: no se puede comprobar que sean de la misma pasada.")
    escenas = sorted(escenas, key=lambda e: e.fecha)
    primero = escenas[0]
    for e in escenas[1:]:
        for campo, nombre in (("polarizacion", "polarización"), ("escala", "escala"), ("radiometria", "radiometría"),
                              ("plataforma", "satélite"), ("nodata", "valor sin dato")):
            if getattr(e, campo) != getattr(primero, campo):
                raise ErrorSAR(f"No se unen productos de distinta {nombre}: {primero.ruta.name} "
                               f"({getattr(primero, campo)}) y {e.ruta.name} ({getattr(e, campo)}).")
        if e.crs != primero.crs:
            raise ErrorSAR(f"{e.ruta.name} está en otro CRS ({e.crs.to_string()} y {primero.crs.to_string()}): "
                           "no se remuestrea para unir.")
        if not _alineadas(primero, e):
            raise ErrorSAR(f"{e.ruta.name} no comparte tamaño de píxel o alineación de cuadrícula con "
                           f"{primero.ruta.name}.")
    if primero.plataforma is None:
        raise ErrorSAR("No se reconoce el satélite por el nombre HyP3: no se puede comprobar la pasada.")
    for a, b in zip(escenas, escenas[1:], strict=False):
        salto = (b.fecha - a.fecha).total_seconds()
        if salto <= 0:
            raise ErrorSAR(f"{a.ruta.name} y {b.ruta.name} tienen la misma hora: parecen el mismo cuadro repetido.")
        if salto > MAX_SEGUNDOS_ENTRE_CUADROS:
            raise ErrorSAR(f"Entre {a.ruta.name} y {b.ruta.name} hay {salto:.0f} s: no son cuadros consecutivos de "
                           "una misma pasada. No se mezclan fechas ni órbitas en un mosaico.")
    return escenas


def _clave(huellas: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps({"v": VERSION, "entradas": huellas}, sort_keys=True).encode()).hexdigest()


def _en_cache(carpeta: Path, clave: str) -> Mosaico | None:
    for lateral in sorted(Path(carpeta).glob("mosaico_*.json")) if Path(carpeta).is_dir() else []:
        try:
            ficha = json.loads(lateral.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        ruta = lateral.with_suffix(".tif")
        if ficha.get("clave_cache") == clave and ruta.is_file() and sha256_archivo(ruta) == ficha.get("sha256"):
            return Mosaico(ruta, ficha, desde_cache=True)
    return None


def unir(rutas: list[str | Path], carpeta: str | Path | None = None, bloque: int = BLOQUE,
         usar_cache: bool = True) -> Mosaico:
    """Une los RTC de una pasada en un GeoTIFF nuevo. No modifica las entradas."""
    escenas = validar([describir_escena(Path(r)) for r in rutas])
    carpeta = Path(carpeta) if carpeta is not None else CARPETA_MOSAICOS
    huellas = {e.ruta.name: sha256_archivo(e.ruta) for e in escenas}
    clave = _clave(huellas)
    if usar_cache:
        hit = _en_cache(carpeta, clave)
        if hit is not None:
            return hit
    base = escenas[0]
    paso_x, paso_y = base.transform.a, base.transform.e
    oeste = min(e.limites[0] for e in escenas)
    norte = max(e.limites[3] for e in escenas)
    este = max(e.limites[2] for e in escenas)
    sur = min(e.limites[1] for e in escenas)
    ancho, alto = round((este - oeste) / paso_x), round((norte - sur) / -paso_y)
    if ancho * alto > MAX_PIXELES:
        raise ErrorSAR(f"El mosaico tendría {ancho * alto:,} píxeles (máximo {MAX_PIXELES:,}).")
    transform = Affine(paso_x, 0.0, oeste, 0.0, paso_y, norte)
    nodata = base.nodata if base.nodata is not None else 0.0
    desplazamientos = [(round((e.transform.c - oeste) / paso_x), round((norte - e.transform.f) / -paso_y)) for e in escenas]

    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = prefijo_libre(carpeta, f"mosaico_{base.plataforma}_{base.fecha:%Y%m%dT%H%M%S}_{base.polarizacion}_n{len(escenas)}")
    destino = carpeta / f"{nombre}.tif"
    validos = solape = 0
    suma_dif = 0.0
    try:
        fuentes = [rasterio.open(e.ruta) for e in escenas]
        try:
            with rasterio.open(destino, "w", driver="GTiff", height=alto, width=ancho, count=1, dtype="float32",
                               crs=base.crs, transform=transform, nodata=nodata, compress="deflate", predictor=3,
                               tiled=True, blockxsize=512, blockysize=512, bigtiff="IF_SAFER") as dst:
                for fila in range(0, alto, bloque):
                    for col in range(0, ancho, bloque):
                        h, w = min(bloque, alto - fila), min(bloque, ancho - col)
                        salida = np.full((h, w), nodata, dtype="float32")
                        lleno = np.zeros((h, w), dtype=bool)
                        for src, (dc, df) in zip(fuentes, desplazamientos, strict=True):
                            c0, f0 = col - dc, fila - df
                            if c0 >= src.width or f0 >= src.height or c0 + w <= 0 or f0 + h <= 0:
                                continue
                            datos = src.read(1, window=Window(c0, f0, w, h), boundless=True, fill_value=nodata,
                                             out_dtype="float32")
                            ok = np.isfinite(datos) & (datos != nodata)
                            ambos = ok & lleno
                            if ambos.any() and base.escala != "db":
                                positivos = ambos & (datos > 0) & (salida > 0)
                                suma_dif += float(np.abs(10 * np.log10(datos[positivos] / salida[positivos])).sum())
                                solape += int(positivos.sum())
                            nuevo = ok & ~lleno
                            salida[nuevo] = datos[nuevo]
                            lleno |= ok
                        validos += int(lleno.sum())
                        dst.write(salida, 1, window=Window(col, fila, w, h))
                dst.update_tags(
                    VISOR_MOSAICO="1", SENSOR="Sentinel-1", PLATAFORMA=base.plataforma, POLARIZACION=base.polarizacion,
                    ESCALA=base.escala, RADIOMETRIA=base.radiometria or "", FECHA_ADQUISICION=f"{base.fecha:%Y-%m-%dT%H:%M:%S}",
                    ENTRADAS=", ".join(huellas))
        finally:
            for src in fuentes:
                src.close()
    except (RasterioError, OSError) as e:
        destino.unlink(missing_ok=True)
        raise ErrorSAR(f"No se pudo escribir el mosaico: {e}") from e
    if {e.ruta.name: sha256_archivo(e.ruta) for e in escenas} != huellas:
        destino.unlink(missing_ok=True)
        raise ErrorSAR("Un RTC cambió durante la unión; se descartó el mosaico.")
    diferencia = round(suma_dif / solape, 3) if solape else None
    avisos = []
    if validos < ancho * alto:
        avisos.append(f"El {1 - validos / (ancho * alto):.0%} del rectángulo del mosaico queda sin dato "
                      "(fuera de los cuadros o sin dato en ellos).")
    if diferencia is not None and diferencia > AVISO_DIFERENCIA_DB:
        avisos.append(f"En el solape, los cuadros difieren {diferencia} dB de media: revisa que sean de la misma "
                      "pasada y del mismo procesamiento.")
    ficha = {
        "tipo": "mosaico_rtc_sentinel1", "version": VERSION, "clave_cache": clave,
        "creado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sensor": "Sentinel-1", "plataforma": base.plataforma, "polarizacion": base.polarizacion,
        "escala": base.escala, "radiometria": base.radiometria,
        "fecha_utc": [f"{e.fecha:%Y-%m-%dT%H:%M:%S}" for e in escenas],
        "entradas": huellas, "entradas_intactas": True,
        "cuadricula": {"crs": base.crs.to_string(), "ancho": ancho, "alto": alto, "transform": list(transform)[:6]},
        "regla_solape": "gana el primer cuadro en orden temporal; sin remuestreo",
        "solape": {"pixeles": solape, "diferencia_media_abs_db": diferencia},
        "pixeles_validos": validos, "pixeles_sin_dato": ancho * alto - validos, "nodata": nodata,
        "sha256": sha256_archivo(destino), "avisos": avisos,
    }
    with destino.with_suffix(".json").open("x", encoding="utf-8") as f:
        json.dump(ficha, f, ensure_ascii=False, indent=2)
    return Mosaico(destino, ficha)
