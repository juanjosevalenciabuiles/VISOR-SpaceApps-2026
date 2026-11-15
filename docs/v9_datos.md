# V9 IA1 · Selección económica de SAR (incremento inicial)

- Código agregado: `utils/v9_datos/seleccion.py` y pruebas sin red en `tests/v9_datos/test_seleccion.py`.
- Lee exclusivamente **metadatos suministrados**; no consume ASF/Harmony, no descarga ni procesa píxeles.
- Filtro de AOI rectangular WGS84, ventana temporal, identidad de granule, banda coherente y tamaño/presupuesto.
- Pares del mismo sensor y fechas diferentes; NISAR L primero, Sentinel-1 C como respaldo; máximo 2 escenas en la salida.
- El estado `PLAN_METADATOS` **no prueba cobertura QA**. Huellas aproximadas nunca son evidencia de agua.
- Casos sin par o cobertura emiten estados explícitos y 0 bytes solicitados.

## Integración futura

Conectar con `utils/nisar_catalogo.py` y catálogo Sentinel-1 mediante un adaptador de metadatos en el integrador, sin modificar esos módulos aquí. El agente desarrollará después validación de píxeles QA, lectura por ventanas, conectores opcionales y cache.

## Pruebas

Se incluyen tests automatizados con datos sintéticos **solo de prueba**. No se afirma que hayan terminado en GitHub Actions ni que se haya probado una escena real. Consultar los checks de la PR correspondiente.


## Planificador pre/post conservador (incremento 2)
`utils/v9_datos/planificador_stack.py::planificar_stack(escenas, aoi, objetivo, dias_antes=30, dias_despues=30, presupuesto_bytes=200000000)` acepta metadatos ya consultados y AOI WGS84. La fecha objetivo se divide en pre (<= objetivo) y post (> objetivo); fuera de ventana no se selecciona. Exige mismo sensor/banda, órbita, stack, madurez, intersección de polarizaciones, huella compartida y presupuesto conjunto. No mezcla PROVISIONAL con VALIDATED ni L con C. El campo `qa_apto=True` debe provenir de inspección QA independiente; `None` retorna SIN_QA. Estados SIN_DATOS, SIN_PAR, SIN_QA, PLAN_METADATOS; ninguno constituye observación de inundación.

**Contrato para integrador:** consultar catálogo antes de descargar, normalizar cada escena a `granule, observed_at, sensor, banda, orbita, stack, madurez, polarizaciones, bbox, tamano_bytes, qa_apto`. No suministrar `qa_apto=True` a partir de huella de catálogo. En caso SIN_QA/SIN_PAR/SIN_DATOS no generar raster ni ficha de inundación. La función no produce GeoTIFF, ficha visor.ficha.v1 ni descarga COG. El integrador conectará selección automática desde área y periodo sin modificar componentes reservados en esta rama.

**Limitaciones conocidas:** no calcula cobertura pixel a pixel, máscara looks/nodata, QA urbano, ni lectura COG; bbox no representa huella real y no cubre antimeridiano. Para NISAR, consultar separadamente colecciones PROVISIONAL (junio 2026 en adelante) y VALIDATED (desde 21 octubre 2026), verificando disponibilidad real de catálogo. Los eventos Chocó julio-agosto requieren búsqueda provisional sin mezclar madurez en el mismo par. Evitar descarga masiva del Atrato; preferir recortes COG por AOI.

**Pruebas añadidas:** `tests/v9_datos/test_planificador_stack.py`, sintéticas, sin red. No ejecutadas localmente en esta sesión; CI por comprobar. No hay evidencia de agua ni raster nuevo.

## Incremento 3 — cambio NISAR L en dB con QA por ventanas

`utils/v9_datos/cambio_cog.py::procesar_par(antes, despues, destino)` recibe **seis GeoTIFF locales**: dos GCOV gamma0 en potencia lineal, dos máscaras QA (1=apto) y dos capas reales de looks efectivos. El integrador debe preparar y documentar las máscaras y looks desde datos observacionales reales: nunca inferir QA a partir de la huella de catálogo. Requiere CRS proyectado y cuadrículas idénticas, mismo sensor NISAR, banda L, órbita, stack, madurez (VALIDATED o PROVISIONAL), polarización y fechas estrictamente crecientes. No mezcla bandas ni madureces, no remuestrea, no descarga.

