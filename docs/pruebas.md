# Pruebas automáticas de V.I.S.O.R.

Objetivo: decidir con **una sola ejecución** si una versión es segura para actualizar
Replit o fusionar, sin pruebas manuales salvo las que exigen hardware o software que no
hay en la nube (QGIS Desktop, teléfono físico).

## Un solo comando

```bash
bash verificar.sh                # Replit / Linux: todo lo posible en este entorno
bash verificar.sh --navegador    # exige además las pruebas de navegador
bash verificar.sh --red          # añade una consulta REAL a ASF
bash verificar.sh --sin-pytest   # rápido: entorno, Git, app y datos reales
```

En Windows (PowerShell): `python scripts\verificar_visor.py`.

Resultado: un **veredicto** en pantalla y un informe en `informes/verificacion_<fecha>.md`
(y `.json`), fuera de Git. El comando termina con código 1 si el veredicto es NO APTO.

| Veredicto | Significado | Qué hacer |
| --- | --- | --- |
| **APTO** | Todo lo crítico e importante se comprobó y aprobó | Se puede integrar |
| **APTO CON ADVERTENCIAS** | Nada bloqueante falló, pero hay advertencias o partes críticas sin comprobar aquí (p. ej. el navegador en Replit) | Leer «Requiere atención» y «No comprobado»; confirmar con GitHub Actions |
| **NO APTO** | Falló algo crítico o importante | No actualizar Replit ni fusionar |

Ninguna prueba valida científicamente un resultado SAR: comprueban que el software hace lo
que dice y que los datos no cambiaron. Las clases son indicios de cambio de
retrodispersión, no inundaciones confirmadas.

## Qué se comprueba

| Área | Dónde | Comprobaciones |
| --- | --- | --- |
| Entorno | verificador | Python ≥ 3.11, dependencias y sus series de versión |
| Git | verificador | Cambios locales sin commit (p. ej. del agente de Replit), merge/rebase a medio terminar, sincronía con la rama remota |
| Código | pytest + ruff | Unidad e integración: cargador, cartografía, interfaz, procedencia, combinación VV/VH, resultados, QGIS, auditoría, flujo SAR, importaciones |
| Motor SAR | `tests/test_invariantes_sar.py` | CRS, cuadrícula y NoData de salida; dB exactos; clases por umbral; superficies (ha = píxeles × área); estadísticas; umbral más estricto ⇒ nunca más disminuciones; entradas intactas |
| Procedencia | `tests/test_procedencia.py`, verificador | Los cuatro estados; ficha completa; SHA-256 del GeoTIFF = el de la ficha |
| QGIS | `tests/test_qgis_auditoria.py`, verificador, navegador | ZIP: GeoTIFF idéntico, ficha idéntica, manifiesto con huellas correctas, `.qml` de paleta con los colores y transparencias del perfil, GeoJSON válido; detecta manipulaciones |
| ASF | `tests/test_buscador_sar.py`, `tests/test_flujo_sar.py` | Con la respuesta real guardada (`tests/datos/`), sin red. La consulta real está aparte: `tests/test_asf_red.py` (marca `red`) |
| Mission Control | `tests/e2e/` (Playwright, marca `navegador`) | Mapa único, rueda y arrastre, paneles que conservan estado, Ir a… (incluido valor inválido), ayuda, Herramientas SAR (abrir, minimizar, restaurar, cerrar), resultados como capas (colores, opacidad, fenómeno, mapa sin recrear), insignias DEMO frente a REAL SIN VALIDAR, exportación QGIS descargada y verificada, flujo AOI → catálogo → RTC → motor → resultado, sin superposiciones en 7 tamaños y en móvil |
| NISAR (banda L) | `tests/test_nisar_*.py`, verificador | Con HDF5 **sintéticos** y respuestas de catálogo sintéticas: nombres de granule, pares y bloqueos; solo términos diagonales; ventana del área; máscara y NoData; banda L nunca con banda C; umbrales obligatorios; escena única; descarga solo confirmada; recortes de `data/nisar/` (etiquetas y SHA-256). Estructura real del procesador: GCOV de prueba de ISCE3 (`VISOR_GCOV_ISCE3`, en CI). Consulta real: trabajo «Catálogo NISAR real» y `tests/test_nisar_red.py` |
| App con datos reales | verificador | Arranca con `data/` real y activa cada resultado: sin excepciones y con el aviso científico |
| Datos reales | verificador | Por cada GeoTIFF de `data/analisis/`: perfil, Σ clases = válidos, NoData, superficies, ficha y SHA-256, paquete QGIS; comparación con `tests/datos/referencia_chigorodo.json` |
| Solo lectura | verificador | Huella de cada archivo de `data/` antes y después; cualquier cambio ⇒ NO APTO |

