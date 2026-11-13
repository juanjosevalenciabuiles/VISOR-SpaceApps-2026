# Registro de cambios de V.I.S.O.R.

Para explicar en la hackathon **qué hace** V.I.S.O.R., **cómo se desarrolló** y **qué datos
usa**. Se actualiza con cada cambio importante. Los identificadores son commits de Git; la
historia completa está en `git log`.

## Cómo se desarrolló

- **Equipo:** cinco integrantes (UdeA). Tareas, estados y roles se gestionan en Notion.
- **Código:** GitHub es la fuente de verdad. Cada tarea en su rama y por Pull Request; `main`
  solo recibe código probado. Los PR #2 a #5 siguen sin fusionarse a `main`.
- **Asistencia de IA:** buena parte del código, las pruebas y la documentación se escribió con
  Claude (Anthropic) mediante Claude Code, siguiendo especificaciones y revisiones del equipo.
  Los commits de esa asistencia aparecen con autor «Claude» y la línea `Co-Authored-By`.
  El agente de IA de Replit solo hizo un commit de configuración (`f6a27c7`); por decisión del
  equipo no se usa para cambiar la aplicación.
- **Ejecución:** Replit (`start.sh`, `actualizar.sh`, `verificar.sh`). Las pruebas corren
  también en GitHub Actions en cada push.
- **Procesamiento SAR pesado:** fuera de la app, en ASF HyP3, por el equipo. La app no descarga
  ni procesa escenas completas en vivo.

## Datos utilizados

| Dato | Origen | Uso | Estado |
| --- | --- | --- | --- |
| Catálogo Sentinel-1 | ASF (búsqueda pública, solo metadatos) | Buscar escenas y proponer pares | Respuesta real guardada en `tests/datos/` para pruebas sin red |
| RTC VV y VH de Chigorodó | Sentinel-1C, 24-sep y 6-oct-2026, órbita ascendente 48, procesados en ASF HyP3 a 30 m por el equipo | Entrada del motor | En Replit (`data/sar/`), fuera de Git |
| `coincidencia_VV_VH_20260924_20261006.tif` | Generado con el motor y `combinar_vv_vh.py` | Resultado reproducible | REAL SIN VALIDAR |
| `coincidencia_VV_VH_Chigorodo.tif` | Script exploratorio del equipo | Resultado exploratorio | Procedencia no declarada; difiere en 15.860 px del reproducible (umbral VV) |
| Hidrografía y vías | Natural Earth 1:10m v5.1.2, dominio público | Contexto cartográfico | Escala general |
| `inundacion.tif`, `deslizamiento.tif`, `deforestacion.tif` | Sintéticos | Demostración de la interfaz | Marcados DEMO |
| Cruce Sentinel-1C × JRC de Chigorodó | Hecho por el equipo en QGIS (13-nov-2026): 40.296 px de detección, 4.004 sobre JRC Occurrence > 0 (360,36 ha) | Referencia para comprobar el cruce automático | Cifras comunicadas; la reproducción con los GeoTIFF reales está pendiente en Replit |
| JRC Global Surface Water Occurrence (1984–2024) | JRC / Comisión Europea; lo copia el equipo en `data/jrc/` | Agua histórica para el cruce | Fuera de Git; no valida eventos de 2026 |
| Límites municipales | DANE (MGN) o IGAC; los copia el equipo en `data/limites/` | AOI y estadísticas por municipio | Fuera de Git; la app no trae polígonos inventados |

No se ha descargado ni procesado NISAR. No se han enviado trabajos a HyP3 desde la app.

## Cronología

### 11-nov-2026 · Base del visor

- MVP v1.0 y v1.1 del equipo: Streamlit + Folium, tres fenómenos con demos (`dffb736`, `1edbf0f`).
- Arranque reproducible en Replit, protecciones de Streamlit, cargador GeoTIFF y sistema
  cartográfico multicapa (`502dcae`, `30f7d3e`); actualización segura desde GitHub (`9dfdf82`).
- PR #1 fusionado a `main`; mapa único del equipo (`88a342e`).
- **PR #2** Motor de análisis temporal SAR para RTC de HyP3 (`ebbd5f5`).
- **PR #3** Buscador de escenas Sentinel-1 en ASF con emparejado antes/después (`9599f63`).

### 12-nov-2026 · Mission Control, procedencia y Fase C

- **PR #4 · Fase A:** tema Mission Control (Liquid Glass), mapa único a pantalla completa con
  superficies flotantes (`a6ba559`, `b1dd49b`).
- **PR #4 · Fase B:** cuatro estados de procedencia (`517f576`), combinación VV/VH reproducible
  (`8b861c0`), resultados como capas (`9845e86`), ficha científica (`7385aee`).
