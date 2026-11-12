"""Pruebas de la interfaz Mission Control Earth Explorer (Fase A).

Comprueban el estado de los paneles, el tema por fenómeno, la navegación por
coordenadas y que el mapa siga siendo uno solo. La interacción real con el
ratón (rueda, arrastre, clics sobre el mapa) se verificó aparte en navegador.
"""
import inspect
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from components import estilos, interfaz, mapa  # noqa: E402
from utils.config import ASSETS_DIR, FENOMENOS, MAPA_CENTRO, MAPA_ZOOM, Fenomeno  # noqa: E402

PALETA = {
    "inundacion": ("#4FDCF4", (79, 220, 244)),
    "deslizamiento": ("#F4A463", (244, 164, 99)),
    "deforestacion": ("#64DFA7", (100, 223, 167)),
}
# Rampas de datos de las capas demostrativas: el tema NO debe tocarlas.
RAMPAS = {
    "inundacion": ("#0B3C5D", "#0096FF", "#00F0FF"),
    "deslizamiento": ("#5A1A00", "#FF6A00", "#FF2D55"),
    "deforestacion": ("#0B3D1E", "#39FF14", "#F5FF00"),
}
CSS = (ASSETS_DIR / "mission_control.css").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tema adaptativo
# ---------------------------------------------------------------------------

def test_paleta_aprobada_con_rgb_exactos():
    for clave, (hexa, rgb) in PALETA.items():
        f = FENOMENOS[clave]
        assert f.tema == hexa and f.tema_rgb == rgb
        assert estilos.variables_tema(f) == (
            f":root{{--theme-rgb:{rgb[0]}, {rgb[1]}, {rgb[2]};--theme-accent:{hexa};--acento:{hexa};}}")


def test_el_tema_no_cambia_los_colores_de_los_datos():
    for clave, rampa in RAMPAS.items():
        assert FENOMENOS[clave].colores == rampa


def test_tema_invalido():
    base = dict(clave="x", nombre="X", icono="", archivo="x.tif", descripcion="", producto="", advertencias=("a",))
    for malo in ("4FDCF4", "#4FDCF", "#GGGGGG", "cian"):
        with pytest.raises(ValueError, match="tema"):
            Fenomeno(**base, tema=malo)


def test_vidrio_sin_opacity_global_y_con_respaldo():
    assert not re.search(r"(?<![-\w])opacity\s*:", CSS)          # nunca `opacity` sobre contenedores
    assert "backdrop-filter: var(--mc-desenfoque)" in CSS and "-webkit-backdrop-filter" in CSS
    assert "@supports not ((backdrop-filter" in CSS               # navegadores sin desenfoque
    assert "blur(28px) saturate(150%)" in CSS and "--mc-radio: 20px" in CSS
    assert "rgba(var(--theme-rgb)" in CSS and "prefers-reduced-motion" in CSS
    assert "@media (max-width: 720px)" in CSS


# ---------------------------------------------------------------------------
# Mapa único
# ---------------------------------------------------------------------------

def test_mapa_fijo_lleva_el_estilo_de_pantalla_completa_y_es_estable():
    from streamlit_folium import _get_header, _get_map_string, generate_js_hash

    a, b = mapa.mapa_fijo(), mapa.mapa_fijo()
    for m in (a, b):
        m.get_root().render()
    cab_a, cab_b = _get_header(a), _get_header(b)
    assert mapa.ESTILO_LIENZO in cab_a and cab_a == cab_b
    assert "100vh" in mapa.ESTILO_LIENZO and "#map_div" in mapa.ESTILO_LIENZO
    # La huella del mapa no cambia entre ejecuciones: streamlit-folium no lo recrea.
    assert generate_js_hash(_get_map_string(a), "mapa", False) == generate_js_hash(_get_map_string(b), "mapa", False)


def test_destino_de_vista():
    assert mapa.destino_vista(None) == (None, None)
    v1 = {"centro": [7.67, -76.68], "zoom": 11.0, "n": 1}
    v2 = {**v1, "n": 2}
    (c1, z1), (c2, z2) = mapa.destino_vista(v1), mapa.destino_vista(v2)
    assert c1 != c2 and z1 != z2                                 # repetir el destino vuelve a mover
    assert abs(c1[0] - 7.67) < 1e-6 and c1[1] == -76.68         # desplazamiento < 1 mm
    assert round(z1) == 11 and abs(z1 - 11) < 1e-3              # Leaflet lo redondea a 11


# ---------------------------------------------------------------------------
# Estado de los paneles
# ---------------------------------------------------------------------------

@pytest.fixture
def estado(monkeypatch):
    """Sustituye st.session_state por un diccionario para probar las acciones."""
    falso = {}
    monkeypatch.setattr(interfaz.st, "session_state", falso)
    interfaz.inicializar_estado()
    return falso


def test_estado_inicial(estado):
    assert estado["ui_explorador"] and estado["ui_info"] and estado["ui_sar"] == "cerrado"
    assert estado["vista"] is None
    assert interfaz.css_estado() == ".st-key-panel_sar,.st-key-sar_minimizado{display:none !important}"


def test_estado_invalido_se_corrige(estado):
    estado["ui_sar"] = "otra cosa"
    interfaz.inicializar_estado()
    assert estado["ui_sar"] == "cerrado"


