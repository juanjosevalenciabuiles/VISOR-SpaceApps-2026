"""El onboarding no altera la sesión SAR ni vuelve a abrirse tras reruns."""
from pathlib import Path
import ast

from components import bienvenida

RAIZ = Path(__file__).resolve().parents[1]


def test_guia_de_inicio_solo_una_vez_por_sesion(monkeypatch):
    estado = {
        "zona": {"limites": (-76.8, 7.55, -76.55, 7.8)},
        "resultado_activo": {"id": "real"},
        "mapa_encuadre_usuario": {"centro": [7.65, -76.7], "zoom": 13},
    }
    monkeypatch.setattr(bienvenida.st, "session_state", estado)
    assert bienvenida.corresponde_mostrar()
    assert not bienvenida.corresponde_mostrar()
    assert estado["zona"] == {"limites": (-76.8, 7.55, -76.55, 7.8)}
    assert estado["resultado_activo"] == {"id": "real"}
    assert estado["mapa_encuadre_usuario"]["zoom"] == 13


def test_guia_se_muestra_despues_del_mapa_y_solo_en_app_principal():
    codigo = (RAIZ / "app.py").read_text(encoding="utf-8")
    arbol = ast.parse(codigo)
    assert arbol is not None
    assert codigo.index("mapa.render(") < codigo.index("bienvenida.mostrar()")
    assert "if bienvenida.corresponde_mostrar():" in codigo
    assert "from components import bienvenida" in codigo


def test_onboarding_explica_recorrido_real_sin_inventar_inundacion():
    codigo = (RAIZ / "components" / "bienvenida.py").read_text(encoding="utf-8")
    assert 'st.dialog("Bienvenido a V.I.S.O.R.' in codigo
    for item in ("Busca un lugar", "Selecciona tu zona", "Elige fechas",
                 "Analiza o revisa resultados", "Interpreta el mapa",
                 "no una inundación confirmada", "historial"):
        assert item in codigo
    assert "st.rerun()" in codigo
    assert "st.session_state" in codigo
    assert "rasterio" not in codigo
    assert "descargar" in codigo  # solo descripción del historial, sin llamada de red
