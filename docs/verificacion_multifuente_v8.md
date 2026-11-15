# V.I.S.O.R. — Integración técnica V8 · verificación multifuente

## Alcance implementado en esta rama

Integración conservadora sobre PR #15 (incluye #13), y PR #14 (NISAR/Harmony/QA) y #12 (preflight OPERA RTC/DSWx).
No reemplaza la aplicación Streamlit/Folium ni modifica imágenes originales. El panel derecho dispone ahora de un apartado
de **verificación multifuente** para el caso histórico documentado de Chigorodó, cuando la selección corresponde
al municipio de Chigorodó y la ventana documental 3–7 octubre 2026. La coincidencia municipal **no significa**
inundación en cada píxel ni en el punto urbano. No confundir documentos del 5 y 7 oct con dos eventos.

`utils/verificacion_multifuente.py` contiene un primer evaluador cualitativo determinista, con fechas, calidad,
relación espacial y deduplicación por origen de adquisición. No asigna porcentajes de confianza.

## Lo que sí ejecuta

- NISAR banda L: planifica y prepara GCOV/COG con Harmony, con autorización explícita y QA; sin clasificación
  automática de inundación en la PR #14.
- Sentinel-1 banda C: flujo previo de RTC conservado como respaldo; depende de RTC locales.
- OPERA: verificadores de catálogo por metadatos, **sin descarga de productos de agua**.
- IDEAM: consulta de alertas **actuales** al confirmar la zona (no prueba retrospectiva).
- NASA EONET: eventos de catálogo para fechas de referencia.
- DAGRAN/IDEAM histórico: ficha institucional de octubre 2026, sin geometrías de inundación.
- ECO/ficha del lugar: panel y guía compatibles con el flujo anterior.

## Pendiente antes de interpretar agua histórica

1. Consultar/descargar en forma controlada producto DSWx-S1/GFM próximo al 03-oct-2026;
   verificar el granule, su huella y clases WTR/BWTR y QA.
2. Agregar IMERG real para 24/72 horas, con resolución y fecha explícitas, y series IDEAM
   históricas cuando existan; una alerta actual nunca se retrotrae.
3. Clasificar cambios espaciales con agua histórica JRC y controles negativos, sin mezclar
   banda C con banda L ni contar DSWx y GFM del mismo Sentinel como réplicas independientes.
4. Integrar derivados observacionales al evaluador tras prueba real de píxeles y fechas.
5. Ejecutar suite y validación visual E2E en Replit antes de fusionar a `main`.

## Caso documentado (NO mapa)

- IDEAM boletín 284 de 11-oct, referencia a creciente súbita reportada 03-oct.
- DAGRAN 05-oct confirma inundaciones, León/Guapá y 397 familias preliminares.
- DAGRAN 07-oct comunica atención de la misma emergencia.
- NISAR 22-oct y 03-nov: 73,3342 km² de QA común en franja occidental, sin QA utilizable
  en el punto urbano (-76.6774845, 7.6645455); **no** es inundación observada.

Fuentes oficiales incorporadas en `utils/verificacion_multifuente.py`.
