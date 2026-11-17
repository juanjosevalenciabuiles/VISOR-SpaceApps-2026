"""Selección rectangular por arrastre, zona única y marca inundaciones."""
import inspect
import json
import re

from components import flujo, interfaz, mapa


def _rectangulo(oeste: float, sur: float, este: float, norte: float) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[
            [oeste, sur], [este, sur], [este, norte], [oeste, norte], [oeste, sur],
        ]]},
        "properties": {},
    }


def test_control_hoja_leaflet_permite_arrastre_y_conserva_un_solo_rectangulo():
    m = mapa.mapa_fijo()
    m.get_root().render()
    script = m.get_root().script.render()
    # La referencia al FeatureGroup es la real que Folium creó; sin IDs
    # fabricados ni un componente JS alterno que pierde el mapa de Streamlit.
    identificador = re.search(r"var (drawnItems_\w+)\s*=", script)
    assert identificador, "Falta el FeatureGroup de Leaflet Draw"
    assert script.count(identificador.group(1)) >= 5
    assert "window.drawnItems = dibujos" in script
    assert "visor-zona-drag" in script
    assert "Seleccionar zona" in script
    assert "new L.Draw.Rectangle(mapa" in script
    assert "dibujos.clearLayers()" in script
    assert "draw:drawstart" in script and "draw:created" in script
    assert "drawnItems_" in script
    assert "alert(coords)" not in script


def test_nueva_seleccion_anula_zona_confirmada_y_resultado_no_historial(monkeypatch):
    anterior = _rectangulo(-76.90, 7.45, -76.73, 7.61)
    nueva = _rectangulo(-76.65, 7.62, -76.48, 7.79)
    estado = {
        "zona": {"limites": (-76.90, 7.45, -76.73, 7.61), "origen": "dibujo",
                 "geometria": anterior["geometry"]},
        "resultado_activo": {"id": "archivo_real_anterior"},
        "mapa_dibujo": anterior,
        "mapa_firma_dibujo": json.dumps(anterior, sort_keys=True),
        "v9_preparacion": "trabajo_anterior",
        "ui_sar": "cerrado",
        "ui_explorador": True,
        "historico_en_disco": "sin_modificar",
    }
    monkeypatch.setattr(mapa.st, "session_state", estado)
    assert mapa._sincronizar_zona_dibujada([anterior, nueva])
    assert estado["zona"] is not None
    assert estado["zona"]["origen"] == "rectángulo dibujado en el mapa"
    assert tuple(estado["zona"]["limites"]) == (-76.65, 7.62, -76.48, 7.79)
    assert estado["resultado_activo"] is None
    assert estado["mapa_dibujo"] == nueva
    assert "v9_preparacion" not in estado
    assert estado["historico_en_disco"] == "sin_modificar"
    assert estado["ui_sar"] == "abierto" and estado["ui_explorador"] is False
    assert not mapa._sincronizar_zona_dibujada([nueva])  # no bucles de rerun


def test_borrar_dibujo_no_vuelve_a_mostrar_una_zona_obsoleta(monkeypatch):
    dibujo = _rectangulo(-76.65, 7.62, -76.48, 7.79)
    estado = {
        "zona": {"limites": (-76.65, 7.62, -76.48, 7.79), "origen": "dibujo"},
        "mapa_dibujo": dibujo,
        "mapa_firma_dibujo": json.dumps(dibujo, sort_keys=True),
        "resultado_activo": {"id": "anterior"},
    }
    monkeypatch.setattr(mapa.st, "session_state", estado)
    assert mapa._sincronizar_zona_dibujada([])
    assert estado["zona"] is None
    assert estado["mapa_dibujo"] is None
    assert estado["resultado_activo"] is None
    assert not mapa._sincronizar_zona_dibujada([])


def test_cambiar_zona_quita_dibujo_pendiente_pero_deja_huella_para_no_repetir(monkeypatch):
    dibujo = _rectangulo(-76.8, 7.5, -76.7, 7.6)
    firma = json.dumps(dibujo, sort_keys=True)
    estado = {"zona": {"limites": (-76.8, 7.5, -76.7, 7.6)},
              "mapa_dibujo": dibujo, "mapa_firma_dibujo": firma}
    monkeypatch.setattr(flujo.st, "session_state", estado)
    flujo.quitar_zona()
    assert estado["zona"] is None and estado["mapa_dibujo"] is None
    assert estado["mapa_firma_dibujo"] == firma
    assert not mapa._sincronizar_zona_dibujada([dibujo])  # no reactivar


def test_marca_de_inundacion_en_barra_superior_con_texto_accesible():
    fuente = inspect.getsource(interfaz.barra_superior)
    assert "V.I.S.O.R." in fuente
    assert 'mc-marca-olas' in fuente
    assert 'aria-label="Agua e inundaciones"' in fuente
    assert "<svg viewBox=" in fuente
