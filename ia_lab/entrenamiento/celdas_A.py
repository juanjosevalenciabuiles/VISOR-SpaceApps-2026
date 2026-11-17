# ========================================
# celdas_A.py
# ========================================

# %% [markdown]
# # V.I.S.O.R. · Flood prediction in the middle Atrato (Chocó)

# %%
import os, json, time, hashlib, warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import joblib
import xgboost as xgb
import lightgbm as lgb
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (roc_auc_score, average_precision_score, brier_score_loss,
                             f1_score, precision_recall_curve)

warnings.filterwarnings("ignore")
plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False})

DIR_ML = Path(os.environ.get("DIR_ML", Path.cwd())).resolve()
DIR_CLIMA, DIR_INS, DIR_OUT = DIR_ML / "clima", DIR_ML / "insumos", DIR_ML / "salidas"
DIR_OUT.mkdir(parents=True, exist_ok=True)
SEMILLA = 42
print("Carpeta de trabajo:", DIR_ML)
for d in (DIR_CLIMA / "ideam_resume", DIR_CLIMA / "condiciones", DIR_INS / "sar40", DIR_INS / "clases", DIR_INS / "terreno"):
    print(f"  {'OK ' if d.exists() else 'FALTA'}  {d.relative_to(DIR_ML)}")

# %% [markdown]
# ## Common functions: models and metrics

# %%
def crear_modelos(peso_pos):
    imp = lambda: SimpleImputer(strategy="median", add_indicator=True)
    return {
        "Regresión logística": make_pipeline(imp(), StandardScaler(),
                                             LogisticRegression(max_iter=3000, C=0.5, class_weight="balanced")),
        "Random Forest": make_pipeline(imp(), RandomForestClassifier(
            n_estimators=300, min_samples_leaf=5, max_features="sqrt", class_weight="balanced_subsample",
            n_jobs=-1, random_state=SEMILLA)),
        "HistGradientBoosting": HistGradientBoostingClassifier(
            max_iter=400, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0,
            class_weight="balanced", early_stopping=False, random_state=SEMILLA),
        "XGBoost": xgb.XGBClassifier(
            n_estimators=500, learning_rate=0.03, max_depth=5, subsample=0.8, colsample_bytree=0.8,
            min_child_weight=3, scale_pos_weight=peso_pos, eval_metric="aucpr", n_jobs=-1, random_state=SEMILLA),
        "LightGBM": lgb.LGBMClassifier(
            n_estimators=500, learning_rate=0.03, num_leaves=31, subsample=0.8, subsample_freq=1,
            colsample_bytree=0.8, min_child_samples=20, scale_pos_weight=peso_pos, random_state=SEMILLA, verbose=-1),
        "Red neuronal (MLP)": make_pipeline(imp(), StandardScaler(), MLPClassifier(
            hidden_layer_sizes=(64, 32), alpha=1e-3, learning_rate_init=1e-3, max_iter=400,
            early_stopping=True, n_iter_no_change=20, random_state=SEMILLA)),
    }


def umbral_max_f1(y, p):
    prec, rec, umb = precision_recall_curve(y, p)
    f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-12)
    i = int(np.nanargmax(f1[:-1])) if len(umb) else 0
    return float(umb[i]) if len(umb) else 0.5


def metricas(y, p, umbral):
    y = np.asarray(y).astype(int); p = np.asarray(p, float); yhat = p >= umbral
    tp = int((yhat & (y == 1)).sum()); fp = int((yhat & (y == 0)).sum()); fn = int((~yhat & (y == 1)).sum())
    return {
        "ROC_AUC": roc_auc_score(y, p) if 0 < y.sum() < len(y) else np.nan,
        "PR_AUC": average_precision_score(y, p) if y.sum() else np.nan,
        "F1": f1_score(y, yhat, zero_division=0),
        "POD": tp / (tp + fn) if tp + fn else np.nan,
        "FAR": fp / (tp + fp) if tp + fp else np.nan,
        "CSI": tp / (tp + fp + fn) if tp + fp + fn else np.nan,
        "Brier": brier_score_loss(y, np.clip(p, 0, 1)),
        "umbral": umbral,
    }

# %% [markdown]
# # Part A · Hydrological model: when does it flood?
# ## A1. IDEAM, GloFAS and ONI data

