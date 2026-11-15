# V9 · Agente 1 — Datos SAR, agua, hidrología y rendimiento

**Alcance:** PC exclusivamente. NISAR L-band principal y Sentinel-1 C-band respaldo; solo inundaciones. Este encargo reemplaza los antiguos chats A/B/C/E.

**Estado inicial:** rama creada desde V8 PR #17 SHA `9ea6535`; Claude continúa editando PR #16. Nunca editar `main`, la rama de Claude ni los archivos compartidos de V8.

**Propiedad exclusiva:** crear/editar solo `utils/v9_datos/`, `tests/v9_datos/`, `docs/v9_datos.md`, y este documento. Los módulos centrales `app.py`, `utils/nisar_*.py`, `utils/trabajos.py`, `utils/verificacion_multifuente.py`, `components/`, `requirements*.txt`, workflows CI y `data/` son solo de lectura. Parches para esos archivos se proponen en `docs/v9_datos.md`.

**Objetivo:** reutilizar catálogo NISAR/Harmony, preflight OPERA DSWx-S1, flujo Sentinel-1 y trabajos. Implementar incrementalmente (1) selección barata por metadatos/huella, fechas y presupuesto; (2) QA real y lectura por ventanas, sin confundir catálogo con observación; (3) adaptadores opt-in DSWx/IMERG con fuente, linaje, fechas y QA si verificables; (4) caché por firma de granules+AOI+versión+QA y medición de tiempos/bytes. No descargar HDF5 grandes por defecto ni datos masivos.

**Contrato:** los registros utilizables deben respetar `utils/verificacion_multifuente.py`: `tipo`, `observed_at`, `valid`, `relacion_espacial`, `origen`, además de `fuente`, `producto`, `url`, `qa`, `limitaciones`. Catálogo solo => `SIN_DATOS`/`SIN_COBERTURA`/`QA_INSUFICIENTE`, jamás `valid=True` observacional. DSWx/GFM derivados de la misma Sentinel-1 comparten `origen`. Separar banda L y banda C. Lluvia nunca confirma inundación.

**Pruebas:** nodata, QA=0 urbano Chigorodó, fecha fuera de ventana, sensor incompatible, cache hit no recalcula, cero escenas, ausencia de secretos, ejemplo negativo IMERG. Simulados solo en tests. Registrar qué ejecución realmente pasó.

**Desarrollo automático:** consultar SHA/PR propia antes de cada sesión; inspeccionar únicamente archivos relacionados; generar un incremento pequeño, pruebas, commit en esta rama y actualizar PR draft con resultados. Repetir hasta cumplir criterios, luego declarar listo para integrador; nunca fusionar por cuenta propia. Notificar solo bloqueo persistente.
