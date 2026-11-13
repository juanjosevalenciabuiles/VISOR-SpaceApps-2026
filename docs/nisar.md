# NISAR en V.I.S.O.R. (banda L, L2 GCOV)

Rama `feature/nisar-gcov`, 13-nov-2026. Este documento separa lo que está **implementado**,
lo que está **probado** (y con qué), lo que **no se ha verificado** y lo que está **bloqueado**.

> Todo lo probado hasta ahora usa HDF5 **sintéticos** o el GCOV de prueba de ISCE3 (datos
> UAVSAR). **Ningún producto real de la misión NISAR se ha descargado ni leído todavía.**

## 1. Qué es y por qué va aparte

- NISAR (NASA-ISRO) es un radar de **banda L**; Sentinel-1 es **banda C**. No son el mismo canal.
- El producto usado es **L2 GCOV**: covarianza geocodificada, gamma0 en potencia, **ya con
  corrección radiométrica del terreno**. Por eso un GCOV **nunca** pasa por HyP3 RTC.
- Polarizaciones típicas HH/HV. `HHHH` es HH y `HVHV` es HV: nunca se rotulan como VV/VH.
- En la app, NISAR es un proveedor separado (selector «Sensor» de Herramientas SAR) y el motor
  rechaza comparar una escena de banda L con una de banda C.

## 2. Flujo

| Paso | Dónde | Qué hace | Estado |
| --- | --- | --- | --- |
| A. Catálogo | `utils/nisar_catalogo.py` · panel NISAR · `scripts/nisar.py buscar` | Consulta de **solo metadatos** al CMR de NASA (colección `NISAR_L2_GCOV_V1` = VALIDATED), sin credenciales. Interpreta el nombre del granule y lo contrasta con el catálogo. | Implementado · probado con respuestas sintéticas · consulta real: ver §6 |
| B. Descarga | `scripts/nisar.py descargar` | **Solo a mano**, un granule, tamaño confirmado, `EARTHDATA_TOKEN`. La app no descarga. | Implementado · probado con servidor simulado · **no verificado con ASF** |
| C. Recorte | `utils/nisar_gcov.py` · panel NISAR · `scripts/nisar.py recortar` | Lee **solo la ventana** del área del HDF5 y escribe gamma0 en potencia (GeoTIFF float32, NoData −9999) con ficha y SHA-256. El HDF5 no se toca. | Implementado · probado con sintéticos y con el GCOV de ISCE3 |
| D. Par | `utils/nisar_flujo.py` | Dos recortes solo forman par con el mismo track, frame, dirección, frecuencia, término y CRID. Si no, se explica el bloqueo. | Implementado · probado |
| E. Cambio | motor común `utils/analisis_sar.py` | Media móvil en **potencia** → 10·log10 → Δ = posterior − anterior; ≤ 0 inválido; umbrales **experimentales** escritos a mano. | Implementado · probado con sintéticos |
| F. Escena única | `utils/nisar_flujo.py` | gamma0 de una fecha en dB, sin umbral. Para cuando no hay par. | Implementado · probado |
| G. Mapa y QGIS | perfiles de resultado, `utils/qgis.py` | Capas con insignia de procedencia; paquete QGIS con GeoTIFF intacto y `.qml`. | Implementado · probado (QGIS Desktop: manual) |

## 3. Reglas de compatibilidad de un par

Catálogo (antes de descargar) y recortes (antes de calcular) exigen lo mismo:

- mismo **track**, **frame** y **dirección** de órbita;
- mismo **modo** (ancho de banda de las frecuencias A/B) y mismas **polarizaciones**;
- misma **frecuencia** (A o B) y mismo **término** (p. ej. HHHH con HHHH);
- mismo **CRID** (versión de procesamiento) y misma **madurez**;
- superposición dentro del área y al menos medio día entre tomas.

Un par que cumple todo en el catálogo es **«CANDIDATO NO VALIDADO»**: solo lo respaldan
metadatos. No hay ningún par declarado confirmado. Si las únicas escenas tienen órbitas o
frames distintos, **no hay cálculo de cambio**: se muestra el bloqueo y queda la escena única.

## 4. Lector GCOV: qué comprueba

- Rejillas en `/science/LSAR/GCOV/grids/frequencyA|B/`; identificación en `/science/LSAR/identification`.
- Solo términos **diagonales reales** (HHHH, HVHV, VVVV, VHVH, RHRH, RVRV). Los cruzados son
  complejos: se listan pero nunca se leen como potencia ni se pasan a dB.
- `xCoordinates`/`yCoordinates` como centros de píxel; cuadrícula regular (tolerancia relativa
  al paso); EPSG de `projection`; orientación x creciente, y decreciente (otras se rechazan).
