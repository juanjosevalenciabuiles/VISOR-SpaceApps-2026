# V.I.S.O.R. · NISAR primero, SOLO inundaciones · descargas pequeñas con NASA Harmony

**Estado (2026-11-14):** implementación EXPERIMENTAL en la [PR #14](https://github.com/juanjosevalenciabuiles/VISOR-SpaceApps-2026/pull/14), rama `feature/nisar-inundaciones-auto`. **No está en `main`, ni se ha comprobado una descarga Harmony autenticada de un GCOV real en Replit**. No se han modificado los originales de `data/sar/`.

## ¿Hace falta actualizar la web antes de implementar?

**No.** La rama se desarrolla y prueba de manera independiente; solo después de QA, autorización y fusión se actualiza Replit. Nunca fusionar PR #14 automáticamente.

## Decisiones obligatorias del equipo

- V.I.S.O.R. estudia **solo inundaciones**. Deslizamientos y deforestación desaparecen de la UI pública, sin borrar código histórico ni fuentes originales.
- El sensor prioritario es **NISAR L-band / L2 GCOV**. Sentinel-1 C-band es alternativa; no comparar directamente retrodispersión entre bandas.
- La adquisición por defecto es **NASA Harmony**, no la descarga íntegra del HDF5.
- La resolución original del GCOV (normalmente **10/20 m**) se preserva: nada de bajar a 30 m, redimensionar o interpolar para economizar.
- Los insumos son **gamma0 en potencia + máscara + numberOfLooks**, y en polarización correspondiente (HH/HV o VV/VH). **NO representan inundaciones confirmadas**.

## Cómo funciona

1. Persona busca/dibuja y confirma una AOI en Colombia.
2. En «Herramientas SAR» NISAR está preseleccionado. Persona elige fechas.
3. `utils/nisar_catalogo.py` consulta NASA CMR ASF (NISAR GCOV VALIDATED), calcula candidatos, pares de misma órbita/polarización y cobertura. No descarga nada.
4. `utils/nisar_auto.py` recomienda un par comparable; si no hay par, una escena única etiquetada como no apta para cambio temporal. Muestra porcentaje de cobertura y HDF5 originales hipotéticos en GB.
5. Por defecto la UI ofrece `Recorte optimizado · NASA Harmony`. Usuario fija **128–512 MB** (384 MB predeterminado) para la suma de imágenes recortadas.
6. Tras autorización explícita y `EARTHDATA_TOKEN` en Secrets, `utils/nisar_harmony.py` consulta capacidades públicas en `https://harmony.earthdata.nasa.gov/capabilities?shortName=NISAR_L2_GCOV_V1`; no admite colecciones ajenas.
7. La solicitud Harmony utiliza `Collection('C3622241360-ASF')` según prueba pública del 14-nov-2026, bbox AOI, `granule_name` único, `max_results=1`, `variables` (nunca `all`), salida `image/tiff`, **sin** `crs` ni `width/height` (sin reproyección ni reescalado).
8. Harmony produce **Cloud-Optimized GeoTIFFs** por variable. Se descargan desde HTTPS firmado sin reenviar `EARTHDATA_TOKEN`, con máximo por archivo y por trabajo; se verifica estructura, CRS proyectado, resolución, coincidencia de cuadrícula, intersección AOI y SHA-256.
9. COGs y manifiestos atómicos se guardan bajo `data/nisar/harmony/<hash>/`. Una transferencia parcial es descartada. Un reuso exige tamaño y SHA originales.
10. La cola de V.I.S.O.R. muestra estados y permite cancelación. La vista del mapa no incorpora automáticamente una falsa capa de inundación.

### Rutas y seguridad

- `utils/nisar_harmony.py`: cliente oficial `harmony-py~=1.8.0`, descubrimiento público de capacidades, request por variable/bbox, seguimiento y streaming acotado.
- `utils/nisar_auto.py::preparar_harmony`: coordinación del par, sin fallback silencioso a HDF5.
- `components/nisar_auto_ui.py`: opción Harmony predeterminada, límite de MB, seguimiento de trabajo; HDF5 completo requiere cambiar explícitamente de modo y confirmar GB.
- `scripts/nisar_auto.py`: CLI; por defecto Harmony.
- `tests/test_nisar_harmony.py`: mocks sin secretos: variables, capa frecuencia A, bloqueo de URLs externas, archivo incompleto, CRS, caché SHA, límites y fallo seguro.
- `scripts/nisar_harmony_preflight.py`: **consulta pública real** de capacidades, sin solicitar trabajos ni descargar.

El token solo se configura como `EARTHDATA_TOKEN` en **Replit Secrets**; nunca se envía al chat, a GitHub ni se guarda en JSON. Los errores de URLs firmadas deben ser sanitizados antes de persistirse. Harmony puede no ofrecer el subconjunto o la variable para una toma concreta: **en ese caso no se inventa la capa ni se descarga HDF5 completo automáticamente**.

## Comandos de consulta y prueba (rama experimental)

```bash
git status --short
bash actualizar.sh --guardar feature/nisar-inundaciones-auto
bash verificar.sh
.venv/bin/python scripts/nisar_harmony_preflight.py
# SOLO catálogo y propuesta, sin transferencia:
.venv/bin/python scripts/nisar_auto.py --inicio 2026-10-21 --fin 2026-11-14
# SOLO con Earthdata Secrets y límites de disco aprobados:
.venv/bin/python scripts/nisar_auto.py --inicio 2026-10-21 --fin 2026-11-14 --max-mb 384 --ejecutar
# Alternativa explícita, puede descargar varios GB:
.venv/bin/python scripts/nisar_auto.py --metodo hdf5 --max-gb 5 --ejecutar
```

**Precaución:** la cola del servidor tiene un tiempo máximo (por defecto 900 s) y Harmony puede tardar; no lanzar descargas grandes durante una presentación sin prueba previa. Los archivos `data/` siguen fuera de GitHub.

## QA: qué está probado y qué no

**Verificado en línea sin credenciales:** el endpoint Harmony público devolvió colección `C3622241360-ASF`, `NISAR_L2_GCOV_V1`, y las variables `/science/LSAR/GCOV/grids/frequencyA/HHHH`, `HVHV`, `mask` y `numberOfLooks`, junto con otras variables de frecuencia A/B. GitHub Actions [preflight](https://github.com/juanjosevalenciabuiles/VISOR-SpaceApps-2026/actions/runs/43639733760) registró estas respuestas públicas.

**Pruebas simuladas:** se generan GeoTIFFs pequeños y respuestas de Harmony simuladas para comprobar etiquetas, límites, errores y ausencia de archivos parciales. `harmony-py` se valida por su API pública.

**SIN verificar:** envío real de trabajo Harmony con Earthdata, generación de COG para granule NISAR real, estructura exacta del nombre de los GeoTIFF producidos, descarga firmada en Replit, recorte multi-fecha homogéneo y validación física de la máscara e intensidad contra HDF5 auténtico. No anunciar «sistema completo funcionando» hasta superar esas puertas.

**Caso piloto:** catálogo anterior registra candidatos del 22 oct y 3 nov para el track 148 frame 5 con ~41 % de cobertura conjunta de la AOI Chigorodó. No declarar que cubre el 100 %; ausencia de cobertura equivale a **SIN DATOS**, no a «no inundado».

**Bloqueo científico restante:** con los insumos obtenidos todavía falta verificar un flujo de detección de **posible nueva agua**, apoyado en agua permanente JRC, QA de máscaras/numberOfLooks, puntos de verificación hidrológica IDEAM y umbrales específicos validados de banda L. Un GCOV nunca se presenta como mapa de inundación automático.

## Fuentes oficiales

- [Guía ASF NISAR Harmony](https://nisar-docs.asf.alaska.edu/harmony/)
- [Guía ASF NISAR GCOV](https://nisar-docs.asf.alaska.edu/gcov/)
- [API harmony-py](https://harmony-py.readthedocs.io/en/main/api.html)
- [NASA Harmony](https://harmony.earthdata.nasa.gov/docs)
