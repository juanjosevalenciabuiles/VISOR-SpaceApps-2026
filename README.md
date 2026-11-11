# V.I.S.O.R.

**Visualización Inteligente de Superficies y Observación por Radar** — NASA Space Apps Challenge 2026, reto *Dancing with the SARs*.

Plataforma web que muestra productos de radar SAR **ya procesados** sobre un mapa interactivo de Antioquia, para tres fenómenos: inundaciones, deslizamientos y deforestación.

> V.I.S.O.R. muestra **indicios**, no detecciones confirmadas. Los archivos que vienen en `data/` son **sintéticos de demostración**: no provienen de ningún satélite.

## Ejecutar

**En Replit:** botón **Run**. La app abre en el puerto 5000 (configurado en `.replit`).

**En local:**

```bash
pip install -r requirements.txt
streamlit run app.py
```

**Pruebas:** `pytest`

### Mapa base (CARTO API key)

El mapa base es CartoDB Dark Matter. CARTO ahora exige una API key gratuita para sus teselas; sin ella el fondo sale con la marca de agua "API KEY REQUIRED".

1. Pedir la key en <https://carto.com/basemaps/apikey/> (gratis, sin cuenta).
2. Guardarla como `CARTO_API_KEY`: en Replit, en **Secrets**; en local, `export CARTO_API_KEY=...`.

Nunca se escribe la key en el código ni se sube al repositorio.

## Estructura

```
app.py                  Punto de entrada: solo orquesta
components/
  barra_lateral.py      Selector de fenómeno y controles de capa
  encabezado.py         Identidad del proyecto
  mapa.py               Mapa Folium + capa SAR + cobertura
  leyenda.py            Leyenda de color
  panel_info.py         Descripción, producto, fuente, advertencias
  estilos.py            Inyecta assets/style.css
utils/
  config.py             Fenómenos, colores, textos, rutas  ← casi todo se ajusta aquí
  geotiff.py            Lectura de GeoTIFF: CRS, NoData, caché, colores
  geo.py                Utilidades GeoPandas
assets/style.css        Tema oscuro / glassmorphism
data/                   GeoTIFF ligeros que lee la app
scripts/generar_datos_demo.py   Regenera los datos sintéticos
tests/                  Pruebas del cargador
```

## Cómo integrar datos reales (HyP3)

1. Procesar fuera de la app (ASF HyP3) y exportar un GeoTIFF **ligero** de una banda.
2. Guardarlo en `data/` con el nombre exacto: `inundacion.tif`, `deslizamiento.tif` o `deforestacion.tif`. Reemplaza al sintético y el aviso de demostración desaparece solo (depende de la etiqueta `VISOR_DEMO=1` del archivo).
3. (Opcional) Crear al lado un `.json` con los metadatos que se muestran en el panel:

   ```json
   { "fuente": "Sentinel-1 IW, ASF HyP3 RTC", "fecha": "2026-05-01 / 2026-05-13", "producto": "Cambio de retrodispersión VV (dB)" }
   ```

4. Ajustar la visualización en `utils/config.py` si hace falta: `vmin`/`vmax` (rango fijo) e `invertir=True` cuando los valores **bajos** son el indicio (p. ej. caída de dB en inundaciones).

El cargador acepta cualquier CRS (reproyecta a EPSG:4326), trata NoData y NaN como transparente, reduce rásters de más de 1024 px y muestra un error legible si el archivo falta, está dañado o no tiene CRS. No subir productos crudos de varios GB: la app no los procesa.

## Trabajo colaborativo

- **Un módulo, una persona a la vez.** Los archivos están separados para que dos personas no editen el mismo: interfaz (`components/`, `assets/`), datos (`utils/geotiff.py`, `scripts/`), configuración y textos (`utils/config.py`), pruebas (`tests/`), documentación.
- **GitHub es el respaldo.** Conectar el Repl a un repositorio (panel **Git** de Replit) y hacer commits pequeños y frecuentes con mensaje claro. Antes de empezar: *pull*. Antes de irse: *commit + push*.
- **Ramas** para cambios grandes (`ui/…`, `datos/…`); `main` siempre debe ejecutar.
- **Antes de subir:** `pytest` y abrir la app.
- La edición simultánea en Replit depende del plan del dueño del Repl; si no está disponible, cada integrante trabaja en su copia y se integra por GitHub.
- Tareas, estados y roles se gestionan **solo en Notion**. Aquí no hay tablero paralelo.

## Limitaciones actuales

- Solo hay datos sintéticos; no existe ningún resultado científico todavía.
- El rectángulo "Área de referencia" es aproximado, no el límite oficial de Antioquia.
- Una capa por fenómeno; sin comparación de fechas ni consulta de valores por clic.