- Inválido: NaN (relleno), valores ≤ 0 y máscara 255 (fuera del radar) o 0 (muestra no válida).
  Regla tomada del código de ISCE3 (`GeocodeCov.cpp`); **hay que confirmarla con un producto real**.
- Lee solo la ventana del área (tope de 16 millones de píxeles).
- Un producto cuyo `missionId` no es NISAR se marca **DEMO**, y lo derivado de él también.

## 5. Umbrales en banda L

- **No hay valores por defecto** y no se usan los de Sentinel-1 (VV −7,5 dB / VH −3 dB).
- Hay que escribirlos en cada análisis; quedan registrados como **experimentales, no calibrados**.
- En banda L el agua bajo vegetación suele **aumentar** la señal (doble rebote). Por eso se
  piden dos umbrales (disminución y aumento) y el resultado es «cambio de radar», nunca
  «inundación».
- Pendiente (no hecho): estudiar la estabilidad y sensibilidad por canal y cobertura con datos
  reales antes de proponer cualquier valor.

## 6. Procedencia

| Cosa | Estado que muestra la app |
| --- | --- |
| Producto GCOV VALIDATED | Es el dato de entrada: calibrado por la misión. **No** vuelve VALIDADO ningún mapa. |
| Recorte de un GCOV de la misión | REAL SIN VALIDAR (en su ficha); madurez `NO_COMPROBADA` salvo que se confirme. |
| Recorte de un GCOV sintético o de prueba | DEMO (`VISOR_DEMO=1`), y todo lo que se derive. |
| Mapa de cambio o escena única | Indicio. VALIDADO exigiría evidencia de campo documentada. |

## 7. Estado real de la verificación

**IMPLEMENTADO Y PROBADO (sin datos reales de NISAR)**

- Catálogo: 40 pruebas con respuestas UMM-G sintéticas, un nombre real del NISAR Cookbook de ASF
  y los 11 nombres reales de Chigorodó. **Consulta real ejecutada** en GitHub Actions (§8).
- Lector: 19 pruebas con HDF5 sintéticos + 1 con el GCOV de prueba de ISCE3 (estructura
  escrita por el procesador oficial; datos UAVSAR, versión de producto 0.1, EPSG:4326).
- Cálculo temporal: 13 pruebas (parche de −6 dB recuperado, bloqueos, mezcla con Sentinel-1 rechazada).
- Interfaz y QGIS: 8 pruebas (AppTest) + 1 de navegador. Descarga: 13 con servidor simulado.
- Verificador: recortes NISAR auditados; un recorte alterado da NO APTO.

**NO VERIFICADO**

- Lectura de un **GCOV real de NISAR** (estructura de la versión actual, máscara, UTM, tamaños).
- Descarga con Earthdata Login contra ASF.
- Todo el flujo en **Replit** y la apertura de los paquetes en **QGIS Desktop**.
- Valores de umbral con sentido físico para banda L en Urabá.

**BLOQUEADO**

- Desde el entorno de desarrollo no hay salida al CMR ni a ASF: la consulta real se hizo en
  GitHub Actions (trabajo «Catálogo NISAR real») y se puede repetir en Replit.
- Pares de los tracks 11, 47 y 112: solo hay una fecha en el catálogo.
- Cualquier descarga: requiere que el equipo confirme granule, tamaño y destino, y un token de
  Earthdata Login.

## 8. Escenas de Chigorodó: resultado REAL del catálogo

Consulta de solo metadatos al CMR de NASA, ejecutada en GitHub Actions el 13-nov-2026 a las
14:28 UTC (colección `NISAR_L2_GCOV_V1`, área −76,80 / 7,55 / −76,55 / 7,80, desde el 21-oct-2026).
**11 productos GCOV VALIDATED** tocan el área; todos con CRID P05036. Nada se descargó.