# %%
t0 = time.time()
RUTA_IDEAM = DIR_CLIMA / "ideam_resume" / "ideam_historico_diario.csv"
if not RUTA_IDEAM.exists():
    RUTA_IDEAM = RUTA_IDEAM.with_suffix(".csv.gz")
ideam = pd.read_csv(RUTA_IDEAM, dtype={"codigo": str},
                    usecols=["codigo", "estacion", "variable", "fecha", "valor"], parse_dates=["fecha"])
ideam["nombre"] = ideam["estacion"].fillna("cod_" + ideam["codigo"])
INICIO, FIN = pd.Timestamp("2006-01-01"), ideam["fecha"].max()
dias = pd.date_range(INICIO, FIN, freq="D")

niveles = ideam[ideam.variable == "NV_MEDIA_D"].pivot_table(index="fecha", columns="nombre", values="valor").reindex(dias)
caudales = ideam[ideam.variable == "Q_MEDIA_D"].pivot_table(index="fecha", columns="nombre", values="valor").reindex(dias)

glofas = pd.read_csv(DIR_CLIMA / "ideam_resume" / "glofas_caudal_diario.csv", parse_dates=["fecha"])
glofas = glofas.pivot_table(index="fecha", columns="estacion", values="caudal_m3s").reindex(dias)

oni = pd.read_csv(DIR_CLIMA / "ideam_resume" / "oni_mensual.csv", parse_dates=["fecha"]).set_index("fecha")["oni"]
oni = oni.reindex(pd.date_range(oni.index.min(), FIN, freq="D")).ffill().reindex(dias)

cobertura = niveles.notna().mean().sort_values(ascending=False)
EST_NIVEL = [e for e in cobertura.index if cobertura[e] >= 0.60 or e == "Quibdo"]
EST_GLOFAS = ["Quibdo", "Belen_AUT", "El_Siete_AUT", "Bellavista", "Puente_Certegui", "Bagado_AUT"]
print(f"IDEAM {ideam.fecha.min().date()} → {FIN.date()} · {ideam.nombre.nunique()} estaciones")
print("Cobertura 2006-2026 de nivel:", (cobertura.round(2)).to_dict())
print("Estaciones de nivel usadas:", EST_NIVEL)
deriva = pd.DataFrame({"media_2006_2018": niveles[EST_NIVEL].loc["2006":"2018"].mean(),
                       "media_2022_2026": niveles[EST_NIVEL].loc["2022":"2026"].mean()})
deriva["cambio_cm"] = deriva.media_2022_2026 - deriva.media_2006_2018
print("\nCambio del nivel medio entre periodos (cm). Cambios grandes = posible cambio de cero de la mira o del cauce:")
print(deriva.round(0).astype(int).to_string())
print(f"GloFAS {glofas.dropna(how='all').index.min().date()} → {glofas.dropna(how='all').index.max().date()}")
print(f"({time.time() - t0:.1f} s)")

# %% [markdown]
# ## A2. Label: high water at Quibdó in the next *H* days

# %%
H = 3
ESTACION = "Quibdo"
q = niveles[ESTACION].ffill(limit=2)
ENTRENA, VALIDA = ("2006-01-01", "2018-12-31"), ("2019-01-01", "2021-12-31")
PRUEBA = ("2022-01-01", str(FIN.date()))
UMBRAL_NIVEL = float(q.loc[ENTRENA[0]:ENTRENA[1]].quantile(0.90))


def etiqueta(serie, h, umbral):
    fut = pd.concat([serie.shift(-k) for k in range(1, h + 1)], axis=1)
    y = (fut.max(axis=1) >= umbral).astype(float)
    y[fut.isna().all(axis=1)] = np.nan
    return y


y_A = etiqueta(q, H, UMBRAL_NIVEL)
print(f"Umbral de nivel alto en {ESTACION}: {UMBRAL_NIVEL:.0f} cm (P90 2006–2018)")
print(f"Días con y=1: {int(y_A.sum())} de {int(y_A.notna().sum())} ({y_A.mean():.1%})")

