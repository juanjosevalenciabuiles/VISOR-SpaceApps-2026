# V.I.S.O.R. · v1.1

**Visualización Inteligente de Superficies y Observación por Radar** — NASA Space Apps Challenge 2026, reto *Dancing with the SARs*.

Visor geoespacial que muestra productos de radar SAR **ya procesados** sobre un mapa interactivo de Antioquia, para tres fenómenos: inundaciones, deslizamientos y deforestación.

> V.I.S.O.R. muestra **indicios**, no detecciones confirmadas. Los GeoTIFF que vienen en `data/` son **sintéticos de demostración**: no provienen de ningún satélite. El color describe la señal medida, no un nivel de riesgo.

## Guía rápida

**En Replit, el uso diario son dos pasos:**

1. Panel **Git** → **Pull** (trae lo nuevo de GitHub).
2. Botón **Run**.

No hay que instalar nada a mano. Al pulsar Run, `start.sh` crea el entorno `.venv` si no existe, instala las dependencias solo si cambió `requirements.txt` e inicia la app. La primera vez tarda unos minutos; después arranca en segundos.

**Otras situaciones** (en la pestaña Shell):

| Quiero… | Comando |
| --- | --- |
| Probar una rama, por ejemplo la v1.1 | `bash actualizar.sh feature/visor-v1.1` |
| Volver a la versión estable | `bash actualizar.sh main` |
| Deshacer la última actualización | `bash actualizar.sh --volver` |
| Actualizar aunque tenga cambios sin guardar | `bash actualizar.sh --guardar` (los aparta; se recuperan con `git stash pop`) |
| Revisar el entorno sin abrir la app | `bash start.sh --verificar` |
| Ejecutar las pruebas | `bash start.sh --pruebas` |
| Empezar de cero si algo quedó mal | borrar la carpeta `.venv` y pulsar Run |

Después de cualquier `actualizar.sh`, pulsar **Run**.

Mientras `main` siga en la v1.0, al pasar a `main` este guion deja de estar disponible (allí aún no existe). Para regresar a la rama de pruebas: `git checkout feature/visor-v1.1` y Run.

**Nunca hace falta** `pip install`. Si aparece el error `externally-managed-environment` es porque se intentó instalar en el Python del sistema: usar Run o `bash start.sh --verificar`.

## Cómo funciona

Requiere **Python 3.12** y bash. En Windows sin bash: crear un entorno virtual, `pip install -r requirements.txt` dentro de él y `python -m streamlit run app.py --server.port 5000`.

### Arranque (`start.sh`)

El botón Run, el despliegue y la ejecución local usan el mismo guion, en este orden:

1. Elige el Python del sistema y comprueba `pyexpat`.
2. Crea o reutiliza `.venv`. Si quedó roto (por ejemplo, al reconstruirse el entorno Nix), lo rehace.
3. Instala dependencias **dentro de `.venv`** solo cuando `requirements.txt` cambió. Nunca instala en el Python de Nix ni usa `--break-system-packages`.
4. Busca una Expat con la que `pyexpat` y `rasterio` importan de verdad (`REPLIT_LD_LIBRARY_PATH`, luego `/nix/store`). No depende de una ruta fija; la ruta antigua queda solo como último recurso.
5. Inicia Streamlit en el puerto **5000** (expuesto como 80 en `.replit`).

Otros detalles:

- **Un solo Streamlit:** si el puerto lo ocupa una instancia anterior de esta misma app, la cierra. Si lo ocupa otro programa, no lo toca y avisa.
- **Arrancar nunca actualiza el código.** Las actualizaciones son siempre una acción explícita (Pull o `actualizar.sh`).
- **Seguridad:** CORS y XSRF de Streamlit están activados. `start.sh` autoriza únicamente el dominio propio del Repl. Si la vista previa se queda en "Connecting…", no desactivar las protecciones: revisar en la consola del navegador qué conexión falla y reportarlo.
- **Secreto:** `CARTO_API_KEY` en **Secrets**. Hay que volver a pulsar Run después de crearlo o cambiarlo. El despliegue público necesita el mismo secreto en su propia configuración.
- **Despliegue:** `.replit` prepara el entorno en la fase de construcción (`bash start.sh --verificar`) y arranca con `bash start.sh`.

### Actualizaciones (`actualizar.sh`)

