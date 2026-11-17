# V.I.S.O.R. · Laboratorio IA (Atrato medio, Chocó)

Investigación del equipo ML de V.I.S.O.R.: etiquetado de NISAR, entrenamiento de modelos y capas para la app. Antes vivía en `VISOR-NISAR-Atrato/` (commit `45dfcb9`); se reorganizó aquí sin cambiar su contenido.

La app **no entrena nada ni importa este código**: la página *Laboratorio IA* (`pages/3_Laboratorio_IA.py`) muestra el mapa ya generado `data/ia_lab/demo_visor_E6.html`. Esta carpeta no se incluye en la publicación de Replit (`.replitignore`) y no la revisa el ruff de la app (`ruff.toml`).

## Qué contiene

| Ruta | Contenido |
|---|---|
| `notebooks/` | 01 descarga NISAR · 02 visualización de recortes · 03 etiquetado de la zona solo con NISAR · 04 capas de terreno |
| `entrenamiento/` | Entrenamiento de los modelos A y B (`entrenamiento_prediccion_inundaciones.ipynb`, `celdas_A.py`, `celdas_B.py`), pruebas sí/no y gráficas |
| `entrenamiento/clima/`, `entrenamiento/insumos/` | IDEAM, GloFAS, ONI, eventos y series NISAR usados para entrenar |
| `entrenamiento/salidas/` | Modelos `.joblib`, métricas, mapas de probabilidad y escenarios |
| `entrenamiento/para_visor/` | Módulo listo para integrar en la app (semáforo del Modelo A, capas de clases, probabilidad y zonas de 2 km) con sus pruebas |
| `etiquetado_zona/` | 22 mapas de clases derivados de NISAR (stacks A_T047, A_T148, D_T011, D_T112) con fichas y series |
| `metadatos/` | Inventario y huellas NISAR, plan de descarga, fases de los eventos |
| `figuras/` | Figuras por región y de cambio |
| `scripts/` | Utilidades (`enlazar_zona_en_sucesos.py`) |

Documentación: [`docs/ia_lab/`](../docs/ia_lab/) (resultados, entrenamiento, datos NISAR, índices de etiquetado e integración) y [`docs/laboratorio_ia.md`](../docs/laboratorio_ia.md).

## Modelos

- **Modelo A · cuándo:** Random Forest calibrado. ¿Superará el Atrato en Quibdó 497 cm en los próximos 3 días? Variables IDEAM, GloFAS y ONI.
- **Modelo B · dónde:** XGBoost sobre celdas de 40 m con radar y clases NISAR, terreno (HAND, DEM, pendiente, WorldCover) y nivel del río. Evaluado en el evento E6, fuera del entrenamiento.

## Reproducir

```bash
cd ia_lab
python3.12 -m venv .venv-ml && . .venv-ml/bin/activate
pip install -r requirements.txt
cd entrenamiento && DIR_ML="$PWD" jupyter lab
```

Los scripts de `entrenamiento/` usan rutas relativas a `DIR_ML` (`clima/`, `insumos/`, `salidas/`); los notebooks buscan la carpeta que contiene `metadatos/`. Los recortes NISAR crudos no están en el repositorio.

Para probar el módulo de integración: `cd entrenamiento/para_visor && pip install -r requirements_ml.txt && python -m pytest tests -q`.

## Límites

La «verdad» del Modelo B son etiquetas derivadas automáticamente de NISAR, no observaciones de campo. Las métricas son históricas. Ninguno de los modelos emite alertas vigentes ni pronostica inundación urbana.
