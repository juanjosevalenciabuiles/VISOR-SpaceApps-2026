# V.I.S.O.R. — investigación de adquisición automática centrada en INUNDACIONES

**Decisión explícita del equipo (14-11-2026): V.I.S.O.R. estudiará únicamente inundaciones.**
Deslizamientos y deforestación no forman parte del alcance final. Este documento
es investigación: **no autoriza cambiar el motor o la UI de `main`** hasta revisar
las pruebas y confirmar la estrategia con el equipo.

## Qué existe realmente en main

- `utils/buscador_sar.py` consulta productos Sentinel-1 GRD y sugiere pares.
- `utils/flujo_sar.py` asocia escenas GRD con RTC GAMMA de HyP3 **locales**.
- `utils/ejecucion_sar.py` declara BLOQUEADO si faltan RTC en `data/sar/`.
- No existe, todavía, descarga automatizada de RTC ni mosaico de OPERA en ese flujo.
- El análisis histórico de Chigorodó (30 m) detecta variación de retrodispersión;
  **no confirma inundaciones**.

## Dos rutas NASA que conviene investigar por separado

### A — OPERA RTC-S1 (ASF DAAC): insumo SAR calibrado de 30 m

- NASA OPERA publica ráfagas L2 RTC-S1 calibradas, gamma0 **en potencia**,
  con cada polarización (normalmente VV/VH) como COG y máscara independiente.
- Estos productos ya están procesados. Evitan pedir RTC nuevos en HyP3 **cuando
  hay datos, fechas, cobertura y polarizaciones suficientes**.
- Se investigan metadatos con `scripts/verificar_opera_asf.py`, sin descargar.
- Para integrarlos se necesitan descubrir ráfagas que cubren la AOI completa,
  elegir fechas y pasada comparables, verificar CRS, grilla y máscaras, y
  realizar un mosaico controlado. **NO insertar los COG sueltos en el motor
  que espera nombres HyP3**.
- Es obligatorio revisar la compatibilidad radiométrica antes de reproducir
  las cifras anteriores. No mezclar gamma0 power con dB ni cambiar speckle
  silenciosamente.

### B — OPERA DSWx-S1 (NASA PO.DAAC): agua superficial clasificada

- Producto L3 de 30 m, directamente relacionado con agua superficial
  y derivado de Sentinel-1. Está en **NASA PO.DAAC/Earthdata**, no en el
  mismo flujo de descarga que OPERA RTC-S1 de ASF.
- `scripts/verificar_dswx_cmr.py` consulta el catálogo público CMR de fechas
  concretas para Chigorodó (solo metadatos).
- Una clasificación de agua presente **no demuestra inundación**. Distinguir
  agua permanente e históricamente frecuente con JRC y comparar fechas
  compatibles; verificar máscaras, NoData y calidad.
- Productos L3 buscan cuerpos de agua abiertos suficientemente grandes; no
  prometer la detección de charcos, calles estrechas ni agua bajo vegetación
  sin evidencia. DSWx es un punto de partida y un producto de contraste, no
  «verdad terreno» para todos los píxeles.

## Ejecución pública de investigación sin credenciales

```bash
python -m pip install asf-search pytest
python -m pytest -q tests/test_opera_preflight.py tests/test_dswx_preflight.py
python scripts/verificar_opera_asf.py --salida informes/preflight/opera_asf.json
python scripts/verificar_dswx_cmr.py --salida informes/preflight/dswx_podaac.json
```

La rama agrega `.github/workflows/preflight-agua.yml` para comprobar consultas
reales y conservar su JSON en artefactos CI. **Si un servicio responde 0
productos, NO se inventarán escenas**, y se investigará si el filtro/fecha
corresponden antes de descartar esa ruta.

**NINGUNO de estos comandos descarga imágenes**, envía trabajos HyP3, modifica
`data/sar/` ni solicita claves. Resultados de pruebas de producción quedan
pendientes hasta que la CI los ejecute.

## Siguiente fase, condicionada por datos reales y QA

1. Descubrimiento: comprobar productos/fechas, AOI, polarizaciones y cobertura
   reales (ASF RTC y PO.DAAC DSWx). Informe por fecha y causa de ausencia.
2. Descarga: implementar sistema con límites de tamaño, autenticación opcional
   Earthdata **solo por secretos Replit**, verificación HTTP y checksum,
   `download.part` seguido de `os.replace`, no sobrescritura y registro
   de procedencia. Descargar únicamente lo requerido por AOI y fecha.
3. Preparación: mosaicado/alineación de ráfagas y máscaras (si RTC),
   pruebas de NoData, EPSG y gamma0. Para DSWx, interpretar sus clases y
   calidad sin reemplazar silenciosamente el método SAR original.
4. Inundaciones: distinguir agua nueva, permanente y casos inciertos;
   integrar referencia histórica JRC/IDEAM cuando exista fuente real.
   Explicar a ciudadanos en panel derecho sin afirmaciones no verificadas.
5. Ejecutar regresión Chigorodó + tests Replit + QA real antes de cambiar
   la experiencia de usuario en `main`.

## Referencias oficiales

- ASF RTC-S1: https://hyp3-docs.asf.alaska.edu/guides/opera_rtc_product_guide/
- ASF asf_search: https://docs.asf.alaska.edu/asf_search/BestPractices/
- NASA JPL OPERA: https://www.jpl.nasa.gov/go/opera/products/
- NASA PO.DAAC DSWx-S1: https://data.nasa.gov/dataset/opera-dynamic-surface-water-extent-from-sentinel-1-version-1-5d63c
- NASA Disasters DSWx: https://science.data.nasa.gov/disasters/data-gallery/opera-dswx
