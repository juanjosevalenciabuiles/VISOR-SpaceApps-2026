# ========================================
# test_modulo_ml.py
# ========================================

import hashlib, json
from pathlib import Path
import folium, pandas as pd
from utils.prediccion_atrato import probabilidad_nivel_alto
from utils.capas_ml import capa_clases, capa_probabilidad, capa_zonas

RAIZ = Path(__file__).resolve().parent.parent
A = RAIZ / "data" / "analisis"


def _series():
    q = pd.read_csv(RAIZ / "data/series/quibdo_nivel_diario.csv", parse_dates=["fecha"]).set_index("fecha")["nivel_cm"]
    oni = pd.read_csv(RAIZ / "data/series/oni_mensual.csv", parse_dates=["fecha"]).set_index("fecha")["oni"]
    return q, oni


def test_semaforo_valores_de_referencia():
    q, oni = _series()
    r = probabilidad_nivel_alto(q[:"2026-05-28"], float(oni[:"2026-05-28"].iloc[-1]))
    assert r["semaforo"] == "amarillo" and abs(r["prob"] - 0.331) < 0.01
    r = probabilidad_nivel_alto(q[:"2026-11-13"], float(oni[:"2026-11-13"].iloc[-1]))
    assert r["semaforo"] == "verde" and abs(r["prob"] - 0.056) < 0.01 and round(r["nivel_hoy_cm"]) == 145


def test_sha256_de_las_fichas():
    for tif in A.glob("*.tif"):
        ficha = json.loads(tif.with_suffix(".json").read_text(encoding="utf-8"))
        assert ficha["procedencia"]["archivo"]["sha256"] == hashlib.sha256(tif.read_bytes()).hexdigest(), tif.name
        assert ficha["procedencia"]["estado"] == "real_sin_validar"


def test_capas_folium():
    m = folium.Map(location=[5.69, -76.66], zoom_start=11)
    f = capa_clases(m, A / "CHOCO_QUIBDO_A_T148_20260904_clases.tif")
    assert f["tipo_producto"] == "clases_inundacion_nisar"
    f = capa_probabilidad(m, A / "CHOCO_A_T148_E6_prob_inundacion_20260904.tif")
    assert f["tipo_producto"] == "probabilidad_inundacion_nisar" and f["umbral_alerta_pct"] == 2
    assert capa_zonas(m, A / "CHOCO_A_T148_E6_zonas_alerta_2km.geojson") == 539
