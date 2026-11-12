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
| v1.1: 121 pruebas (82 anteriores + 39 del motor SAR) con Python 3.12 y las versiones de `requirements.txt` | Comprobado fuera de Replit y en GitHub Actions |
| Instalación desde cero, segundo arranque sin reinstalar, cambio de `requirements.txt`, reparación de `.venv` | Comprobado fuera de Replit |
| Tres fenómenos y cinco mapas base en navegador | Comprobado fuera de Replit (sin ver las teselas) |
| `actualizar.sh` contra el repositorio real de GitHub | Comprobado fuera de Replit |
| Selección de Expat en Nix | Comprobado solo con un almacén Nix simulado |
| Run y Preview dentro del Replit real, con CORS/XSRF activos | **Pendiente** |
| Carga real de teselas (CARTO con la clave del equipo, OpenTopoMap, Sentinel-2) | **Pendiente** en la v1.1 |
| Despliegue público | **Pendiente** |

## Verificación automática

```bash
bash verificar.sh
```

Una sola ejecución comprueba entorno, Git (cambios locales, p. ej. del agente de Replit), pytest, ruff, navegador (si Playwright está instalado), la app con los datos reales y cada GeoTIFF de `data/analisis/` (clases, NoData, superficies, procedencia, SHA-256, paquete QGIS) frente a la referencia verificada de Chigorodó, sin modificar `data/`. Termina con un veredicto (**APTO**, **APTO CON ADVERTENCIAS** o **NO APTO**) y un informe en `informes/`. GitHub Actions ejecuta lo mismo, más las pruebas de navegador, en cada push y pull request. Detalle: `docs/pruebas.md`.

## Interfaz Mission Control Earth Explorer

Un **único mapa a pantalla completa** con superficies de vidrio flotantes. No hay páginas separadas: todo ocurre sobre el mismo mapa.

| Superficie | Qué hace |
| --- | --- |
| Barra superior | Dos grupos rotulados: **Fenómeno** (con su insignia, p. ej. DEMO) y **Resultado SAR** (cada resultado activo con la suya, p. ej. REAL SIN VALIDAR); botones Explorador, Información, Ir a…, Herramientas SAR y Ayuda |
| Explorador (izquierda) | Fenómeno, mapa base, capa SAR y opacidad, hidrografía, vías, cobertura, área de referencia y **Resultados SAR** de `data/analisis/` |
| Información (derecha) | Ficha científica del resultado SAR activo (si hay) y, debajo, la del fenómeno: descripción, producto, procedencia, cómo interpretar, leyendas y créditos |
| Ir a… | Coordenadas validadas (por defecto, el centro del AOI de Chigorodó, zoom 11), botón Chigorodó y Área inicial (vista de Antioquia) |
| Herramientas SAR | Panel que se abre, minimiza y cierra, con cuatro pasos conectados: Área (AOI y fechas), Escenas (catálogo ASF y par recomendado sin validar), Análisis (RTC de `data/sar/` con el motor) y Resultados. Ver «Flujo de Herramientas SAR» |
| Línea temporal | De solo lectura. Muestra T₁ y T₂ cuando hay un único resultado activo con ficha de procedencia válida; si no, es conceptual |

- **El mapa no se reinicia.** Cambiar de fenómeno, de fondo, abrir o cerrar paneles conserva centro, zoom y capas. "Ir a…" mueve el mapa existente.
- **Modo inmersivo.** Cerrar el explorador y la información deja solo el mapa, la barra superior y la línea temporal.
- **Paneles cerrados no pierden nada.** Se ocultan con CSS pero siguen dibujados, así que sus controles conservan su valor.
- **Tema adaptativo por fenómeno.** Inundaciones `#4FDCF4`, deslizamientos `#F4A463`, deforestación `#64DFA7`. Tiñe paneles, bordes y foco; no cambia los colores de los datos.
- **Móvil (≤ 720 px).** Los paneles pasan a hojas inferiores que dejan visible la atribución del mapa; la barra superior muestra solo iconos.

Archivos: `components/interfaz.py` (superficies y estado), `assets/mission_control.css` (vidrio y disposición), `components/mapa.py` (pantalla completa y "Ir a…"). Las páginas de análisis y búsqueda siguen usando `assets/style.css`.

## Procedencia y resultados SAR

### Cuatro estados de procedencia (`utils/procedencia.py`)

