# V9 · Integración funcional PC (PR #21)

Estado: EN VALIDACIÓN AUTOMÁTICA; SIN PRUEBA REAL EN REPLIT. Base: main V8 d8f7b7b.

## Qué está conectado

1. El mapa conserva el AOI. Se añadió una entrada «Analizar cambios en el agua» para seleccionar periodo de interés; solo hace consulta NASA/ASF al pulsar el botón.
2. Para fechas después del 21/10/2026 consulta exclusivamente NISAR VALIDATED, exige dos adquisiciones que encierren el periodo y prepara por Harmony recortes gamma0 + máscara + looks, límite 384 MiB, con secreto Earthdata. No trae HDF5 completo ni mezcla Sentinel-1 C con NISAR L.
3. Si ya existe una preparación NISAR apta para el AOI y periodo de esta sesión, la reutiliza sin descargar.
4. El puente utils/v9_nisar_puente.py comprueba el manifiesto de Harmony y stack (órbita, frame, dirección, modo, versión), recupera dos tríos gamma0/mask/looks y rechaza rutas inseguras.
5. El procesamiento utils/v9_datos/cambio_cog.py calcula por ventanas la diferencia en dB donde gamma0 es positiva, looks son aptos y máscara NISAR está entre 1 y 254; 0 y 255 inválidos. No se remuestrea silenciosamente.
6. Se genera GeoTIFF + ficha visor.ficha.v1, SHA-256 y estado real_sin_validar en data/analisis/; el visor valida procedencia antes de dibujarla.
7. El panel separa lugar buscado (Rionegro) de municipios del área (San Carlos). Conserva el flujo avanzado y respaldo Sentinel-1.

## Límites

No es un clasificador de inundaciones, solo un mapa de cambio de señal SAR. Sin un par y QA suficientes no publica mapa. El piloto Chocó con NISAR PROVISIONAL necesita otra validación de madurez. No se han probado todavía los 119,8 MB COG reales de Replit ni se ha validado la aplicación ejecutándose en ese entorno. Ningún modelo de ML predictivo está conectado.

## Próximos pasos científicos

Construir y validar capas observacionales de agua con referencia previa y QA, contrastrar con DSWx-S1 y evidencia independiente, antes de habilitar leyendas de agua nueva, agua persistente o vegetación posiblemente inundada. Nunca inferir esas clases únicamente a partir de un cambio en dB.
