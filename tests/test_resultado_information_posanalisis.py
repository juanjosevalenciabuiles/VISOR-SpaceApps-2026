"""Regresiones UI del resultado NISAR, sin consultas a NASA ni acceso a GeoTIFF."""
from pathlib import Path

from components import v9_experiencia


def test_resultado_sar_se_ve_en_information_no_en_explorer(monkeypatch):
    """La publicación cambia SOLO visibilidad; no el plan ni el resultado SAR."""
    zona = {"limites": [-76.8, 7.55, -76.55, 7.80]}
    resultado = {"id": "sar_actual", "origen": "ANALISIS"}
    estado = {
        "ui_explorador": True,
        "ui_info": False,
        "ui_sar": "abierto",
        "resultado_activo": resultado,
        "zona": zona,
        "v9_preparacion": "prep_real",
        "v9_mapa_job": "trabajo_real",
        "v9_publicado": "trabajo_real",
    }
    monkeypatch.setattr(v9_experiencia.st, "session_state", estado)

    v9_experiencia._mostrar_resultado_en_information()

    assert estado["ui_explorador"] is False
    assert estado["ui_info"] is True
    assert estado["ui_sar"] == "abierto"
    assert estado["resultado_activo"] is resultado
    assert estado["zona"] is zona
    assert estado["v9_preparacion"] == "prep_real"
    assert estado["v9_mapa_job"] == "trabajo_real"
    assert estado["v9_publicado"] == "trabajo_real"


def test_wikipedia_permanece_solo_en_panel_derecho():
    """No mover Wikipedia del panel Information a Explorer o SAR."""
    raiz = Path(__file__).resolve().parents[1]
    interfaz = (raiz / "components" / "interfaz.py").read_text(encoding="utf-8")
    explorer = interfaz.split("def panel_explorador(", 1)[1].split("def panel_informacion(", 1)[0]
    information = interfaz.split("def panel_informacion(", 1)[1].split("def guia_eco(", 1)[0]
    assert "wikipedia_zona(" not in explorer
    assert "wikipedia_zona(" in information
    assert "ficha_breve_html(" in information