Replit no ofrece una sincronización automática al recibir commits: hay que pedir los cambios con **Pull** en el panel Git. `actualizar.sh` hace lo mismo desde la Shell y además permite cambiar de rama y regresar:

- Si hay cambios locales en archivos del proyecto, **se detiene** y explica las opciones. Nunca los descarta.
- Solo avanza la rama (fast-forward). No fusiona, no reescribe historia y no sube nada a GitHub.
- Guarda dónde estabas para poder regresar con `--volver`.
- Al terminar prepara las dependencias con `bash start.sh --verificar`.
- Los Secrets viven en el Repl, no en Git: ninguna actualización los cambia.

### Pruebas

- GitHub ejecuta `pytest` en cada Pull Request y en cada push a `main` (`.github/workflows/pruebas.yml`).
- Para que sea obligatorio antes de integrar: en GitHub, **Settings → Branches → Add rule** para `main`, activar *Require status checks to pass* y elegir `pytest`. Esto lo configura el dueño del repositorio.
- Las pruebas no se ejecutan al iniciar la app, para no retrasarla.

### Estado de verificación (11-nov-2026)

| Qué | Estado |
| --- | --- |
| v1.0 en el Replit del equipo (app, CARTO, Rasterio 1.5.2) | Comprobado por el equipo |
| v1.1: 82 pruebas con Python 3.12 y las versiones de `requirements.txt` | Comprobado fuera de Replit y en GitHub Actions |
| Instalación desde cero, segundo arranque sin reinstalar, cambio de `requirements.txt`, reparación de `.venv` | Comprobado fuera de Replit |
| Tres fenómenos y cinco mapas base en navegador | Comprobado fuera de Replit (sin ver las teselas) |
| `actualizar.sh` contra el repositorio real de GitHub | Comprobado fuera de Replit |
| Selección de Expat en Nix | Comprobado solo con un almacén Nix simulado |
| Run y Preview dentro del Replit real, con CORS/XSRF activos | **Pendiente** |
| Carga real de teselas (CARTO con la clave del equipo, OpenTopoMap, Sentinel-2) | **Pendiente** en la v1.1 |
| Despliegue público | **Pendiente** |

## Interfaz Mission Control Earth Explorer

Un **único mapa a pantalla completa** con superficies de vidrio flotantes. No hay páginas separadas: todo ocurre sobre el mismo mapa.

| Superficie | Qué hace |
| --- | --- |
| Barra superior | Fenómeno activo y etiqueta de procedencia (DEMO…), botones Explorador, Información, Ir a…, Herramientas SAR y Ayuda |
| Explorador (izquierda) | Fenómeno, mapa base, capa SAR y opacidad, hidrografía, vías, cobertura, área de referencia |
| Información (derecha) | Descripción, producto, procedencia, cómo interpretar, leyenda y créditos |
| Herramientas SAR | Panel que se abre, minimiza y cierra, con cuatro pasos: Área, Escenas, Análisis, Resultados. **Aún no ejecuta nada**: se conectará a los motores reales en una fase posterior |
| Línea temporal | Conceptual y deshabilitada hasta que existan dos productos fechados y comparables |

- **El mapa no se reinicia.** Cambiar de fenómeno, de fondo, abrir o cerrar paneles conserva centro, zoom y capas. "Ir a…" mueve el mapa existente.
- **Modo inmersivo.** Cerrar el explorador y la información deja solo el mapa, la barra superior y la línea temporal.
- **Paneles cerrados no pierden nada.** Se ocultan con CSS pero siguen dibujados, así que sus controles conservan su valor.
- **Tema adaptativo por fenómeno.** Inundaciones `#4FDCF4`, deslizamientos `#F4A463`, deforestación `#64DFA7`. Tiñe paneles, bordes y foco; no cambia los colores de los datos.
- **Móvil (≤ 720 px).** Los paneles pasan a hojas inferiores que dejan visible la atribución del mapa; la barra superior muestra solo iconos.

Archivos: `components/interfaz.py` (superficies y estado), `assets/mission_control.css` (vidrio y disposición), `components/mapa.py` (pantalla completa y "Ir a…"). Las páginas de análisis y búsqueda siguen usando `assets/style.css`.

## Sistema cartográfico multicapa

