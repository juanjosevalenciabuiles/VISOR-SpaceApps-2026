# Training results

Source: `_ml_entrenamiento/entrenamiento_prediccion_inundaciones.ipynb` and `_ml_entrenamiento/salidas/`.

## Model A · when (high water at Quibdó, 3 days ahead)

- Label: Quibdó daily level above the 2006–2018 90th percentile (497 cm) in the next 3 days.
- Split by time: train 2006–2018, tune 2019–2021, test 2022–2026.
- 6 models × 3 feature sets: (1) Quibdó IDEAM + ONI, (2) + GloFAS discharge today, (3) + GloFAS 3-day forecast.

Test results, feature set 2:

| Model | PR-AUC | ROC-AUC | Detection (POD) | False alarms (FAR) | CSI |
|---|---|---|---|---|---|
| **Random Forest** | **0.478** | **0.776** | **0.52** | 0.53 | **0.33** |
| Logistic regression | 0.468 | 0.771 | 0.65 | 0.62 | 0.31 |
| Neural network (MLP) | 0.457 | 0.762 | 0.66 | 0.64 | 0.30 |
| LightGBM | 0.440 | 0.757 | 0.49 | 0.58 | 0.29 |
| HistGradientBoosting | 0.436 | 0.746 | 0.58 | 0.63 | 0.29 |
| XGBoost | 0.420 | 0.748 | 0.67 | 0.69 | 0.27 |
| Rule "today's level" | 0.516 | 0.772 | 0.33 | 0.39 | 0.27 |

- Random Forest had the best validation score of the 6 models and the best CSI in the test.
- Against the "today's level" rule it ranks days about as well (ROC-AUC 0.776 vs 0.772) but catches more high-water days (52 % vs 33 %), at the cost of more false alarms.
- Adding the GloFAS forecast (set 3) raises ROC-AUC to about 0.80: forecast rain or discharge is what is missing.
- Predicting the exact start of a flood is much harder: PR-AUC ≤ 0.32 for every model.

2026 events (highest probability in the 3 days before; decision threshold ≈ 0.33):

| Event | Place | Probability | Max level | Above 497 cm |
|---|---|---|---|---|
| E1 | Murindó | 0.43 | 510 cm | Yes |
| E2 | Vigía del Fuerte | 0.22 | 469 cm | No |
| E3 | Río Quito | 0.09 | 512 cm | Yes (missed) |
| E4 | Quibdó | 0.33 | 545 cm | Yes |
| E5 | Middle Atrato | 0.09 | 253 cm | No |
| E6 | Quibdó | 0.09 | 478 cm | No |

## Model B · where (new water in the next NISAR pass, 40 m)

- 18 pass pairs, 329,679 training cells: all new-flood cells and 6 negatives per positive, half of them near water.
- Label: new open water or new flooded vegetation (classes 2 + 4) at *t+1*.
- Two validations: spatial (10 km blocks, all dates mixed) and by event (trained before E6, tested on E6).

| Model | PR-AUC spatial | PR-AUC E6 | ROC-AUC E6 |
|---|---|---|---|
| **XGBoost** | 0.876 | **0.622** | **0.934** |
| HistGradientBoosting | 0.877 | 0.614 | 0.928 |
| Random Forest | 0.864 | 0.583 | 0.932 |
| LightGBM | 0.880 | 0.577 | 0.902 |
| Logistic regression | 0.701 | 0.536 | 0.872 |
| Neural network (MLP) | 0.870 | 0.328 | 0.777 |
| Terrain rule (HAND + distance to water) | 0.363 | 0.406 | 0.891 |
| Persistence | 0.115 | 0.145 | 0.523 |

- With dates mixed the task looks easy (PR-AUC ≈ 0.88); a new event is the honest test, and XGBoost was the best there.
- These numbers are on the training sample. On the full E6 map (A_T148) new flood is ≈ 0.1 % of the cells, so the map is read as a ranking:

| Cells flagged | XGBoost | Terrain rule | Persistence |
|---|---|---|---|
| Top 1 % | 23 % of new flood | 1 % | 1 % |
| Top 5 % | 42 % | 31 % | 5 % |
| Top 10 % | 61 % | 46 % | 21 % |

## Figures

`_ml_entrenamiento/salidas/`: `A_comparacion_pr_auc.png`, `A_anticipacion.png`, `A_eventos_2026.png`, `B_comparacion_e_importancia.png`, `B_mapa_E6_A_T148.png`, `grafica_aciertos.png`.
