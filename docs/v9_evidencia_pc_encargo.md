# V9 · Agente 2 — Verificación científica y panel PC

**Alcance:** PC exclusivamente (1366×768, 1440×900, 1920×1080), solo inundaciones; esta tarea reemplaza antiguos chats D/F. V8 PR #17 es base provisional y Claude PR #16 sigue trabajando. No tocar sus archivos mientras está activo.

**Propiedad exclusiva:** crear/editar solo `utils/v9_evidencia/`, `components/v9_desktop/`, `assets/v9_desktop/`, `tests/v9_evidencia/`, `tests/v9_desktop/`, `docs/v9_evidencia_pc.md` y este encargo. `app.py`, `components/interfaz.py`, `components/contexto_zona.py`, `components/eco.py`, `components/barra_lateral.py`, `assets/mission_control.css`, `utils/verificacion_multifuente.py`, requirements, workflows y data/ son solo lectura. Proponer parches de integración en tu doc.

**Misión:** interpretar evidencias científicas con QA, escala espacial, fecha observacional, linaje por granule; reutilizar `utils/verificacion_multifuente.py`. Crear panel Streamlit de escritorio separado para mostrar fuentes, disponibilidad, incertidumbres cualitativas, explicación breve de ECO, ausencia de QA y estados reales, sin procesar ni descargar rasters al render. Prohibidas nuevas tareas móviles o responsive.

**Contrato independiente del Agente 1:** `{tipo, observed_at, valid, relacion_espacial, origen, fuente, producto, url, qa, limitaciones}`. La misma adquisición Sentinel-1 agrupa DSWx y GFM. Estados correctos: reporte municipal documentado (no un píxel), agua observada en AOI con QA, posible inundación cuando corresponda, contexto meteorológico y `INFORMACION_INSUFICIENTE`. Ni la lluvia sola, ni falta de cobertura, ni catálogo permiten afirmar inundación confirmada.

**Pruebas obligatorias:** lluvia sola, reporte municipal ≠ agua en un AOI, QA cero, fuente sin fecha, observación fuera de ventana, mismo origen duplicado, DEMO rotulado como sintético y panel sin trabajo pesado. Pruebas Streamlit escritorio con fixtures explícitos; no crear pruebas móviles ni refactorizar base.

**Desarrollo automático:** consultar SHA/PR propia, generar incremento pequeño con pruebas, commit en rama exclusiva, actualizar PR draft y continuar hasta criterio completo; sin merge a main. Cuando esté listo, señalar archivos de enganche y tests para integrador. Solo notificar bloqueo persistente.
