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
| Catálogo NISAR L2 GCOV VALIDATED | CMR de NASA / ASF, consulta real del 13-nov-2026 (solo metadatos) | Saber qué escenas de banda L existen sobre Chigorodó | 11 productos, 2 pares candidatos no validados (~41 % del área) |
| HDF5 GCOV sintéticos | `tests/nisar_sintetico.py` | Probar el lector y el cálculo NISAR | Inventados; marcados DEMO |
| GCOV de prueba de ISCE3 | Repositorio de ISCE3 (datos UAVSAR) | Comprobar la estructura que escribe el procesador oficial | No es NISAR; no se redistribuye |

NISAR: solo se ha consultado el catálogo (metadatos). No se ha descargado ni procesado ningún producto real. No se han enviado trabajos a HyP3 desde la app.

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

### 13-nov-2026 · Integración NISAR (rama `feature/nisar-gcov`)

El equipo autorizó empezar NISAR antes de la hackathon y entregó un prototipo independiente
(`VISOR_NISAR_inicio_2026-11-13.zip`, 5 pruebas sintéticas). Se revisó contra la documentación
de ASF y el código de ISCE3 y se adaptó al repositorio real.

| Commit | Fase | Cambio |
| --- | --- | --- |
| `a4d38a0` | N1 | Catálogo NISAR GCOV de solo metadatos (CMR), separado de Sentinel-1; pares «CANDIDATO NO VALIDADO» |
| `643fd24` | N2 | Lector GCOV: solo términos diagonales, ventana del área, GeoTIFF gamma0 en potencia con ficha y SHA-256 |
| `12e4000` | N3 | Motor: sensores y bandas no se mezclan; umbrales experimentales obligatorios en banda L; escena única |
| `04099b6` | N4 | Panel NISAR en Mission Control; perfil y escala propios; QGIS |
| `a6b09f3` | N5 | Descarga confirmada a mano, verificador NISAR, CI con GCOV de ISCE3 y catálogo real informativo |

Cambios respecto al prototipo: la regularidad de la cuadrícula se mide relativa al paso (la
tolerancia absoluta no detectaba saltos en grados); la máscara descarta 0 además de 255; no se
añade `asf_search` (se consulta el CMR directamente); la madurez no se supone; los productos
que no son de la misión quedan DEMO.

Resultado real del catálogo (13-nov, 14:28 UTC): 11 GCOV VALIDATED sobre Chigorodó; dos pares
candidatos del track 148 / frame 5 (22-oct → 3-nov) que cubren ~41 % del área; la escena de
mayor cobertura (94 %, track 112) no tiene segunda fecha. Detalle en `docs/nisar.md`.

Regla de la competencia sobre trabajo previo al evento: sigue **sin respuesta escrita** del
organizador.

## Cómo añadir una entrada

Una línea por cambio importante: fecha, commit, qué cambió y por qué importa para explicar el
proyecto. Si cambia un dato usado, actualizar también la tabla «Datos utilizados».