| Fecha (UTC) | Track · frame · órbita | Modo · polarizaciones | Cubre el área | HDF5 | Notas |
| --- | --- | --- | --- | --- | --- |
| 22-oct 10:47 | 148 · 5 · asc | 20+05 MHz · HH/HV | 41 % | 1,64 GB | modos mixtos |
| 22-oct 10:47 | 148 · 5 · asc | 40+05 MHz · HH/HV | 42 % | 2,45 GB | frame parcial |
| 24-oct 23:28 | 11 · 85 · desc | 40+05 MHz · HH/HV | 58 % | 7,34 GB | |
| 27-oct 10:39 | 47 · 5 · asc | 40+05 MHz · HH/HV | 69 % | 7,29 GB | |
| 27-oct 10:39 | 47 · 6 · asc | 40+05 MHz · HH/HV | 81 % | 5,74 GB | |
| 31-oct 23:36 | 112 · 84 · desc | 20+05 MHz · HH | 55 % | 1,19 GB | modos mixtos |
| 31-oct 23:36 | 112 · 84 · desc | 40+05 MHz · HH/HV | 55 % | 4,35 GB | frame parcial |
| 31-oct 23:36 | 112 · 85 · desc | 20+05 MHz · HH | 94 % | 1,23 GB | modos mixtos |
| 31-oct 23:36 | 112 · 85 · desc | 40+05 MHz · HH/HV | 94 % | 3,09 GB | frame parcial |
| 3-nov 10:47 | 148 · 5 · asc | 20+05 MHz · HH/HV | 40 % | 1,64 GB | modos mixtos |
| 3-nov 10:47 | 148 · 5 · asc | 40+05 MHz · HH/HV | 41 % | 2,29 GB | frame parcial |

**Pares candidatos (NO VALIDADOS), los dos del track 148 / frame 5, 22-oct → 3-nov (12 días):**

1. 20+05 MHz, HH/HV, modos mixtos, frame completo: 2 × 1,64 GB. Cubre ~41 % del área.
2. 40+05 MHz, HH/HV, un solo modo, frame parcial: 2,45 + 2,29 GB. Cubre ~41 % del área.

Lo que esto significa, sin adornos:

- **Sí existe un par temporal real**, pero solo sobre ~41 % del recuadro de Chigorodó. No se
  sabe aún qué parte (hay que ver la huella o inspeccionar el HDF5).
- La escena que mejor cubre el área (**94 %**, track 112 / frame 85, 31-oct) **no tiene segunda
  fecha** en el catálogo VALIDATED al momento de la consulta. Sirve como escena única.
- Los tracks 11, 47 y 112 solo tienen una fecha: sus pares quedan **bloqueados** hasta que el
  catálogo publique otra toma con el mismo track y frame.
- Los productos «modos mixtos» cambian de modo dentro del frame: antes de comparar hay que
  comprobar en el HDF5 que el modo es el mismo sobre el área.
- No se ha elegido ni descargado nada. La decisión (qué granule, cuántos GB, dónde) es del equipo.

El registro completo de la búsqueda está en `tests/datos/` (ver registro de cambios) y se
regenera con `scripts/nisar.py buscar`.

## 9. Uso en Replit (cuando la rama esté revisada)

```bash
git status --short                          # debe salir vacío
bash actualizar.sh feature/nisar-gcov       # instala h5py
bash verificar.sh
.venv/bin/python scripts/nisar.py buscar --inicio 2026-10-21     # solo metadatos
```

Descargar un granule (solo tras revisar su tamaño y el espacio de Replit; `EARTHDATA_TOKEN` en Secrets):

```bash
.venv/bin/python scripts/nisar.py descargar --registro data/nisar/catalogo/busqueda_….json \
    --granule NISAR_L2_PR_GCOV_… --confirmo-gb <tamaño>
.venv/bin/python scripts/nisar.py inspeccionar data/nisar/crudos/NISAR_L2_PR_GCOV_….h5
.venv/bin/python scripts/nisar.py recortar data/nisar/crudos/NISAR_L2_PR_GCOV_….h5 --termino HHHH --madurez VALIDATED
bash start.sh                               # recarga solo V.I.S.O.R., sin Stop
```

`data/nisar/` y `*.h5` están fuera de Git.

## 10. Hipótesis y limitaciones

- Se asume que los GCOV VALIDATED conservan la estructura de grupos descrita por ASF e ISCE3.
- El significado de la máscara viene del código de ISCE3, no de un documento de producto.
- La madurez no está dentro del HDF5: se toma del catálogo o queda `NO_COMPROBADA`.
- Solo se admite la orientación estándar de la cuadrícula.
- Filtro de speckle: media móvil; el GCOV ya trae multilooking adaptativo.
- Sin InSAR, sin polarimetría (términos cruzados) y sin series temporales.
- Reglas de la competencia sobre trabajo previo al evento: **sin respuesta escrita del
  organizador**; revisar antes del envío final.

## Fuentes

- NISAR GCOV, madurez, problemas conocidos, búsqueda y QGIS: nisar-docs.asf.alaska.edu
- NISAR Cookbook (ASF): github.com/ASFOpenSARlab/NISAR_Cookbook
- `asf_search` (colecciones y campos del catálogo): github.com/asfadmin/Discovery-asf_search
- ISCE3 (escritor GCOV, máscara, nombres de granule): github.com/isce-framework/isce3