- **PR #5 · QGIS y Fase C:** exportación con GeoTIFF intacto y auditoría (`2d8996d`), flujo
  catálogo ASF → RTC locales → motor → resultados (`70ac7a2`, `edf444a`).
- **Pruebas automáticas:** invariantes del motor (`f0c8dad`), Playwright (`b9f6c11`),
  verificador integral con veredicto (`2aba9ff`), GitHub Actions (`97ca9ee`).
- **Estabilización para Replit:** Expat en el almacén configurado (`4530067`), perfil continuo
  para `…_dif_db.tif` (`33ca4fd`), actualizar y verificar sin el botón Stop (`add074a`).

### 12-nov-2026 · Revisión autónoma para versión candidata

| Commit | Cambio | Por qué importa |
| --- | --- | --- |
| `8027be5` | Prueba de seguridad de metadatos con HTML | Confirma que fichas y etiquetas se muestran escapadas |
| `e2e734b` | Imagen de resultados en caché, una sola lectura, tope en dB | Redibujar el mapa pasó de 0,145 s a 0,023 s; memoria acotada con rásteres grandes |
| `f7883c1` | `shapely` declarada; prueba de importaciones no declaradas | Evita fallos de instalación en un entorno limpio |
| `ea10fb3` | El motor no sobrescribe; SHA-256 de entradas y salidas; área según unidades del CRS | Repetir un análisis ya no borra el anterior ni invalida fichas VV/VH |
| `fe17839` | «Mismo día» exige aceptación y queda no confirmada; RTC empatados; sesión entre páginas | Una asociación dudosa nunca pasa por confirmada; corrige un fallo al abrir Mission Control tras usar la página Analisis SAR |
| `5e36961` | Nombres reservados de Windows; lista manual Q1–Q8 de QGIS Desktop | Paquetes que se abren en cualquier sistema |
| `f9a9604` | El verificador convierte cualquier excepción en NO APTO | Ningún error puede quedar oculto |
| `6f130de` | Firefox en CI; el navegador que no arranca falla en vez de omitirse | Las pruebas e2e no pueden pasar «en verde» sin ejecutarse |

Validación científica añadida (`tests/test_validacion_cientifica.py`): parche de −6 dB
recuperado exactamente, detección con speckle gamma (ENL 4,9) con más de 97 % de acierto y
menos de 2 % de falsos cambios, reducción de varianza del filtro acorde a la teoría,
reconstrucción de la máscara desde el dB continuo y conversión de unidades del CRS.

### 13-nov-2026 · Alcance regional y cruce SAR × JRC (rama `feature/regional-uraba`)

El equipo decidió que V.I.S.O.R. deje de limitarse a Chigorodó: región piloto Chigorodó, Carepa, Apartadó y
Turbo, ampliable a Urabá y a otras áreas. Entregó un prototipo independiente del cruce SAR × JRC
(`VISOR_automatizacion_regional_para_Claude_2026-11-13.zip`, 6 pruebas sintéticas) y sus cifras de QGIS.
Se revisó y se integró en una rama propia, separada de NISAR (PR #6).

| Commit | Fase | Cambio |
| --- | --- | --- |
| `687e2bb` | R1 | AOI configurable: municipios oficiales, uniones y GeoJSON |
| `6e0287a` | R2 | Cruce SAR × JRC por bloques, por municipio y por umbrales; puerta de reproducción de Chigorodó |
| `cf12c8c` | R3 | Cobertura sobre el polígono, pasadas, pares comparables y mosaico de una pasada con caché |
| `0922cfa` | R4 | Paso «05 · Regional» en Mission Control; capas del cruce exportables a QGIS |
| `dca57ee` | R5 | El verificador reproduce el cruce de Chigorodó cuando los GeoTIFF reales están en `data/` |

Cambios frente al prototipo: el tamaño de bloque se usa de verdad; zonas solapadas cuentan en ambas; se añade
cobertura por municipio y N/D; se rechazan máscaras NISAR; las salidas llevan ficha de procedencia y entran al
explorador y a QGIS; hay caché; no se añade ninguna dependencia nueva salvo declarar `pyproj`.

Estado real: probado con datos sintéticos y con el catálogo de ASF guardado. **El cruce no se ha ejecutado con
los GeoTIFF reales** (están en Replit) y por eso el análisis regional está bloqueado en la app. No existe aún
ninguna cifra para Carepa, Apartadó ni Turbo. Detalle en `docs/regional.md`.

## Cómo añadir una entrada

Una línea por cambio importante: fecha, commit, qué cambió y por qué importa para explicar el
proyecto. Si cambia un dato usado, actualizar también la tabla «Datos utilizados».
