# ========================================
# prueba_si_no.py
# ========================================

import os, json, time, warnings
from pathlib import Path
import numpy as np, pandas as pd, joblib
from sklearn.metrics import roc_auc_score, confusion_matrix
warnings.filterwarnings("ignore")
DIR_ML = Path(os.environ.get("DIR_ML", Path.cwd())).resolve()
DIR_OUT = DIR_ML / "salidas"

# ========================================
# 0) Notebook definitions (A1-A3 and B1-B3)
# ========================================
src = open(DIR_ML / "celdas_A.py", encoding="utf-8").read()
srcB = open(DIR_ML / "celdas_B.py", encoding="utf-8").read()
cortar = lambda s, a, b: s[s.index(a): s.index(b)]
codigo = (cortar(src, "import os, json", "# %% [markdown]\n# ## Common functions")
          + cortar(src, "def crear_modelos", "# %% [markdown]\n# # Part A")
          + cortar(src, "t0 = time.time()\nRUTA_IDEAM", "# %% [markdown]\n# ## A2.")
          + cortar(src, "H = 3\n", "fig, ax = plt.subplots(figsize=(11, 3))")
          + cortar(src, "def rasgos_quibdo", "for k, v in conjuntos(H).items():")
          + cortar(src, "FIN_COMUN = ", "def comparar(")
          + cortar(srcB, "import rasterio", "# %% [markdown]\n# ## B2.")
          + cortar(srcB, "def escenario", "PARES = [")
          + "PARES = [(s, FECHAS[s][i], FECHAS[s][i + 1]) for s in FECHAS for i in range(len(FECHAS[s]) - 1)]\n"
          + cortar(srcB, "VAR_B = None", "t0 = time.time()\npartes = []"))
codigo = codigo.replace("plt.show()", "plt.close()")
exec(codigo)


def tabla_si_no(y, yhat):
    tn, fp, fn, tp = confusion_matrix(y, yhat, labels=[0, 1]).ravel()
    return {"aciertos_%": 100 * (tp + tn) / len(y),
            "aciertos_balanceados_%": 50 * (tp / max(tp + fn, 1) + tn / max(tn + fp, 1)),
            "detecta_SI_%": 100 * tp / max(tp + fn, 1), "acierta_NO_%": 100 * tn / max(tn + fp, 1),
            "falsas_alarmas_%": 100 * fp / max(tp + fp, 1),
            "VP": int(tp), "FN": int(fn), "FP": int(fp), "VN": int(tn), "n": int(len(y))}


resultados = {}
SOLO_B = os.environ.get('SOLO_B') == '1'

# ========================================
# 1) MODEL A · Will Quibdó reach flood level?
# ========================================
filas = []
for h in ((1, 3, 7) if not SOLO_B else ()):
    yh = etiqueta(q, h, UMBRAL_NIVEL)
    X2 = conjuntos(h)["2 · + GloFAS hoy"]
    (Xe, ye), (Xv, yv), (Xp, yp) = partir(X2, yh)
    if h == 3:
        pk = joblib.load(DIR_OUT / "modeloA_operativo.joblib")
        pv = pk["calibrador"].predict(pk["modelo"].predict_proba(Xv[pk["variables"]])[:, 1])
        pp = pk["calibrador"].predict(pk["modelo"].predict_proba(Xp[pk["variables"]])[:, 1])
        u = pk["umbral_decision"]
    else:
        peso = float((ye == 0).sum() / max((ye == 1).sum(), 1))
        mod = crear_modelos(peso)["Random Forest"].fit(Xe, ye)
        pv, pp = mod.predict_proba(Xv)[:, 1], mod.predict_proba(Xp)[:, 1]
        u = umbral_max_f1(yv, pv)
    r = tabla_si_no(yp.values, pp >= u); r.update(H=h, modelo="Random Forest (Modelo A)", ROC_AUC=roc_auc_score(yp, pp))
    filas.append(r)
    hoy = Xp["q_l0"].values >= UMBRAL_NIVEL
    r = tabla_si_no(yp.values, hoy); r.update(H=h, modelo="Regla: nivel de hoy ≥ umbral", ROC_AUC=np.nan); filas.append(r)
    r = tabla_si_no(yp.values, np.zeros(len(yp), bool)); r.update(H=h, modelo="Siempre 'no'", ROC_AUC=np.nan); filas.append(r)
tA = pd.read_csv(DIR_OUT / "PRUEBA_A_si_no_diario.csv") if SOLO_B else pd.DataFrame(filas)[["H", "modelo", "aciertos_%", "aciertos_balanceados_%", "detecta_SI_%", "acierta_NO_%",
                          "falsas_alarmas_%", "ROC_AUC", "VP", "FN", "FP", "VN", "n"]]
tA.to_csv(DIR_OUT / "PRUEBA_A_si_no_diario.csv", index=False)
print("\n=== MODELO A · días de prueba 2022-01-01 → 2026-06-30 ===")
print(tA.round(1).to_string(index=False))