| Estado | Cuándo |
| --- | --- |
| DEMO · DATOS SINTÉTICOS | El GeoTIFF lleva `VISOR_DEMO=1`. Una ficha no puede quitar esa marca |
| PROCEDENCIA NO DECLARADA | Por defecto: no hay ficha, está incompleta o no corresponde al archivo |
| REAL SIN VALIDAR | Ficha `<nombre>.json` con `procedencia.estado = "real_sin_validar"`, todos los campos de trazabilidad (sensor, fechas, polarizaciones, método, entradas, generado_por, archivo) y el **SHA-256 del propio GeoTIFF** |
| VALIDADO | Lo anterior con `estado = "validado"` y `procedencia.validacion` completa (responsable, fecha, método, referencia). Si falta la validación, se muestra REAL SIN VALIDAR |

REAL SIN VALIDAR y VALIDADO **nunca se asignan por defecto**. Si el GeoTIFF cambia después de escribir su ficha, la huella deja de coincidir y la capa vuelve a PROCEDENCIA NO DECLARADA. No se escriben fichas a mano: las genera el código que produce el resultado.

### Resultados de `data/analisis/` como capas opcionales (`utils/resultados.py`)

Cada GeoTIFF de `data/analisis/` aparece en el explorador, en **Resultados SAR**, con su insignia de procedencia, un interruptor, su opacidad y «Centrar en el mapa». Se superpone a la capa del fenómeno sin reemplazarla y sin reiniciar el mapa; cambiar de fenómeno no lo apaga. El perfil se reconoce por lo que declara el archivo (ficha o etiquetas internas), no por su nombre:

| Perfil | Clases |
| --- | --- |
| Coincidencia VV/VH | 1 solo VV (cian `#00F0FF`) · 2 solo VH (naranja `#FF9F0A`) · 3 VV y VH (violeta `#7D7AFF`) · 0 y 255 transparentes |
| Máscara del motor (una polarización) | Clases de `utils/analisis_sar.CLASES_MASCARA` |
| Diferencia del motor en dB (`…_dif_db.tif`) | Continua, sin umbral: rampa divergente fija de ±10 dB (azul disminución, naranja-rojo aumento), opacidad según \|Δ\|, NoData transparente |

La clase 0 de la coincidencia **no significa «sin cambios»**: incluye aumentos significativos y señal baja en ambas fechas; solo indica que no hubo disminución significativa en ninguna polarización. La visualización solo cambia colores: los valores del GeoTIFF no se tocan, y las estadísticas (píxeles, % de válidos, hectáreas) se calculan a resolución completa desde el archivo.

La ficha científica del panel de información dice de dónde sale cada dato (ficha de procedencia o etiquetas del GeoTIFF). Lo que no está declarado aparece como «No declarado en el archivo». Por eso el GeoTIFF exploratorio `coincidencia_VV_VH_Chigorodo.tif`, que no tiene ficha, se muestra como **PROCEDENCIA NO DECLARADA** y sin sensor, fechas ni método.

### Flujo de Herramientas SAR (`components/herramientas_sar.py`, `utils/flujo_sar.py`)

1. **Área:** AOI en grados (por defecto Chigorodó) y período; se dibuja en el mapa.
2. **Escenas:** consulta de solo lectura a ASF; par recomendado **sin validar** y alternativas; huellas en el mapa.
3. **Análisis:** busca en `data/sar/` los RTC de HyP3 que derivan de cada escena del par. Asociación **exacta** (mismo satélite y hora de inicio) o **mismo día** (se marca para verificar); nunca entre satélites. Umbral por polarización y filtro de speckle; corre el motor y, con VV y VH, la combinación.
4. **Resultados:** lo generado aparece en el explorador. **Nunca se sobrescribe** un archivo de `data/analisis/`: si el nombre existe se usa `_r2`, `_r3`… Un registro `flujo_…_registro.json` enlaza escenas GRD, RTC, AOI, parámetros y salidas.

Si faltan RTC, el panel lo dice: convertir GRD → RTC requiere HyP3 (Fase D, plan en `docs/fase_d_earthdata_hyp3.md`, sin implementar).

### QGIS (opcional) y auditoría

