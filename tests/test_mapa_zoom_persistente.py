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



def test_pan_y_zoom_normal_no_disparan_rerun_del_servidor(monkeypatch):
    """Los eventos de encuadre se quedan en Leaflet salvo herramientas que los necesitan."""
    from types import SimpleNamespace

    estado = {"visor_idioma": "en"}
    monkeypatch.setattr(mapa.st, "session_state", estado)
    monkeypatch.setattr(mapa, "mapa_fijo", lambda: object())
    monkeypatch.setattr(mapa, "construir_capas", lambda *_: [])
    monkeypatch.setattr(mapa, "_centro_y_zoom_guardados", lambda *_: (None, None))
    llamados = []

    def folium_falso(*args, **kwargs):
        llamados.append(kwargs)
        return {"all_drawings": None}  # pan/zoom no cambia dibujos

    monkeypatch.setattr(mapa, "st_folium", folium_falso)
    control = SimpleNamespace(resultados={}, hidrografia=False, vias=False)
    mapa.render(None, None, control)
    mapa.render(None, None, control)  # simulación de rerun por otro widget
    assert len(llamados) == 2
    assert [x["returned_objects"] for x in llamados] == [
        ["all_drawings"], ["all_drawings"],
    ]
    assert llamados[0]["key"] == llamados[1]["key"], "no remontar Leaflet en zoom"
    assert "on_change" in llamados[0]


def test_capturar_encuadre_solo_al_activar_modo_area_visible_o_capas_recortadas(monkeypatch):
    from types import SimpleNamespace

    estado = {"visor_idioma": "en"}
    monkeypatch.setattr(mapa.st, "session_state", estado)
    monkeypatch.setattr(mapa, "mapa_fijo", lambda: object())
    monkeypatch.setattr(mapa, "construir_capas", lambda *_: [])
    monkeypatch.setattr(mapa, "_centro_y_zoom_guardados", lambda *_: (None, None))
    llamadas = []

    def folium_falso(*args, **kwargs):
        llamadas.append(kwargs)
        return {"all_drawings": None, "bounds": {
            "_southWest": {"lat": 5.6, "lng": -76.8},
            "_northEast": {"lat": 5.8, "lng": -76.5},
        }}

    monkeypatch.setattr(mapa, "st_folium", folium_falso)
    normal = SimpleNamespace(resultados={}, hidrografia=False, vias=False)
    mapa.render(None, None, normal)
    mapa.render(None, None, normal, seguir_vista=True)
    mapa.render(None, None, normal, seguir_vista=True)
    mapa.render(None, None, SimpleNamespace(resultados={}, hidrografia=True, vias=False))
    assert llamadas[0]["returned_objects"] == ["all_drawings"]
    assert all(x["returned_objects"] == ["all_drawings", "bounds", "zoom", "center"]
               for x in llamadas[1:])
    assert llamadas[1]["key"] == llamadas[2]["key"]
    assert llamadas[1]["key"].endswith("__seguir_vista")
    assert estado["mapa_limites"] == (-76.8, 5.6, -76.5, 5.8)



def test_resultado_nuevo_recupera_zoom_del_navegador_sin_navegacion_explicita(monkeypatch):
    """Al cambiar un raster se respeta el viewport local; recomendación sí puede centrar."""
    from types import SimpleNamespace

    estado = {"visor_idioma": "en", "mapa_ultimo_destino": 4}
    monkeypatch.setattr(mapa.st, "session_state", estado)
    monkeypatch.setattr(mapa, "mapa_fijo", lambda: object())
    monkeypatch.setattr(mapa, "construir_capas", lambda *_: [])
    monkeypatch.setattr(mapa, "_centro_y_zoom_guardados", lambda *_: ([7.67, -76.67], 13.0))
    llamadas = []

    def fake_folium(*args, **kwargs):
        llamadas.append(kwargs)
        return {"all_drawings": None}

    monkeypatch.setattr(mapa, "st_folium", fake_folium)
    vista = {"centro": [7.67, -76.67], "zoom": 13, "n": 4}
    mapa.render(None, None, SimpleNamespace(resultados={"uno": .85}, hidrografia=False, vias=False),
                vista=vista)
    mapa.render(None, None, SimpleNamespace(resultados={"dos": .85}, hidrografia=False, vias=False),
                vista=vista)
    assert llamadas[0]["center"] == [7.67, -76.67]
    assert llamadas[1]["center"] is None and llamadas[1]["zoom"] is None
    assert llamadas[0]["key"] != llamadas[1]["key"]
    mapa.render(None, None, SimpleNamespace(resultados={"tres": .85}, hidrografia=False, vias=False),
                vista={**vista, "n": 5})
    assert llamadas[2]["center"] == [7.67, -76.67]
    assert llamadas[2]["zoom"] == 13.0


