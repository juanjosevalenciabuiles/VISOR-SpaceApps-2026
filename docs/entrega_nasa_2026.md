# Entrega NASA Space Apps Challenge 2026 — V.I.S.O.R.
> Documento de preparación para el formulario. **No equivale a envío realizado.** Actualizado 2026-11-15. Verificar cada enlace y la licencia del material incorporado antes de enviar.

## Project Name
V.I.S.O.R. — Visualización Inteligente de Superficies y Observación por Radar

## Project Summary (español, 50–200 palabras, máximo 1500 caracteres)
V.I.S.O.R. (Visualización Inteligente de Superficies y Observación por Radar) es una plataforma web de exploración territorial que facilita el análisis de cambios ambientales en Colombia mediante imágenes de radar de apertura sintética (SAR). Permite seleccionar una zona y un período, consultar catálogos satelitales, inspeccionar la cobertura disponible y comparar observaciones compatibles de distintas fechas. Integra productos NISAR de NASA, información de Sentinel-1 y capas de contexto ambiental y territorial.

Su objetivo es acercar herramientas de teledetección a estudiantes, investigadores y comunidades, especialmente donde las nubes dificultan la observación óptica. La plataforma presenta resultados y sus limitaciones de manera comprensible, distinguiendo datos reales, demostraciones y análisis experimentales. Un cambio de señal radar no constituye por sí solo una inundación confirmada. V.I.S.O.R. propone una experiencia accesible y reproducible para investigar el territorio y orientar preguntas que requieren validación adicional.

## Project Details
V.I.S.O.R. es una aplicación web de exploración geoespacial construida en Python, Streamlit, Folium/Leaflet y herramientas de análisis ráster. El usuario delimita un área de interés (AOI) y un rango temporal. La plataforma consulta metadatos de catálogos satelitales, presenta candidatos de NISAR GCOV y evalúa si existen escenas de geometría, cobertura, modo y polarización compatibles antes de preparar productos o calcular cambios. La ruta de NISAR utiliza datos SAR en banda L y puede preparar recortes COG mediante NASA Harmony; la exploración de Sentinel-1 corresponde a un sensor diferente en banda C y no debe presentarse como si fuese NISAR. Los resultados se superponen en un mapa con fuentes ambientales y territoriales, identificando procedencia, fechas y limitaciones. La búsqueda sin escenas compatibles, una interrupción de red y la falta de validación científica son estados diferentes.

El Laboratorio IA expone de forma independiente resultados históricos experimentales del Atrato: un Random Forest para predicción de nivel alto y un XGBoost para priorizar zonas según etiquetas derivadas de NISAR. **No es un sistema de alerta en tiempo real ni un detector de inundaciones confirmado en campo.** Modelo A, horizonte 3 días: exactitud balanceada ~69,7 %, sensibilidad ~51,9 %. Modelo B, agregado E6: exactitud balanceada ~83,9 %, sensibilidad ~81,7 % frente a etiquetas satelitales, y ~82,6 % de falsos positivos entre zonas marcadas. Estas métricas no son precisión clínica ni validez externa; deben acompañarse de prevalencia, definición de etiquetas y muestras.

Beneficio: facilitar el acceso y la interpretación crítica de observaciones SAR en regiones tropicales. Creatividad: combinar búsqueda geográfica, controles de procedencia, capas contextuales, flujo SAR y un laboratorio IA pedagógico, sin presentar indicadores indirectos como desastres confirmados. Impacto previsto: apoyar educación, investigación y decisiones informadas, siempre con verificación local independiente.

## Project links — rellenar solo enlaces verificados
- **Project (público, sin registro):** https://github.com/juanjosevalenciabuiles/VISOR-SpaceApps-2026 (repositorio confirmado público el 15-nov-2026; comprobar que la rama/código final sea accesible y documentado).
- **Project Demonstration:** PENDIENTE: URL pública de video de **máximo 30 segundos** o presentación de **máximo 7 diapositivas**. No usar una vista previa privada de Replit. Comprobar desde navegador incógnito sin sesión.
- **Web app Replit:** NO CONFIRMADA como publicada; no colocar URL de editor como demo pública.

## Guion de demo de 30 segundos (máximo; grabar con OBS/ShareX, editar con Clipchamp/Shotcut)
- 0–4 s: título original V.I.S.O.R. y pregunta «¿Qué cambia en nuestro territorio?».
- 4–9 s: mapa, búsqueda de Chigorodó y delimitación de AOI.
- 9–15 s: fechas y consulta de metadatos reales; mostrar explícitamente si la cobertura es insuficiente.
- 15–22 s: visualización de un par SAR **real previamente validado**, o mostrar honestamente demo histórica etiquetada. Sin insinuar una inundación confirmada.
- 22–27 s: Laboratorio IA y su rótulo «experimental».
- 27–30 s: cierre «Explorar. Comparar. Verificar.» y enlace público. Música solo original/licenciada, sin logotipos NASA generados.
Si el flujo de datos falla, grabar solo funcionalidades realmente operativas y declarar los límites. Exportar MP4, subir a YouTube sin listar/público o Drive con «cualquier persona con enlace», verificar sin sesión.

