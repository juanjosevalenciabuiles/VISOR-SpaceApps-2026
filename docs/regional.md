# V.I.S.O.R. regional: AOI configurables y cruce SAR × JRC

Rama `feature/regional-uraba` (parte de `feature/qgis-fase-c`, PR #5; **independiente del PR #6 de NISAR**).
13-nov-2026. Este documento separa lo implementado, lo probado con datos reales, lo probado con datos
sintéticos y lo pendiente.

> **Ninguna cifra regional existe todavía.** Los únicos resultados científicos son los de Chigorodó, hechos por
> el equipo en QGIS. El código regional está probado con datos **sintéticos**; con datos reales solo se probó el
> catálogo de ASF guardado. La coincidencia con agua histórica **no confirma inundaciones**.

## 1. Qué cambia

V.I.S.O.R. deja de estar atado al recuadro de Chigorodó. El área de trabajo es un **AOI**:

| AOI | Cómo | Estadísticas por municipio |
| --- | --- | --- |
| Un municipio o la unión de varios | Límites oficiales (DANE MGN / IGAC) en `data/limites/` | Sí |
| Piloto: Chigorodó, Carepa, Apartadó y Turbo | Grupo predefinido (códigos DIVIPOLA 05172, 05147, 05045, 05837) | Sí |
| Urabá antioqueño (11 municipios) | Grupo predefinido | Sí |
| Cualquier polígono | GeoJSON en WGS84 (subido en la app o por línea de comandos) | Por cada Feature |
| Recuadro | Coordenadas | No (avisa que no es un límite administrativo) |

Un AOI **no implica cobertura**: que el piloto esté definido no significa que haya escenas que lo cubran.

## 2. Flujo automatizado (lo que antes se hacía a mano en QGIS)

| Paso | Módulo | Qué hace |
| --- | --- | --- |
| AOI | `utils/regiones.py` | Lee límites oficiales o GeoJSON, une polígonos, valida (WGS84, solo polígonos, repara inválidos, avisa solapes), guarda el AOI con el SHA-256 de su fuente |
| Cobertura | `utils/cobertura.py` | Con metadatos de ASF: fracción del **polígono** cubierta por cada escena, pasadas (cuadros consecutivos), pares comparables y cobertura por municipio; avisa huecos |
| Mosaico | `utils/mosaico.py` | Une los RTC de **una** pasada por bloques, con caché; rechaza mezclar fechas, órbitas, polarizaciones o cuadrículas |
| Motor | `utils/analisis_sar.py` (sin cambios de método) | Analiza RTC sueltos o mosaicos |
| Cruce JRC | `utils/sar_jrc.py` | Máscara VV/VH × JRC Occurrence reproyectado en memoria; por bloques; umbrales ≥ 1, 10, 25, 50 %; por clase y por municipio |
| Resultados | perfiles nuevos en `utils/resultados.py` | Dos capas en el explorador, con leyenda, ficha y exportación QGIS |
| Interfaz | `components/regional.py` | Pestaña «05 · Regional» de Herramientas SAR |
| CLI | `scripts/regional.py` | `reproducir`, `limites`, `aoi`, `cobertura`, `mosaico`, `cruzar` |

### Salidas del cruce (en `data/analisis/`, nunca se sobrescriben)

- `sar_jrc_<máscara>_<AOI>_coincidencia.tif`: 0 sin detección · 1 detección sin agua histórica · 2 detección
  sobre JRC ≥ 1 % · 255 sin dato.
- `…_polarizaciones.tif`: 0 · 1/2/3 solo VV / solo VH / ambas con JRC 0 % · 11/12/13 las mismas sobre
  JRC ≥ 1 % · 255 sin dato.
- `…_estadisticas.csv` (UTF-8 con BOM; abre en Excel y QGIS en Windows) y `…_informe.json`: por zona y
  umbral, con denominadores, coberturas, huellas SHA-256 de entradas y salidas, avisos y limitaciones.
- Cada GeoTIFF lleva su ficha de procedencia, heredada de la máscara SAR (REAL SIN VALIDAR como máximo).

### Reglas que el código hace cumplir

- **JRC:** válido 0–100. El NoData y cualquier valor > 100 (p. ej. 255) son «sin dato JRC» y **nunca** se
  convierten en 0. Se lleva a la cuadrícula SAR con vecino más cercano, sin escribir un JRC intermedio.
- **SAR:** 255 se conserva. Lo que queda fuera del AOI o sin dato sale 255, no 0.
- **Hectáreas:** del CRS y del tamaño de píxel reales (determinante de la transformada y unidades); no se
  supone 30 m. En un CRS geográfico no se dan hectáreas.
- **Cobertura:** por municipio se informan los píxeles de la zona dentro de la cuadrícula, el % de la zona que
  la cuadrícula cubre y el % con SAR válido. Una cobertura parcial nunca se muestra como completa.
- **N/D:** una zona sin observaciones válidas muestra N/D, nunca 0 %.
- **Denominadores:** cada tasa va con «coincidentes / total».
- **Entradas intactas:** SHA-256 antes y después; si cambian, se descartan las salidas.
- **Sensores:** las clases VV/VH y sus umbrales son de Sentinel-1 (banda C). Una máscara que declare NISAR o
  banda L se rechaza. NISAR sigue en su PR (#6) y no entra aquí.

## 3. Puerta: reproducir Chigorodó con los GeoTIFF reales

El cruce regional (en la app y en `regional.py cruzar`) está **bloqueado** hasta que este comando dé APROBADA
en Replit, con los archivos reales:

```bash
.venv/bin/python scripts/regional.py reproducir \
    --sar data/analisis/coincidencia_VV_VH_20260924_20261006.tif \
    --jrc data/jrc/<JRC de Chigorodó>.tif
```

Corre el cruce en una carpeta temporal y compara con las cifras de QGIS del equipo
(`tests/datos/referencia_sar_jrc_chigorodo.json`). Esas cifras son la referencia de una comprobación, **no**
constantes del motor.

| Cifra de QGIS (13-nov-2026) | Valor |
| --- | --- |
| Cuadrícula | EPSG:32618 · 924 × 926 px |
| Píxeles sin dato SAR (se conservan) | 91 |
| Detecciones SAR | 40.296 px = 3.626,64 ha |
| Sobre JRC Occurrence > 0 | 4.004 px = 360,36 ha (9,94 %) |
| Solo VV | 1 de 11 |
| Solo VH | 1.335 de 27.992 |
| VV y VH | 2.668 de 12.293 |

Si no coincide, el registro dice en qué cifra y la app sigue bloqueada. Si la máscara usada cambia después,
la puerta se cierra. `bash verificar.sh` repite la comprobación (REG-01) sin escribir en `data/`.

**Estado: NO EJECUTADO con datos reales.** Los GeoTIFF están solo en Replit; aquí se probó con un ráster
sintético que tiene el mismo histograma (ubicaciones inventadas).

## 4. Preparar los datos en Replit (el equipo)

```bash
git status --short                                  # debe salir vacío
bash actualizar.sh feature/regional-uraba
mkdir -p data/jrc data/limites
# 1. Copiar el JRC Occurrence (GeoTIFF original o VRT) a data/jrc/
# 2. Copiar el GeoJSON de municipios del MGN de DANE y extraer Urabá (el original no se toca):
.venv/bin/python scripts/regional.py limites --mgn /ruta/MGN_municipios.geojson
# 3. Reproducir Chigorodó (habilita el cruce):
.venv/bin/python scripts/regional.py reproducir --sar data/analisis/coincidencia_VV_VH_20260924_20261006.tif --jrc data/jrc/<archivo>.tif
bash verificar.sh
bash start.sh                                       # recarga solo V.I.S.O.R., sin Stop
```

`data/jrc/`, `data/limites/` y `data/aoi/` están fuera de Git. Fuentes oficiales: límites municipales de DANE
(datos.gov.co, conjunto «Municipio») o IGAC (Colombia en Mapas); JRC Global Surface Water Occurrence.

## 5. Áreas grandes: qué hay y qué no

| Necesidad | Estado |
| --- | --- |
| Buscar escenas sobre el AOI | Implementado (recuadro del AOI, cobertura medida sobre el polígono). Límite del buscador: 5° por lado y 250 resultados por consulta |
| Porcentaje de cobertura por escena, pasada, par y municipio | Implementado; probado con huellas sintéticas y con el catálogo real guardado de Chigorodó |
| Pares comparables | Misma órbita relativa, dirección y polarización; siempre «sin validar». No se combinan órbitas distintas |
| Mosaico válido por fecha | Implementado para RTC de una pasada; probado con rásteres sintéticos. **Sin probar con RTC reales** |
| Procesamiento por bloques | Cruce JRC y mosaico: por bloques. **El motor de cambio sigue leyendo el AOI entero en memoria** (tope de 16 millones de píxeles ≈ 120 × 120 km a 30 m) |
| Caché | Mosaico y cruce: por SHA-256 de entradas y parámetros |
| Conexión del mosaico con los pasos 02–03 de la app | **Pendiente.** Hoy el mosaico se hace con `regional.py mosaico` y se analiza con `scripts/analizar_sar.py` |

**Cobertura real hoy:** solo existen RTC de Chigorodó (un cuadro, 24-sep y 6-oct-2026). No hay RTC ni máscara
para Carepa, Apartadó ni Turbo: para el piloto, el cruce mostrará esos municipios como N/D o con cobertura
parcial. No se ha buscado en el catálogo real qué pasadas cubren el piloto (desde el entorno de desarrollo no
hay acceso a ASF): `regional.py cobertura` lo responde en Replit, solo con metadatos.

## 6. Límites científicos

- JRC Occurrence es la frecuencia de agua 1984–2024; no es agua en la fecha del radar. Ocurrencia 0 es «sin
  agua observada», no «nunca hubo agua».
- Porcentajes y «enriquecimiento» son descriptivos: no son precisión, sensibilidad ni causalidad. Hay
  autocorrelación espacial y sesgos de terreno y cultivo.
- Las clases VV y VH usan umbrales distintos y tamaños muy desiguales (11 px frente a 27.992): sus tasas no son
  sensibilidades comparables.
- Se informan cuatro umbrales a la vez para no escoger a posteriori el que dé la cifra más llamativa.
- Las cifras de Chigorodó no se extrapolan al piloto ni a Urabá.
- Vecino más cercano: los bordes pueden moverse hasta medio píxel. Un píxel pertenece a una zona si su centro
  cae dentro.
- La máscara SAR es REAL SIN VALIDAR; el cruce no la valida.

## 7. Estado

| | Implementado | Probado con datos reales | Probado con datos sintéticos | Pendiente |
| --- | --- | --- | --- | --- |
| AOI (municipios, uniones, GeoJSON) | Sí | No (no hay límites oficiales en el entorno) | Sí | Límites DANE/IGAC en Replit |
| Cruce SAR × JRC | Sí | **No** | Sí (incluido el histograma de QGIS) | Reproducción en Replit |
| Estadísticas por municipio y umbral | Sí | No | Sí | Máscaras que cubran más municipios |
| Cobertura y pares | Sí | Catálogo ASF guardado (Chigorodó, 20-sep a 10-oct) | Sí | Búsqueda real para el piloto |
| Mosaico | Sí | No | Sí | RTC de cuadros contiguos |
| Mission Control (paso 05) | Sí | No (Replit) | Sí (AppTest y navegador) | Verificación en Replit |
| Exportación QGIS de las capas del cruce | Sí | No | Sí (estructura del paquete) | Abrir en QGIS Desktop (lista Q1–Q8) |

## 8. Relación con los otros PR

- **PR #5 → PR #4 → `main`:** sin cambios; sigue pendiente de `verificar.sh` en Replit con datos reales y de
  la lista Q1–Q8 en QGIS. Nada se ha fusionado.
- **PR #6 (NISAR):** independiente. Esta rama no lo incluye. Los dos tocan `components/herramientas_sar.py`
  (`render`), `utils/verificacion.py`, `scripts/verificar_visor.py` y `utils/resultados.py`: al integrar el
  segundo habrá conflictos pequeños y previsibles en esos puntos.