El mapa tiene capas independientes, de abajo hacia arriba: **mapa base → capa SAR → hidrografía y carreteras → cobertura y área de referencia**. Cambiar el fondo, el fenómeno o la opacidad no reinicia el mapa: se conservan la ubicación, el zoom y la capa SAR.

### Mapas base (`utils/mapas_base.py`)

| Fondo | Proveedor | Condiciones de uso |
| --- | --- | --- |
| Oscuro · Dark Matter (predeterminado) | CARTO | Requiere `CARTO_API_KEY`. Datos © OpenStreetMap (ODbL) |
| Carreteras · Voyager | CARTO | Igual que el anterior |
| Claro · Positron | CARTO | Igual que el anterior |
| Relieve · OpenTopoMap | OpenTopoMap | Teselas CC-BY-SA; datos OpenStreetMap y SRTM. Servidor de voluntarios: uso moderado, sin descargas masivas |
| Satélite 2016 · Sentinel-2 | EOX IT Services (Copernicus Sentinel-2) | Mosaico *Sentinel-2 cloudless* 2016, CC BY 4.0 con atribución |

- La atribución de cada proveedor aparece dentro del mapa y en **Créditos y fuentes** de la barra lateral.
- La imagen satelital es de **2016**: sirve de contexto, no muestra el estado actual del terreno.
- No se usa Esri World Imagery porque sus condiciones piden cuenta y clave de ArcGIS.
- La clave de CARTO solo se añade a las URL de CARTO, codificada; nunca se envía a otros proveedores ni se imprime. Como toda clave de mapas web, es visible en el navegador: conviene restringirla al dominio de la app en el panel de CARTO.

### Capas de contexto (`utils/capas_contexto.py`, `data/contexto/`)

| Capa | Fuente | Alcance real |
| --- | --- | --- |
| Hidrografía | Natural Earth 1:10m v5.1.2, dominio público | Solo ríos Cauca, Magdalena y Atrato. Sin quebradas, drenaje ni cuencas |
| Carreteras | Natural Earth 1:10m v5.1.2, dominio público | Solo vías principales. Sin vías secundarias |

Son datos reales pero de escala general. `python scripts/preparar_contexto.py` los regenera. Para más detalle hay que conseguir una fuente oficial (IGAC, IDEAM) o un extracto de OpenStreetMap, guardar su GeoJSON en `data/contexto/` y declararlo en `CAPAS_CONTEXTO` con fuente y licencia. Si falta el archivo de una capa, su interruptor queda desactivado: la app no inventa geometrías.

**Precipitación:** no está implementada. No es hidrografía: es un dato ráster con fecha. Queda pendiente hasta elegir una fuente verificable (por ejemplo NASA GPM IMERG) y definir fechas.

## Datos SAR

### Integrar productos reales (HyP3)

1. Procesar fuera de la app (ASF HyP3) y exportar un GeoTIFF **ligero** de una banda.
2. Guardarlo en `data/` como `inundacion.tif`, `deslizamiento.tif` o `deforestacion.tif`. El aviso de demostración depende de la etiqueta `VISOR_DEMO=1` del propio archivo y desaparece solo.
3. Crear al lado un `.json` con los metadatos **verificables**. Fuente y fecha solo se muestran si vienen aquí o en las etiquetas del GeoTIFF; si no, el panel dice "No disponible".

   ```json
   {
     "fuente": "Sentinel-1 IW, ASF HyP3 RTC",
     "fecha": "2026-05-01 / 2026-05-13",
     "producto": "Cambio de retrodispersión VV",
     "unidades": "dB"
   }
   ```

4. Revisar el **perfil del fenómeno** en `utils/config.py`. Los perfiles actuales están pensados para los sintéticos (índice 0–1):

   | Campo | Para qué sirve |
   | --- | --- |
   | `tipo_valores` | `"continuo"` (remuestreo bilinear) o `"categorico"` (nearest, no inventa clases) |
   | `vmin`, `vmax` | Rango fijo de la escala. `None` usa `percentiles` de los datos |
   | `invertir` | `True` si el extremo relevante son los valores **bajos** (p. ej. caída de dB) |
   | `transparencia` | `"gradual"` (de `alfa_min` a opaco) o `"nodata"` (todo dato válido opaco) |
   | `clases` | Solo categórico: `(valor, etiqueta, color)`; `color=None` deja la clase transparente |
   | `unidades`, `leyenda_min`, `leyenda_max` | Textos de la leyenda |

