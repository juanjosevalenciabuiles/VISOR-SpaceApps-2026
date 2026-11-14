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


## Hito real verificado en Replit — 14 de noviembre de 2026

En la carpeta aislada \`~/visor-nisar-prueba\`, el usuario confirmó un procesamiento **NASA Harmony REAL** y una descarga final auténtica con \`scripts/nisar_harmony_recuperar_job.py\` sobre el trabajo completado \`c442bc11-689a-4ae4-8e35-9af7b77f3ab2\`.

| Evidencia | Valor observado |
| --- | --- |
| Granule | \`NISAR_L2_PR_GCOV_033_148_A_005_4005_DHDH_A_20261022T104744_20261022T104757_P05036_N_P_J_001\` |
| Variable | \`frequencyA/HHHH\` (potencia gamma0, banda L) |
| Estado Harmony | \`successful\`, 100 %, sin errores reportados |
| Archivo válido | \`tmp_harmony_recuperado/gcov_c442bc11689a4ae48e359af7b77f3ab2_HHHH.tif\` |
| Bytes | **16 520 489** = **15,755 MiB** (UNA capa de UNA fecha) |
| CRS / resolución | \`EPSG:32618\`, **10 m × 10 m** |
| Dimensiones / tipo | **2768 × 2775**, \`float32\` |
| Transformación afín | \`[10, 0, 301400, 0, -10, 862610]\` |
| SHA-256 | \`859d28d784e205ae752dd388bb3119ac861da3c56567d85380deded939480f23\` |
| Validez parcial | 14 976 píxeles finitos en muestra de 128×128; **no representa cobertura útil total** |

**Incidente resuelto:** la primera descarga por \`urllib\` sin sesión autenticada escribió 9277 bytes de HTML (firma \`<!DOCTYP\`) con extensión \`.tif\`; Rasterio lo rechazó. Tras recuperar el **mismo** trabajo usando la sesión autenticada y verificar la firma TIFF, Rasterio abrió el GeoTIFF correctamente. Se añadieron pruebas de regresión y rechazo de HTML.

**Conclusión limitada:** la extracción antes de descargar *sí funciona* para **una variable de una fecha real NISAR** y evita traer el HDF5 completo para esa consulta. No afirmar todavía que están verificadas la pareja completa, la máscara, las capas auxiliares, la clasificación de agua/inundación ni los ahorros del flujo completo. La pareja de catálogo 22-oct/3-nov tiene 4,744 GB en HDF5 originales **entre las dos fechas** y cobertura común estimada 41,38 %; no comparar esos 4,744 GB contra 15,755 MiB como un cociente preciso de ahorro de dos escenas.

**Siguiente prueba:** obtener \`HHHH\` de la segunda fecha, \`mask\`, \`numberOfLooks\` y, cuando aplique, \`HVHV\`; comparar las dos cuadrículas, metadatos, píxeles válidos, cobertura, compatibilidad orbital y calidad radiométrica antes de cualquier análisis temporal.


## Hito real: par NISAR preparado automáticamente — 14 de noviembre de 2026

**Confirmado por la salida del usuario en Replit (sin interpretación ambiental):**

Comando ejecutado desde el worktree separado \`~/visor-nisar-prueba\`:

\`\`\`bash
~/workspace/.venv/bin/python scripts/nisar_auto.py \
  --inicio 2026-10-21 --fin 2026-11-14 \
  --metodo harmony --max-mb 256 --ejecutar
\`\`\`

Se observaron cuatro eventos \`Descargando capa\` para la primera fecha y cuatro para la segunda, seguidos por:

\`\`\`text
Insumos NISAR preparados; informe: /home/runner/visor-nisar-prueba/data/nisar/catalogo/preparacion_7d03a543e5754867bba3875d71a7fc6c.json. NO son mapas de inundación.
\`\`\`

Esto verifica que el flujo automatizado de búsqueda CMR → solicitud Harmony → procesamiento remoto → transferencia de variables → validación y manifiestos completó **dos escenas** sin HDF5 manual. **No se ha verificado todavía el tamaño agregado ni las fracciones válidas de las 8 capas**, pues el contenido del informe no ha sido inspeccionado en esta conversación.

Auditoría añadida a PR #14, sin transferir datos ni exponer token, para ejecutar DESPUÉS de actualizar únicamente el worktree experimental:

\`\`\`bash
cd ~/visor-nisar-prueba
git fetch origin feature/nisar-inundaciones-auto
git switch --detach origin/feature/nisar-inundaciones-auto
~/workspace/.venv/bin/python scripts/verificar_nisar_harmony_pares.py \
 --informe data/nisar/catalogo/preparacion_7d03a543e5754867bba3875d71a7fc6c.json
\`\`\`

La auditoría verifica tamaño de cada archivo y SHA-256, integridad del manifiesto, estructura GeoTIFF, máscaras y looks presentes, geometría compartida entre capas por fecha, igualdad geométrica entre fechas (sin reproyección automática), MB totales y proporción completa de píxeles HHHH con potencia positiva/finita; esto último **NO** equivale a agua, ni a cobertura QA decodificada, ni a inundación validada. Si las grillas temporales difieren, se reporta como condición pendiente de alineación, no como inundación.


## Auditoría de solape QA de dos fechas (antes de cambios de agua)

El primer informe real auditado por el usuario arrojó:

- Estado \`ARCHIVOS_GCOV_AUDITADOS_SIN_CLASIFICAR\`, **2 fechas, 8 capas, SHA-256 verificados**.
- **100 757 700 bytes = 96,09 MiB** en total; 22-oct: 48,152 MiB; 3-nov: 47,938 MiB.
- CRS **EPSG:32618**, misma cuadrícula temporal y **10 m** de resolución.
- HHHH finito + positivo: **3 182 253 / 7 681 200 píxeles** (41,4291%) en primera fecha; **3 161 990 / 7 681 200** (41,1653%) en segunda. **Esta fracción NO representa agua, inundación ni cobertura QA común**. Las huellas del catálogo sugerían 41,38 % de cobertura común aproximada.

Se incorporó una segunda auditoría de precisión en \`scripts/nisar_solape_qa.py\`, que **no descarga ni modifica datos**, comprueba de nuevo hashes y alineación, y calcula en ventanas pequeñas **solo la intersección de píxeles utilizables en AMBAS fechas**, con estas reglas conservadoras:

- \`mask\`: valores **1–254** (subswath plenamente enfocada), 0 = mezcla con muestras no válidas o parcialmente enfocadas; 255 = fuera del alcance radar. Consultar la descripción y versión de producto correspondiente.
- \`numberOfLooks\`: finito y estrictamente positivo.
- \`HHHH\` y \`HVHV\`: finitos y estrictamente positivos (poder usar logaritmos/radios), sin interpretar intensidad como inundación.

Fuente científica: [Guía ASF NISAR GCOV](https://nisar-docs.asf.alaska.edu/gcov/) y [NISAR Cookbook](https://asfopensarlab.github.io/NISAR_Cookbook/nisar-data-access/). La medida es de **cobertura y calidad técnica**, no una clasificación de inundación.

Para ejecutar con el informe ya generado, sin otra transferencia:

\`\`\`bash
cd ~/visor-nisar-prueba
git fetch origin feature/nisar-inundaciones-auto
git switch --detach origin/feature/nisar-inundaciones-auto
~/workspace/.venv/bin/python scripts/nisar_solape_qa.py \
  --informe data/nisar/catalogo/preparacion_7d03a543e5754867bba3875d71a7fc6c.json
\`\`\`

La siguiente fase, una vez medido el solape, será diseñar/validar inferencia hidrológica por pixel en el dominio común y distinguir agua permanente de agua potencialmente nueva con referencias externas. Ni la máscara QA ni el ratio radar por sí solos verifican inundaciones.


## Hito real: cobertura NISAR validada en ambas fechas (14-nov-2026)

La ejecución real en Replit de \`scripts/nisar_solape_qa.py\` sobre las 8 capas del piloto Chigorodó informó:

- \`SOLAPE_GCOV_QA_NO_INUNDACION\`
- Cuadrícula 2 fechas: **7 681 200 píxeles** de **10 m** (768,12 km²).
- \`mask\` 1..254 + \`numberOfLooks\` >0 + \`HHHH\` y \`HVHV\` >0 finitos en 22-oct: **753 397 píxeles = 75,3397 km² (9,8083%)**.
- Mismos criterios en 3-nov: **733 342 píxeles = 73,3342 km² (9,5472%)**.
- Intersección **simultáneamente utilizable**: **733 342 píxeles = 73,3342 km² (9,5472%)**; los píxeles útiles del 3-nov están contenidos en los útiles del 22-oct bajo estos criterios.
- No confundir con cobertura de huellas de catálogo 41,38 %, ni con proporción inundada. El 41,38 % es una aproximación de huellas AOI; 9,5472 % es QA por píxel sobre la cuadrícula del TIFF.
- La máscara NISAR GCOV distingue valor \`0\` (al menos una muestra del ensemble parcialmente enfocada o inválida), \`255\` (fuera de adquisición) y \`1..254\` (subfranja válida): [ASF NISAR Cookbook](https://asfopensarlab.github.io/NISAR_Cookbook/nisar-data-access/) y [guía GCOV](https://nisar-docs.asf.alaska.edu/gcov/).

### Capa geográfica compacta de disponibilidad QA

Se añadió \`scripts/nisar_mapa_cobertura_qa.py\` para transformar únicamente los estados QA de las dos fechas en un **GeoTIFF técnico comprimido \`uint8\`** que QGIS puede abrir. Conserva CRS, orientación y resolución de 10 m; las clases son:

| Valor | Significado |
| --- | --- |
| 0 | No utilizable simultáneamente en ninguna de las fechas (incluye zonas sin adquisición) |
| 1 | Utilizable solo el 22 oct |
| 2 | Utilizable solo el 3 nov |
| 3 | **Utilizable en ambas fechas**; zona técnicamente comparable tras QA |

**Nunca interpretar el valor 3 como agua o inundación.** La salida almacena además recuentos y un rectángulo delimitador aproximado WGS84 de la clase 3 (no su polígono exacto). Solo lectura de originales y nuevo archivo pequeño en \`data/nisar/qa/\`.

\`\`\`bash
cd ~/visor-nisar-prueba
git fetch origin feature/nisar-inundaciones-auto
git switch --detach origin/feature/nisar-inundaciones-auto
~/workspace/.venv/bin/python scripts/nisar_mapa_cobertura_qa.py \
  --informe data/nisar/catalogo/preparacion_7d03a543e5754867bba3875d71a7fc6c.json
\`\`\`

**Condición pendiente:** revisión cartográfica de ubicación de clase 3 respecto al área de interés, verificación de comparabilidad radiométrica y desarrollo de metodología de agua nueva con evidencia independiente; solo después sería defendible una hipótesis de inundación.
