"""V.I.S.O.R. AI Lab — resultados históricos para jurados, sin inferencia en vivo.

Esta página es intencionalmente independiente de app.py y del motor V9.
Presenta exclusivamente resultados históricos de dos modelos de machine learning.
El mapa E6 es la salida del Modelo B, no una herramienta SAR de la aplicación.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

RAIZ = Path(__file__).resolve().parent.parent
PROTOTIPO = RAIZ / "data" / "ia_lab" / "demo_visor_E6.html"
ORIGEN_MAPA = "https://drive.google.com/file/d/1iCF-9Fk78ybbpk1cOHGwKUBidAvYATSM/view"
ORIGEN_METRICAS = "https://drive.google.com/file/d/1HSazqhn5eYe5j-Lp6FB8cOyAo-7R8sq2/view"

st.set_page_config(page_title="V.I.S.O.R. · Laboratorio IA", page_icon="🧪",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown(
    """
    <style>
    /* Laboratorio aislado: no mostrar navegación de módulos antiguos. */
    [data-testid="stSidebarNav"], .stSidebarNav {display: none !important;}
    .block-container {padding-top: 1.4rem; max-width: 1440px;}
    .visor-ia-hero {background: linear-gradient(130deg, #0a2233 5%, #0d3445 80%);
        color: #f2fbff; border: 1px solid #226a85; border-radius: 18px;
        padding: 20px 24px; margin: 8px 0 16px;}
    .visor-ia-hero h1 {font-size: clamp(1.4rem, 3vw, 2.2rem); margin: 0 0 .3rem;}
    .visor-ia-hero p {font-size: .94rem; opacity: .9; margin-bottom: 0;}
    .visor-etiqueta {font-size: .7rem; font-weight: 750; letter-spacing: .12em;
        color: #72e5f3; margin-bottom: 8px;}
    </style>
    <div class="visor-ia-hero">
      <div class="visor-etiqueta">V.I.S.O.R. · MACHINE LEARNING LAB</div>
      <h1>Modelos de machine learning</h1>
      <p>Dos modelos experimentales del equipo · Atrato, Chocó ·
      Resultados históricos, separados del análisis NISAR operativo.</p>
    </div>
    """, unsafe_allow_html=True,
)

st.warning(
    "Demostración histórica, NO una alerta actual. Los modelos no determinan "
    "inundaciones confirmadas: A estima nivel alto del río y B anticipa "
    "etiquetas satelitales derivadas de un algoritmo no supervisado.",
    icon="🔬",
)

# Solo dos secciones del laboratorio: los modelos de ML del equipo.
# El mapa precalculado pertenece al Modelo B y no habilita procesamiento SAR.
cuando, donde = st.tabs(["🕒 Modelo A · Random Forest", "🗺️ Modelo B · XGBoost"])

with cuando:
    st.subheader("Nivel alto del río Atrato en Quibdó · horizonte 3 días")
    st.markdown(
        "**Random Forest calibrado**, probado con datos de IDEAM, "
        "GloFAS y ONI. Objetivo histórico: estimar si el nivel en Quibdó "
        "superará aproximadamente **497 cm dentro de 3 días**. "
        "No es una predicción actual ni una inundación urbana confirmada."
    )
    a1, a2, a3 = st.columns(3)
    a1.metric("Exactitud balanceada", "69,7 %")
    a2.metric("Días altos detectados", "51,9 %")
    a3.metric("Exactitud general", "81,4 %")
    st.caption(
        "Evaluación histórica 2022–junio 2026. La regla sencilla basada "
        "en el nivel actual obtuvo 64,3 % de exactitud balanceada y detectó "
        "33,0 % de los días altos. El modelo puede emitir falsas alarmas."
    )
    st.info(
        "Ejemplo para explicar al jurado: el modelo ofrece una señal "
        "para investigar si el río alcanzará un nivel alto, pero no "
        "puede sustituir las alertas oficiales IDEAM/UNGRD."
    )

with donde:
    st.subheader("Etiquetas NISAR y prioridades espaciales · episodio E6")
    st.markdown(
        "Este mapa es el **prototipo original de Folium ya calculado** "
        "por el equipo, no una inferencia nueva. "
        "Corresponde a un experimento sobre Quibdó y el medio Atrato; "
        "incluye observaciones NISAR del **4 de septiembre de 2026** "
        "en la pasada A_T148 (comparación temporal desde el 11 de agosto)."
    )
    st.caption(
        "Activa y desactiva las capas en el control superior derecho del mapa: "
        "clases del radar, probabilidad calculada por XGBoost y zonas de 2 km "
        "priorizadas para revisión. La disponibilidad de teselas de fondo requiere red."
    )
    if PROTOTIPO.is_file():
        html = PROTOTIPO.read_text(encoding="utf-8")
        components.html(html, height=720, scrolling=True)
    else:
        st.error(
            "No se encontró el mapa histórico precalculado. "
            "No se generará una sustitución sintética."
        )
    st.markdown(
        "La capa de **clases NISAR** procede de etiquetado no supervisado. "
        "La capa **probable** refleja el puntaje del Modelo B; "
        "las zonas de **2 × 2 km** son propuestas de inspección, no alertas oficiales."
    )

    with st.expander("🔎 Evaluación, confiabilidad y límites del Modelo B", expanded=False):
        st.subheader("Resultados del experimento espacial E6")
        b1, b2, b3 = st.columns(3)
        b1.metric("Exactitud balanceada · zonas 2 km", "83,9 %")
        b2.metric("Detección de zonas etiquetadas positivas", "81,7 %", "161 de 197")
        b3.metric("Zonas marcadas que resultaron positivas", "17,4 %")
        st.warning(
            "**82,6 % de las zonas marcadas fueron falsos positivos frente "
            "a las etiquetas NISAR evaluadas** (765 de 926). El modelo sirve "
            "para priorizar revisión, NO para anunciar que un lugar se inundará.",
            icon="⚠️",
        )
        st.markdown(
            "La evaluación comprende **5.656 zonas de 2 × 2 km** en tres pasadas "
            "del episodio E6. Esta es una métrica agregada por zonas: "
            "**no equivale a precisión por píxel** ni a validación en terreno."
        )
        st.markdown(
            "La pregunta del Modelo A es **«¿subirá el nivel del río?»**. "
            "La pregunta del Modelo B es **«¿qué sectores podrían mostrar nuevas "
            "etiquetas de agua en la siguiente observación?»**. "
            "Ninguno responde directamente **«¿qué predios están inundados hoy?»**."
        )
        st.markdown(
            "**Limitaciones:** NISAR provisional, pocas fechas, "
            "posibles cambios ajenos al agua, etiquetas sin verificación de campo, "
            "falsos positivos frecuentes y ausencia de lluvia futura en el modelo principal."
        )

st.divider()
with st.expander("📚 Fuentes y trazabilidad del experimento", expanded=False):
    st.markdown(
        f"[Prototipo original E6]({ORIGEN_MAPA}) · "
        f"[Informe y métricas del equipo]({ORIGEN_METRICAS}) · "
        "[Repositorio V.I.S.O.R.](https://github.com/juanjosevalenciabuiles/VISOR-SpaceApps-2026)"
    )
st.caption(
    "Este laboratorio muestra solo los dos modelos de machine learning del equipo. "
    "No modifica ni descarga GeoTIFF SAR de V9. "
    "No importa modelos .joblib ni entrena algoritmos en la página. "
    "Visualiza exclusivamente un experimento histórico ya producido."
)
try:
    st.page_link("app.py", label="← Volver a V.I.S.O.R.", icon=":material/map:")
except Exception:
    st.caption("Para regresar al visor SAR, usa el selector de páginas.")
