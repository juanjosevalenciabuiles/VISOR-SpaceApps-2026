# Integration with the V.I.S.O.R. app

The app (Python + Streamlit + Folium) does not train anything: it reads precomputed files from `_ml_entrenamiento/para_visor/`.

## Layers

| Layer | Question | Files |
|---|---|---|
| Traffic light (Model A) | Will the Atrato at Quibdó exceed 497 cm in the next 3 days? | `modelos/modeloA_solo_ideam.joblib`, `data/series/quibdo_nivel_diario.csv`, `data/series/oni_mensual.csv` |
| NISAR classes | What did the radar see? (9 classes, 4 Sep 2026, 20 m, 20 × 20 km window at Quibdó) | `data/analisis/CHOCO_QUIBDO_A_T148_20260904_clases.tif` + `.json` |
| New-water probability (Model B) | Where is new water most likely in the next pass? (40 m, A_T148 swath) | `data/analisis/CHOCO_A_T148_E6_prob_inundacion_20260904.tif` + `.json` |
| 2 km alert zones (Model B) | Which zones to check first? (2,676 zones, 539 in alert) | `data/analisis/CHOCO_A_T148_E6_zonas_alerta_2km.geojson` |

## Code

| File | Use |
|---|---|
| `utils/prediccion_atrato.py` | `probabilidad_nivel_alto(q, oni_hoy)` → probability, traffic light, today's level |
| `utils/capas_ml.py` | `capa_clases()`, `capa_probabilidad()`, `capa_zonas()`, `leyenda_clases()` for Folium |
| `components/alerta_atrato.py` | `panel_alerta()` Streamlit panel |
| `tests/test_modulo_ml.py` | 3 tests: `python -m pytest tests/test_modulo_ml.py -q` |

- Traffic light: red if probability ≥ 0.6, yellow if ≥ `umbral_decision`, green otherwise. Reference: data up to 2026-05-28 (day before E4) → 0.331, yellow; up to 2026-11-13 → 0.056, green.
- Classes: categorical, nearest-neighbour resampling, NoData 255; classes 2, 4 and 8 (flood evidence) drawn more opaque.
- Probability: 0–100 %, NoData 255, drawn only above `umbral_alerta_pct` (2, the top 5 % of cells).
- Layer order: classes (on), alert zones (on), probability (off).
- The `.joblib` files need scikit-learn 1.9.1.
- Every layer carries `visor.ficha.v1` metadata with `estado = real_sin_validar` and SHA-256: show it as **REAL, NOT VALIDATED**.

## What the app can and cannot say

| Can say | Cannot say |
|---|---|
| "Probability that the Atrato at Quibdó exceeds 497 cm in the next 3 days: X %." | "Quibdó will flood." |
| "On E6, unseen by the model, it found 81.7 % of the flooded 2 km zones and cleared 86 % of the dry ones." | "There are X hectares flooded." |
| "About 17 of every 100 zones in alert flooded in E6." | "This zone is safe." |
| "Classes come from NISAR radar only, without field verification." | Calling anything "validated". |
