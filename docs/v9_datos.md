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