yh7 = etiqueta(q, 7, UMBRAL_NIVEL)
X2 = conjuntos(7)["2 · + GloFAS hoy"]
(Xe, ye), (Xv, yv), (Xp, yp) = partir(X2, yh7)
peso = float((ye == 0).sum() / max((ye == 1).sum(), 1))
mod7 = crear_modelos(peso)["Random Forest"].fit(Xe, ye)
u7 = umbral_max_f1(yv, mod7.predict_proba(Xv)[:, 1])
lunes = Xp.index.dayofweek == 0
p7 = mod7.predict_proba(Xp[lunes])[:, 1]
rs = tabla_si_no(yp[lunes].values, p7 >= u7); rs.update(ROC_AUC=roc_auc_score(yp[lunes], p7))
rb = tabla_si_no(yp[lunes].values, Xp[lunes]["q_l0"].values >= UMBRAL_NIVEL)
print("\n=== MODELO A · semanal (cada lunes: ¿nivel alto en los próximos 7 días?) ===")
print(pd.DataFrame([dict(modelo="Random Forest", **rs), dict(modelo="Regla nivel de hoy", **rb)]).round(1).to_string(index=False))
resultados["A_semanal"] = {"modelo": rs, "regla": rb}

# ========================================
# 2) MODEL B · Will this 2 × 2 km zone flood in the next NISAR pass?
# ========================================
pkB = joblib.load(DIR_OUT / "modeloB_espacial.joblib")
modB, VARS = pkB["modelo"], pkB["variables"]
LADO = 50
FRAC_MIN = 0.01


def zonas(stack, t, t1):
    cache = {"sar": {d: sar40(stack, d) for d in FECHAS[stack]}, "cl": {d: clases40(stack, d) for d in FECHAS[stack]}}
    d = rasgos_par(stack, t, t1, cache, todo=True)
    p = np.concatenate([modB.predict_proba(d[VARS].iloc[i:i + 500_000])[:, 1] for i in range(0, len(d), 500_000)])
    regla = (1 / (1 + d.HAND.fillna(50).clip(0))) * np.exp(-d.d_agua_km.values / 2)
    z = pd.DataFrame({"zf": d.fila.values // LADO, "zc": d.col.values // LADO, "y": d.y.values,
                      "alerta_mod": p >= np.quantile(p, 0.95), "alerta_reg": regla >= np.quantile(regla, 0.95), "p": p})
    g = z.groupby(["zf", "zc"]).agg(n=("y", "size"), frac=("y", "mean"), f_mod=("alerta_mod", "mean"),
                                   f_reg=("alerta_reg", "mean"), p_media=("p", "mean"))
    g = g[g.n >= LADO * LADO * 0.5]
    g["si"] = (g.frac >= FRAC_MIN).astype(int)
    return g


t0 = time.time()
filasB = []
for stack, t, t1 in [("A_T148", "2026-08-11", "2026-09-04"), ("D_T011", "2026-08-13", "2026-09-06"), ("D_T112", "2026-08-20", "2026-09-01")]:
    g = zonas(stack, pd.Timestamp(t), pd.Timestamp(t1))
    for nombre, col in [("XGBoost (Modelo B)", "f_mod"), ("Regla de terreno", "f_reg")]:
        r = tabla_si_no(g.si.values, g[col].values >= 0.10)
        r.update(par=f"{stack} {t[5:]} → {t1[5:]}", modelo=nombre, ROC_AUC=roc_auc_score(g.si, g[col]))
        filasB.append(r)
    print(f"  {stack} listo ({time.time() - t0:.0f} s)")
g_all = pd.DataFrame(filasB)
for nombre in g_all.modelo.unique():
    s_ = g_all[g_all.modelo == nombre][["VP", "FN", "FP", "VN"]].sum()
    tp, fn, fp, tn = s_.VP, s_.FN, s_.FP, s_.VN
    filasB.append({"par": "TOTAL E6", "modelo": nombre, "aciertos_%": 100 * (tp + tn) / (tp + fn + fp + tn),
                   "aciertos_balanceados_%": 50 * (tp / (tp + fn) + tn / (tn + fp)), "detecta_SI_%": 100 * tp / (tp + fn),
                   "acierta_NO_%": 100 * tn / (tn + fp), "falsas_alarmas_%": 100 * fp / max(tp + fp, 1), "ROC_AUC": np.nan,
                   "VP": tp, "FN": fn, "FP": fp, "VN": tn, "n": tp + fn + fp + tn})
tB = pd.DataFrame(filasB)[["par", "modelo", "aciertos_%", "aciertos_balanceados_%", "detecta_SI_%", "acierta_NO_%",
                           "falsas_alarmas_%", "ROC_AUC", "VP", "FN", "FP", "VN", "n"]]
tB.to_csv(DIR_OUT / "PRUEBA_B_si_no_zonas_2km.csv", index=False)
print("\n=== MODELO B · zonas de 2 × 2 km en E6 (nunca vistas) ===")
print(tB.round(1).to_string(index=False))
resultados.update({"A_diario": tA.to_dict("records"), "B_zonas": tB.to_dict("records"),
                   "B_regla": "zona SÍ si ≥10 % de sus celdas está en el 5 % más probable de la franja", "B_frac_min": FRAC_MIN, "B_lado_km": LADO * RES / 1000})
(DIR_OUT / "PRUEBA_si_no.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
