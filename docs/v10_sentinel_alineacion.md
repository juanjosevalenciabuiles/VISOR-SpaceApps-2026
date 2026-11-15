# Corrección científica P1 — alineación espacial de WTR (15/11/2026)

La función `comparar_wtr()` ahora exige `georef_anterior` y `georef_posterior`, cada uno con `crs` y `transform` reales leídos de los GeoTIFF originales mediante rasterio. Compara CRS con `rasterio.crs.CRS` y la transformación afín de las dos cuadrículas. Mismo número de filas/columnas **NO** prueba alineación.

Cuando faltan CRS/transform, se desplaza un píxel, hay resoluciones diferentes o CRS distintos, **se rechaza con ValueError antes de producir clases**; no se remuestrea ni se inventa un resultado. El llamador debe recortar/reproyectar explícitamente a una cuadrícula común con trazabilidad y comparar QA de ambas fechas. Todas las pruebas son sintéticas; **sin datos reales y sin producto GeoTIFF de inundación validado**.

Ejemplo obligatorio del llamador:
```python
with rasterio.open(pre_path) as pre, rasterio.open(post_path) as post:
    geo_pre = {"crs": pre.crs, "transform": tuple(pre.transform)[:6]}
    geo_post = {"crs": post.crs, "transform": tuple(post.transform)[:6]}
    # usar las ventanas válidas previamente leídas y máscaras QA reales
    comparar_wtr(pre_array, post_array, qa_pre, qa_post,
                 codigos=codigos_oficiales, version_verificada=True,
                 georef_anterior=geo_pre, georef_posterior=geo_post,
                 mascara_aoi=mascara_aoi)
```