- **Exportar para QGIS** (ficha del resultado o `scripts/exportar_qgis.py`): ZIP con el GeoTIFF original byte a byte, estilo `.qml`, ficha, leyenda, AOI declarada y manifiesto con SHA-256.
- **Auditoría** (`scripts/auditar_geotiff.py`): cuadrícula, clases, SHA-256 frente a la ficha, comparación con otra versión (matriz de transiciones) y reconstrucción desde VV/VH. Solo lectura.
- Guía completa: `docs/qgis.md`.

### Combinación VV/VH reproducible (`utils/combinacion_sar.py`)

Combina las máscaras VV y VH del motor (mismo par de fechas, misma cuadrícula) con la misma regla del script exploratorio y escribe el GeoTIFF y su ficha completa. Se ejecuta donde estén las máscaras del motor (no hacen falta las escenas RTC):

```bash
.venv/bin/python scripts/combinar_vv_vh.py \
    --vv data/analisis/cambio_VV_20260924_20261006_mascara.tif \
    --vh data/analisis/cambio_VH_20260924_20261006_mascara.tif \
    --zona "Chigorodó, Antioquia" \
    --comparar data/analisis/coincidencia_VV_VH_Chigorodo.tif
```

Produce `coincidencia_VV_VH_20260924_20261006.tif` y `.json` (no sobrescribe el exploratorio) e indica si ambos son **EQUIVALENTES** píxel a píxel. Para que la ficha quede como REAL SIN VALIDAR, junto a cada máscara debe estar su informe del motor (`…_analisis.json`), de donde se lee el satélite. Para solo resumir un GeoTIFF de clases existente: `--describir data/analisis/coincidencia_VV_VH_Chigorodo.tif`.

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

## Análisis temporal SAR (datos reales)

Motor independiente (`utils/analisis_sar.py`) que compara dos productos **RTC de Sentinel-1 procesados con ASF HyP3** y calcula el cambio de retrodispersión entre fechas. No descarga datos, no envía trabajos a HyP3 y no usa credenciales: trabaja con GeoTIFF que ya están en disco.

> El resultado muestra **cambios de la señal de radar**. Una disminución de retrodispersión no es una inundación confirmada: requiere validación independiente.

### Cómo ejecutarlo con los GeoTIFF reales

1. Copiar a `data/sar/` los GeoTIFF ya descomprimidos de las dos fechas. Basta con los archivos `…_VV.tif` (y `…_VH.tif` si se quiere analizar también VH). Esa carpeta está excluida de Git: **no subir estos archivos a GitHub**.
2. **Desde la app:** Run, y abrir la página **Analisis SAR** añadiendo `/Analisis_SAR` a la dirección de la app (la interfaz principal no muestra la barra lateral). Elegir imagen anterior y posterior, la zona y los parámetros, y pulsar *Ejecutar análisis*.
3. **O desde la Shell:**

   ```bash
   .venv/bin/python scripts/analizar_sar.py \
       data/sar/S1C_IW_20260924T…_VV.tif data/sar/S1C_IW_20261006T…_VV.tif \
       --aoi -76.80 7.55 -76.55 7.80
   ```

   `--aoi` es oeste, sur, este, norte en grados. `--help` muestra el resto de opciones.

Los resultados quedan en `data/analisis/` (también fuera de Git):

| Archivo | Contenido |
| --- | --- |
| `cambio_VV_<antes>_<después>_dif_db.tif` | Diferencia en dB, posterior − anterior. Negativo = la señal disminuyó |
| `…_mascara.tif` | 0 sin cambio · 1 disminución significativa · 2 aumento significativo · 3 señal baja en ambas fechas · 255 sin dato |
| `…_analisis.json` | Procedencia: archivos, fechas, satélite, polarización, cuadrícula, alineación, parámetros, estadísticas, avisos y limitaciones |
| `…_dif_db.json`, `…_mascara.json` | Metadatos que muestra el visor (fuente, fecha, producto, unidades) |

Para ver un resultado en el mapa principal como capa de un fenómeno, copiar el `.tif` y su `.json` a `data/` con el nombre del fenómeno (por ejemplo `inundacion.tif`) y ajustar su perfil en `utils/config.py`.

### Qué hace el motor

