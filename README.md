# V.I.S.O.R.

**Visualización Inteligente de Superficies y Observación por Radar** · NASA Space Apps Challenge 2026 · reto *Dancing with the SARs*

**App publicada:** https://visor-space-apps-2026--juanvalenciab1.replit.app

V.I.S.O.R. es una plataforma web para explorar cambios en la superficie de Colombia con radar de apertura sintética (SAR), sobre todo cambios relacionados con agua e inundaciones. La persona elige una zona y un periodo; la app busca tomas del satélite **NISAR** (NASA-ISRO, banda L), recorta en la nube solo lo necesario, aplica control de calidad píxel a píxel y dibuja en el mapa dónde cambió la señal del radar, con la procedencia de cada archivo.

> **Regla esencial:** un cambio en la retrodispersión del radar **no confirma por sí solo una inundación**. Lluvia, humedad del suelo, cultivos, relieve o ruido también cambian la señal. Todo resultado se etiqueta **REAL · SIN VALIDAR** hasta contrastarlo con una fuente independiente.

*English summary:* V.I.S.O.R. lets anyone pick an area in Colombia and a date range, finds NASA-ISRO NISAR L-band radar scenes, subsets them in the cloud with NASA Harmony, applies per-pixel quality masks and maps the radar backscatter change (ΔdB) with full provenance (SHA-256). Results are change indicators, not confirmed floods. The interface is bilingual (ES/EN).

---

## Qué hace

| Función | Descripción |
|---|---|
| **Mapa Mission Control** | Un solo mapa oscuro con paneles flotantes, mapas base intercambiables y guía de bienvenida bilingüe (ES/EN). |
| **Modo Colombia** | Solo acepta zonas dentro del límite oficial (DANE MGN 2025, con San Andrés y Providencia). Rechaza zonas que salen del país. |
| **Zona y periodo** | Buscador de municipios, dibujo de rectángulo en el mapa y zonas de estudio sugeridas (Chigorodó, Atrato en Quibdó, etc.). |
| **Contexto de la zona** | Panel derecho con municipios cubiertos, alertas hidrológicas vigentes del **IDEAM**, eventos de **NASA EONET** y ficha del lugar. Las alertas IDEAM y los municipios DANE también se dibujan en el mapa. |
| **Análisis NISAR automático** | Busca en el catálogo de NASA (CMR/ASF) dos tomas NISAR L2 GCOV compatibles, pide a **NASA Harmony** los recortes COG de la zona (intensidad, máscara y looks), calcula ΔdB y publica un GeoTIFF con ficha. |
| **Modo jurado** | Muestra un par NISAR real ya preparado (ANTES/DESPUÉS) y calcula su ΔdB con archivos locales, sin descargar nada. |
| **ECO** | Guía animado que explica cada paso con el estado real de la app; nunca inventa cifras. |
| **Laboratorio IA** | Página aparte con los modelos históricos del Atrato (Quibdó): clases derivadas de NISAR y zonas de 2 km priorizadas. Es una demostración histórica, no una alerta vigente. |
| **Exportación QGIS** | GeoTIFF original byte a byte, estilo `.qml`, ficha JSON y manifiesto con SHA-256. |
| **Respaldo Sentinel-1** | Análisis temporal con RTC de Sentinel-1 (ESA, procesados con ASF HyP3) cuando ya están en `data/sar/`. |

## Cómo funciona el análisis NISAR

```text
Zona (Colombia) + periodo
   → catálogo NASA CMR/ASF: dos tomas NISAR L2 GCOV, misma órbita y stack, una sola madurez (VALIDATED, o PROVISIONAL declarada)
   → NASA Harmony: recorte COG de la zona (HHHH o VVVV, mask, numberOfLooks), con límite de transferencia por trabajo
   → control de calidad por píxel en ambas fechas:
        γ⁰ > 0 y finito · mask entre 1 y 254 · numberOfLooks ≥ 1 · misma cuadrícula y CRS (sin remuestreo)
   → ΔdB = 10·log10(γ⁰ posterior / γ⁰ anterior)
   → GeoTIFF + ficha visor.ficha.v1 + SHA-256 → mapa (azul: bajó la señal · naranja: subió)
```

- Se usa `10·log10` porque γ⁰ de GCOV ya está en **potencia**.
- Si no hay dos tomas compatibles o no pasan la calidad, **no se publica mapa**. Nunca se rellenan huecos ni se inventan datos.
- NISAR (banda L) y Sentinel-1 (banda C) nunca se mezclan ni comparten umbrales.
- Las tomas NISAR VALIDATED existen desde el 21-oct-2026; para fechas anteriores la app lo indica.

### Estados de procedencia (`utils/procedencia.py`)

| Estado | Significado |
|---|---|
| DEMO | Dato sintético de interfaz. |
| PROCEDENCIA NO DECLARADA | Sin ficha que lo respalde. |
| REAL · SIN VALIDAR | Ficha completa y SHA-256 del propio archivo; sin validación independiente. |
| VALIDADO | Además, responsable y método de validación declarados. |