### Reglas del cargador (`utils/geotiff.py`)

- Acepta cualquier CRS y reproyecta a EPSG:4326.
- Solo NoData y NaN son transparentes; un valor bajo o un cero son datos válidos y se ven.
- Reduce rásters de más de 1024 px y lee una sola vez, ya a resolución de pantalla.
- Relee solo si cambia el `.tif` o su `.json`.
- Avisa si la capa queda fuera de Antioquia, si es constante o si su `.json` está dañado.
- Da un error legible si el archivo falta, está dañado, vacío, sin CRS o con extensión inválida.

No subir productos crudos de varios GB: la app no los procesa.

## Estructura

```
app.py                  Punto de entrada: mapa único y superficies flotantes
start.sh                Arranque único: entorno .venv, Expat y Streamlit
actualizar.sh           Actualización segura desde GitHub
components/
  interfaz.py           Barra superior, paneles flotantes, Herramientas SAR, línea temporal
  barra_lateral.py      Fenómeno, configuración cartográfica, leyendas, créditos
  mapa.py               Mapa Folium por grupos de capas independientes
  leyenda.py            Leyenda SAR (continua o por clases) y de contexto
  panel_info.py         Descripción, producto, metadatos, advertencias
  encabezado.py · estilos.py
utils/
  config.py             Perfil de cada fenómeno, clave de CARTO, rutas
  mapas_base.py         Catálogo de fondos: proveedor, licencia, atribución
  capas_contexto.py     Hidrografía y vías: lectura, caché, fuentes
  geotiff.py            Lectura de GeoTIFF: CRS, NoData, caché, colores
  geo.py                Utilidades GeoPandas
assets/style.css        Tema clásico (páginas experimentales)
assets/mission_control.css  Interfaz Mission Control: vidrio adaptativo y disposición
data/                   GeoTIFF ligeros · data/contexto/ GeoJSON de contexto
scripts/                generar_datos_demo.py · preparar_contexto.py
tests/                  test_geotiff.py · test_cartografia.py · test_replit.py
.github/                Plantilla de Pull Request y pruebas automáticas
```

## Trabajo colaborativo (5 integrantes)

**GitHub es la fuente de verdad.** Replit es un lugar donde editar y ejecutar.

1. `main` solo recibe código por Pull Request, después de probarlo en Replit.
2. Una rama por tarea, con prefijo del módulo: `ui/…`, `datos/…`, `mapas/…`, `docs/…`.
3. Ciclo de trabajo:

   ```bash
   git checkout main && git pull
   git checkout -b mapas/mi-cambio
   # editar, luego: bash start.sh --pruebas  y abrir la app
   git add -A && git commit -m "mapas: describe el cambio"
   git push -u origin mapas/mi-cambio      # y abrir el Pull Request en GitHub
   ```

4. Otra persona revisa. GitHub ejecuta `pytest` en cada Pull Request (`.github/workflows/pruebas.yml`).

**Para evitar conflictos:**

- Un módulo, una persona a la vez: interfaz (`components/`, `assets/`), datos SAR (`data/*.tif`, `scripts/`), cargador (`utils/geotiff.py`, `tests/`), cartografía (`utils/mapas_base.py`, `utils/capas_contexto.py`, `data/contexto/`), contenido científico (`utils/config.py`, `.json`), integración (`.replit`, `start.sh`, `requirements.txt`, README).
- En `utils/config.py` cada quien edita solo el bloque de su fenómeno.
- Los `.tif` son binarios y no se fusionan: un responsable por archivo.
- No cambiar versiones de `requirements.txt` sin volver a correr las pruebas. Al cambiarlo, cada integrante recibe las nuevas dependencias solo con pulsar Run.
- La edición simultánea en un mismo Repl depende del plan de Replit; este flujo no la necesita.

Tareas, estados y roles se gestionan **solo en Notion**.

## Limitaciones actuales

- Solo hay datos SAR sintéticos; no existe ningún resultado científico todavía.
- Los perfiles de visualización no están calibrados con productos reales.
- Hidrografía y vías son de escala general; sin quebradas, cuencas ni vías secundarias.
- Sin capa de precipitación.
- El "Área de referencia" es un rectángulo aproximado, no el límite oficial de Antioquia.
- Una capa SAR por fenómeno; sin comparación de fechas ni consulta de valores por clic.
