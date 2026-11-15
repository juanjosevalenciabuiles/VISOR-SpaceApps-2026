"""Política conservadora para comparar WTR, sin asignar códigos no verificados.

El llamador debe aportar un diccionario de clases obtenido de la especificación
oficial de la versión del producto y una máscara QA por cada observación.
Este módulo no hace IO ni confirma inundaciones.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence


def comparar_wtr(
    anterior: Sequence[Sequence[int]],
    posterior: Sequence[Sequence[int]],
    qa_anterior: Sequence[Sequence[bool]],
    qa_posterior: Sequence[Sequence[bool]],
    *,
    codigos: Mapping[str, int],
    version_verificada: bool = False,
    mascara_aoi: Sequence[Sequence[bool]] | None = None,
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