## NASA Data — recursos a comprobar y citar si realmente usados
- NASA Earthdata Search — https://search.earthdata.nasa.gov/
- NASA CMR — https://cmr.earthdata.nasa.gov/search/
- NASA-ISRO SAR (NISAR) — https://nisar.jpl.nasa.gov/
- Alaska Satellite Facility (ASF) — https://search.asf.alaska.edu/
- NASA Harmony — https://harmony.earthdata.nasa.gov/
- NASA EONET — https://eonet.gsfc.nasa.gov/
**No declarar como procesado un producto NISAR si solo se consultaron sus metadatos.** El requisito NASA Data exige uso efectivo de datos o recursos NASA.

## Space Agency Partner & Other Data / Software — incluir solo lo realmente usado
- ESA Copernicus Sentinel-1 — https://dataspace.copernicus.eu/
- IDEAM Colombia — https://www.ideam.gov.co/
- DANE Colombia — https://www.dane.gov.co/
- Copernicus Emergency Management Service / GloFAS — https://global-flood.emergency.copernicus.eu/
- OpenStreetMap — https://www.openstreetmap.org/copyright
- Streamlit — https://streamlit.io/
- Folium — https://python-visualization.github.io/folium/
- Leaflet — https://leafletjs.com/
- Rasterio — https://rasterio.readthedocs.io/
- Shapely — https://shapely.readthedocs.io/
- Python — https://www.python.org/
- XGBoost — https://xgboost.readthedocs.io/
- scikit-learn — https://scikit-learn.org/
Auditar dependencias, fuentes de mosaicos, fotos, iconos, textos, audios y modelos adicionales desde el repositorio y registrar licencias/atribuciones antes de afirmar originalidad.

## Uso de Super Intelligence (SI)
Declarar todas las categorías que efectivamente se usaron: **Data Analysis and Interpretation; Building SI/ML Into the Project; Coding, Debugging, or Troubleshooting; Visual Design or Image Creation; Other Project-Related SI Use; Presentation, Video, or Audio** (estas dos últimas solo si se usaron herramientas generativas para esos materiales). Texto sugerido: «Se emplearon asistentes de IA (incluidos ChatGPT y Claude, según tareas) para apoyar investigación, planificación, revisión de código, depuración, documentación y comunicación visual. El equipo definió los objetivos, seleccionó datos, revisó resultados y conserva la responsabilidad científica y autoral. El laboratorio de aprendizaje automático está identificado como experimental y sus métricas se reportan con limitaciones». Registrar asistencia de IA en documentación y metadatos de código/datos. Las imágenes y videos generados por IA requieren marca de agua **visible**; el audio generado por IA requiere reconocimiento en descripción y metadatos. No generar, modificar ni simular logos, banderas o identificadores de misión NASA mediante IA.

## Lista de verificación previa a Submit
- [ ] Resumen dentro de 50–200 palabras y 1500 caracteres (contar antes de pegar; traducir si se prefiere inglés).
- [ ] Project Details con funcionamiento, beneficios, herramientas, creatividad y límites.
- [ ] Enlace de proyecto público probado en incógnito; repositorio contiene la versión de entrega.
- [ ] Demo pública accesible sin permiso, <=30 segundos **o** <=7 diapositivas; comprobar duración real.
- [ ] NASA Data con enlaces completos y evidencia de uso real.
- [ ] Space Agency Partner & Other Data con licencias y atribuciones de **todos** los recursos externos.
- [ ] Declaración de SI precisa, con marcas/metadata según el tipo de contenido.
- [ ] CI Python/ruff y navegador verde; prueba manual Replit de AOI, fechas, catálogo, mapa, laboratorio, zoom, errores y móvil.
- [ ] Sin secretos, datos personales, ni archivos pesados sensibles en repositorio.
- [ ] Confirmación de originalidad, términos, permisos y derechos.
- [ ] Pulsar **Save o Submit** y verificar estado de envío; no asumir que guardar un borrador envía el proyecto.

## Auditoría de estabilidad 15-nov-2026
En PR #35, commit `ddcf80c`, CI Python/ruff pasó pero Playwright Chromium/Firefox falló. En logs de Chromium, la superposición flotante «🧪 Laboratorio IA» interceptaba clics del buscador en móvil; se eliminó su montaje en la rama de esta auditoría. El acceso alternativo permanece en Explorador y el botón de la barra superior. Otras fallas de selectores/estado Playwright requieren evaluación y pruebas manuales antes de declarar el proyecto estable. **No se fusiona ni se despliega automáticamente.**
