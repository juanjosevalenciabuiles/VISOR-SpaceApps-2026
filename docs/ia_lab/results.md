# Results and decisions

V.I.S.O.R. · NASA Space Apps Challenge 2026 · Dancing with the SARs · Middle Atrato (Chocó)

## Decisions

| Piece | Choice | Why |
|---|---|---|
| Labeling | NISAR only: Lee 5×5 → K-means → GMM per stack, relative mapping (Otsu for water, scene forest as anchor), consensus and rules for permanent water, permanent flooded vegetation and urban. 9 classes + "doubtful" | Complete for the 4 stacks and 22 dates, runs offline. Optical data is mostly blocked by clouds: Sentinel-2 had 0–7 % cloud-free pixels in the E6 scenes |
| Model A · when | Random Forest with isotonic calibration. Quibdó IDEAM gauges + GloFAS discharge + ONI. Lead time 3 days (`salidas/modeloA_operativo.joblib`) | Best of 6 models in validation (2019–2021) |
| Model B · where | XGBoost on 40 m cells: NISAR radar and classes at *t*, terrain (HAND, DEM, slope, WorldCover) and river level (`salidas/modeloB_espacial.joblib`) | Best of 6 models on the unseen event E6 (PR-AUC 0.62, ROC-AUC 0.93) |
| App | Observed (NISAR classes), probable (top 5 % cells of Model B), decision (2 km zones in alert) and a traffic light (Model A) | Each layer answers a different question |

## What was done

- NISAR L2 GCOV (HH, HV): 4 stacks (A_T047, A_T148, D_T011, D_T112), 22 dates Jun–Sep 2026 + 1 beta (Jan), subset and mosaicked at 20 m.
- Unsupervised labeling of the whole area: 22 class maps with `visor.ficha.v1` metadata and a km² series per class.
- Terrain layers: Copernicus DEM, slope, HAND and ESA WorldCover.
- Hydroclimate: IDEAM (31 stations, daily levels and discharge up to 13 Nov 2026), GloFAS (12 points, 2006 → 1 Jul 2026), ONI, NASA rainfall and soil moisture for E1–E6.
- Models A and B: 6 algorithms each, yes/no test on unseen data, layers and Folium demo for the app.

## Test on unseen data

### Model B · will this 2 × 2 km zone flood? (event E6)

Alert rule fixed before looking at labels: a zone is in alert if ≥ 10 % of its cells are in the top 5 % of the swath. A zone is flooded if ≥ 1 % of its area (4 ha) is new flood.

| Model | Accuracy | Balanced accuracy | Detects YES | Correct NO | Zones |
|---|---|---|---|---|---|
| **XGBoost** | 85.8 % | **83.9 %** | **81.7 %** (161/197) | 86.0 % | 5,656 |
| Terrain rule | 84.6 % | 72.7 % | 59.9 % | 85.5 % | 5,656 |

Per orbit pair, XGBoost balanced accuracy: 84.6 % (A_T148), 85.7 % (D_T011), 74.3 % (D_T112). About 17 of every 100 zones in alert flooded: use it to prioritize where to look.

### Model A · will the Atrato at Quibdó exceed 497 cm? (days 2022 – Jun 2026)

| Lead time | Model | Accuracy | Balanced accuracy | Detects YES | Correct NO | ROC-AUC |
|---|---|---|---|---|---|---|
| 1 day | Random Forest | 90.3 % | 74.1 % | 54.2 % | 94.0 % | 0.90 |
| | Rule "today's level" | 91.5 % | 74.8 % | 54.2 % | 95.3 % | — |
| **3 days** | **Random Forest** | 81.4 % | **69.7 %** | **51.9 %** | 87.5 % | 0.77 |
| | Rule "today's level" | 84.8 % | 64.3 % | 33.0 % | 95.7 % | — |
| 7 days | Random Forest | 57.6 % | 63.7 % | 79.6 % | 47.9 % | 0.70 |

Moderate skill. With the GloFAS 3-day discharge forecast, ROC-AUC rises from 0.77 to 0.80. In 2026, E1 and E4 were flagged 1–3 days ahead; E3 was missed (probability 0.09, river at 512 cm); in E6 the river stayed below the threshold (478 cm, urban rainfall).

## Limitations

- Labels come from unsupervised NISAR labeling, not field truth.
- Few NISAR dates: 18 pass pairs (Jun–Sep 2026); A_T047 has no new-flood cells.
- No daily rainfall forecast for Model A.
- Gauges with drift (El Siete, Bellavista, Belén) were left out.
- NISAR products are provisional (1–2 dB banding); flooding under very dense forest is underestimated.

## Next steps

1. Feed the GloFAS discharge forecast to Model A (`modeloA_con_pronostico.joblib`).
2. Add daily rainfall (IMERG or CHIRPS) and retrain Model A.
3. Validate alert zones with UNGRD or IDEAM reports.
