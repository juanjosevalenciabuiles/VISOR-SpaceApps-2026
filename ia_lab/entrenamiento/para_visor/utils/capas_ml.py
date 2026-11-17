# ========================================
# capas_ml.py
# ========================================

import base64, io, json
from pathlib import Path
import numpy as np
import rasterio
import folium
from matplotlib import colormaps, colors as mcolors
from PIL import Image
from rasterio.warp import calculate_default_transform, reproject, Resampling


def leer_ficha(ruta_tif):
    return json.loads(Path(ruta_tif).with_suffix(".json").read_text(encoding="utf-8"))


def _a_4326(arr, transform, crs, max_lado=1024):
    alto, ancho = arr.shape
    oeste, sur, este, norte = rasterio.transform.array_bounds(alto, ancho, transform)
    t, w, h = calculate_default_transform(crs, "EPSG:4326", ancho, alto, oeste, sur, este, norte)
    f = max(w, h) / max_lado
    if f > 1:
        w, h = int(w / f), int(h / f)
        t, w, h = calculate_default_transform(crs, "EPSG:4326", ancho, alto, oeste, sur, este, norte, dst_width=w, dst_height=h)
    out = np.full((h, w), 255, np.uint8)
    reproject(arr, out, src_transform=transform, src_crs=crs, dst_transform=t, dst_crs="EPSG:4326",
              resampling=Resampling.nearest, src_nodata=255, dst_nodata=255)
    o, s, e, n = rasterio.transform.array_bounds(h, w, t)
    return out, [[s, o], [n, e]]


def _png(rgba):
    buf = io.BytesIO(); Image.fromarray(rgba).save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def capa_clases(mapa, ruta_tif, nombre=None, mostrar=True):
    ficha = leer_ficha(ruta_tif)
    with rasterio.open(ruta_tif) as src:
        arr, bounds = _a_4326(src.read(1), src.transform, src.crs)
    indicio = set(ficha.get("indicio_inundacion", [2, 4, 8]))
    rgba = np.zeros(arr.shape + (4,), np.uint8)
    for k, c in ficha["clases"].items():
        if "color" in c and int(k) not in (0, 255):
            r, g, b = (np.array(mcolors.to_rgb(c["color"])) * 255).astype(np.uint8)
            rgba[arr == int(k)] = (r, g, b, 210 if int(k) in indicio else 140)
    folium.raster_layers.ImageOverlay(_png(rgba), bounds=bounds, show=mostrar,
                                      name=nombre or f"Etiquetado NISAR {ficha.get('fecha', '')}").add_to(mapa)
    return ficha


def capa_probabilidad(mapa, ruta_tif, nombre=None, mostrar=False):
    ficha = leer_ficha(ruta_tif)
    with rasterio.open(ruta_tif) as src:
        arr, bounds = _a_4326(src.read(1), src.transform, src.crs)
    u = ficha.get("umbral_alerta_pct", 0)
    rgba = (colormaps["magma_r"](np.clip(arr / 100.0, 0, 1)) * 255).astype(np.uint8)
    rgba[..., 3] = np.where((arr == 255) | (arr < u), 0, 210)
    folium.raster_layers.ImageOverlay(_png(rgba), bounds=bounds, show=mostrar,
                                      name=nombre or "Modelo B: 5 % más probable de agua nueva").add_to(mapa)
    return ficha


def capa_zonas(mapa, ruta_geojson, nombre="Zonas de 2 km en alerta (Modelo B)", mostrar=True, solo_alerta=True):
    gj = json.loads(Path(ruta_geojson).read_text(encoding="utf-8"))
    if solo_alerta:
        gj = {**gj, "features": [f for f in gj["features"] if f["properties"]["alerta"]]}
    folium.GeoJson(gj, name=nombre, show=mostrar,
                   style_function=lambda f: {"color": "#d62728", "weight": 1.5, "fillOpacity": 0.2},
                   tooltip=folium.GeoJsonTooltip(["pct_celdas_alerta", "prob_media_pct"],
                                                 aliases=["% de celdas en alerta", "Prob. media (%)"])).add_to(mapa)
    return len(gj["features"])


def leyenda_clases(mapa, ficha):
    filas = "".join(f"<div><span style='display:inline-block;width:12px;height:12px;background:{c['color']};margin-right:6px'></span>{c['nombre']}</div>"
                    for k, c in ficha["clases"].items() if "color" in c and k not in ("0", "255"))
    mapa.get_root().html.add_child(folium.Element(
        "<div style='position:fixed;bottom:24px;left:24px;z-index:9999;background:white;padding:8px 10px;border-radius:6px;"
        f"font:12px sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3)'><b>Etiquetado NISAR · {ficha.get('fecha', '')}</b>{filas}"
        "<div style='color:#666;margin-top:4px'>REAL SIN VALIDAR</div></div>"))