1. **Valida** cada escena: CRS, transformación, tamaño, NoData y polarización. Lee fecha, satélite, radiometría y escala del nombre de HyP3 (`S1C_IW_20260924T…_RTC30_G_gpuned_XXXX_VV.tif`); si el nombre es otro, se indican a mano.
2. **Valida el par:** misma polarización, escala y radiometría; fechas distintas y en orden.
3. **Alinea:** usa la cuadrícula de la imagen anterior, recortada a la zona común y al AOI. Si la posterior ya está en esa cuadrícula se lee tal cual; si no (otro CRS, otra resolución o desfase de fracción de píxel) se remuestrea, y queda anotado. Nunca se restan píxeles que no coinciden en el terreno.
4. **Filtra el speckle** con una media móvil en potencia (por defecto 5×5 px).
5. **Convierte a dB:** 10·log10(potencia). Nulos, no finitos y no positivos quedan sin dato.
6. **Resta:** posterior − anterior, solo donde ambas fechas tienen dato.
7. **Clasifica** con umbrales configurables (por defecto ±3 dB).

Una escena completa a 30 m supera el límite de 16 millones de píxeles: hay que indicar un AOI.

### Limitaciones

- Una disminución puede deberse a agua en superficie, pero también a cambios de humedad del suelo, cosechas, quemas o viento.
- **Vegetación:** bajo dosel denso el agua puede no oscurecer la señal en banda C; la vegetación inundada puede incluso aumentarla.
- **Humedad:** la lluvia reciente cambia la retrodispersión sin que haya inundación.
- **Relieve:** en sombra y layover el radar no observa bien el terreno.
- **Speckle:** produce falsos cambios píxel a píxel; el filtro lo reduce a costa de detalle.
- **Agua permanente:** ríos y ciénagas son oscuros en ambas fechas y no aparecen como cambio.
- Solo se comparan dos fechas y los umbrales no están calibrados para la zona.
- El motor se probó con rásteres sintéticos; **aún no se ha ejecutado con las escenas reales**.

## Estructura

```
app.py                  Punto de entrada: mapa único y superficies flotantes
start.sh                Arranque único: entorno .venv, Expat y Streamlit
actualizar.sh           Actualización segura desde GitHub
pages/1_Analisis_SAR.py  Página para ejecutar y ver el análisis SAR
pages/2_Buscador_SAR.py  Página del buscador de escenas Sentinel-1 en ASF
components/
  interfaz.py           Barra superior, paneles flotantes, Herramientas SAR, línea temporal
  herramientas_sar.py   Pasos 01–04 de Herramientas SAR
  resultados.py         Ficha científica y leyenda de los resultados SAR activos
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
  analisis_sar.py       Motor de análisis temporal SAR (RTC de HyP3)
  buscador_sar.py       Búsqueda de escenas Sentinel-1 en ASF y emparejado
  combinacion_sar.py    Combinación VV/VH de máscaras del motor + ficha de procedencia
  procedencia.py        Estados DEMO / NO DECLARADA / REAL SIN VALIDAR / VALIDADO
  flujo_sar.py          Catálogo ASF → RTC locales → motor → resultados
  qgis.py · auditoria.py  Exportación para QGIS y auditoría de GeoTIFF
  resultados.py         Resultados de data/analisis/ como capas opcionales
  geo.py                Utilidades GeoPandas
assets/style.css        Tema clásico (páginas experimentales)
assets/mission_control.css  Interfaz Mission Control: vidrio adaptativo y disposición
data/                   GeoTIFF ligeros · data/contexto/ GeoJSON de contexto
scripts/                generar_datos_demo.py · preparar_contexto.py · analizar_sar.py · combinar_vv_vh.py ·
                        auditar_geotiff.py · exportar_qgis.py
docs/                   qgis.md · fase_d_earthdata_hyp3.md · pruebas.md
tests/e2e/              Pruebas de navegador (Playwright) de Mission Control
verificar.sh            Verificación integral con informe y veredicto
tests/                  test_geotiff.py · test_cartografia.py · test_replit.py · test_analisis_sar.py ·
                        test_interfaz.py · test_procedencia.py · test_combinacion_sar.py · test_resultados.py
.github/                Plantilla de Pull Request y pruebas automáticas
```

## Buscador de escenas Sentinel-1

Encuentra en el catálogo de **Alaska Satellite Facility (ASF)** las escenas Sentinel-1 que cubren una región y propone pares antes/después comparables, sin tener que buscar a mano en ASF Vertex.

