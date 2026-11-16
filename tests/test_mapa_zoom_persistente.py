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



def test_regresion_dos_geotiff_y_zoom_no_reactivan_historial(monkeypatch):
    """Folium debe recrearse al elegir otro GeoTIFF, pero no al hacer zoom."""
    from types import SimpleNamespace
    import inspect

    assert inspect.getsource(mapa.render).lstrip().startswith("def render("), (
        "Un fragmento del mapa reutiliza el GeoTIFF de una ejecución anterior"
    )
    estado = {"visor_idioma": "en"}
    monkeypatch.setattr(mapa.st, "session_state", estado)
    monkeypatch.setattr(mapa, "mapa_fijo", lambda: object())
    monkeypatch.setattr(mapa, "construir_capas", lambda *_: [])
    monkeypatch.setattr(mapa, "_centro_y_zoom_guardados", lambda *_: (None, None))
    claves = []

    def mapa_simulado(*args, **kwargs):
        claves.append(kwargs["key"])
        return {"all_drawings": [], "bounds": None}

    monkeypatch.setattr(mapa, "st_folium", mapa_simulado)

    def dibujar(id_resultado):
        controles = SimpleNamespace(resultados={id_resultado: 0.85})
        mapa.render(None, None, controles)

    dibujar("chigorodo")
    dibujar("otra_zona")
    dibujar("otra_zona")   # zoom: debe conservar el mismo componente/capa
    dibujar("chigorodo")   # cambio explícito: debe cambiar otra vez el componente

    assert claves == [
        "mapa__chigorodo__en", "mapa__otra_zona__en",
        "mapa__otra_zona__en", "mapa__chigorodo__en",
    ]


def test_resultado_nuevo_no_elimina_aoi_al_remontar_mapa(monkeypatch):
    from types import SimpleNamespace
    estado = {"visor_idioma": "en", "zona": {"limites": (-77, 7, -76, 8)},
              "mapa_firma_dibujo": "rectangulo_anterior"}
    monkeypatch.setattr(mapa.st, "session_state", estado)
    monkeypatch.setattr(mapa, "mapa_fijo", lambda: object())
    monkeypatch.setattr(mapa, "construir_capas", lambda *_: [])
    monkeypatch.setattr(mapa, "_centro_y_zoom_guardados", lambda *_: (None, None))
    monkeypatch.setattr(mapa, "st_folium",
                        lambda *args, **kwargs: {"all_drawings": [], "bounds": None})
    mapa.render(None, None, SimpleNamespace(resultados={"resultado_nuevo": 0.85}))
    assert estado["zona"]["limites"] == (-77, 7, -76, 8)
    assert estado["mapa_firma_dibujo"] is None