def test_leaflet_conserva_vista_localmente_sin_guardar_datos_sar():
    from folium import MacroElement
    assert issubclass(mapa.RecordarVistaNavegador, MacroElement)
    import folium

    m = folium.Map(location=[7.67, -76.67])
    mapa.RecordarVistaNavegador().add_to(m)
    script = m.get_root().render()
    assert "sessionStorage" in script
    assert "moveend" in script
    assert "getCenter" in script and "getZoom" in script
    assert "GeoTIFF" not in script and "fetch(" not in script


def test_fragmento_mapa_lee_resultados_frescos_y_no_reactiva_historico(monkeypatch):
    """Un evento posterior de zoom no puede revivir overlays del rerun anterior."""
    from components import capas_ambientales, herramientas_sar, v9_experiencia
    from components.barra_lateral import Controles

    controles_antiguos = Controles("inundacion", False, .85, False, False,
                                 resultados={"historico": .8})
    controles_nuevos = Controles("inundacion", False, .85, False, False,
                               resultados={"nisar_actual": .8})
    estado = {
        "vista": {"centro": [7.67, -76.67], "zoom": 12, "n": 3},
        "visor_mapa_render_actual": {
            "fenomeno": "inundacion", "capa": None,
            "controles": controles_antiguos, "resultados": ["historico"],
        },
    }
    monkeypatch.setattr(mapa.st, "session_state", estado)
    monkeypatch.setattr(herramientas_sar, "grupos_mapa", lambda: [])
    monkeypatch.setattr(herramientas_sar, "necesita_vista", lambda: False)
    monkeypatch.setattr(capas_ambientales, "grupos_mapa", lambda: [])
    monkeypatch.setattr(v9_experiencia, "grupos_mapa", lambda: [])
    monkeypatch.setattr(v9_experiencia, "modo_seleccion_mapa", lambda: False)
    vistos = []

    def render_falso(_fenomeno, _capa, controles, _vista, resultados, _extras,
                     **_kwargs):
        vistos.append((set(controles.resultados), list(resultados)))

    monkeypatch.setattr(mapa, "render", render_falso)
    mapa._render_estado_actual()
    estado["visor_mapa_render_actual"] = {
        "fenomeno": "inundacion", "capa": None,
        "controles": controles_nuevos, "resultados": ["nisar_actual"],
    }
    mapa._render_estado_actual()  # solo el fragmento se vuelve a ejecutar
    assert vistos == [
        ({"historico"}, ["historico"]),
        ({"nisar_actual"}, ["nisar_actual"]),
    ]


def test_fragmento_recorta_contexto_con_viewport_nuevo(monkeypatch):
    """Ríos y vías toman los bounds actuales, sin dejar el viewport anterior."""
    from components import capas_ambientales, herramientas_sar, v9_experiencia
    from components.barra_lateral import Controles

    previo = (-76.8, 5.6, -76.6, 5.8)
    nuevo = (-76.6, 6.9, -76.4, 7.1)
    controles = Controles("inundacion", False, .85, False, False,
                        hidrografia=True, vista_limites=previo, vista_zoom=9)
    estado = {"visor_mapa_render_actual": {
        "fenomeno": "inundacion", "capa": None,
        "controles": controles, "resultados": [],
    }}
    monkeypatch.setattr(mapa.st, "session_state", estado)
    monkeypatch.setattr(mapa, "vista_actual", lambda _vista: (nuevo, 13))
    monkeypatch.setattr(herramientas_sar, "grupos_mapa", lambda: [])
    monkeypatch.setattr(herramientas_sar, "necesita_vista", lambda: False)
    monkeypatch.setattr(capas_ambientales, "grupos_mapa", lambda: [])
    monkeypatch.setattr(v9_experiencia, "grupos_mapa", lambda: [])
    monkeypatch.setattr(v9_experiencia, "modo_seleccion_mapa", lambda: False)
    vistos = []

    def render_falso(_fenomeno, _capa, c, *_args, **_kwargs):
        vistos.append((c.vista_limites, c.vista_zoom))

    monkeypatch.setattr(mapa, "render", render_falso)
    mapa._render_estado_actual()
    assert vistos == [(nuevo, 13)]
    assert controles.vista_limites == previo  # no muta los controles del panel


def test_app_entrega_snapshot_actual_al_fragmento():
    from pathlib import Path
    archivo = Path(__file__).resolve().parents[1] / "app.py"
    codigo = archivo.read_text(encoding="utf-8")
    assert 'st.session_state["visor_mapa_render_actual"] = {' in codigo
    assert "mapa.render_vivo()" in codigo

