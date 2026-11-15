# V9 IA2 · Contrato científico y panel PC

Implementación aislada: `utils/v9_evidencia/contrato.py`, `components/v9_desktop/panel_evidencia.py`, `components/v9_desktop/estados.py` y `components/v9_desktop/flujo_publico.py`. No modifica V8, `app.py`, main ni las otras ramas.

## Entrada pública única

`flujo_publico.render(interfaz, respuesta, lugar_buscado, area_analisis)` solicita **Zona de estudio**, **Desde/Hasta** y el botón **Buscar y analizar cambios**. Sensor en expander científico oculto, NISAR L preferido, Sentinel-1 C de respaldo; no fusionar bandas. El render **no** llama a red, Harmony, GeoTIFF ni inferencia. Devuelve un dict de solicitud solo al pulsar. El integrador encola trabajo fuera de render y pasa la respuesta persistida del backend en el siguiente rerender. No se ofrece una descarga AOI sin autorización.

Estados intermedios: buscando, descargando, preparando, procesando. Terminales: apto, sin cobertura, QA insuficiente, solo catálogo/RTC sin preparar, sin par, error. Un `HARMONY_COG_SUBSET` o `INSUMOS_GCOV_SIN_CLASIFICAR` **siempre** termina en `solo_catalogo` para visualización, aunque un proveedor marque `apto`. Nunca pintar clases si no existen rasters validados.

El integrador pasa por separado `lugar_buscado` (p.ej. Rionegro) y `area_analisis` (p.ej. San Carlos), conforme al contrato de PR #20. No inferir identidad del lugar desde la huella AOI.

## Evidencia y procedencia

El adaptador exige QA observacional positivo, fecha en ventana, relación espacial y origen, y delega la deduplicación a `utils.verificacion_multifuente.evaluar_evidencias` de V8. Lluvia sola y documentos municipales no confirman píxeles de inundación; GFM/DSWx del mismo granule cuentan como una adquisición. Falta de QA o cobertura significa información insuficiente, **no ausencia de agua**.

El piloto Chocó sigue experimental: no hay modelo ML entrenado, predicciones, probabilidades ni métricas validadas. Los GCOV Harmony son insumos. Un futuro `LR_ref_HH` GeoTIFF `diferencia_db` necesita ficha `visor.ficha.v1`, SHA-256 del raster, fechas, método, QA y procedencia; `real_sin_validar` no se anuncia como inundación confirmada. `clases_inundacion_nisar` es propuesta, no capa exportada. Si existe raster científico válido, usar leyenda de cambio dB y «Indicio exploratorio, no predicción». La leyenda categórica (agua persistente azul, nueva agua cian, posible vegetación inundada violeta, dudoso amarillo, NoData transparente) se habilita **solo** cuando existan clases reales verificadas.

## Enganches pendientes del integrador

1. Conectar la solicitud pública a cola de trabajos V8 sin ejecutar procesamiento en Streamlit.
2. Convertir resultados de catálogo/descarga/QA/análisis en estados de `estado_backend` y entregar ficha de capa solo cuando exista y se haya verificado independientemente.
3. Renderizar el GeoTIFF real mediante el visor V8 únicamente cuando `mostrar_mapa` sea verdadero; no fabricar raster, clasificación ni métricas.
4. Probar en PC 1366×768, 1440×900 y 1920×1080 y revisar fallas Playwright de la PR #19.

Los fixtures de tests son simulaciones explícitas, **no observaciones satelitales**. Tests añadidos: `tests/v9_desktop/test_flujo_publico.py`; las verificaciones CI se reportan únicamente tras consultar GitHub Actions.

## Perfil declarativo de capas (incremento IA2)

`components/v9_desktop/perfiles.py:perfil_publicable(ficha, raster_verificado=...)` es una **compuerta de presentación**, no verifica por sí misma un GeoTIFF. El integrador debe verificar previamente archivo existente, hash SHA-256, máscara, QA y compatibilidad espacial/temporal en V8, y solo entonces pasar `raster_verificado=True`. Un `diferencia_db` real con `real_sin_validar` y unidad dB puede visualizarse únicamente como **indicio exploratorio**; no representa agua clasificada. `clases_inundacion_nisar` exige `validado` y `clases_verificadas=True`, además de raster verificado; hoy no existe esa exportación. La leyenda de cinco clases es declarativa y jamás colorea píxeles por sí sola. Las fichas de tests son sintéticas. El adaptador espera campos normalizados `schema, estado, tipo_producto, sha256, qa_apto, fecha_inicio, fecha_fin, unidad`; el integrador debe mapear explícitamente desde el bloque `procedencia` de V8 y NO tomar estas etiquetas de un JSON no verificado.


## Validación temporal de fichas (incremento IA2)

La compuerta `perfil_publicable` rechaza fechas inexistentes, mal formadas,
no textuales o invertidas aun cuando el backend haya indicado raster verificado.
Esto es validación defensiva de metadatos, **no** QA satelital. Las pruebas
`test_fecha_invalida_o_invertida_bloquea_mapa` usan exclusivamente fichas
sintéticas. Sigue siendo obligación del integrador verificar hash, cobertura
AOI, máscaras y fecha observacional contra los archivos reales antes de
habilitar el visor.

## Compuerta compartida de publicación (incremento IA2)

`estados.describir_estado("apto", ficha=...)` ahora delega a
`perfiles.perfil_publicable` y exige además `raster_validado is True`.
Un indicador `apto` del backend sin QA positivo, fechas ISO coherentes,
perfil permitido y ficha válida se presenta como `qa_insuficiente`, sin mapa.
El integrador debe verificar hash/archivo/QA en V8; esta comprobación es
solo de metadatos y no certifica observaciones. Test de regresión:
`tests/v9_desktop/test_estados.py::test_apto_no_elude_compuerta_temporal_ni_qa`.
