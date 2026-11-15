# V10 · IA1 Sentinel-1 / OPERA DSWx-S1

## Incremento 1: planificación sin IO

`utils/v10_sentinel/planificador.py::planificar(aoi_bbox, inicio, fin, escenas, presupuesto_bytes=...)` recibe bbox EPSG:4326 y fechas ISO del mismo formulario V9. `escenas` son metadatos previamente normalizados desde CMR (NO píxeles). Requiere `collection=OPERA_L3_DSWX-S1_V1`, `observed_at`, `granule_id`, `source_s1_granule`, `bbox`, `wtr_url`, `estimated_window_bytes` y `qa_metadata=APTO`. Esta última marca debe ser provista por un verificador externo, nunca inventada por el catálogo.

Devuelve `APTA_METADATA` (no equivale a apta para análisis), `NO_APTA` o `SIN_DATOS`; dos escenas estrictamente pre/post, fechas exactas, motivos de rechazo y presupuesto. El límite máximo es 384 MiB para ambos recortes sumados. La cobertura bbox es conservadora; no soporta antimeridiano ni mosaicos y **no demuestra cobertura de píxeles**. Sin par completo, el integrador no debe publicar raster. Ninguna descarga ocurre en este módulo.

Fuente de producto: [PO.DAAC](https://podaac.jpl.nasa.gov/dataset/OPERA_L3_DSWX-S1_V1) y [NASA JPL OPERA](https://www.jpl.nasa.gov/go/opera/products/dswx-product-suite/). Aún **no se verificaron** CMR en vivo, scopes Earthdata, assets WTR, clases/nodata de la versión real ni autorización de COG HTTP range. Hasta verificarlo no hay clasificación de agua, cambio de agua ni inundación. No se infiere vegetación inundada, probabilidad o área confirmada. NISAR L y Sentinel-1 C se muestran en capas separadas; origen Sentinel-1 compartido no cuenta como observación independiente.

## Contrato futuro para integrador

Tras pulsar «Buscar y analizar»: búsqueda CMR → comprobación de assets/QA y presupuesto → lectura remota por ventanas → máscara WTR validada contra especificación de versión → baseline pre/post → GeoTIFF georreferenciado + `visor.ficha.v1` con fechas, QA, SHA256 y linaje → registro en visor. Los jobs de cada sensor deberán comunicar fallos parciales independientes y limitar concurrencia. **Este incremento solo implementa el primer filtro de metadatos.**

Tests sintéticos sin red: `pytest -q tests/v10_sentinel/`. No se han ejecutado en GitHub todavía; CI debe confirmar.

## Incremento 2: validación defensiva de metadatos

`utils/v10_sentinel/validacion.py` comprueba coordenadas finitas y rango de bbox (rechaza NaN, infinito y antimeridiano), fechas de observación completas con zona horaria y URLs candidatas HTTPS sin credenciales, IP literal, localhost, puerto no estándar o fragmento. El planificador reutiliza las validaciones de bbox y URL; conserva fechas ISO de día completo para compatibilidad con V9 y fixtures, pero acepta timestamps ISO con zona. Esto **no** demuestra que el host sea de NASA, que el enlace esté autorizado, que soporte HTTP Range ni que sea un COG: un verificador de assets confiables sigue siendo obligatorio antes de cualquier IO. Tests sintéticos en `tests/v10_sentinel/test_validacion.py` (sin red).

CI del commit anterior `8d67a4d`: unidad/integración/Ruff **success**; Playwright Firefox y Chromium **failure**; verificaciones reales manuales omitidas. El CI de este incremento aún no está verificado. No hay WTR real, raster, ni mapa de agua.

## Incremento 3: reparación de parser y regresión temporal

Se corrigió un defecto de sintaxis verificable en `planificador.py::_fecha`: el archivo contenía secuencias literales `\\n` dentro del cuerpo de la función, impidiendo importar el módulo. El arreglo conserva la entrada V9 por fecha diaria y la normalización de observaciones UTC. `tests/v10_sentinel/test_regresion_fechas.py` cubre un par pre/post sintético y la ausencia de post. **No se ejecutaron estas pruebas localmente**; la CI del nuevo SHA debe confirmarlas. La CI del SHA anterior `ed5bac3` concluyó en fallo global, sin diagnóstico por job en esta comprobación. No hay raster ni observaciones verificadas.
