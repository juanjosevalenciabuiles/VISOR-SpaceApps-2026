# V9 IA2 · Adaptador científico y panel PC (primer incremento)

Se añadieron `utils/v9_evidencia/contrato.py` y `components/v9_desktop/panel_evidencia.py`.

- El adaptador requiere evidencia observacional explícita, fecha, fuente, origen estable y píxeles QA positivos antes de aceptar un registro SAR/agua. Los documentos oficiales conservan su escala municipal: NO confirman píxeles.
- Utiliza el evaluador original V8 `utils.verificacion_multifuente.evaluar_evidencias`, para aprovechar estados y deduplicación por granule, sin modificar código compartido.
- La UI opt-in no descarga imágenes ni ejecuta procesos raster; muestra estados científicos, fuentes y descartes. No se ha conectado a `app.py` ni se ha probado con un servidor real.
- Los fixtures de los tests son **sintéticos de prueba** y no constituyen observaciones de Chocó/Chigorodó.

## Pendientes

Conectar un productor real de registros QA del agente 1, revisar su trazabilidad y realizar una prueba de escritorio en Chromium/Firefox. Conectar el panel al flujo de V8 tras cierre de Claude y CI verde. Solo PC.

## Pruebas

Se incluyen tests unitarios reproducibles; no afirmar que GitHub Actions o Playwright aprobaron hasta consultar el estado real del commit.
