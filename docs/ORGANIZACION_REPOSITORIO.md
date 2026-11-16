# Organización del repositorio V.I.S.O.R.

Este mapa permite trabajar en GitHub y trasladar el código a otra plataforma
sin romper importaciones ni rutas relativas.

## Directorios con responsabilidades claras

| Ubicación | Responsabilidad | ¿Se publica con Docker? |
| --- | --- | --- |
| `app.py` | Entrada Streamlit | Sí |
| `components/` | UI Mission Control, herramientas SAR, capas, ECO | Sí |
| `utils/` | Funciones científicas, metadatos, GeoTIFF, trabajos | Sí |
| `pages/` | Análisis, buscador y Laboratorio IA | Sí |
| `assets/`, `static/` | CSS y recursos visuales de la interfaz | Sí |
| `data/contexto/` | Límites y contexto geográfico ligero incluido en Git | Sí |
| `data/ia_lab/` | Mapa Folium E6 histórico del laboratorio IA | Sí |
| `data/*.tif` | Capas de ejemplo DEMO **sintéticas** | Sí, rotuladas |
| `data/analisis/` | Resultados GeoTIFF reales y fichas JSON | **No** |
| `data/sar/`, `data/nisar/` | Entradas satelitales descargadas | **No** |
| `data/trabajos/` | Estados locales de tareas SAR | **No** |
| `docs/` | Arquitectura, datos, ciencia y despliegue | Código Git, no Docker |
| `tests/` | Pruebas de Python y navegador | Git/CI, no Docker |
| `scripts/` | Auditoría, inicio portable, preparación | Sí |
| `.github/workflows/` | CI y verificaciones | Git/CI, no Docker |
| `start.sh`, `.replit` | Arranque y configuración **solo Replit** | Se conservan en Git |
| `Dockerfile`, `.dockerignore` | Construcción portable | Sí |

`VISOR-NISAR-Atrato/` es un subproyecto de investigación separado existente
en algunas ramas y no forma parte del servicio web Docker. No se elimina ni
se mueve en esta propuesta.

## Convenciones de ramas y revisión

- `main`: rama principal; NO siempre refleja la sesión presentada a jurados.
- `respaldo/demo-jurados-2026-11-15-157c129`: respaldo histórico de código;
  no modificar ni reescribir.
- `feature/jurados-demo-zona-ia-20261115`: integración de interfaz y laboratorio
  (validación requerida).
- `deploy/visor-portable-jurados-20261115`: Docker y documentación de
  despliegue, partiendo de la rama anterior; **no fusionar por error contra
  `main`**.
- `feature/*`, `fix/*`, `audit/*`: desarrollo por PR con pruebas y
  evidencias, no despliegues sin aprobación.

El SHA que se usó ante los jurados locales todavía necesita comparación con
la instancia o grabación auténtica. No marcar una rama como «la final»
únicamente por su nombre.

## Reglas para integridad científica

1. No añadir datos satelitales pesados ni tokens al repositorio.
2. Mantener juntos GeoTIFF y JSON de procedencia; verificar SHA-256.
3. No sustituir datos faltantes por DEMO sin señalarlo visiblemente.
4. Distinguir cobertura no disponible, consulta fallida y análisis no ejecutado.
5. Un ΔdB no equivale a una inundación confirmada.
6. Mantener trazabilidad NASA NISAR, ESA Sentinel-1 y demás recursos de terceros.
7. Exigir CI verde y prueba pública antes de fijar URL final.