def test_flujo_de_herramientas_sar(estado):
    interfaz.abrir_sar()
    assert estado["ui_sar"] == "abierto" and not estado["ui_explorador"]
    assert ".st-key-panel_explorador" in interfaz.css_estado() and ".st-key-panel_sar," not in interfaz.css_estado()
    interfaz.minimizar_sar()
    assert estado["ui_sar"] == "minimizado" and ".st-key-sar_minimizado" not in interfaz.css_estado()
    interfaz.abrir_sar()                                        # restaurar
    assert estado["ui_sar"] == "abierto"
    interfaz.cerrar_sar()
    assert estado["ui_sar"] == "cerrado" and estado["ui_explorador"]   # vuelve como estaba


def test_cerrar_sar_respeta_el_explorador_contraido(estado):
    interfaz.alternar_explorador()
    assert not estado["ui_explorador"]
    interfaz.abrir_sar()
    interfaz.cerrar_sar()
    assert not estado["ui_explorador"]


def test_abrir_el_explorador_con_sar_abierto_lo_minimiza(estado):
    interfaz.abrir_sar()
    interfaz.alternar_explorador()
    assert estado["ui_explorador"] and estado["ui_sar"] == "minimizado"


def test_modo_inmersivo(estado):
    interfaz.alternar_explorador()
    interfaz.alternar_info()
    css = interfaz.css_estado()
    for panel in ("panel_explorador", "panel_info", "panel_sar", "sar_minimizado"):
        assert f".st-key-{panel}" in css


def test_ir_a_coordenadas_y_volver(estado):
    interfaz.ir_a(7.67, -76.68, 11)
    interfaz.ir_a(7.67, -76.68, 11)
    assert estado["vista"] == {"centro": [7.67, -76.68], "zoom": 11.0, "n": 2}
    interfaz.volver_al_inicio()
    assert estado["vista"]["centro"] == list(MAPA_CENTRO) and estado["vista"]["zoom"] == MAPA_ZOOM
    assert estado["vista"]["n"] == 3


def test_insignias_de_procedencia():
    class Capa:
        es_demo = True
    assert "DEMO" in interfaz.insignia_procedencia(Capa())
    Capa.es_demo = False
    assert "PROCEDENCIA" in interfaz.insignia_procedencia(Capa()) and "REAL" not in interfaz.insignia_procedencia(Capa())
    assert "SIN CAPA" in interfaz.insignia_procedencia(None)


def test_ayuda_explica_etiquetas_nisar_e_ia():
    texto = inspect.getsource(interfaz.mostrar_ayuda)
    for frase in ("DEMO", "REAL SIN VALIDAR", "VALIDADO", "NISAR", "Sentinel-1", "inteligencia artificial", "no confirma"):
        assert frase in texto


def test_herramientas_sar_no_simulan_resultados():
    texto = inspect.getsource(interfaz.herramientas_sar)
    assert "AÚN NO CONECTADO" in inspect.getsource(interfaz._paso_pendiente)
    assert "ningún resultado de aquí es real" in texto
    for falso in ("DEMO-S1", "Coherencia InSAR", "Cambio de cobertura", "progress"):
        assert falso not in texto


# ---------------------------------------------------------------------------
# La app completa
# ---------------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(RAIZ)
    return AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60).run()


def textos(at) -> str:
    return " ".join(m.value for m in at.markdown)


def test_app_un_solo_mapa_sin_barra_lateral(app):
    assert not app.exception and len(app.error) == 0
    assert len(app.sidebar) == 0                                  # todo es superficie flotante
    assert "--theme-rgb:79, 220, 244" in textos(app)
    assert "LÍNEA TEMPORAL · CONCEPTUAL" in textos(app) and len(app.select_slider) == 0
    assert app.session_state["ui_sar"] == "cerrado"


def test_app_tema_cambia_con_el_fenomeno(app):
    for clave, (_hexa, rgb) in PALETA.items():
        app.radio(key="fenomeno").set_value(clave).run()
        assert not app.exception
        assert f"--theme-rgb:{rgb[0]}, {rgb[1]}, {rgb[2]}" in textos(app)


def test_app_contraer_el_explorador_conserva_sus_valores(app):
    app.radio(key="fenomeno").set_value("deforestacion").run()
    app.selectbox(key="mapa_base").set_value("topografico").run()
    app.button(key="cerrar_explorador").click().run()
    assert not app.exception and app.session_state["ui_explorador"] is False
    assert ".st-key-panel_explorador" in textos(app)              # oculto con CSS, no eliminado
    assert app.radio(key="fenomeno").value == "deforestacion"
    assert app.selectbox(key="mapa_base").value == "topografico"
    assert "--theme-rgb:100, 223, 167" in textos(app)
    app.button(key="btn_explorador").click().run()
    assert app.session_state["ui_explorador"] is True and app.radio(key="fenomeno").value == "deforestacion"


def test_app_flujo_sar_e_ir_a(app):
    app.button(key="btn_sar").click().run()
    assert app.session_state["ui_sar"] == "abierto" and app.session_state["ui_explorador"] is False
    app.button(key="minimizar_sar").click().run()
    assert app.session_state["ui_sar"] == "minimizado"
    app.button(key="restaurar_sar").click().run()
    app.button(key="cerrar_sar").click().run()
    assert app.session_state["ui_sar"] == "cerrado" and app.session_state["ui_explorador"] is True

    app.number_input(key="ir_lat").set_value(7.67)
    app.number_input(key="ir_lon").set_value(-76.68)
    app.slider(key="ir_zoom").set_value(12)
    app.button(key="btn_ir").click().run()
    assert not app.exception
    assert app.session_state["vista"] == {"centro": [7.67, -76.68], "zoom": 12.0, "n": 1}
    app.button(key="btn_inicio").click().run()
    assert app.session_state["vista"]["centro"] == list(MAPA_CENTRO) and app.session_state["vista"]["n"] == 2