fig, ax = plt.subplots(figsize=(11, 3))
ax.plot(q.index, q, lw=0.6, color="#3b6ea5")
ax.axhline(UMBRAL_NIVEL, color="#d62728", lw=1, ls="--", label=f"P90 = {UMBRAL_NIVEL:.0f} cm")
ax.axvspan(pd.Timestamp(VALIDA[0]), pd.Timestamp(VALIDA[1]), color="#e3a21a", alpha=0.12, label="validación")
ax.axvspan(pd.Timestamp(PRUEBA[0]), pd.Timestamp(PRUEBA[1]), color="#2ca02c", alpha=0.10, label="prueba")
ax.set_ylabel("nivel (cm)"); ax.set_title("Río Atrato en Quibdó (IDEAM, nivel medio diario)"); ax.legend(loc="upper left", ncol=3, fontsize=8)
plt.tight_layout(); plt.savefig(DIR_OUT / "A_nivel_quibdo.png"); plt.show()

# %% [markdown]
# ## A3. Features

# %%
def rasgos_quibdo(s):
    s = s.ffill(limit=2)
    d = {f"q_l{k}": s.shift(k) for k in range(7)}
    d.update(q_d1=s - s.shift(1), q_d3=s - s.shift(3),
             q_m7=s.rolling(7, min_periods=4).mean(), q_x7=s.rolling(7, min_periods=4).max(),
             q_m30=s.rolling(30, min_periods=15).mean())
    return pd.DataFrame(d)


