"""Huellas CMR sobre el mapa Folium; jamás representa agua ni inundaciones."""
from __future__ import annotations

import folium
from shapely.geometry import box

from utils.i18n import tr
from utils import nisar_coberturas as geo

COLOR_T1 = "#b59aff"
COLOR_T2 = "#42d9ff"
COLOR_COMUN = "#52e3a9"
COLOR_OTRO = "#d3af62"


def _forma(grupo, geometria, color: str, texto: str, *,
           opacidad: float, relleno: bool, linea: str = "") -> None:
    if geometria is None or geometria.is_empty:
        return
    # Simplificación solo gráfica: porcentajes/QA calculados sobre huellas íntegros.
    dibujo = geometria.simplify(0.0002, preserve_topology=True)
    folium.GeoJson(
        data=dibujo.__geo_interface__, name=texto,
        style_function=lambda _, col=color, fo=opacidad, fill=relleno, dash=linea: {
            "color": col, "weight": 2.2 if fo > 0.12 else 1.2,
            "opacity": 0.96, "fill": fill, "fillColor": col,
            "fillOpacity": fo if fill else 0.0, "dashArray": dash,
        },
        tooltip=folium.Tooltip(texto, sticky=True),
        control=False,
    ).add_to(grupo)


def grupos(estado: dict | None, firma) -> list[folium.FeatureGroup]:
    """3 pares visibles, T1/T2 del seleccionado y hueco gris del AOI."""
    opciones = geo.opciones_mapa(estado, firma)
    if not opciones:
        return []
    elegido = geo.seleccion_actual(estado, firma)
    grupo = folium.FeatureGroup(
        name=tr("Coberturas de pares NISAR (CMR)", "NISAR pair footprints (CMR)"),
        show=True, control=False,
    )
    for indice, item in enumerate(opciones, 1):
        fraccion = item["cobertura"]
        seleccionado = bool(elegido and elegido["id"] == item["id"])
        descripcion = tr(
            f"Par {indice}: cobertura CMR {fraccion:.0%} (NO píxeles verificados). Clic para elegir.",
            f"Pair {indice}: CMR footprint {fraccion:.0%} (NOT verified pixels). Click to select.",
        )
        _forma(grupo, item["geometria"], COLOR_COMUN if seleccionado else COLOR_OTRO,
               descripcion, opacidad=0.23 if seleccionado else 0.065, relleno=True)
    if elegido:
        p = elegido["par"]
        aoi = box(*estado["firma"][0])
        # Mostrar T1/T2 íntegros recortados alrededor del AOI, no raster SAR.
        for escena, color, nombre in (
            (p.antes, COLOR_T1, "T1"), (p.despues, COLOR_T2, "T2"),
        ):
            if escena.huella is not None:
                _forma(grupo, escena.huella.intersection(aoi.buffer(0.03)), color,
                       f"{nombre} · {escena.nombre.inicio:%Y-%m-%d} · NASA CMR",
                       opacidad=0.0, relleno=False, linea="5 5")
        vacio = aoi.difference(elegido["geometria"])
        _forma(grupo, vacio, "#8d98a7",
               tr("Zona sin cobertura común de catálogo; no implica inundación.",
                  "No common catalog coverage; this is not a flood signal."),
               opacidad=0.10, relleno=True, linea="3 5")
    return [grupo]
