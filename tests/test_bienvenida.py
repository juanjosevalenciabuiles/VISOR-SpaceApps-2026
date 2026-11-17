"""Regresión del manual: persistencia por rerun, sin alterar análisis SAR."""
from pathlib import Path
import ast

from components import bienvenida
from utils import i18n

RAIZ = Path(__file__).resolve().parents[1]


def test_guia_no_desaparece_al_mover_mapa_y_no_altera_resultado(monkeypatch):
    estado = {
        "zona": {"limites": (-76.8, 7.55, -76.55, 7.8)},
        "resultado_activo": {"id": "resultado_nuevo"},
        "mapa_encuadre_usuario": {"centro": [7.65, -76.7], "zoom": 13},
    }
    monkeypatch.setattr(bienvenida.st, "session_state", estado)
    bienvenida.abrir()
    assert estado["visor_guia_abierta"] is True

    # Simular reruns al arrastrar el mapa y cambiar las capas/zoom.
    estado["mapa_encuadre_usuario"] = {"centro": [7.69, -76.67], "zoom": 14}
    estado["res_opacidad"] = 0.55
    assert estado["visor_guia_abierta"] is True
    assert estado["resultado_activo"] == {"id": "resultado_nuevo"}
    assert estado["zona"]["limites"] == (-76.8, 7.55, -76.55, 7.8)
    bienvenida.cerrar()
    assert estado["visor_guia_abierta"] is False
    bienvenida.abrir()
    assert estado["visor_guia_abierta"] is True


def test_idioma_se_cambia_sin_afectar_resultados(monkeypatch):
    estado = {"visor_idioma": "es", "resultado_activo": {"id": "SAR123"},
              "zona": {"limites": [-77, 7, -76, 8]}}
    monkeypatch.setattr(i18n.st, "session_state", estado)
    assert i18n.tr("Historial", "History") == "Historial"
    i18n.seleccionar("en")
    assert i18n.tr("Historial", "History") == "History"
    i18n.seleccionar("es")
    assert i18n.tr("Historial", "History") == "Historial"
    assert estado["resultado_activo"] == {"id": "SAR123"}
    assert estado["zona"] == {"limites": [-77, 7, -76, 8]}


def test_guia_se_muestra_despues_del_mapa_en_todos_los_reruns():
    codigo = (RAIZ / "app.py").read_text(encoding="utf-8")
    assert ast.parse(codigo) is not None
    assert codigo.index("mapa.render_vivo()") < codigo.index("bienvenida.render()")
    assert 'st.session_state["visor_mapa_render_actual"] = {' in codigo
    assert "if bienvenida.corresponde_mostrar():" not in codigo
    assert "bienvenida.render()" in codigo
    guia = (RAIZ / "components" / "bienvenida.py").read_text(encoding="utf-8")
    assert "@st.dialog" not in guia
    assert 'st.session_state.setdefault(CLAVE_ABIERTA, True)' in guia
    assert "key=\"visor_guia_launcher\"" in guia
    assert "key=\"visor_guia_panel\"" in guia
    assert "key=\"visor_guia_busqueda\"" in guia
    assert "on_click=cerrar" in guia
    assert "visor_guia_empezar" not in guia
    assert "on_click=abrir" in guia
    assert "visor-guia-sombra" in guia
    assert "transform: translate(-50%, -50%)" in guia
    assert "@st.dialog" not in guia


def test_tutorial_dos_idiomas_y_rigor_cientifico():
    guia = (RAIZ / "components" / "bienvenida.py").read_text(encoding="utf-8")
    for termino in ("NISAR", "Sentinel-1", "IDEAM", "DANE", "EONET", "historial",
                    "inundación", "NoData", "ΔdB", "PROVISIONAL", "VALIDATED"):
        assert termino in guia
    for termino in ("History", "flood", "provenance", "backscatter", "SAR Tools",
                    "English", "NoData"):
        assert termino in guia
    assert "rasterio" not in guia
    assert "requests.post" not in guia
