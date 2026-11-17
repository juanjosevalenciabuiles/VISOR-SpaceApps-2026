# ========================================
# capas_visor.py
# ========================================

import base64, hashlib, io, json, os
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, rasterio, folium
from rasterio.windows import from_bounds
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
from matplotlib import colors as mcolors
from PIL import Image

DIR_ML = Path(os.environ.get("DIR_ML", Path.cwd())).resolve()
DIR_OUT = DIR_ML / "salidas"; DIR_V = DIR_OUT / "visor"; DIR_V.mkdir(parents=True, exist_ok=True)
F_CLASES = DIR_ML / "insumos" / "clases" / "A_T148_20260904_clases_solo_nisar.tif"
F_PROB = DIR_OUT / "CHOCO_A_T148_E6_prob_inundacion_20260904.tif"
FICHA_PROB = json.loads((DIR_OUT / "CHOCO_A_T148_E6_prob_inundacion_20260904.json").read_text(encoding="utf-8"))
VENTANA = (306000, 619700, 326000, 639700)

CLASES = {1: ("Agua permanente", "#08306B"), 2: ("Agua abierta nueva", "#41B6C4"), 3: ("Veg. inundada permanente", "#9E9AC8"),
          4: ("Veg. inundada nueva", "#54278F"), 5: ("Bosque no inundado", "#1B7837"), 6: ("Veg. baja / pasto / suelo", "#C2E699"),
          7: ("Urbano", "#737373"), 8: ("Urbano con aumento", "#E6550D"), 9: ("Dudoso", "#FFD92F")}

# ========================================
# 1) Class GeoTIFF for the Quibdó window + visor.ficha.v1 metadata
# ========================================
with rasterio.open(F_CLASES) as src:
    win = from_bounds(*VENTANA, transform=src.transform).round_offsets().round_lengths()
    cl = src.read(1, window=win)
    tr = src.window_transform(win)
    perfil = {"driver": "GTiff", "height": cl.shape[0], "width": cl.shape[1], "count": 1, "dtype": "uint8",
              "crs": src.crs, "transform": tr, "nodata": 255, "compress": "deflate"}
cl = np.where(cl == 0, 255, cl).astype(np.uint8)
nombre = "CHOCO_QUIBDO_A_T148_20260904_clases.tif"
with rasterio.open(DIR_V / nombre, "w", **perfil) as dst:
    dst.write(cl, 1)
    dst.update_tags(TIPO_PRODUCTO="clases_inundacion_nisar", UNIDADES="clase", FECHA="2026-09-04", SENSOR="NISAR L-SAR banda L")
ficha_cl = {
    "esquema": "visor.ficha.v1", "tipo_producto": "clases_inundacion_nisar",
    "producto": "Clases de inundación NISAR (etiquetado no supervisado solo NISAR)", "fecha": "2026-09-04", "unidades": "clase",
    "fuente": "NISAR L2 GCOV, ASF DAAC", "nodata": 255,
    "advertencia": "Indicio exploratorio sin validar en campo. Detección de cambio en una fecha observada.",
    "procedencia": {"estado": "real_sin_validar", "sensor": "NISAR L-SAR (banda L), stack A_T148", "polarizaciones": ["HH", "HV"],
                    "fechas": ["referencia: mediana de 2026-06-24, 2026-07-06, 2026-08-11, 2026-09-16", "2026-09-04"],
                    "metodo": "Filtro Lee 5x5; K-means → GMM por stack; mapeo relativo (Otsu para agua, bosque de la escena como ancla); "
                              "consenso K-means/GMM; reglas de agua permanente, vegetación inundada permanente y urbano",
                    "generado_por": {"modulo": "ml_choco", "notebook": "etiquetado_zona_solo_nisar.ipynb + capas_visor.py"},
                    "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "archivo": {"nombre": nombre, "sha256": hashlib.sha256((DIR_V / nombre).read_bytes()).hexdigest()},
                    "validacion": None},
    "fechas_detalle": {"observacion": "2026-09-04", "fecha_objetivo": None},
    "cuadricula": {"crs": "EPSG:32618", "resolucion": [20, 20], "limites": list(VENTANA), "ancho": int(cl.shape[1]), "alto": int(cl.shape[0])},
    "clases": {str(k): {"nombre": n, "color": c} for k, (n, c) in CLASES.items()} | {"255": {"nombre": "Sin dato"}},
    "indicio_inundacion": [2, 4, 8],
}
(DIR_V / nombre.replace(".tif", ".json")).write_text(json.dumps(ficha_cl, ensure_ascii=False, indent=2), encoding="utf-8")
km2 = {CLASES[k][0]: round(float((cl == k).sum() * 400 / 1e6), 2) for k in CLASES}
print("Clases en la ventana de Quibdó (km²):", km2)

# ========================================
# 2) 2 km alert zones
# ========================================
with rasterio.open(F_PROB) as src:
    pb = src.read(1); trp = src.transform
valido = pb != 255
u95 = np.quantile(pb[valido], 0.95)
L = 50
ny, nx = pb.shape[0] // L, pb.shape[1] // L
blq_v = valido[:ny * L, :nx * L].reshape(ny, L, nx, L).sum((1, 3))
blq_a = ((pb >= u95) & valido)[:ny * L, :nx * L].reshape(ny, L, nx, L).sum((1, 3))
blq_p = np.where(valido, pb, 0)[:ny * L, :nx * L].reshape(ny, L, nx, L).sum((1, 3)) / np.maximum(blq_v, 1)
feats = []
for i in range(ny):
    for j in range(nx):
        if blq_v[i, j] < L * L * 0.5:
            continue
        frac = blq_a[i, j] / blq_v[i, j]
        x0, y1 = trp.c + j * L * 40, trp.f - i * L * 40
        lon0, lat0, lon1, lat1 = transform_bounds("EPSG:32618", "EPSG:4326", x0, y1 - L * 40, x0 + L * 40, y1)
        feats.append({"type": "Feature",
                      "properties": {"alerta": bool(frac >= 0.10), "pct_celdas_alerta": round(100 * float(frac), 1),
                                     "prob_media_pct": round(float(blq_p[i, j]), 1)},
                      "geometry": {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]}})
