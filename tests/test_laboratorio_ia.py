"""La exhibición IA debe ser estática y ajena al pipeline de NISAR."""
from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]
PAGINA = ROOT / "pages" / "3_Laboratorio_IA.py"
MAPA = ROOT / "data" / "ia_lab" / "demo_visor_E6.html"


def test_lab_conserva_mapa_original_3_capas_y_controles():
    assert MAPA.is_file()
    html = MAPA.read_text(encoding="utf-8")
    assert len(html) > 600_000
    assert "L.control.layers" in html
    assert html.count("L.imageOverlay") >= 2
    assert "L.geoJson" in html
    assert "Etiquetado NISAR" in html
    assert "Zonas de 2 km en alerta" in html


def test_pagina_no_infiere_predicciones_ni_modifica_motor_sar():
    codigo = PAGINA.read_text(encoding="utf-8")
    ast.parse(codigo)
    for prohibido in ("import joblib", "joblib.load", "XGBClassifier", "RandomForestClassifier",
                       "harmony.", "st_folium(", "descargar_", "rasterio.open",
                       "pd.read_csv", "requests.get", "subprocess."):
        assert prohibido not in codigo, prohibido
    assert 'components.html(html, height=720, scrolling=True)' in codigo
    assert "82,6 %" in codigo and "69,7 %" in codigo


def test_no_tocar_app_ni_geoTIFF_en_este_modulo():
    codigo = PAGINA.read_text(encoding="utf-8")
    assert "from components import flujo" not in codigo
    assert "from components import mapa" not in codigo
    assert "st.session_state" not in codigo
    assert "data/analisis" not in codigo


def test_acceso_visible_en_barra_superior_a_pagina_independiente():
    from components import interfaz
    import inspect
    codigo = inspect.getsource(interfaz.barra_superior)
    assert 'key="btn_laboratorio_ia"' in codigo
    assert 'st.switch_page("pages/3_Laboratorio_IA.py")' in codigo
