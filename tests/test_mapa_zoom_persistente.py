"""Regresión: zoom y centro no se reinician en cada interacción con Streamlit."""
from components import mapa


def test_el_zoom_del_usuario_sobrevive_a_reruns_y_cambio_de_capas(monkeypatch):
    estado = {}
    monkeypatch.setattr(mapa.st, "session_state", estado)
    assert mapa._centro_y_zoom_guardados(None) == (None, None)

    # La devolución real de Leaflet tiene zoom, centro y bounds.
    estado["mapa"] = {
        "zoom": 14,
        "center": {"lat": 7.675, "lng": -76.675},
        "bounds": {
            "_southWest": {"lat": 7.6, "lng": -76.7},
            "_northEast": {"lat": 7.75, "lng": -76.6},
        },
        "all_drawings": [],
    }
    mapa._guardar_encuadre_usuario()
    assert mapa._centro_y_zoom_guardados(None) == ([7.675, -76.675], 14.0)

    # Cambiar IDEAM / DANE o la opacidad no es navegación explícita.
    estado["visor_mapa_alertas_ideam"] = False
    estado["res_opacidad"] = .35
    assert mapa._centro_y_zoom_guardados(None) == ([7.675, -76.675], 14.0)

    # Nuevo zoom/arrastre sobre el mismo resultado se refleja inmediatamente.
    estado["mapa"] = {
        **estado["mapa"], "zoom": 17, "center": {"lat": 7.69, "lng": -76.66},
    }
    mapa._guardar_encuadre_usuario()
    assert mapa._centro_y_zoom_guardados(None) == ([7.69, -76.66], 17.0)


def test_solo_una_navegacion_explicita_puede_recentrar(monkeypatch):
    estado = {"mapa_encuadre_usuario": {"centro": [7.69, -76.66], "zoom": 17}}
    monkeypatch.setattr(mapa.st, "session_state", estado)
    destino = {"centro": [7.675, -76.675], "zoom": 12, "n": 10}

    nuevo = mapa._centro_y_zoom_guardados(destino)
    assert nuevo[1] > 12 and nuevo[1] < 12.001
    assert nuevo[0][0] > 7.675
    # Un rerun posterior NO restaura el destino: respeta al usuario.
    estado["mapa_encuadre_usuario"] = {"centro": [7.70, -76.65], "zoom": 15.0}
    assert mapa._centro_y_zoom_guardados(destino) == ([7.70, -76.65], 15.0)
    # Una petición nueva sí mueve.
    otro = mapa._centro_y_zoom_guardados({**destino, "n": 11})
    assert otro[1] > 12
    assert estado["mapa_ultimo_destino"] == 11


def test_fallback_a_bounds_mercator_y_valores_invalidos(monkeypatch):
    estado = {}
    monkeypatch.setattr(mapa.st, "session_state", estado)
    estado["mapa"] = {"zoom": 12, "bounds": {
        "_southWest": {"lat": 7.5, "lng": -76.8},
        "_northEast": {"lat": 7.8, "lng": -76.4},
    }}
    mapa._guardar_encuadre_usuario()
    assert mapa._centro_y_zoom_guardados(None) == ([7.65, -76.6], 12.0)
    estado["mapa"] = {"zoom": None}
    mapa._guardar_encuadre_usuario()
    assert mapa._centro_y_zoom_guardados(None) == ([7.65, -76.6], 12.0)
