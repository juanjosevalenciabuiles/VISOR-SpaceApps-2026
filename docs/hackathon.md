# V.I.S.O.R. en la hackathon · documento técnico

NASA Space Apps Challenge 2026 · reto «Dancing with the SARs» · Antioquia, Colombia.
Estado al 12-nov-2026, rama `feature/qgis-fase-c` (PR #5). Lo que no se ha ejecutado se dice.

## 1. Qué es

Una aplicación web (Python + Streamlit) que convierte imágenes de radar Sentinel-1 ya
procesadas en mapas que se pueden explicar: dónde bajó o subió la retrodispersión entre dos
fechas, con qué datos, con qué parámetros y con qué grado de confianza. Un cambio de señal
es un **indicio**, nunca una inundación confirmada.

## 2. Arquitectura

```
                       ┌──────────────────────────── app.py (Mission Control) ───────────────────────────┐
  Navegador ◄─────────►│ components/interfaz.py   barra superior, paneles flotantes, «Ir a…»             │
                       │ components/mapa.py       un solo mapa Folium (st_folium, sin recargas al moverlo)│
                       │ components/herramientas_sar.py   01 área → 02 escenas → 03 análisis → 04 resultados│
                       │ components/resultados.py ficha científica, leyenda, exportar para QGIS          │
                       └──────────────┬───────────────────────────────────────────────┬──────────────────┘
                                      │                                               │
            utils/buscador_sar.py ────┤  catálogo ASF (solo metadatos, sin descargar) │
            utils/flujo_sar.py ───────┤  RTC locales ↔ escenas del catálogo           │
            utils/analisis_sar.py ────┤  motor: alinear, filtrar, dB, Δ, máscara      │
            utils/combinacion_sar.py ─┤  VV + VH → coincidencia, ficha de procedencia │
            utils/procedencia.py ─────┤  4 estados + SHA-256                          │
            utils/resultados.py ──────┤  perfiles de resultado (clases / dB continuo) │
            utils/diferencia_db.py ───┤  rampa ±10 dB, estadísticas                   │
            utils/qgis.py ────────────┘  paquete ZIP (GeoTIFF intacto + QML + manifiesto)
                                      │
                         data/  (fuera de Git salvo los demos)
                           ├─ sar/        RTC de HyP3 copiados por el equipo
                           ├─ analisis/   resultados generados (nunca se sobrescriben)
                           ├─ contexto/   hidrografía y vías (Natural Earth)
                           └─ *.tif       tres demos sintéticos (VISOR_DEMO=1)
```

Páginas adicionales: `pages/1_Analisis_SAR.py` (motor con parámetros completos) y
`pages/2_Buscador_SAR.py` (buscador independiente). Herramientas de línea de comandos en
`scripts/` (analizar, combinar, auditar, exportar para QGIS, verificar).

**Regla de oro (arquitectura híbrida):** la app no descarga ni procesa gigabytes en vivo.
Lee GeoTIFF ya procesados de `data/`. El catálogo de ASF solo se consulta para metadatos.

## 3. Flujo completo: Sentinel-1 → RTC → análisis → resultados → QGIS

| Paso | Dónde ocurre | Qué se hace | Estado |
| --- | --- | --- | --- |
| 1. Escenas | ASF (catálogo público) | Búsqueda de Sentinel-1 GRD IW por región y fechas; pares antes/después con la misma órbita relativa y dirección y al menos una polarización común (se prefiere el mismo satélite; las versiones duplicadas de ASF se avisan) | Implementado; consulta real probada a mano |
| 2. RTC | ASF HyP3 (fuera de la app) | GRD → RTC gamma0 a 30 m, potencia, UTM | **Hecho por el equipo fuera de la app.** Generarlo desde la app es la Fase D (sin implementar, requiere autorización y consume créditos) |
| 3. Copia | `data/sar/` | El equipo copia los RTC con su nombre de HyP3 | Manual |
| 4. Asociación | `utils/flujo_sar.py` | RTC ↔ escena del par: **exacta** (mismo satélite, ±2 s) o **mismo día** (requiere aceptación expresa y queda «no confirmada»); varios candidatos = ambiguo, no se elige | Implementado y probado |
| 5. Análisis | `utils/analisis_sar.py` | Cuadrícula de la imagen anterior ∩ AOI → media móvil en potencia → 10·log10 → Δ = después − antes → máscara con umbral por polarización | Implementado y probado |
| 6. VV + VH | `utils/combinacion_sar.py` | Clases 1 = solo VV, 2 = solo VH, 3 = ambas, 0 = ninguna, 255 = sin dato; ficha JSON con SHA-256 | Implementado y probado |
| 7. Visualización | Mission Control | Capa opcional con insignia de procedencia, leyenda, ficha y estadísticas | Implementado y probado (Chromium; Firefox en CI) |
| 8. QGIS | `utils/qgis.py` | ZIP con el GeoTIFF original byte a byte, estilo `.qml`, leyenda, ficha, AOI y manifiesto SHA-256 | Implementado; abrir en QGIS Desktop es **manual** (lista Q1–Q8 en `docs/qgis.md`) |

### Datos reales usados (Chigorodó, Urabá antioqueño)

- Sentinel-1C IW GRDH, órbita ascendente, relativa 48: 24-sep-2026 y 6-oct-2026, 23:22:18 UTC.
- RTC de ASF HyP3 a 30 m, VV y VH, procesados por el equipo.
- Cuadrícula de resultados: EPSG:32618, 924 × 926 píxeles, NoData 255.
- Dos productos VV/VH **no equivalentes** y documentados así:
  - `coincidencia_VV_VH_Chigorodo.tif`, exploratorio y sin ficha (procedencia no declarada);
  - `coincidencia_VV_VH_20260924_20261006.tif`, reproducible, con ficha REAL SIN VALIDAR, umbral VV −7,5 dB y VH −3 dB.
- Difieren en 15.860 píxeles, todos por el umbral VV. No se exige ni se fuerza la equivalencia.
- Las cifras de referencia están en `tests/datos/referencia_chigorodo.json`.
- Contexto cartográfico: Natural Earth 1:10m v5.1.2 (dominio público; solo ríos y vías principales).
- Demos sintéticos (`inundacion.tif`, `deslizamiento.tif`, `deforestacion.tif`), marcados como DEMO.

## 4. Lo que la aplicación garantiza

- **Procedencia en cuatro estados** (DEMO / NO DECLARADA / REAL SIN VALIDAR / VALIDADO). Un
  estado real exige ficha completa y que el SHA-256 del GeoTIFF coincida con ella. VALIDADO
  exige evidencia documentada; hoy ningún producto lo tiene.
- **Nada se sobrescribe:** el motor, la combinación y el flujo crean `_r2`, `_r3`…; un
  prefijo explícito ocupado detiene el análisis salvo `--sobrescribir`.
- **Trazabilidad:** cada `_analisis.json` registra parámetros, método, avisos, limitaciones y
  el SHA-256 de las dos escenas de entrada y de cada salida.
- **Coherencia entre salidas:** aplicar los mismos umbrales al `_dif_db.tif` reproduce la
  máscara exactamente (probado).
- **Escapado de metadatos:** el texto de fichas y etiquetas nunca se interpreta como HTML.
- **Lenguaje:** ninguna etiqueta afirma una inundación (probado).

## 5. Limitaciones científicas

- Una disminución de retrodispersión puede ser agua en superficie, pero también humedad del
  suelo, cosechas, quemas, viento o cambios de rugosidad.
- Bajo dosel denso la banda C apenas ve el agua; la vegetación inundada puede **aumentar** la señal.
- Sombra y layover en ladera: el radar no observa bien el terreno (relevante en Antioquia).
- El agua permanente es oscura en ambas fechas: no aparece como cambio.
- El filtro de speckle es una media móvil (boxcar) en potencia: reduce falsos cambios a costa
  de detalle; no es un filtro adaptativo (Lee, Refined Lee).
- Solo dos fechas; umbrales **no calibrados** para la zona; no hay validación de campo.
- Los resultados de Chigorodó son REAL SIN VALIDAR: indicios, no un mapa de inundación.

## 6. Pruebas

| Batería | Cómo se ejecuta | Qué cubre |
| --- | --- | --- |
| Unidad e integración | `python -m pytest -q -m "not navegador and not red"` | motor, validación científica con verdad conocida, procedencia, combinación, QGIS, flujo de Fase C (casos excepcionales), interfaz con `AppTest`, seguridad, dependencias |
| Navegador | `python -m pytest -q -m navegador` | 19 escenarios de Mission Control en Chromium (escritorio, 1200–1366 px, móvil); Firefox en GitHub Actions |
| Red | `VISOR_PRUEBAS_RED=1 python -m pytest -q -m red` | consulta real al catálogo de ASF (manual) |
| Verificación integral | `bash verificar.sh` | todo lo anterior + datos reales de `data/`, referencia de Chigorodó, garantía de solo lectura; veredicto APTO / APTO CON ADVERTENCIAS / NO APTO |
| GitHub Actions | cada push y PR | ruff, unidad, verificación `--ci`, navegador (Chromium y Firefox) |

Cualquier excepción durante la verificación cuenta como fallo crítico (NO APTO); una batería
sin pruebas o un navegador que no arranca en CI también fallan. Detalles en `docs/pruebas.md`.

**Manual:** QGIS Desktop (lista Q1–Q8), Safari y teléfono físico, juicio científico.

## 7. Funciones pendientes

- **Fase D:** generar RTC con ASF HyP3 desde la app (cuenta Earthdata, créditos). Plan en
  `docs/fase_d_earthdata_hyp3.md`; no se ejecuta sin autorización expresa.
- Calibración de umbrales para Urabá y validación con información de campo o de autoridades.
- Filtro de speckle adaptativo y series de más de dos fechas.
- Precipitación (p. ej. GPM IMERG) como capa de contexto con fecha.
- Hidrografía y vías de mayor detalle (IGAC, IDEAM u OpenStreetMap).
- Deslizamientos (fase InSAR) y deforestación (coherencia): hoy solo existen como demos.

## 8. NISAR (banda L)

Desde el 13-nov-2026 hay una integración en la rama `feature/nisar-gcov` (PR aparte, sin
fusionar): catálogo de solo metadatos, lector de L2 GCOV, cálculo temporal con el motor común,
escena única, panel propio en Mission Control y exportación QGIS. Sentinel-1C **no** es NISAR y
las dos bandas nunca se combinan. Está probada con HDF5 **sintéticos**; **ningún producto real
de NISAR se ha descargado ni leído**. Estado exacto, escenas reales disponibles sobre Chigorodó
y límites en [`docs/nisar.md`](nisar.md).
