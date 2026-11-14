# V.I.S.O.R. — Modo Colombia + Contexto Ambiental Inteligente

**Estado:** rama experimental de integración, aún sin aprobar. No fusionar a main sin autorización.

## Propósito y acoplamiento mínimo

La app conserva Python, Streamlit, Folium, Shapely y el motor SAR intacto. Por defecto
`VISOR_REGION_MODE=CO`: restringe el mapa, las búsquedas y los análisis al territorio
de Colombia; `VISOR_REGION_MODE=GLOBAL` queda como configuración interna reversible.
No se ofrece un botón al público para salir de Colombia.

Archivos reutilizados y punto de integración:

- `utils/sesion.py`: validación de zona que usan los controles SAR.
- `utils/ejecucion_sar.py`: verificación adicional dentro del trabajo de análisis,
  de forma que una petición no autorizada no esquive el control visual.
- `utils/lugares.py`: Nominatim con `countrycodes=co` y filtrado local por posición.
- `components/mapa.py`: contorno nacional y sombreado del exterior, por encima de
  las teselas pero debajo de las capas de contexto/resultado. Límites de navegación
  Leaflet limitados a la caja nacional que incluye San Andrés y Providencia.
- `components/interfaz.py`: uso del panel ambiental dentro de Herramientas SAR,
  sin añadir un segundo selector de AOI ni un segundo flujo científico.
- `utils/colombia.py`: única fuente de verdad para validación, con geometría original
  no simplificada. `assets/colombia_departamentos_mgn2025.geojson`: 33 entidades
  territoriales, incluidas islas. La máscara se simplifica **solo para pintar**.

**Atribución obligatoria:** Cartografía: Marco Geoestadístico Nacional 2025, DANE
(https://www.dane.gov.co). Simplificación y publicación:
https://github.com/ytolosa/mapas-colombia (CC BY 4.0).
Se incluye una copia derivada del dataset anterior. La validación utiliza polígonos
terrestres; si el usuario requiere estudiar una zona costera que incluye mar,
debe delimitar una caja completamente contenida en el territorio o solicitar
un futuro modo marino diferenciado; nunca se procesa silenciosamente otra nación.

### Limitación geoespacial importante

**El motor SAR sigue analizando el rectángulo envolvente de la zona**, aunque el
usuario dibuje un polígono irregular. Por ello la validación geográfica comprueba
la caja completa, no únicamente el polígono: el sistema **rechaza** zonas que
crucen fronteras o aguas internacionales. No se ha implementado recorte de
valores SAR según fronteras nacionales ni zonas marítimas.

## Contexto ambiental: NASA EONET

`components/contexto_ambiental.py` se monta en la misma ventana de Herramientas SAR.
Lee la AOI confirmada del flujo existente y, preferentemente, las fechas del par SAR
seleccionado; si no hay par, usa el intervalo de búsqueda. El botón **Consultar
contexto** es explícito: no genera consultas al arrastrar el mapa ni en cada rerun
de Streamlit. Usa caché temporal de 15 minutos por geometría y fechas.

`utils/contexto_ambiental.py` consulta **NASA EONET API v3**:
https://eonet.gsfc.nasa.gov/docs/v3

- Ventana alrededor de fechas: ±15 días.
- `bbox` sirve solo como prefiltro; después compara **geometría real contra AOI**
  mediante Shapely. Una noticia de texto **nunca** recibe posición ficticia.
- Categoría: evento catalogado, no evidencia de inundación/deforestación ni de
  exactitud temática del SAR.
- Puede responder SIN_COINCIDENCIAS o ERROR_FUENTE y **nunca bloquea Analizar**.
- No escribe ni altera `data/sar/`, `data/analisis/`, `data/trabajos/`,
  run_id, las máscaras ni resultados previos.
- Una respuesta de otra zona/fecha queda invisible, aunque llegue tarde.
- No consume credenciales Earthdata, no realiza llamadas a LLM ni genera noticias.

**Otros proveedores en la propuesta original:** GDACS, GDELT, IDEAM, UNGRD, Copernicus,
GFW y ReliefWeb. Permanecen **pendientes**, porque falta verificar y probar sus
endpoints y límites operativos con datos auténticos. No prometer cobertura completa.
EONET es un catálogo de eventos seleccionados, no un censo de desastres locales.

## Pruebas y puertas de aceptación

- `python -m pytest -q tests/test_colombia_contexto.py` — lógica sin red.
- `python -m pytest -q -m 'not navegador and not red'` — regresión existente.
- `python -m pytest -q -m navegador` — Chromium/Firefox y prueba visual inicial
  Colombia; la suite global heredada utiliza modo GLOBAL para no invalidar
  casos previos del backend.
- `bash verificar.sh` con datos auténticos originales si están disponibles.
- `ruff check --select F,E9,B .`.
- EONET real opcional (con límite, sin afirmar eventos si API devuelve 0);
  **no probado en red desde esta entrega hasta que exista evidencia de ejecución**.

No confundir CI verde con (a) EONET real consultado, (b) Replit desplegado,
(c) adquisición automática RTC disponible ni (d) validación ambiental.

**Prioridad P0 intacta:** el bloqueo `data/sar/` por falta de RTC continúa
pendiente hasta integrar adquisición y preparación OPERA/HyP3. El contexto
ambiental no puede ocupar la cola de procesado ni autorizar análisis falsos.

## Integración con la PR #11 (14-nov-2026)

Esta rama se integró en `feature/modo-colombia` (PR #11) con un merge, sin reescribir historial. Para que
interfaz, servidor y contexto ambiental decidan igual, queda **una sola política**:

- `utils/alcance_geografico.py` es la fuente única (MGN 2025 DANE al nivel `municipal`, 69 polígonos;
  ficha en `data/contexto/colombia/FUENTE.json`). `utils/colombia.py` conserva la API de esta PR y la delega.
- Un solo velo y contorno: el del lienzo fijo del mapa (panel propio, sin captura de puntero), en lugar del
  grupo que se reenviaba en cada recarga.
- «Ir a…» usa la regla de `alcance_geografico` (con tolerancia de 1 km solo para ubicar lugares).
- Se añaden barreras que esta PR no tenía: búsqueda ASF, motor (`comprobar_alcance`) e historial.
- El panel de contexto ambiental EONET se conserva sin cambios.
- `assets/colombia_departamentos_mgn2025.geojson` ya no decide permisos; se conserva hasta que el equipo decida.
