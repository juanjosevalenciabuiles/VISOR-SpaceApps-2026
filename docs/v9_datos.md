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