Si alguien modifica un GeoTIFF, su huella deja de coincidir y la capa pierde la etiqueta.

## Estructura del repositorio

```text
app.py                  Mission Control (Streamlit)
pages/                  Análisis SAR, Buscador SAR y Laboratorio IA
components/             Interfaz: mapa, paneles, ECO, modo jurado, flujo NISAR
utils/                  Ciencia y datos: NISAR (catálogo, Harmony, GCOV), ΔdB, procedencia, QGIS, contexto
  v9_datos/             Cálculo ΔdB sobre COG con control de calidad
data/                   Productos ligeros, contexto cartográfico y salidas (los datos pesados viven en Replit, fuera de Git)
static/, assets/        ECO, estilos y recursos
scripts/                Herramientas de línea de comandos (NISAR, QA, QGIS, verificación)
tests/                  Pruebas (pytest; Playwright para navegador)
docs/                   Documentación técnica y científica
  ia_lab/               Resultados, datos y decisiones del Laboratorio IA
ia_lab/                 Investigación del equipo ML (notebooks, entrenamiento, modelos). Ver ia_lab/README.md
start.sh                Arranque: entorno .venv, dependencias y Streamlit en el puerto 5000
actualizar.sh           Actualiza desde GitHub sin perder cambios locales
verificar.sh            Verificación integral con los datos reales del Repl (solo lectura)
.replitignore           Qué NO va en la publicación (ver docs/despliegue_replit.md)
```

## Ejecutar

**En Replit** (entorno del equipo): pulsar **Run**. `start.sh` crea `.venv` si falta, instala dependencias solo si cambió `requirements.txt` y arranca Streamlit en el puerto 5000.

| Quiero… | Comando (Shell de Replit) |
|---|---|
| Traer lo último de `main` | `bash actualizar.sh main` |
| Deshacer la última actualización | `bash actualizar.sh --volver` |
| Revisar el entorno sin abrir la app | `bash start.sh --verificar` |
| Verificar con los datos reales | `bash verificar.sh` |
| Ejecutar las pruebas | `bash start.sh --pruebas` |

**En local** (Python 3.12):

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Para el análisis NISAR automático hace falta un token de NASA Earthdata en la variable de entorno `EARTHDATA_TOKEN` (en Replit: **Secrets**, también en los del despliegue). Nunca se guarda en el repositorio.

## Publicación

La app se publica en Replit (Autoscale) con el mismo arranque que en desarrollo: build `bash start.sh --verificar`, run `bash start.sh`, puerto 5000 → 80.

`.replitignore` deja fuera `.git`, cachés de Harmony históricos y la carpeta `ia_lab/`, pero **no puede excluir `.venv/` ni `.pythonlibs/`**: el Python de `.venv` es un enlace a `.pythonlibs`. Causa y comprobaciones en [`docs/despliegue_replit.md`](docs/despliegue_replit.md).

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest -q -m "not navegador and not red"   # unidad e integración
ruff check --select F,E9,B .
```

GitHub Actions (`.github/workflows/pruebas.yml`) ejecuta unidad, integración, ruff y Playwright (Chromium y Firefox) en cada push. Las pruebas usan datos sintéticos o respuestas guardadas: **no validan resultados ambientales**.

## Fuentes de datos

| Fuente | Uso |
|---|---|
| NASA-ISRO **NISAR** L2 GCOV (ASF DAAC, NASA Harmony, NASA CMR) | Fuente principal: intensidad γ⁰ en banda L. |
| ESA **Sentinel-1** (Copernicus) vía **ASF HyP3** | Respaldo y primer caso real (Chigorodó, 24-sep → 6-oct-2026). |
| **IDEAM** | Alertas hidrológicas vigentes; series del Laboratorio IA. |
| **DANE** MGN 2025 | Límite nacional y municipios. |
| **NASA EONET** | Eventos naturales catalogados. |
| JRC Global Surface Water | Contexto de agua histórica (1984–2024). |
| OpenStreetMap, CARTO, OpenTopoMap, EOX | Mapas base. |

## Limitaciones

- ΔdB es un **indicador de cambio**, no un mapa de inundación validado. No hay validación de campo.
- La cobertura depende de que existan dos tomas NISAR compatibles sobre la zona; parte del área puede quedar sin datos válidos.
- Los resultados calculados en la app publicada se guardan en disco temporal del contenedor.
- El Laboratorio IA usa etiquetas derivadas automáticamente de NISAR, no verdad de campo; sus métricas son históricas.
- Solo Colombia; solo versión para PC.

## Equipo

Juan José Valencia Builes · Andrés Felipe Merchán Caina · Valeria Riobo Gutiérrez · María Paula Valderrama Montero · Samuel Jiménez Arroyave

## Uso de inteligencia artificial

Se usaron asistentes de IA (Claude y ChatGPT) para escribir y revisar código, pruebas y documentación. Las decisiones, la ejecución con datos reales en Replit y QGIS, y la revisión final son del equipo. El historial completo está en Git.

---

NASA no respalda esta aplicación. Los datos de NISAR, Sentinel-1, IDEAM, DANE y EONET pertenecen a sus respectivas agencias.
