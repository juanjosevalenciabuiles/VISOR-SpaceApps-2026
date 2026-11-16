"""V.I.S.O.R. AI Laboratory — historical machine-learning model results.

Independent of the operational V9 NISAR pipeline. Never changes prepared data
or retrains models. The historical E6 map is Model B's precomputed output.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from utils.i18n import idioma, seleccionar, tr

RAIZ = Path(__file__).resolve().parent.parent
PROTOTIPO = RAIZ / "data" / "ia_lab" / "demo_visor_E6.html"
ORIGEN_MAPA = "https://drive.google.com/file/d/1iCF-9Fk78ybbpk1cOHGwKUBidAvYATSM/view"
ORIGEN_METRICAS = "https://drive.google.com/file/d/1HSazqhn5eYe5j-Lp6FB8cOyAo-7R8sq2/view"

# Replace only presentation labels in memory, never the original E6 HTML,
# observations, coordinates, masks, percentages or raster data.
ETIQUETAS_MAPA_EN = (
    ("Etiquetado NISAR · 04-sep-2026", "NISAR-derived labels · 04 Sep 2026"),
    ("Etiquetado NISAR 04-sep (clases)", "NISAR labels · 04 Sep (classes)"),
    (r"Modelo B: 5 % m\u00e1s probable de agua nueva",
     "Model B: top 5% most likely to show new water"),
    ("Zonas de 2 km en alerta (Modelo B)", "2 km priority zones (Model B)"),
    ("Zona de 2 km en alerta (Modelo B)", "2 km priority zone (Model B)"),
    ("Agua permanente", "Permanent water"),
    ("Agua abierta nueva", "New open water"),
    ("Veg. inundada permanente", "Permanent flooded vegetation"),
    ("Veg. inundada nueva", "New flooded vegetation"),
    ("Bosque no inundado", "Non-flooded forest"),
    ("Veg. baja / pasto / suelo", "Low vegetation / grass / soil"),
    ("Urbano con aumento", "Urban area with increased backscatter"),
    ("Urbano", "Urban"),
    ("Dudoso", "Uncertain"),
    ("REAL SIN VALIDAR · no es verdad de campo",
     "REAL, NOT VALIDATED · not ground truth"),
    ('"Alerta", "% de celdas en alerta", "Prob. media (%)"',
     '"Flagged", "% flagged cells", "Mean probability (%)"'),
)


def html_mapa_por_idioma(html: str, lenguaje: str) -> str:
    """Translate labels only in the rendered HTML; never alter source or imagery."""
    if lenguaje != "en":
        return html
    for original, ingles in ETIQUETAS_MAPA_EN:
        html = html.replace(original, ingles)
    return html


st.set_page_config(
    page_title=tr("V.I.S.O.R. · Laboratorio IA", "V.I.S.O.R. · AI Laboratory"),
    page_icon="🧪", layout="wide", initial_sidebar_state="collapsed",
)
st.markdown(
    """
    <style>
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
    """, unsafe_allow_html=True,
)

# Same global language state as the main app; English by default, Spanish opt-in.
lang_en, lang_es = st.columns([1, 1])
with lang_en:
    st.button("English", key="ml_lab_en", use_container_width=True,
              type="primary" if idioma() == "en" else "secondary",
              on_click=seleccionar, args=("en",))
with lang_es:
    st.button("Español", key="ml_lab_es", use_container_width=True,
              type="primary" if idioma() == "es" else "secondary",
              on_click=seleccionar, args=("es",))

st.markdown(
    f"""
    <div class="visor-ia-hero">
      <div class="visor-etiqueta">V.I.S.O.R. · MACHINE LEARNING LAB</div>
      <h1>{tr("Modelos de aprendizaje automático", "Machine learning models")}</h1>
      <p>{tr(
          "Dos modelos experimentales del equipo · Atrato, Chocó · "
          "Resultados históricos, separados del análisis NISAR operativo.",
          "Two experimental models developed by the team · Atrato, Chocó · "
          "Historical results, separate from operational NISAR analysis."
      )}</p>
    </div>
    """, unsafe_allow_html=True,
)

st.warning(
    tr(
        "Demostración histórica, NO una alerta actual. Los modelos no determinan "
        "inundaciones confirmadas: A estima niveles altos del río y B anticipa "
        "etiquetas satelitales derivadas de un algoritmo no supervisado.",
        "Historical demonstration, NOT a current warning. Neither model confirms "
        "flooding: A estimates high river levels, while B forecasts satellite-derived "
        "labels based on an unsupervised algorithm.",
    ),
    icon="🔬",
)

cuando, donde = st.tabs([
    tr("🕒 Modelo A · Random Forest", "🕒 Model A · Random Forest"),
    tr("🗺️ Modelo B · XGBoost", "🗺️ Model B · XGBoost"),
])

with cuando:
    st.subheader(tr(
        "Nivel alto del río Atrato en Quibdó · horizonte de 3 días",
        "High Atrato River levels in Quibdó · 3-day horizon",
    ))
    st.markdown(tr(
        "**Random Forest calibrado**, evaluado con datos de IDEAM, GloFAS y ONI. "
        "Objetivo histórico: estimar si el nivel en Quibdó superará aproximadamente "
        "**497 cm dentro de 3 días**. No es una predicción actual ni una inundación "
        "urbana confirmada.",
        "**Calibrated Random Forest** evaluated using IDEAM, GloFAS and ONI data. "
        "Historical target: estimate whether the river level in Quibdó will exceed "
        "approximately **497 cm within 3 days**. This is neither a live forecast "
        "nor confirmation of urban flooding.",
    ))
    a1, a2, a3 = st.columns(3)
    a1.metric(tr("Exactitud balanceada", "Balanced accuracy"),
              tr("69,7 %", "69.7%"))
    a2.metric(tr("Días altos detectados", "High-water days detected"),
              tr("51,9 %", "51.9%"))
    a3.metric(tr("Exactitud general", "Overall accuracy"),
              tr("81,4 %", "81.4%"))
    st.caption(tr(
        "Evaluación histórica 2022–junio 2026. Una regla sencilla basada en el "
        "nivel actual obtuvo 64,3 % de exactitud balanceada y detectó 33,0 % "
        "de los días altos. El modelo puede generar falsas alarmas.",
        "Historical evaluation: 2022–June 2026. A simple current-level rule "
        "achieved 64.3% balanced accuracy and identified 33.0% of high-water "
        "days. The model may produce false alarms.",
    ))
    st.info(tr(
        "Ejemplo para el jurado: el modelo aporta una señal para investigar "
        "niveles altos, pero no sustituye alertas oficiales de IDEAM/UNGRD.",
        "For judges: the model provides a signal for investigating high river "
        "levels, but does not replace official IDEAM/UNGRD warnings.",
    ))

with donde:
    st.subheader(tr(
        "Etiquetas NISAR y prioridades espaciales · episodio E6",
        "NISAR-derived labels and spatial priorities · E6 episode",
    ))
    st.markdown(tr(
        "Este mapa es el **prototipo Folium ya calculado** por el equipo, no una "
        "inferencia nueva. Corresponde a Quibdó y el medio Atrato e incluye "
        "observaciones NISAR del **4 de septiembre de 2026** en la pasada "
        "A_T148 (comparadas con el 11 de agosto).",
        "This map is the team's **precomputed Folium prototype**, not a new "
        "inference. It covers Quibdó and the Middle Atrato area and includes "
        "NISAR observations from **September 4, 2026**, pass A_T148 "
        "(compared with August 11).",
    ))
    st.caption(tr(
        "Usa el control de capas en la esquina superior derecha del mapa: "
        "etiquetas SAR, puntajes de XGBoost y zonas de 2 km priorizadas para "
        "revisión. El fondo cartográfico necesita conexión de red.",
        "Use the map layer control at the top right to explore SAR-derived "
        "labels, XGBoost scores and 2 km zones prioritized for review. "
        "Base-map tiles require internet access.",
    ))
    if PROTOTIPO.is_file():
        html = PROTOTIPO.read_text(encoding="utf-8")
        html = html_mapa_por_idioma(html, idioma())
        components.html(html, height=720, scrolling=True)
    else:
        st.error(tr(
            "No se encontró el mapa histórico precalculado. "
            "No se generará una sustitución sintética.",
            "The precomputed historical map was not found. "
            "No synthetic replacement will be generated.",
        ))
    st.markdown(tr(
        "Las **etiquetas NISAR** proceden de clasificación no supervisada. "
        "Los puntajes de **Modelo B** y las zonas de **2 × 2 km** son "
        "prioridades de inspección, **no alertas oficiales**.",
        "The **NISAR-derived labels** come from unsupervised classification. "
        "**Model B** scores and **2 × 2 km** zones indicate inspection priorities, "
        "**not official warnings**.",
    ))

    with st.expander(tr(
        "🔎 Evaluación, confiabilidad y límites del Modelo B",
        "🔎 Model B evaluation, reliability and limitations",
    ), expanded=False):
        st.subheader(tr(
            "Resultados del experimento espacial E6",
            "E6 spatial experiment results",
        ))
        b1, b2, b3 = st.columns(3)
        b1.metric(tr("Exactitud balanceada · zonas 2 km",
                     "Balanced accuracy · 2 km zones"),
                  tr("83,9 %", "83.9%"))
        b2.metric(tr("Detección de zonas etiquetadas positivas",
                     "Recall of positively labeled zones"),
                  tr("81,7 %", "81.7%"), tr("161 de 197", "161 of 197"))
        b3.metric(tr("Zonas marcadas que resultaron positivas",
                     "Flagged zones labeled positive"),
                  tr("17,4 %", "17.4%"))
        st.warning(tr(
            "**82,6 % de las zonas marcadas fueron falsos positivos** frente "
            "a las etiquetas NISAR evaluadas (765 de 926). Sirve para priorizar "
            "revisión, NO para anunciar una futura inundación.",
            "**82.6% of flagged zones were false positives** relative to "
            "the evaluated NISAR-derived labels (765 of 926). This model can "
            "prioritize review, NOT announce future flooding.",
        ), icon="⚠️")
        st.markdown(tr(
            "Se evaluaron **5.656 zonas de 2 × 2 km** en tres pasadas del "
            "episodio E6. Son métricas agregadas por zona: **no equivalen "
            "a precisión por píxel ni a validación en campo**.",
            "The evaluation covers **5,656 zones of 2 × 2 km** across "
            "three passes of episode E6. These are zone-level metrics: "
            "**not pixel-level accuracy or field validation**.",
        ))
        st.markdown(tr(
            "Modelo A: **¿subirá el nivel del río?** "
            "Modelo B: **¿qué sectores podrían mostrar nuevas etiquetas de agua "
            "en la siguiente observación?** Ninguno establece **qué predios "
            "están inundados hoy**.",
            "Model A asks: **Will the river level rise?** Model B asks: "
            "**Which areas may show new water labels in the next observation?** "
            "Neither establishes **which properties are flooded today**.",
        ))
        st.markdown(tr(
            "**Limitaciones:** NISAR provisional, pocas fechas, cambios ajenos "
            "al agua, etiquetas no verificadas en campo, falsos positivos frecuentes "
            "y ausencia de lluvia futura en el modelo principal.",
            "**Limitations:** Provisional NISAR inputs, few observation dates, "
            "non-water changes, labels without field validation, frequent "
            "false positives and no future-rainfall input in the main model.",
        ))

st.divider()
with st.expander(tr(
    "📚 Fuentes y trazabilidad del experimento",
    "📚 Experiment sources and traceability",
), expanded=False):
    st.markdown(
        f"[{tr('Prototipo original E6', 'Original E6 prototype')}]({ORIGEN_MAPA}) · "
        f"[{tr('Informe y métricas del equipo', 'Team report and metrics')}]({ORIGEN_METRICAS}) · "
        f"[{tr('Repositorio V.I.S.O.R.', 'V.I.S.O.R. repository')}]"
        "(https://github.com/juanjosevalenciabuiles/VISOR-SpaceApps-2026)"
    )
st.caption(tr(
    "El laboratorio muestra únicamente dos modelos de machine learning "
    "en un experimento histórico. No modifica GeoTIFF SAR de V9, "
    "no carga modelos .joblib ni ejecuta entrenamiento o inferencia en vivo.",
    "This laboratory presents two machine-learning models from a historical "
    "experiment. It does not modify V9 SAR GeoTIFFs, load .joblib models, "
    "or perform live training or inference.",
))
try:
    st.page_link("app.py", label=tr("← Volver a V.I.S.O.R.", "← Back to V.I.S.O.R."),
                 icon=":material/map:")
except Exception:
    st.caption(tr(
        "Para regresar al visor, usa la navegación de la aplicación.",
        "To return to the map, use the app navigation.",
    ))