tr = q.loc[ENTRENA[0]:ENTRENA[1]]
clim = tr.groupby(tr.index.dayofyear).mean().reindex(range(1, 367)).interpolate().bfill().ffill()
doy = dias.dayofyear.values
X_q = rasgos_quibdo(q)
X_q["q_anom"] = q - clim.reindex(doy).values
X_q["oni"] = oni.values
X_q["doy_sin"], X_q["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)

X_gf_hoy = pd.concat([pd.DataFrame({f"gf_{e}": glofas[e], f"gf_{e}_d1": glofas[e] - glofas[e].shift(1)})
                      for e in EST_GLOFAS], axis=1)


def gf_pronostico(h):
    return pd.concat([pd.DataFrame({f"gfP_{e}_t{k}": glofas[e].shift(-k) for k in range(1, h + 1)})
                      for e in ("Quibdo", "Belen_AUT", "El_Siete_AUT")], axis=1)


def conjuntos(h):
    return {"1 · Quibdó IDEAM + ONI": X_q,
            "2 · + GloFAS hoy": pd.concat([X_q, X_gf_hoy], axis=1),
            "3 · + pronóstico GloFAS (techo)": pd.concat([X_q, X_gf_hoy, gf_pronostico(h)], axis=1)}


for k, v in conjuntos(H).items():
    print(f"{k:<34} {v.shape[1]:>3} variables")

# %% [markdown]
# ## A4. Training and comparison of the 6 models

# %%
FIN_COMUN = "2026-06-30"


def partir(X, y, fin_prueba=FIN_COMUN, solo_bajo=False):
    ok = y.notna() & q.notna()
    if solo_bajo:
        ok &= q < UMBRAL_NIVEL
    X, y = X[ok], y[ok].astype(int)
    tramo = lambda a, b: (X.index >= pd.Timestamp(a)) & (X.index <= pd.Timestamp(b))
    return [(X[tramo(*r)], y[tramo(*r)]) for r in (ENTRENA, VALIDA, (PRUEBA[0], fin_prueba))]


def comparar(h, tareas=("nivel alto", "inicio de crecida"), nombres_mod=None, guardar=False):
    yh = etiqueta(q, h, UMBRAL_NIVEL)
    filas = []
    for tarea in tareas:
        for nombre_conj, X in conjuntos(h).items():
            (Xe, ye), (Xv, yv), (Xp, yp) = partir(X, yh, solo_bajo=(tarea == "inicio de crecida"))
            base = metricas(yp, Xp["q_l0"].values / UMBRAL_NIVEL / 2, 0.5) if tarea == "nivel alto" else \
                metricas(yp, Xp["q_l0"].values / UMBRAL_NIVEL, umbral_max_f1(yv, Xv["q_l0"].values / UMBRAL_NIVEL))
            base.update(tarea=tarea, conjunto=nombre_conj, modelo="Línea base (nivel de hoy)", H=h, Brier=np.nan,
                        PR_AUC_valida=average_precision_score(yv, Xv["q_l0"]))
            filas.append(base)
            peso = float((ye == 0).sum() / max((ye == 1).sum(), 1))
            for nombre_mod, mod in crear_modelos(peso).items():
                if nombres_mod and nombre_mod not in nombres_mod:
                    continue
                mod.fit(Xe, ye)
                pv, pp = mod.predict_proba(Xv)[:, 1], mod.predict_proba(Xp)[:, 1]
                u = umbral_max_f1(yv, pv)
                m = metricas(yp, pp, u)
                m.update(tarea=tarea, conjunto=nombre_conj, modelo=nombre_mod, H=h,
                         PR_AUC_valida=average_precision_score(yv, pv))
                filas.append(m)
                if guardar:
                    MODELOS_A[(tarea, nombre_conj, nombre_mod)] = {"modelo": mod, "umbral": u, "pv": pv, "yv": yv.values,
                                                                   "pp": pp, "yp": yp.values, "fechas_p": yp.index}
            print(f"  H={h} · {tarea:<17} · {nombre_conj:<32} entrena {len(ye):>5} ({ye.mean():.0%} +) · "
                  f"valida {len(yv)} · prueba {len(yp)} ({yp.mean():.0%} +)")
    return pd.DataFrame(filas)


MODELOS_A = {}
t0 = time.time()
tabla_A = comparar(H, guardar=True)
cols = ["tarea", "conjunto", "modelo", "PR_AUC", "ROC_AUC", "F1", "POD", "FAR", "CSI", "Brier", "PR_AUC_valida"]
tabla_A = tabla_A[cols].sort_values(["tarea", "conjunto", "PR_AUC_valida"], ascending=[False, True, False])
tabla_A.to_csv(DIR_OUT / f"A_comparacion_modelos_H{H}.csv", index=False)
print(f"({time.time() - t0:.0f} s)")
tabla_A.round(3)

# %% [markdown]
# ### Comparison plot

# %%
fig, axs = plt.subplots(1, 2, figsize=(12, 4), sharex=False)
for ax, tarea in zip(axs, ["nivel alto", "inicio de crecida"]):
    t = tabla_A[tabla_A.tarea == tarea].pivot_table(index="modelo", columns="conjunto", values="PR_AUC")
    t = t.loc[t.mean(axis=1).sort_values().index]
    t.plot.barh(ax=ax, width=0.8, color=["#8fb3d9", "#3b6ea5", "#c9a227"])
    ax.set_title(f"{tarea} · H={H} días"); ax.set_xlabel("PR-AUC en prueba (2022–2026)"); ax.set_ylabel("")
    ax.legend(fontsize=7, loc="lower right")
plt.tight_layout(); plt.savefig(DIR_OUT / "A_comparacion_pr_auc.png"); plt.show()

# %% [markdown]
# ## A5. Lead time: H = 1, 3, 5 and 7 days

# %%
t0 = time.time()
tabla_H = pd.concat([comparar(h, tareas=("inicio de crecida",),
                              nombres_mod=("Regresión logística", "Random Forest", "LightGBM", "Red neuronal (MLP)"))
                     for h in (1, 3, 5, 7)])
tabla_H = tabla_H[tabla_H.conjunto != "3 · + pronóstico GloFAS (techo)"]
tabla_H.to_csv(DIR_OUT / "A_anticipacion.csv", index=False)
fig, ax = plt.subplots(figsize=(7, 3.5))
for (conj, mod), g in tabla_H[tabla_H.conjunto == "2 · + GloFAS hoy"].groupby(["conjunto", "modelo"]):
    ax.plot(g.H, g.PR_AUC, marker="o", label=mod)
ax.set_xlabel("días de anticipación (H)"); ax.set_ylabel("PR-AUC en prueba"); ax.set_xticks([1, 3, 5, 7])
ax.set_title("Inicio de crecida en Quibdó · conjunto 2"); ax.legend(fontsize=8)
plt.tight_layout(); plt.savefig(DIR_OUT / "A_anticipacion.png"); plt.show()
print(f"({time.time() - t0:.0f} s)")
tabla_H.pivot_table(index=["conjunto", "modelo"], columns="H", values="PR_AUC").round(3)

# %% [markdown]
# ## A6. Selected model, calibration and check against the 2026 events

# %%
def elegir(tarea, conjunto):
    t = tabla_A[(tabla_A.tarea == tarea) & (tabla_A.conjunto == conjunto) & (~tabla_A.modelo.str.startswith("Línea"))]
    return t.sort_values("PR_AUC_valida", ascending=False).iloc[0]["modelo"]


ELEGIDOS = {}
for clave, conj in [("operativo", "2 · + GloFAS hoy"), ("con_pronostico", "3 · + pronóstico GloFAS (techo)"),
                    ("solo_ideam", "1 · Quibdó IDEAM + ONI")]:
    nombre = elegir("nivel alto", conj)
    r = MODELOS_A[("nivel alto", conj, nombre)]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(r["pv"], r["yv"])
    pp_cal = iso.predict(r["pp"])
    u_cal = umbral_max_f1(r["yv"], iso.predict(r["pv"]))
    m = metricas(r["yp"], pp_cal, u_cal)
    variables = list(conjuntos(H)[conj].columns)
    paquete = {"modelo": r["modelo"], "calibrador": iso, "umbral_decision": u_cal, "variables": variables,
               "H_dias": H, "estacion": ESTACION, "umbral_nivel_cm": UMBRAL_NIVEL, "conjunto": conj, "nombre": nombre,
               "entrenado": ENTRENA, "validado": VALIDA, "metricas_prueba": m,
               "climatologia_doy": clim.values.tolist(), "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    joblib.dump(paquete, DIR_OUT / f"modeloA_{clave}.joblib")
    ELEGIDOS[clave] = paquete
    print(f"{clave:<15} {nombre:<22} {conj:<32} PR-AUC {m['PR_AUC']:.3f} · ROC {m['ROC_AUC']:.3f} · CSI {m['CSI']:.3f} · "
          f"Brier calibrado {m['Brier']:.3f} · umbral {u_cal:.2f}")

pk = ELEGIDOS["solo_ideam"]
Xs = conjuntos(H)[pk["conjunto"]][pk["variables"]]
ok = q.notna()
prob = pd.Series(pk["calibrador"].predict(pk["modelo"].predict_proba(Xs[ok])[:, 1]), index=Xs[ok].index)
clima_ev = pd.read_csv(DIR_CLIMA / "condiciones" / "2_datos_nasa_clima_eventos.csv", parse_dates=["fecha"])
eventos = clima_ev.groupby("evento_id").agg(lugar=("municipio_id", "first"), fecha=("fecha", "min"),
                                           lluvia_7d_max_mm=("lluvia_7d_mm", "max"), humedad_raiz=("humedad_raiz_nasa", "max"))
filas = []
for ev, r in eventos.iterrows():
    f = r.fecha
    filas.append({"evento": ev, "lugar": r.lugar, "fecha": f.date(), "lluvia_7d_max_mm": r.lluvia_7d_max_mm,
                  "prob_max_3d_antes": prob.loc[f - pd.Timedelta(days=3): f - pd.Timedelta(days=1)].max(),
                  "nivel_max_Quibdo_cm_en_evento": q.loc[f: f + pd.Timedelta(days=3)].max(),
                  "supera_P90": bool(q.loc[f: f + pd.Timedelta(days=3)].max() >= UMBRAL_NIVEL)})
verif = pd.DataFrame(filas)
verif.to_csv(DIR_OUT / "A_verificacion_eventos_2026.csv", index=False)

fig, ax1 = plt.subplots(figsize=(11, 3.4))
ax1.plot(q.loc["2026-01-01":].index, q.loc["2026-01-01":], color="#3b6ea5", lw=1, label="nivel Quibdó")
ax1.axhline(UMBRAL_NIVEL, color="#d62728", ls="--", lw=0.8)
ax2 = ax1.twinx(); ax2.fill_between(prob.loc["2026-01-01":].index, prob.loc["2026-01-01":], color="#c9a227", alpha=0.35, label=f"prob. nivel alto en {H} d")
ax2.set_ylim(0, 1); ax2.set_ylabel("probabilidad")
for _, r in verif.iterrows():
    ax1.axvline(pd.Timestamp(r.fecha), color="k", lw=0.6, ls=":"); ax1.text(pd.Timestamp(r.fecha), ax1.get_ylim()[1] * 0.97, r.evento, fontsize=8)
ax1.set_ylabel("nivel (cm)"); ax1.set_title("2026: nivel observado, probabilidad del modelo y eventos E1–E6")
plt.tight_layout(); plt.savefig(DIR_OUT / "A_eventos_2026.png"); plt.show()
verif.round(2)