Por bloques calcula `ΔdB=10log10(gamma0_post/gamma0_pre)` exclusivamente donde gamma0 es positiva y finita, QA=1 y looks superan umbral; NoData y bordes inválidos quedan enmascarados. Emite GeoTIFF `diferencia_db` float32 y JSON lateral `visor.ficha.v1` con fechas, SHA-256 de las seis entradas y de la salida, QA y advertencias. Ante QA insuficiente o par incompatible no publica raster. Declara `real_sin_validar`, **no inundación confirmada** ni agua clasificada.

**Contrato de escena**: `sensor,banda,orbita,stack,madurez,polarizacion,observed_at,granule,cog,qa_mask,looks`. Procesa una polarización por llamada; para HH y HV usar llamadas separadas con sus capas y productos propios. La selección de fechas, cobertura AOI y baseline temporal se resuelven antes con el planificador; este módulo no interpreta una lluvia como inundación. Pendiente conectar los COG reales de Harmony y verificar sus variables QA/looks. **No se ha producido un mapa con datos reales.**

**Pruebas**: cuatro casos sintéticos (Δ=10 dB, SHA/ficha, QA=0, madurez incompatible, ausencia de looks y banda C). La ejecución aislada previa de cuatro pruebas equivalentes pasó con un sustituto local de procedencia; la CI del commit de GitHub debe confirmar compatibilidad con el módulo real. No hay validación satelital.

## Incremento 4 — periodo de interés sin fechas SAR manuales

`utils/v9_datos/ventanas.py::planificar_periodo(escenas, aoi, inicio, fin=None, margen_dias=30, presupuesto_bytes=200000000)` selecciona fechas automáticamente desde **área + periodo**. La escena pre debe preceder estrictamente el inicio y la post seguir estrictamente el final; observaciones durante el periodo no se utilizan como baseline pre/post. El filtro conserva fechas originales, exige compatibilidad y QA mediante `planificar_stack`, cuenta escenas excluidas por margen (`fuera_ventana`) y devuelve `periodo_interes`. Una fecha aproximada se expresa con `fin=None`. Si faltan QA/par/cobertura, no genera raster. Los resultados `PLAN_METADATOS` son planes, no detección de inundación.

Pruebas sintéticas añadidas en `tests/v9_datos/test_ventanas.py`; consultar CI para ejecución verificada. Este adaptador no consulta directamente ASF, no descarga y no integra todavía COG reales. **Reconciliación requerida:** V8 PR #17 cambió a `e73d3de` y no se fusionó en IA1.

## Incremento 5 — adaptadores DSWx-S1 / IMERG con verificación explícita

`utils/v9_datos/fuentes.py::adaptar_observacion(producto, metadatos, pixeles_verificados=False)` convierte **únicamente observaciones ya inspeccionadas** al contrato de `utils/verificacion_multifuente.py`: `tipo, observed_at, valid, relacion_espacial, origen, fuente, producto, url, qa, limitaciones`. No consulta APIs ni lee píxeles. Requiere fecha ISO, URL HTTPS, granule de origen, QA `APTO`, cobertura local `aoi`, y confirmación explícita del integrador de haber inspeccionado los píxeles. Por defecto devuelve `valid=False`.

- DSWx-S1: `tipo=agua_satelital` solo si el integrador documenta `agua_observada=True` tras verificar clasificación y QA. `origen=S1:<granule_origen>` debe coincidir con el linaje de cualquier otro derivado del mismo Sentinel-1, evitando contarlo como observación independiente. Agua observada **no equivale** a inundación.
- IMERG: `tipo=lluvia`, nunca agua ni inundación. Exige precipitación numérica finita y no negativa y QA observacional. `origen=GPM:<granule_origen>`. La lluvia no confirma inundaciones.
- `pixeles_verificados=True` **no ejecuta una comprobación**: es una declaración de responsabilidad del llamador. Se prohíbe pasarla automáticamente desde metadatos de catálogo. Falta implementar y validar el lector real de DSWx/IMERG, máscaras, calidad y procedencia.
- Pruebas offline: `tests/v9_datos/test_fuentes.py`, con negativos de catálogo, QA, AOI, linaje, fechas, URL y lluvia inválida. No se usaron escenas reales ni se descargaron datos.

El integrador debe reconciliar el HEAD V8 #17 `e73d3de` ya fusionado a main, sin merge forzado de la rama IA1. La PR sigue draft, **no lista para fusionar**. La CI del nuevo incremento se comprueba por separado.
