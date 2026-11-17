# ========================================
# prediccion_atrato.py
# ========================================

from pathlib import Path
import joblib
import numpy as np
import pandas as pd

RUTA_MODELOS = Path(__file__).resolve().parent.parent / "modelos"
_CACHE = {}


def cargar(nombre="modeloA_solo_ideam.joblib"):
    if nombre not in _CACHE:
        _CACHE[nombre] = joblib.load(RUTA_MODELOS / nombre)
    return _CACHE[nombre]


def rasgos_quibdo(q: pd.Series, clim) -> pd.DataFrame:
    q = q.sort_index().asfreq("D").ffill(limit=2)
    d = {f"q_l{k}": q.shift(k) for k in range(7)}
    d.update(q_d1=q - q.shift(1), q_d3=q - q.shift(3),
             q_m7=q.rolling(7, min_periods=4).mean(), q_x7=q.rolling(7, min_periods=4).max(),
             q_m30=q.rolling(30, min_periods=15).mean())
    X = pd.DataFrame(d)
    X["q_anom"] = q - np.asarray(clim)[q.index.dayofyear - 1]
    doy = q.index.dayofyear.values
    X["doy_sin"], X["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    return X


def probabilidad_nivel_alto(q: pd.Series, oni_hoy: float, glofas: pd.DataFrame | None = None,
                            nombre_modelo: str = "modeloA_solo_ideam.joblib") -> dict:
    paq = cargar(nombre_modelo)
    X = rasgos_quibdo(q, paq["climatologia_doy"])
    X["oni"] = oni_hoy
    if glofas is not None:
        X = X.join(glofas, how="left")
    fila = X.reindex(columns=paq["variables"]).tail(1)
    p = float(paq["calibrador"].predict(paq["modelo"].predict_proba(fila)[:, 1])[0])
    semaforo = "rojo" if p >= 0.6 else ("amarillo" if p >= paq["umbral_decision"] else "verde")
    return {"fecha": fila.index[0].date().isoformat(), "nivel_hoy_cm": float(q.dropna().iloc[-1]), "prob": p,
            "semaforo": semaforo, "umbral_decision": float(paq["umbral_decision"]), "H_dias": int(paq["H_dias"]),
            "umbral_nivel_cm": float(paq["umbral_nivel_cm"]), "modelo": paq["nombre"], "conjunto": paq["conjunto"]}
