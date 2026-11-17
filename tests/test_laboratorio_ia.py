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


def test_acceso_ia_sin_tapar_controles_del_mapa():
    from components import interfaz
    import inspect
    main = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "interfaz.acceso_laboratorio_ia()" not in main
    assert 'label=tr("🧪 Abrir Laboratorio IA", "🧪 Open AI Laboratory")' in inspect.getsource(interfaz.panel_explorador)


def test_laboratorio_muestra_solo_dos_modelos_ml_y_oculta_navegacion_antigua():
    """La página del laboratorio no expone módulos legados ni ejecuta SAR operativo."""
    codigo = PAGINA.read_text(encoding="utf-8")
    assert 'initial_sidebar_state="collapsed"' in codigo
    assert '[data-testid="stSidebarNav"]' in codigo
    assert 'cuando, donde = st.tabs(' in codigo
    assert "Modelo A · Random Forest" in codigo
    assert "Modelo B · XGBoost" in codigo
    assert "cuando, donde, confianza = st.tabs(" not in codigo
    assert "Evaluación, confiabilidad y límites del Modelo B" in codigo
    assert "PROTOTIPO.read_text" in codigo
    assert "app.py" in codigo


def test_lab_bilingue_por_defecto_y_selector_en_es_sin_modelos_nuevos():
    codigo = PAGINA.read_text(encoding="utf-8")
    arbol = ast.parse(codigo)
    assert "from utils.i18n import idioma, seleccionar, tr" in codigo
    assert 'on_click=seleccionar, args=("en",)' in codigo
    assert 'on_click=seleccionar, args=("es",)' in codigo
    assert "Model A · Random Forest" in codigo and "Model B · XGBoost" in codigo
    assert "High Atrato River levels" in codigo and "NISAR-derived labels" in codigo
    assert "82.6%" in codigo and "69.7%" in codigo
    assert "Balanced accuracy" in codigo and "False positives" not in codigo
    assert any(isinstance(n, ast.FunctionDef) and n.name == "html_mapa_por_idioma"
               for n in arbol.body)


def test_lab_mapa_folium_traduce_etiquetas_en_memoria_sin_alterar_archivo():
    import hashlib
    import re

    codigo = PAGINA.read_text(encoding="utf-8")
    arbol = ast.parse(codigo)
    seleccion = [n for n in arbol.body if (
        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
                                           t.id == "ETIQUETAS_MAPA_EN" for t in n.targets)
    ) or (isinstance(n, ast.FunctionDef) and n.name == "html_mapa_por_idioma")]
    assert len(seleccion) == 2
    espacio = {}
    exec(compile(ast.Module(body=seleccion, type_ignores=[]), str(PAGINA), "exec"), espacio)

    antes = MAPA.read_bytes()
    mapa_es = antes.decode("utf-8")
    traducir = espacio["html_mapa_por_idioma"]
    mapa_en = traducir(mapa_es, "en")
    assert traducir(mapa_es, "es") == mapa_es
    assert "NISAR labels · 04 Sep (classes)" in mapa_en
    assert "2 km priority zones (Model B)" in mapa_en
    assert "Permanent water" in mapa_en
    assert "Mean probability (%)" in mapa_en
    assert "Etiquetado NISAR 04-sep (clases)" not in mapa_en
    # The embedded PNG overlays remain byte-for-byte identical.
    pngs = r"data:image/png;base64,[A-Za-z0-9+/=]+"
    assert re.findall(pngs, mapa_es) == re.findall(pngs, mapa_en)
    assert hashlib.sha256(MAPA.read_bytes()).digest() == hashlib.sha256(antes).digest()
