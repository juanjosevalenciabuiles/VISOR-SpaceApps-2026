# ========================================
# alerta_atrato.py
# ========================================

from pathlib import Path
import pandas as pd
import streamlit as st
from utils.prediccion_atrato import probabilidad_nivel_alto

RUTA_SERIES = Path(__file__).resolve().parent.parent / "data" / "series"
COLOR = {"verde": st.success, "amarillo": st.warning, "rojo": st.error}


@st.cache_data
def series_quibdo():
    q = pd.read_csv(RUTA_SERIES / "quibdo_nivel_diario.csv", parse_dates=["fecha"]).set_index("fecha")["nivel_cm"]
    oni = pd.read_csv(RUTA_SERIES / "oni_mensual.csv", parse_dates=["fecha"]).set_index("fecha")["oni"]
    return q, oni


def panel_alerta(fecha_corte=None):
    q, oni = series_quibdo()
    if fecha_corte is not None:
        q, oni = q[:fecha_corte], oni[:fecha_corte]
    r = probabilidad_nivel_alto(q, float(oni.iloc[-1]))
    st.subheader("Alerta Atrato · Quibdó")
    st.metric(f"Probabilidad de nivel alto en los próximos {r['H_dias']} días", f"{r['prob']:.0%}",
              help=f"Nivel alto = más de {r['umbral_nivel_cm']:.0f} cm (P90 2006–2018). Modelo {r['modelo']}, datos IDEAM hasta {r['fecha']}.")
    COLOR[r["semaforo"]](f"Semáforo {r['semaforo']} · nivel de hoy {r['nivel_hoy_cm']:.0f} cm")
    st.line_chart(q.tail(60).rename("nivel (cm)"))
    st.caption("Pronóstico experimental, REAL SIN VALIDAR. En la prueba 2022–2026 detectó 52 % de los días de nivel alto con 3 días de anticipación.")
    return r