> Es **solo consulta**: no descarga imágenes, no envía trabajos a HyP3, no consume créditos y no usa credenciales. Un par **recomendado** es el mejor candidato por órbita, polarización, cobertura y fechas; **no es un par validado científicamente**.

### Cómo usarlo

1. Run, y abrir la página **Buscador SAR** añadiendo `/Buscador_SAR` a la dirección de la app (la interfaz principal no muestra la barra lateral).
2. Indicar la región: un recuadro (oeste, sur, este, norte en grados) o un punto con radio. Los valores iniciales son los de Chigorodó.
3. Elegir el período y, si se conoce, una fecha de interés (por ejemplo el día de una lluvia fuerte).
4. Pulsar **Buscar imágenes**.
5. Revisar la tabla de escenas y la de pares, elegir un par y ver sus metadatos, sus huellas en el mapa y el enlace a ASF Vertex.

Límites por consulta: 5° de lado y 366 días. Descargar o procesar las escenas requiere una cuenta gratuita de NASA Earthdata y se hace en ASF.

### Qué hace (`utils/buscador_sar.py`)

| Paso | Función | Qué hace |
| --- | --- | --- |
| Validación | `validar_region`, `region_desde_punto`, `validar_fechas` | Rechaza coordenadas, fechas y tamaños inválidos antes de consultar |
| Consulta | `construir_consulta`, `consultar_asf` | Una petición GET al SearchAPI público de ASF, con 30 s de espera |
| Filtrado | `interpretar_respuesta` | Deja solo Sentinel-1 GRD de alta resolución en modo IW; descarta productos de solo metadatos, SLC, otros modos y escenas sin órbita, polarización o huella; agrupa duplicados |
| Emparejado | `emparejar` | Pares con la misma órbita relativa y dirección, alguna polarización en común, fechas distintas y cobertura conjunta suficiente |
| Todo junto | `buscar` | Devuelve escenas, pares y la consulta exacta que se hizo |

- **Orden de los pares:** se prefiere mayor cobertura de la región, mismo satélite, más polarizaciones en común y fechas cercanas (y, si se indica, que encierren la fecha de interés).
- **Versiones repetidas:** ASF publica a veces la misma adquisición con dos identificadores. Se muestra una y se anotan las otras; conviene usar la misma que se procese en HyP3.
- **Errores:** sin conexión, tiempo agotado, servicio caído o respuesta inesperada se muestran con un mensaje claro y no detienen la app.
- **Dependencias:** ninguna nueva. Usa `urllib` de Python y Shapely, que ya llega con GeoPandas. No se usa el paquete `asf_search` para no ampliar la instalación en Replit.

### Caso de prueba: Chigorodó

Consulta real hecha el 12-nov-2026 (recuadro −76.85, 7.40, −76.40, 7.95; del 20-sep al 10-oct-2026):

- ASF devolvió 13 productos, que corresponden a 10 adquisiciones (3 están publicadas dos veces).
- Par recomendado: `S1C_IW_GRDH_1SDV_20260924T232218_…_1338` → `S1C_IW_GRDH_1SDV_20261006T232218_…_116E`. Sentinel-1C, órbita relativa 48 ascendente, VV+VH, 12 días, 100 % de la región. Coincide con el par que el equipo ya había elegido a mano.
- Otros 5 pares compatibles en las órbitas 48 y 142. La órbita 40 solo cubre hasta el 29 % de la región y queda fuera.

Esa respuesta está guardada en `tests/datos/asf_chigorodo_20260920_20261010.json` (solo metadatos) y la usan las pruebas, que nunca tocan la red.

### Integración con el motor de análisis

Conectados en Herramientas SAR (ver «Flujo de Herramientas SAR»). `utils/flujo_sar.py` asocia el par GRD del catálogo con los RTC de HyP3 presentes en `data/sar/`. La conversión GRD → RTC sigue fuera de la app (Fase D, sin implementar).

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

- En el repositorio solo hay datos SAR sintéticos; el motor de análisis aún no se ha ejecutado con escenas reales y no existe ningún resultado científico todavía.
- Los perfiles de visualización no están calibrados con productos reales.
- Hidrografía y vías son de escala general; sin quebradas, cuencas ni vías secundarias.
- Sin capa de precipitación.
- El "Área de referencia" es un rectángulo aproximado, no el límite oficial de Antioquia.
- Una capa SAR por fenómeno; sin comparación de fechas ni consulta de valores por clic.
