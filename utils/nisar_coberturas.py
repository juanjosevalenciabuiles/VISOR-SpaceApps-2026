"""Selección por cobertura geodésica de PARES NISAR, sin descargar imágenes.

Las huellas CMR son metadatos y nunca sustituyen el QA de los píxeles GCOV.
La comparación se hace sobre la intersección T1 ∩ T2 ∩ AOI (no huellas aisladas).
"""
from __future__ import annotations

import hashlib
from dataclasses import replace

from pyproj import Geod
from shapely.geometry import Point, box

from utils import nisar_auto

GEOD = Geod(ellps="WGS84")
MAX_PARES_VISIBLES = 3
MAX_PARES_LISTA = 30


def area_m2(geometria) -> float:
    if geometria is None or geometria.is_empty:
        return 0.0
    return abs(float(GEOD.geometry_area_perimeter(geometria)[0]))


def interseccion(par, aoi):
    """Geometría efectivamente cubierta por ambas huellas de CMR dentro de AOI."""
    a = getattr(par.antes, "huella", None)
    b = getattr(par.despues, "huella", None)
    if a is None or b is None or a.is_empty or b.is_empty:
        return box(0, 0, 0, 0).difference(box(0, 0, 0, 0))
    region = aoi if hasattr(aoi, "intersection") else box(*aoi)
    return region.intersection(a).intersection(b)


def cobertura(par, aoi) -> tuple[float, object]:
    region = aoi if hasattr(aoi, "intersection") else box(*aoi)
    comun = interseccion(par, region)
    total = area_m2(region)
    fraccion = min(1.0, max(0.0, area_m2(comun) / total)) if total else 0.0
    return fraccion, comun


def identificador(par) -> str:
    """ID estable derivado de granules reales, no de un índice de pantalla."""
    nombre = par.antes.granule + "|" + par.despues.granule
    return hashlib.sha256(nombre.encode("utf-8")).hexdigest()[:16]


def opciones(resultado, pares, max_gb: float = 15.0,
             punto_prioritario: tuple[float, float] | None = None) -> list[dict]:
    """Clasifica pares compatibles. No consulta red, no lee archivos ni lanza jobs.

    Los 30 mejores pares se conservan en memoria de sesión; el mapa muestra 3
    a la vez, y la lista permite elegir los demás. Se mantiene la misma política
    de presupuesto y cobertura mínima de nisar_auto.planear.
    """
    region = box(*resultado.region.limites)
    punto = Point(*punto_prioritario) if punto_prioritario else None
    calculados = []
    for par in pares:
        frac, geometria = cobertura(par, region)
        if frac <= 0:
            continue
        cubre_punto = punto is None or geometria.covers(punto)
        calculados.append((frac, cubre_punto, par, geometria))
    calculados.sort(key=lambda x: (-int(x[1]), -x[0], x[2].dias,
                                  x[2].antes.granule))
    salida = []
    for frac, cubre_punto, par, geometria in calculados[:MAX_PARES_LISTA]:
        plan = None
        bloqueo = None
        try:
            # Reutilizar el motor existente y sus límites sin permitir una sola escena.
            from dataclasses import replace as reemplazar
            evaluado = reemplazar(par, cobertura_comun=frac)
            plan = nisar_auto.planear(
                replace(resultado, pares=[evaluado]), max_gb=max_gb,
                aceptar_escena_unica=False,
                punto_prioritario=punto_prioritario if cubre_punto and punto else None,
            )
        except (nisar_auto.ErrorAutoNISAR, ValueError) as exc:
            bloqueo = str(exc)
        salida.append({
            "id": identificador(par), "par": par, "cobertura": frac,
            "geometria": geometria, "cubre_punto": cubre_punto,
            "plan": plan, "bloqueo": bloqueo,
        })
    return salida


def seleccion_actual(estado: dict | None, firma) -> dict | None:
    """Solo acepta el par de la misma AOI y período, sin recuperar una sesión vieja."""
    if not estado or estado.get("firma") != firma:
        return None
    ident = estado.get("seleccionado")
    return next((x for x in estado.get("opciones") or [] if x["id"] == ident), None)


def opciones_mapa(estado: dict | None, firma) -> list[dict]:
    if not estado or estado.get("firma") != firma:
        return []
    todos = estado.get("opciones") or []
    primeros = todos[:MAX_PARES_VISIBLES]
    seleccionado = seleccion_actual(estado, firma)
    if seleccionado and all(x["id"] != seleccionado["id"] for x in primeros):
        primeros = [*primeros[:MAX_PARES_VISIBLES - 1], seleccionado]
    return primeros
