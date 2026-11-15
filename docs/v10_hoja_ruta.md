# V.I.S.O.R. V10 — dos sensores, mapa simple y línea temporal

**Estado:** desarrollo experimental en rama. No fusionar ni desplegar sin CI ni pruebas científicas con escenas reales.

## Un único recorrido para el visitante (PC)

1. Buscar lugar. Pulsar «Seleccionar zona» en el mapa, hacer clic en la primera esquina y clic en la opuesta. Confirmar con «Usar esta zona». El rectángulo permanece como GeoJSON nativo de Leaflet.Draw.
2. Elegir fecha inicial/final en la línea temporal inferior (única fuente de fechas del flujo público). Pulsar «Buscar y analizar cambios». Nada pesado se ejecuta al mover fechas, capas o mapa.
3. Se planean **dos pipelines independientes y concurrentes** sobre el mismo AOI/periodo:
   - NISAR GCOV L (Harmony) → QA y diferencia de retrodispersión en dB, **NO clasificación de inundación**. Conservar validación de madurez/stack.
   - Sentinel-1 C mediante **OPERA L3 DSWx-S1 V1** validado de NASA PO.DAAC → clasificación observacional WTR + confianza/máscaras, en dos adquisiciones (y línea base cuando sea posible). Un aumento de agua observada respecto al estado previo = posible inundación, no confirmación en terreno. Si DSWx-S1 no está disponible, no se substituye automáticamente por GRD ni un RTC inexistente; avisar «sin datos».
4. Cada trabajo publica solo GeoTIFF real + ficha `visor.ficha.v1` con SHA256, fechas, polarización/banda, geometría, fuente, calidad, advertencias; rechaza mapas sin QA.
5. La línea temporal muestra **fechas discretas de adquisición** de productos ya disponibles, su madurez y la opción de comparar los dos sensores; nunca interpola una imagen para otra fecha. `Ambos` pone dos capas independientes con opacidad, no les atribuye probabilidades equivalentes.
6. Cambiar base desde «Mapas» en barra superior; no toca AOI ni resultados. El panel derecho contiene contexto IDEAM/DANE/EONET como capas opt-in según PR22.

## Rendimiento y seguridad

- Primero consulta metadatos (CMR/ASF/PO.DAAC); limita resultados, áreas y tamaño. COG por ventanas, almacenamiento en caché por granule/fecha/AOI/madurez; sin granules completos gigabytes cuando exista AOI subset.
- Procesadores asincrónicos independientes con cupos por recurso; no bloquear UI mientras se descarga. Cancelación, reintento, estado error y «sin evidencia suficiente» explícitos.
- Separar NISAR VALIDATED / PROVISIONAL; no utilizar datos de Chocó PROVISIONAL como si fueran VALIDATED. NISAR no tiene por este hecho un clasificador de inundación.
- Separar fuentes IDEAM de fecha consulta de fechas SAR. Sin mapa de inundación inventado, sin promedios de confianza no calibrados, sin umbrales cambiados silenciosamente.
- Evitar tareas móviles, Replit Agent y HyP3; no solicitar secretos ni cargar sus valores a GitHub.

## Pruebas y criterios de aceptación

- Dos clics funcionan en Chromium/Firefox y el GeoJSON llega a st_folium; cancelar Escape; compatibilidad con dibujos anteriores.
- Fechas únicas compartidas; cambiar el periodo no lanza descargas ni muestra capas anteriores como actuales.
- DSWx-S1: comprobar clases WTR y máscaras con especificación **de la versión real**; no extrapolar agua de tierra a vegetación inundada sin evidencia; recortar validando CRS, tamaño y cobertura.
- Permitir NISAR y Sentinel-1 con sus fechas reales y QA en el mismo mapa y controlarlos por separado. Si falla uno, el otro sigue disponible.
- Reproducir ensayos con fixtures sintéticos etiquetados como tests + ejecutar al menos un caso pequeño real por sensor con trazabilidad completa. E2E sin red no equivale a ese último paso.
- Auditoría independiente de código/seguridad/ciencia/UX, sin merge automático si quedan bloqueantes.

**Referencias oficiales:** https://www.jpl.nasa.gov/go/opera/products/dswx-product-suite/ · https://podaac.jpl.nasa.gov/dataset/OPERA_L3_DSWX-S1_V1 · https://www.earthdata.nasa.gov/data/catalog/podaac-opera-l3-dswx-s1-v1