gj = {"type": "FeatureCollection", "features": feats,
      "metadata": {"producto": "Zonas de 2 km en alerta de inundación nueva (Modelo B, E6, A_T148 11-ago → 04-sep)",
                   "regla": "alerta si ≥ 10 % de las celdas de 40 m de la zona está en el 5 % más probable de la franja",
                   "estado": "real_sin_validar"}}
(DIR_V / "CHOCO_A_T148_E6_zonas_alerta_2km.geojson").write_text(json.dumps(gj), encoding="utf-8")
print(f"Zonas de 2 km: {len(feats)} · en alerta: {sum(f['properties']['alerta'] for f in feats)}")

# ========================================
# 3) Folium demo
# ========================================
def a_4326(arr, transform, crs, nearest=True):
    dst_t, w, h = calculate_default_transform(crs, "EPSG:4326", arr.shape[1], arr.shape[0],
                                              *rasterio.transform.array_bounds(arr.shape[0], arr.shape[1], transform))
    out = np.full((h, w), 255, np.uint8)
    reproject(arr, out, src_transform=transform, src_crs=crs, dst_transform=dst_t, dst_crs="EPSG:4326",
              resampling=Resampling.nearest if nearest else Resampling.bilinear, src_nodata=255, dst_nodata=255)
    b = rasterio.transform.array_bounds(h, w, dst_t)
    return out, [[b[1], b[0]], [b[3], b[2]]]


def png_b64(rgba):
    buf = io.BytesIO(); Image.fromarray(rgba).save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


cl4, bcl = a_4326(cl, tr, "EPSG:32618")
rgba = np.zeros(cl4.shape + (4,), np.uint8)
for k, (_, c) in CLASES.items():
    r, g, b = (np.array(mcolors.to_rgb(c)) * 255).astype(np.uint8)
    rgba[cl4 == k] = (r, g, b, 200 if k in (2, 4, 8) else 140)
with rasterio.open(F_PROB) as src:
    w = from_bounds(*VENTANA, transform=src.transform).round_offsets().round_lengths()
    pw = src.read(1, window=w); tpw = src.window_transform(w)
pw4, bpw = a_4326(pw, tpw, "EPSG:32618")
cmap = __import__("matplotlib").colormaps["magma_r"]
rgba_p = (cmap(np.clip(pw4 / 100.0, 0, 1)) * 255).astype(np.uint8)
rgba_p[..., 3] = np.where((pw4 == 255) | (pw4 < u95), 0, 210)

cx, cy = (bcl[0][0] + bcl[1][0]) / 2, (bcl[0][1] + bcl[1][1]) / 2
m = folium.Map(location=[cx, cy], zoom_start=11, tiles="OpenStreetMap", control_scale=True)
folium.raster_layers.ImageOverlay(png_b64(rgba), bounds=bcl, name="Etiquetado NISAR 04-sep (clases)", interactive=False).add_to(m)
folium.raster_layers.ImageOverlay(png_b64(rgba_p), bounds=bpw, name="Modelo B: 5 % más probable de agua nueva", show=False).add_to(m)
lat0, lat1 = bcl[0][0] - 0.3, bcl[1][0] + 0.3
gj_v = {"type": "FeatureCollection", "features": [f for f in feats if lat0 <= f["geometry"]["coordinates"][0][0][1] <= lat1]}
folium.GeoJson(gj_v, name="Zonas de 2 km en alerta (Modelo B)",
               style_function=lambda f: {"color": "#d62728" if f["properties"]["alerta"] else "#999999",
                                         "weight": 1.5 if f["properties"]["alerta"] else 0.3,
                                         "fillOpacity": 0.25 if f["properties"]["alerta"] else 0.0},
               tooltip=folium.GeoJsonTooltip(["alerta", "pct_celdas_alerta", "prob_media_pct"],
                                             aliases=["Alerta", "% de celdas en alerta", "Prob. media (%)"])).add_to(m)
folium.Marker([5.6947, -76.6611], tooltip="Quibdó").add_to(m)
leyenda = "".join(f"<div><span style='display:inline-block;width:12px;height:12px;background:{c};margin-right:6px'></span>{n}</div>"
                  for _, (n, c) in CLASES.items())
m.get_root().html.add_child(folium.Element(
    "<div style='position:fixed;bottom:24px;left:24px;z-index:9999;background:white;padding:8px 10px;border-radius:6px;"
    "font:12px sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3)'><b>Etiquetado NISAR · 04-sep-2026</b>" + leyenda +
    "<div style='margin-top:6px'><span style='display:inline-block;width:12px;height:12px;border:2px solid #d62728;margin-right:6px'></span>"
    "Zona de 2 km en alerta (Modelo B)</div><div style='color:#666;margin-top:4px'>REAL SIN VALIDAR · no es verdad de campo</div></div>"))
folium.LayerControl(collapsed=False).add_to(m)
m.save(DIR_V / "demo_visor_E6.html")
print("Escrito:", sorted(p.name for p in DIR_V.iterdir()))
