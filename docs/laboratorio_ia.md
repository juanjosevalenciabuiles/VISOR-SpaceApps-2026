# V.I.S.O.R. AI Lab — anexo histórico para el jurado

Fecha: 15 de noviembre de 2026. Rama aislada basada en el respaldo `157c129`.

## Entrada

En el visor principal pulsar **Laboratorio IA** en la barra superior.
La navegación usa Streamlit `st.switch_page`, dado que Mission Control oculta
el menú lateral nativo. Para volver usar el enlace **Volver al visor SAR
principal** en el pie del laboratorio.
El fichero `pages/3_Laboratorio_IA.py` es autónomo y **no modifica el
sistema SAR V9**. El HTML original del equipo está copiado sin cambios en
`data/ia_lab/demo_visor_E6.html`.

Si la aplicación principal oculta el menú de Streamlit y no aparece el acceso,
la página se considera una demostración separada pendiente de validación de
navegación. No modificar el visor principal sin probarlo y aceptar el cambio.

## Qué contiene

- **Modelo A («Cuándo»):** Random Forest calibrado para nivel alto en Quibdó
  dentro de tres días. Umbral aproximado 497 cm. Variables IDEAM, GloFAS
  y ONI. Prueba histórica 2022–junio 2026. Exactitud balanceada 69,7 %,
  sensibilidad 51,9 %, exactitud general 81,4 %.
- **Modelo B («Dónde»):** XGBoost, entrenamiento con NISAR HH/HV,
  terreno y niveles; experimento espacial E6 fuera de entrenamiento.
  Prueba agregada 5.656 zonas de 2×2 km: 83,9 % exactitud balanceada,
  81,7 % sensibilidad (161/197), 17,4 % valor predictivo positivo
  (161/926), 82,6 % falsos positivos entre zonas marcadas.
- **Mapa Folium E6:** dos superposiciones raster incrustadas, un GeoJSON
  de zonas y control de capas. La capa A_T148 compara
  11 de agosto y 4 de septiembre de 2026.

## Límites científicos

La «verdad» del Modelo B son **etiquetas derivadas automáticamente de NISAR**,
no visitas ni pruebas de inundación de campo. No comparar su métrica agregada
de zonas con una evaluación por píxel. El Modelo A no pronostica inundación
urbana ni emite alertas vigentes. Evitar expresiones de certeza como
«esta zona se va a inundar».

La página no importa `.joblib`, no ejecuta XGBoost, no realiza descargas,
no procesa imágenes ni modifica `data/analisis` y `data/nisar`.
Las capas de fondo OpenStreetMap y librerías Leaflet pueden requerir red.
Si el HTML no existe, se muestra un error y no se fabrican datos.

## Trazabilidad

- Prototipo HTML original:
  https://drive.google.com/file/d/1iCF-9Fk78ybbpk1cOHGwKUBidAvYATSM/view
- Informe de métricas:
  https://drive.google.com/file/d/1HSazqhn5eYe5j-Lp6FB8cOyAo-7R8sq2/view
- Plan de integración del equipo: `VISOR_PLAN_LABORATORIO_IA_JURADOS_2026-11-15.md`.

## Criterios previos a incorporación

- CI Python/Ruff, pruebas de la página en sesión limpia y navegador real.
- Comprobar control de capas Folium, zoom, retorno al visor.
- Comprobar la procedencia de cada capa y que no se muestra «alerta actual».
- Mantener la rama de respaldo de jurado y `main` sin alterar.
- Revisar permisos de Drive: se observó acceso `anyone: writer` en
  artefactos del laboratorio. Corresponde al dueño revisar y restringir
  permisos; esta integración NO los modifica.

## Investigación y modelos

El trabajo completo del equipo ML (notebooks, entrenamiento, datos y modelos) está en [`ia_lab/`](../ia_lab/README.md) y sus resultados en [`docs/ia_lab/`](ia_lab/).