### Referencia de Chigorodó y la diferencia de 15.860 píxeles

`tests/datos/referencia_chigorodo.json` guarda lo que el equipo verificó en Replit el
12-nov-2026: cuadrícula (EPSG:32618, 924 × 926, NoData 255, 91 px sin dato), conteos por
clase de los dos productos, sus estados de procedencia y los umbrales del reproducible
(VV −7,5 dB / VH −3,0 dB).

Los dos productos **no son equivalentes** y no se exige que lo sean: se comprueba que
siguen difiriendo en exactamente **15.860 píxeles** (configuraciones distintas; toda la
diferencia viene de VV). Si un archivo cambia respecto a la referencia, el verificador
lo marca como ADVERTENCIA: puede ser una regeneración legítima, pero hay que saberlo.
Nunca se corrige un dato para que coincida.

Si el equipo regenera un producto a propósito, se actualiza la referencia en un commit
aparte, explicando por qué.

## GitHub Actions (`.github/workflows/pruebas.yml`)

En cada push (cualquier rama) y cada pull request:

1. **Unidad, integración, ruff y verificación:** `ruff`, `pytest -m "not navegador and not red"`
   y el verificador en modo `--ci`. El informe aparece en el resumen del trabajo y como
   artefacto `informe-calidad`.
2. **Mission Control en Chromium:** instala Playwright y corre `pytest -m navegador`. Si
   algo falla, las capturas quedan en el artefacto `informe-navegador`.
3. **Consulta real a ASF:** solo a mano (Actions → Pruebas → Run workflow → `red`).

CI no tiene los datos reales (no están en Git): esas comprobaciones se hacen en Replit con
`bash verificar.sh`.

## Ejecutar partes sueltas

```bash
.venv/bin/python -m pytest -q -m "not navegador and not red"   # unidad e integración
.venv/bin/python -m pip install -r requirements-dev.txt        # una vez, para el navegador
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q -m navegador                     # Mission Control
VISOR_PRUEBAS_RED=1 .venv/bin/python -m pytest -q -m red       # ASF real
```

En Replit, Chromium puede no arrancar por bibliotecas del sistema que faltan. En ese caso
el verificador lo indica como OMITIDA (no como aprobada) y GitHub Actions cubre el
navegador.

Variables solo para pruebas (la app las rotula si están activas):

- `VISOR_DATA_DIR`: usa otra carpeta de datos (las pruebas trabajan sobre copias temporales).
- `VISOR_ASF_SIMULADO`: respuesta de ASF guardada; el paso 02 muestra «CATÁLOGO SIMULADO».
- `VISOR_E2E_RECURSOS`: Leaflet y jQuery locales para entornos sin Internet.

## Actualizar Replit y verificar sin el botón Stop

```bash
git status --short                          # debe salir vacío (data/ e informes/ están ignorados)
bash actualizar.sh feature/qgis-fase-c      # trae la versión; no toca data/
bash verificar.sh                           # no necesita detener la app
bash start.sh                               # opcional: recarga la app con la versión nueva
```

`verificar.sh` no usa el puerto de la app: las pruebas de navegador levantan su propio
servidor en un puerto libre sobre una copia temporal de datos. `start.sh` cierra solo la
instancia anterior de V.I.S.O.R. (comprueba PID, carpeta y comando) y arranca la nueva;
nunca cierra procesos ajenos. Se detiene con Ctrl+C.

## Productos continuos (diferencia en dB)

`…_dif_db.tif` del motor (Δ = posterior − anterior, NoData −9999) se reconoce como
**Diferencia de retrodispersión (dB)**: rampa divergente fija de ±10 dB, sin umbral,
estadísticas de la distribución y exportación QGIS en pseudocolor. El verificador comprueba
unidades, NoData, coherencia de conteos, estadísticas finitas, ficha y paquete QGIS. Las
retrodispersiones de cada fecha (`…_antes_db.tif`, `…_despues_db.tif`) siguen sin perfil:
se listan como «no se muestran».

## Lo que sigue siendo manual

- Abrir el ZIP exportado en **QGIS Desktop** (la estructura del `.qml` sí se verifica).
- **Safari, Firefox y teléfono físico** (las pruebas usan Chromium, también en modo móvil).
- Juicio científico de los resultados.
