"""Política conservadora para comparar WTR, sin asignar códigos no verificados.

El llamador debe aportar un diccionario de clases obtenido de la especificación
oficial de la versión del producto y una máscara QA por cada observación.
Este módulo no hace IO ni confirma inundaciones.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

from rasterio.crs import CRS


def _grilla_verificada(info: Mapping | None) -> tuple[CRS, tuple[float, ...]]:
    """Exigir CRS real y geotransformación afín en el orden rasterio (a,b,c,d,e,f)."""
    if not isinstance(info, Mapping):
        raise ValueError("SIN_GEOREFERENCIA: falta CRS/transform real del GeoTIFF")
    try:
        crs = CRS.from_user_input(info.get("crs"))
        transformacion = tuple(float(v) for v in info["transform"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("SIN_GEOREFERENCIA: CRS o transformación inválidos") from exc
    if len(transformacion) == 9:
        if transformacion[6:] != (0.0, 0.0, 1.0):
            raise ValueError("Transformación afín homogénea inválida")
        transformacion = transformacion[:6]
    if (len(transformacion) != 6 or not all(math.isfinite(v) for v in transformacion)
            or abs(transformacion[0] * transformacion[4]
                   - transformacion[1] * transformacion[3]) < 1e-12):
        raise ValueError("Transformación afín de GeoTIFF inválida o degenerada")
    return crs, transformacion


def _comprobar_alineacion(anterior: Mapping | None, posterior: Mapping | None) -> None:
    """Bloqueo P1: mismas dimensiones NO implican los mismos píxeles geográficos."""
    crs_a, af_a = _grilla_verificada(anterior)
    crs_b, af_b = _grilla_verificada(posterior)
    if crs_a != crs_b:
        raise ValueError("CRS distintos: remuestreo explícito requerido antes de comparar WTR")
    if not all(math.isclose(x, y, rel_tol=1e-12, abs_tol=1e-9)
               for x, y in zip(af_a, af_b, strict=True)):
        raise ValueError("Cuadrículas WTR desalineadas: no comparar píxeles desplazados")


def comparar_wtr(
    anterior: Sequence[Sequence[int]],
    posterior: Sequence[Sequence[int]],
    qa_anterior: Sequence[Sequence[bool]],
    qa_posterior: Sequence[Sequence[bool]],
    *,
    codigos: Mapping[str, int],
    version_verificada: bool = False,
    mascara_aoi: Sequence[Sequence[bool]] | None = None,
    georef_anterior: Mapping | None = None,
    georef_posterior: Mapping | None = None,
) -> dict:
    """Devuelve clases exploratorias 0=no agua, 1=persistente, 2=nueva, 255=sin QA.

    Rechaza clases desconocidas, ambiguas y ausencia de validación del codebook.
    No distingue inundación de otros cambios de agua observada.
    """
    if not version_verificada:
        raise ValueError("La tabla de clases WTR no está verificada")
    if set(codigos) != {"agua", "no_agua"}:
        raise ValueError("Se requieren únicamente códigos inequívocos de agua/no agua")
    agua, seco = codigos["agua"], codigos["no_agua"]
    if type(agua) is not int or type(seco) is not int or agua == seco:
        raise ValueError("Códigos WTR inválidos")
    grids = (anterior, posterior, qa_anterior, qa_posterior)
    if mascara_aoi is not None:
        grids += (mascara_aoi,)
    # No clasificar ni un píxel sin demostrar su identidad espacial.
    _comprobar_alineacion(georef_anterior, georef_posterior)
    if not anterior or not anterior[0]:
        raise ValueError("Raster vacío")
    alto, ancho = len(anterior), len(anterior[0])
    if any(len(grid) != alto or any(len(row) != ancho for row in grid) for grid in grids):
        raise ValueError("Las matrices WTR/QA deben coincidir")
    if mascara_aoi is not None and any(type(v) is not bool for row in mascara_aoi for v in row):
        raise ValueError("Máscara AOI debe ser booleana")
    total_aoi = sum(sum(row) for row in mascara_aoi) if mascara_aoi is not None else alto * ancho
    if total_aoi == 0:
        raise ValueError("AOI sin píxeles dentro de la cuadrícula")
    salida = []
    validos = 0
    for y in range(alto):
        fila = []
        for x in range(ancho):
            pre, post = anterior[y][x], posterior[y][x]
            if mascara_aoi is not None and not mascara_aoi[y][x]:
                valor = 255
            elif not (qa_anterior[y][x] is True and qa_posterior[y][x] is True):
                valor = 255
            elif pre not in (agua, seco) or post not in (agua, seco):
                valor = 255
            elif post == agua:
                valor = 1 if pre == agua else 2
            else:
                valor = 0
            validos += valor != 255
            fila.append(valor)
        salida.append(fila)
    return {
        "estado": "APTA" if validos == total_aoi else "NO_APTA",
        "clases": salida if validos == total_aoi else None,
        "pixeles_validos": validos,
        "pixeles_totales": total_aoi,
        "pixeles_fuera_aoi": alto * ancho - total_aoi,
        "cobertura_qa_completa": validos == total_aoi,
        "advertencia": "Cambio exploratorio de agua observada; NO inundación confirmada.",
    }
