# ========================================
# celdas_B.py
# ========================================

# %% [markdown]
# # Part B · NISAR spatial model: where does it flood?
# ## B0. (Optional) Downsample the subsets to 40 m

# %%
REDUCIR = False
DIR_RECORTES = DIR_ML.parent / "recortes"


def reducir_recortes(dir_recortes, dir_salida):
    dir_salida.mkdir(parents=True, exist_ok=True)
    for r in sorted(Path(dir_recortes).glob("[AD]_T*/2026-*/*.npz")):
        stack, fecha = r.name[:6], r.name[7:15]
        dst = dir_salida / f"{stack}_{fecha}_sar40.npz"
        if dst.exists():
            continue
        res = {}
        with np.load(r) as z:
            for b in ("HH", "HV"):
                if b in z.files:
                    a = z[b].astype(np.float32)
                    ny, nx = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
                    with np.errstate(all="ignore"):
                        m = np.nanmean(a[:ny, :nx].reshape(ny // 2, 2, nx // 2, 2), axis=(1, 3))
                        db = 10 * np.log10(np.maximum(m, 1e-3))
                    db[~np.isfinite(m)] = np.nan
                    res[b] = db.astype(np.float16)
        np.savez_compressed(dst, **res)
        print("ok", dst.name)


if REDUCIR:
    reducir_recortes(DIR_RECORTES, DIR_INS / "sar40")

# %% [markdown]
# ## B1. Terrain, classes and radar on the 40 m grid

# %%
import rasterio
from rasterio.transform import from_origin
from scipy import ndimage
from sklearn.model_selection import GroupKFold

X0, Y1, NY20, NX20 = 272_880, 796_440, 9144, 3351
NY, NX, RES = NY20 // 2, NX20 // 2, 40
TRANSF40 = from_origin(X0, Y1, RES, RES)


def a40_media(a):
    a = a[:NY * 2, :NX * 2].astype(np.float32).reshape(NY, 2, NX, 2)
    with np.errstate(all="ignore"):
        return np.nanmean(a, axis=(1, 3))


def leer(ruta):
    with rasterio.open(ruta) as r:
        return r.read(1), r.transform, r.nodata


t0 = time.time()
TER = {}
for nombre in ("HAND", "DEM", "PEND"):
    a, _, nd = leer(DIR_INS / "terreno" / f"{nombre}.tif")
    TER[nombre] = a40_media(np.where(a == nd, np.nan, a) if nd is not None and not np.isnan(nd) else a)
wc, _, _ = leer(DIR_INS / "terreno" / "WORLDCOVER.tif")
TER["WC"] = wc[:NY * 2:2, :NX * 2:2]
print({k: v.shape for k, v in TER.items()}, f"({time.time() - t0:.0f} s)")

FECHAS = {}
for f in sorted((DIR_INS / "clases").glob("*_clases_solo_nisar.tif")):
    stack, fecha = f.name[:6], pd.Timestamp(f.name[7:15])
    if (DIR_INS / "sar40" / f"{stack}_{fecha:%Y%m%d}_sar40.npz").exists():
        FECHAS.setdefault(stack, []).append(fecha)
for s in FECHAS:
    FECHAS[s] = sorted(FECHAS[s])
    print(s, [d.strftime("%m-%d") for d in FECHAS[s]])


def clases40(stack, fecha):
    a, t, _ = leer(DIR_INS / "clases" / f"{stack}_{fecha:%Y%m%d}_clases_solo_nisar.tif")
    full = np.full((NY20, NX20), 255, np.uint8)
    r0, c0 = int(round((Y1 - t.f) / 20)), int(round((t.c - X0) / 20))
    full[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] = a
    b = full[:NY * 2, :NX * 2].reshape(NY, 2, NX, 2)
    cnt = lambda ks: np.isin(b, ks).sum(axis=(1, 3)).astype(np.uint8)
    return {"valido": cnt(range(1, 10)), "c1": cnt([1]), "c2": cnt([2]), "c3": cnt([3]), "c4": cnt([4]),
            "c78": cnt([7, 8]), "c9": cnt([9])}


def sar40(stack, fecha):
    with np.load(DIR_INS / "sar40" / f"{stack}_{fecha:%Y%m%d}_sar40.npz") as z:
        hh = z["HH"].astype(np.float32)
        hv = z["HV"].astype(np.float32) if "HV" in z.files else np.full_like(hh, np.nan)
    return hh, hv

# %% [markdown]
# ## B2. Hydrological scenario for each pair (IDEAM Quibdó)

# %%
def escenario(t, t1):
    tramo = q.loc[t:t1]
    return {"nivel_t": float(q.get(t, np.nan)), "nivel_t1": float(q.get(t1, np.nan)),
            "nivel_max_tramo": float(tramo.max()), "dnivel": float(q.get(t1, np.nan) - q.get(t, np.nan)),
            "nivel_max_rel_P90": float(tramo.max() / UMBRAL_NIVEL), "dias": int((t1 - t).days),
            "oni_t1": float(oni.get(t1, np.nan))}


PARES = [(s, FECHAS[s][i], FECHAS[s][i + 1]) for s in FECHAS for i in range(len(FECHAS[s]) - 1)]
tabla_pares = pd.DataFrame([{"stack": s, "t": t.date(), "t1": t1.date(), **escenario(t, t1)} for s, t, t1 in PARES])
tabla_pares.round(2)

# %% [markdown]
# ## B3. Building the training set

# %%
VAR_B = None
rng = np.random.default_rng(SEMILLA)


def rasgos_par(stack, t, t1, cache, todo=False):
    hh, hv = cache["sar"][t]
    pasadas = [d for d in FECHAS[stack] if d <= t]
    with np.errstate(all="ignore"):
        pila = np.stack([cache["sar"][d][0] for d in pasadas])
        hh_ref, hh_min, hh_max = np.nanmean(pila, 0), np.nanmin(pila, 0), np.nanmax(pila, 0)
    c, c1 = cache["cl"][t], cache["cl"][t1]
    vt = np.maximum(c["valido"], 1).astype(np.float32)
    agua = (c["c1"] + c["c3"]) >= 2
    nueva = (c["c2"] + c["c4"]) >= 2
    d_agua = ndimage.distance_transform_edt(~agua) * RES / 1000 if agua.any() else np.full(agua.shape, 99.0)
    d_nueva = ndimage.distance_transform_edt(~nueva) * RES / 1000 if nueva.any() else np.full(agua.shape, 99.0)
    ok = (c["valido"] >= 2) & (c1["valido"] >= 2) & np.isfinite(hh)
    y = ((c1["c2"] + c1["c4"]) >= 2) & ok
    esc = escenario(t, t1)
    if todo:
        idx = np.flatnonzero(ok.ravel())
    else:
        pos = np.flatnonzero(y.ravel())
        pos = rng.choice(pos, min(len(pos), 15000), replace=False) if len(pos) else pos
        n_neg = max(6 * len(pos), 15000)
        neg_cerca = np.flatnonzero((ok & ~y & (d_agua <= 3)).ravel())
        neg_lejos = np.flatnonzero((ok & ~y & (d_agua > 3)).ravel())
        idx = np.concatenate([pos, rng.choice(neg_cerca, min(len(neg_cerca), n_neg // 2), replace=False),
                              rng.choice(neg_lejos, min(len(neg_lejos), n_neg // 2), replace=False)])
    filas, cols = np.unravel_index(idx, (NY, NX))
    g = lambda a: a.ravel()[idx]
    wcv = g(TER["WC"])
    df = pd.DataFrame({
        "HH": g(hh), "HV": g(hv), "HH_HV": g(hh - hv), "HH_menos_ref": g(hh - hh_ref), "HH_min": g(hh_min), "HH_max": g(hh_max),
        "f_agua_perm": g(c["c1"] / vt), "f_agua_nueva": g(c["c2"] / vt), "f_veg_inund_perm": g(c["c3"] / vt),
        "f_veg_inund_nueva": g(c["c4"] / vt), "f_urbano": g(c["c78"] / vt), "f_dudoso": g(c["c9"] / vt),
        "d_agua_km": g(d_agua), "d_inund_nueva_km": g(d_nueva),
        "HAND": g(TER["HAND"]), "DEM": g(TER["DEM"]), "PEND": g(TER["PEND"]),
        "wc_bosque": (wcv == 10).astype(np.int8), "wc_herb": np.isin(wcv, [20, 30, 40]).astype(np.int8),
        "wc_urbano": (wcv == 50).astype(np.int8), "wc_agua": (wcv == 80).astype(np.int8), "wc_humedal": np.isin(wcv, [90, 95]).astype(np.int8),
        "ascendente": int(stack.startswith("A")),
        **{k: v for k, v in esc.items()},
    })
    df["y"] = g(y).astype(np.int8)
    df["stack"], df["t"], df["t1"] = stack, t, t1
    df["fila"], df["col"] = filas, cols
    df["bloque"] = (filas // 250) * 100 + cols // 250
    return df


t0 = time.time()
partes = []
for stack in FECHAS:
    cache = {"sar": {d: sar40(stack, d) for d in FECHAS[stack]}, "cl": {d: clases40(stack, d) for d in FECHAS[stack]}}
    for s, t, t1 in [p for p in PARES if p[0] == stack]:
        d = rasgos_par(s, t, t1, cache)
        partes.append(d)
        print(f"{s} {t:%m-%d} → {t1:%m-%d}: {int(d.y.sum()):>6} positivas · {len(d):>6} filas")
    del cache
datos_B = pd.concat(partes, ignore_index=True)
VAR_B = [c for c in datos_B.columns if c not in ("y", "stack", "t", "t1", "fila", "col", "bloque")]
print(f"Total: {len(datos_B):,} filas · {int(datos_B.y.sum()):,} positivas ({datos_B.y.mean():.1%}) · {len(VAR_B)} variables · "
      f"({time.time() - t0:.0f} s)")

# %% [markdown]
# ## B4. Model comparison

# %%
def lineas_base(df):
    return {"Persistencia (inund. nueva en t)": (df.f_agua_nueva + df.f_veg_inund_nueva).values,
            "Regla de terreno (HAND y d_agua)": (1 / (1 + df.HAND.fillna(50).clip(0))) * np.exp(-df.d_agua_km.values / 2)}


def modelos_B(peso):
    m = crear_modelos(peso)
    m["Random Forest"].set_params(randomforestclassifier__n_estimators=150, randomforestclassifier__max_samples=0.3,
                                  randomforestclassifier__min_samples_leaf=10)
    m["Red neuronal (MLP)"].set_params(mlpclassifier__max_iter=60)
    m["XGBoost"].set_params(n_estimators=400, max_depth=7, tree_method="hist")
    m["LightGBM"].set_params(n_estimators=400, num_leaves=63)
    m["HistGradientBoosting"].set_params(max_iter=300)
    return m


UMBRAL_B = 0.5
t0 = time.time()
filas = []
# ---- 1) Spatial validation ----
gkf = GroupKFold(n_splits=3)
oof = {n: np.zeros(len(datos_B)) for n in list(modelos_B(1)) + list(lineas_base(datos_B.head()))}
for k, (ie, ip) in enumerate(gkf.split(datos_B, datos_B.y, datos_B.bloque)):
    de, dp = datos_B.iloc[ie], datos_B.iloc[ip]
    peso = float((de.y == 0).sum() / max((de.y == 1).sum(), 1))
    for nombre, mod in modelos_B(peso).items():
        mod.fit(de[VAR_B], de.y)
        oof[nombre][ip] = mod.predict_proba(dp[VAR_B])[:, 1]
    for nombre, s in lineas_base(dp).items():
        oof[nombre][ip] = s
    print(f"  pliegue espacial {k + 1}/3 listo ({time.time() - t0:.0f} s)")
for nombre, p in oof.items():
    es_base = nombre not in modelos_B(1)
    m = metricas(datos_B.y.values, p, umbral_max_f1(datos_B.y.values, p) if es_base else UMBRAL_B)
    m.update(validacion="espacial (bloques 10 km)", modelo=nombre); filas.append(m)

# ---- 2) Event validation (E6) ----
CORTE = pd.Timestamp("2026-08-20")
de_all, dp = datos_B[datos_B.t1 < CORTE], datos_B[datos_B.t1 >= CORTE]
bl = de_all.bloque.unique(); bl_val = set(rng.choice(bl, max(1, len(bl) // 5), replace=False))
dv, de = de_all[de_all.bloque.isin(bl_val)], de_all[~de_all.bloque.isin(bl_val)]
peso = float((de.y == 0).sum() / max((de.y == 1).sum(), 1))
MODELOS_B = {}
for nombre, mod in modelos_B(peso).items():
    mod.fit(de[VAR_B], de.y)
    u = UMBRAL_B
    m = metricas(dp.y.values, mod.predict_proba(dp[VAR_B])[:, 1], u)
    m.update(validacion="por evento (prueba E6)", modelo=nombre); filas.append(m)
    MODELOS_B[nombre] = (mod, u)
for nombre, s in lineas_base(dp).items():
    sv = lineas_base(dv)[nombre]
    m = metricas(dp.y.values, s, umbral_max_f1(dv.y.values, sv))
    m.update(validacion="por evento (prueba E6)", modelo=nombre); filas.append(m)
print(f"Evento: entrena {len(de):,} · umbral {len(dv):,} · prueba E6 {len(dp):,} ({dp.y.mean():.1%} +) · ({time.time() - t0:.0f} s)")

tabla_B = pd.DataFrame(filas)[["validacion", "modelo", "PR_AUC", "ROC_AUC", "F1", "POD", "FAR", "CSI", "Brier", "umbral"]]
tabla_B = tabla_B.sort_values(["validacion", "PR_AUC"], ascending=[False, False])
tabla_B.to_csv(DIR_OUT / "B_comparacion_modelos.csv", index=False)
tabla_B.round(3)

# %% [markdown]
# ### Comparison plot and feature importance

# %%
fig, axs = plt.subplots(1, 2, figsize=(13, 4))
t = tabla_B.pivot_table(index="modelo", columns="validacion", values="PR_AUC")
t = t.loc[t.mean(axis=1).sort_values().index]
t.plot.barh(ax=axs[0], width=0.8, color=["#3b6ea5", "#c9a227"])
axs[0].set_xlabel("PR-AUC"); axs[0].set_ylabel(""); axs[0].set_title("Modelo B · inundación nueva en la pasada siguiente"); axs[0].legend(fontsize=8)
MEJOR_B = tabla_B[(tabla_B.validacion.str.startswith("por evento")) & tabla_B.modelo.isin(MODELOS_B)].iloc[0]["modelo"]
mod_b = MODELOS_B[MEJOR_B][0]
imp = getattr(mod_b, "feature_importances_", None)
if imp is None:
    from sklearn.inspection import permutation_importance
    muestra = dp.sample(min(20000, len(dp)), random_state=SEMILLA)
    imp = permutation_importance(mod_b, muestra[VAR_B], muestra.y, n_repeats=3, random_state=SEMILLA, scoring="average_precision").importances_mean
imp = pd.Series(imp, index=VAR_B).sort_values().tail(15)
(imp / imp.sum()).plot.barh(ax=axs[1], color="#3b6ea5"); axs[1].set_title(f"Importancia de variables · {MEJOR_B}")
plt.tight_layout(); plt.savefig(DIR_OUT / "B_comparacion_e_importancia.png"); plt.show()
print("Mejor modelo B (prueba por evento):", MEJOR_B)

# %% [markdown]
# ## B5. Probability map for V.I.S.O.R. (E6 · A_T148, Aug 11 → Sep 4)

# %%
STACK_DEMO, T_DEMO, T1_DEMO = "A_T148", pd.Timestamp("2026-08-11"), pd.Timestamp("2026-09-04")
cache = {"sar": {d: sar40(STACK_DEMO, d) for d in FECHAS[STACK_DEMO]},
         "cl": {d: clases40(STACK_DEMO, d) for d in FECHAS[STACK_DEMO]}}
todo = rasgos_par(STACK_DEMO, T_DEMO, T1_DEMO, cache, todo=True)
p_todo = np.zeros(len(todo), np.float32)
for i in range(0, len(todo), 500_000):
    p_todo[i:i + 500_000] = mod_b.predict_proba(todo[VAR_B].iloc[i:i + 500_000])[:, 1]
mapa = np.full((NY, NX), 255, np.uint8)
mapa[todo.fila.values, todo.col.values] = np.clip(np.round(p_todo * 100), 0, 100).astype(np.uint8)
real = todo.y.values == 1

def captura(puntaje, frac):
    k = int(len(puntaje) * frac)
    return float(real[np.argpartition(-puntaje, k)[:k]].sum() / max(real.sum(), 1))


eval_mapa = pd.DataFrame([{"puntaje": n, "PR_AUC": average_precision_score(real, sc), "ROC_AUC": roc_auc_score(real, sc),
                           **{f"captura_top_{int(f * 100)}%": captura(np.asarray(sc, float), f) for f in (0.01, 0.05, 0.10)}}
                          for n, sc in [(MEJOR_B, p_todo)] + list(lineas_base(todo).items())])
eval_mapa.to_csv(DIR_OUT / "B_mapa_E6_evaluacion.csv", index=False)
u_b = float(np.quantile(p_todo, 0.95))
pred = p_todo >= u_b
iou = (pred & real).sum() / max((pred | real).sum(), 1)
m_demo = metricas(real.astype(int), p_todo, u_b)
print(f"Celdas evaluadas: {len(todo):,} · inundación nueva (etiquetado): {real.sum() * 0.0016:.1f} km² ({real.mean():.2%}) · "
      f"zona de alerta (5 % más probable): {pred.sum() * 0.0016:.0f} km² · umbral {u_b:.2f}")
print(eval_mapa.round(3).to_string())

nombre_tif = f"CHOCO_{STACK_DEMO}_E6_prob_inundacion_{T1_DEMO:%Y%m%d}.tif"
perfil = {"driver": "GTiff", "height": NY, "width": NX, "count": 1, "dtype": "uint8", "crs": "EPSG:32618",
          "transform": TRANSF40, "nodata": 255, "compress": "deflate", "tiled": True}
with rasterio.open(DIR_OUT / nombre_tif, "w", **perfil) as dst:
    dst.write(mapa, 1)
    dst.update_tags(TIPO_PRODUCTO="probabilidad_inundacion_nisar", UNIDADES="porcentaje", FECHA=f"{T1_DEMO:%Y-%m-%d}",
                    SENSOR="NISAR L-SAR banda L", VERSION_MODELO=f"modeloB_{MEJOR_B}")
sha = hashlib.sha256((DIR_OUT / nombre_tif).read_bytes()).hexdigest()
filas_v, cols_v = np.nonzero(mapa != 255)
ficha = {
    "esquema": "visor.ficha.v1",
    "tipo_producto": "probabilidad_inundacion_nisar",
    "producto": "Probabilidad de inundación nueva en la pasada siguiente (modelo B)",
    "fuente": "NISAR L2 GCOV (ASF DAAC) + IDEAM + Copernicus DEM/HAND + ESA WorldCover",
    "fecha": f"{T1_DEMO:%Y-%m-%d}", "unidades": "porcentaje (0-100)", "nodata": 255,
    "advertencia": "Pronóstico experimental entrenado con etiquetas no supervisadas (sin verdad de campo). "
                   "Indica dónde es más probable que aparezca agua nueva si se da el escenario hidrológico indicado.",
    "procedencia": {
        "estado": "real_sin_validar",
        "sensor": f"NISAR L-SAR (banda L), stack {STACK_DEMO}",
        "fechas": [f"{T_DEMO:%Y-%m-%d}", f"{T1_DEMO:%Y-%m-%d}"],
        "polarizaciones": ["HH", "HV"],
        "metodo": f"{MEJOR_B} sobre {len(VAR_B)} variables (radar en t, clases en t, terreno, escenario IDEAM t→t+1); "
                  f"entrenado sin el evento E6; umbral de alerta {u_b:.2f}",
        "entradas": [{"papel": "estado", "fecha": f"{T_DEMO:%Y-%m-%d}"}, {"papel": "escenario", "nivel_max_cm": escenario(T_DEMO, T1_DEMO)["nivel_max_tramo"]}],
        "generado_por": {"modulo": "ml_choco", "notebook": "entrenamiento_prediccion_inundaciones.ipynb"},
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "archivo": {"nombre": nombre_tif, "sha256": sha},
        "validacion": None,
    },
    "fechas_detalle": {"observacion": f"{T_DEMO:%Y-%m-%d}", "fecha_objetivo": f"{T1_DEMO:%Y-%m-%d}",
                       "nota": "Fecha objetivo = pasada siguiente. La prueba se hizo con E6 fuera del entrenamiento."},
    "umbral_alerta_pct": round(u_b * 100),
    "criterio_umbral": "percentil 95 de la franja: la alerta marca el 5 % de celdas más probables",
    "metricas_prueba_E6": {k: round(float(v), 3) for k, v in m_demo.items()} | {"IoU": round(float(iou), 3)}
                          | {k: round(float(v), 3) for k, v in eval_mapa.iloc[0].items() if k.startswith("captura")},
    "cuadricula": {"crs": "EPSG:32618", "resolucion": [RES, RES],
                   "limites": [X0, Y1 - NY * RES, X0 + NX * RES, Y1], "ancho": NX, "alto": NY},
    "limitaciones": ["Etiquetas del etiquetado no supervisado solo NISAR, no de campo.",
                     "Productos NISAR provisionales (bandeo de 1-2 dB).",
                     "Bajo bosque muy denso la inundación se subestima.",
                     "Solo 18 pares de fechas (jun-sep 2026) y un escenario hidrológico por par."],
}
(DIR_OUT / nombre_tif.replace(".tif", ".json")).write_text(json.dumps(ficha, ensure_ascii=False, indent=2), encoding="utf-8")

r0, r1, c0, c1 = filas_v.min(), filas_v.max(), cols_v.min(), cols_v.max()
real_map = np.full((NY, NX), np.nan); real_map[todo.fila.values, todo.col.values] = real
prob_map = np.where(mapa == 255, np.nan, mapa / 100.0)
fig, axs = plt.subplots(1, 3, figsize=(13, 6), sharey=True)
hh_t1 = cache["sar"][T1_DEMO][0]
axs[0].imshow(hh_t1[r0:r1, c0:c1], cmap="gray", vmin=-25, vmax=0); axs[0].set_title(f"HH {T1_DEMO:%d-%b} (dB)")
axs[1].imshow(real_map[r0:r1, c0:c1], cmap="Blues", vmin=0, vmax=1, interpolation="nearest"); axs[1].set_title("Etiquetado: inundación nueva")
im = axs[2].imshow(prob_map[r0:r1, c0:c1], cmap="magma_r", vmin=0, vmax=1, interpolation="nearest")
axs[2].set_title(f"Modelo B ({MEJOR_B}) · {eval_mapa.iloc[0]['captura_top_5%']:.0%} de lo nuevo en el 5 % más probable", fontsize=9)
plt.colorbar(im, ax=axs[2], fraction=0.04, label="probabilidad")
for a in axs: a.set_xticks([]); a.set_yticks([])
plt.tight_layout(); plt.savefig(DIR_OUT / "B_mapa_E6_A_T148.png"); plt.show()
del cache

joblib.dump({"modelo": mod_b, "umbral": u_b, "variables": VAR_B, "nombre": MEJOR_B, "malla": {"x0": X0, "y1": Y1, "res": RES, "forma": [NY, NX]},
             "entrenado_con": "pares con t+1 < 2026-08-20", "metricas_E6": ficha["metricas_prueba_E6"]},
            DIR_OUT / "modeloB_espacial.joblib")
print("Escrito:", nombre_tif, "+ ficha .json · SHA-256", sha[:16], "…")

# %% [markdown]
# ## B5b. Scenarios for the app traffic light (low · medium · high)

# %%
ESCENARIOS = {"bajo": float(q.loc[ENTRENA[0]:ENTRENA[1]].quantile(0.50)),
              "medio": UMBRAL_NIVEL,
              "alto": float(q.loc[ENTRENA[0]:ENTRENA[1]].quantile(0.99))}
filas_esc = []
for nombre_esc, nivel in ESCENARIOS.items():
    X = todo[VAR_B].copy()
    X["nivel_t1"] = nivel
    X["nivel_max_tramo"] = np.maximum(X["nivel_t"], nivel)
    X["dnivel"] = nivel - X["nivel_t"]
    X["nivel_max_rel_P90"] = X["nivel_max_tramo"] / UMBRAL_NIVEL
    pe = np.concatenate([mod_b.predict_proba(X.iloc[i:i + 500_000])[:, 1] for i in range(0, len(X), 500_000)])
    m_esc = np.full((NY, NX), 255, np.uint8)
    m_esc[todo.fila.values, todo.col.values] = np.clip(np.round(pe * 100), 0, 100).astype(np.uint8)
    nombre_e = f"CHOCO_{STACK_DEMO}_escenario_{nombre_esc}.tif"
    with rasterio.open(DIR_OUT / nombre_e, "w", **perfil) as dst:
        dst.write(m_esc, 1)
        dst.update_tags(TIPO_PRODUCTO="probabilidad_inundacion_nisar", UNIDADES="porcentaje", ESCENARIO=nombre_esc)
    ficha_e = json.loads(json.dumps(ficha))
    ficha_e["producto"] = f"Probabilidad de inundación nueva · escenario {nombre_esc} (nivel en Quibdó {nivel:.0f} cm)"
    ficha_e["escenario"] = {"nombre": nombre_esc, "nivel_quibdo_cm": round(nivel), "estado_base": f"{T_DEMO:%Y-%m-%d}"}
    ficha_e["fechas_detalle"]["fecha_objetivo"] = None
    ficha_e["fechas_detalle"]["nota"] = "Escenario hipotético: mismo estado del radar, nivel del río fijado por el usuario o por el Modelo A."
    ficha_e.pop("metricas_prueba_E6", None)
    ficha_e["procedencia"]["archivo"] = {"nombre": nombre_e, "sha256": hashlib.sha256((DIR_OUT / nombre_e).read_bytes()).hexdigest()}
    (DIR_OUT / nombre_e.replace(".tif", ".json")).write_text(json.dumps(ficha_e, ensure_ascii=False, indent=2), encoding="utf-8")
    alerta = pe >= u_b
    filas_esc.append({"escenario": nombre_esc, "nivel_cm": round(nivel), "km2_sobre_umbral": round(alerta.sum() * RES**2 / 1e6, 1),
                      "prob_media_%": round(pe.mean() * 100, 2)})
pd.DataFrame(filas_esc)

# %% [markdown]
# ## B6. Summary for the report

# %%
resumen = {
    "modelo_A": {k: {"modelo": v["nombre"], "conjunto": v["conjunto"], "H_dias": v["H_dias"],
                     "umbral_nivel_cm": round(v["umbral_nivel_cm"]),
                     **{m: round(float(x), 3) for m, x in v["metricas_prueba"].items()}} for k, v in ELEGIDOS.items()},
    "modelo_B": {"modelo": MEJOR_B, "umbral": round(float(u_b), 3), "E6_A_T148": ficha["metricas_prueba_E6"],
                 "filas_entrenamiento": int(len(datos_B)), "pares": len(PARES)},
}
(DIR_OUT / "resumen_resultados.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(resumen, ensure_ascii=False, indent=2))
