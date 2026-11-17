"""Regresiones cartograficas, sin abrir ni modificar GeoTIFF ni pedir NASA."""
from types import SimpleNamespace

import folium

from components import flujo, mapa


def test_confirmar_otra_zona_centra_y_elimina_encuadre_antiguo(monkeypatch):
    anterior = (-76.8, 5.6, -76.6, 5.8)
    nueva = (-76.76, 7.62, -76.60, 7.78)
    estado = {
        "zona": {"limites": anterior, "origen": "busqueda"},
        "lugar": {"etiqueta": "Quibdo", "latitud": 5.7, "longitud": -76.7},
        "vista": {"centro": [5.7, -76.7], "zoom": 14, "n": 4},
        "mapa_ultimo_destino": 4,
        "mapa_encuadre_usuario": {"centro": [5.7, -76.7], "zoom": 14},
        "mapa_limites": anterior,
    }
    monkeypatch.setattr(flujo.st, "session_state", estado)
    monkeypatch.setattr(flujo.sesion, "validar_zona", lambda b: tuple(b))

    flujo.confirmar_zona(nueva, "seleccion confirmada")

    assert estado["zona"]["limites"] == nueva
    assert estado["vista"]["centro"] == [(nueva[1] + nueva[3]) / 2,
                                          (nueva[0] + nueva[2]) / 2]
    assert estado["vista"]["n"] == 5
    assert "mapa_encuadre_usuario" not in estado
    assert "mapa_ultimo_destino" not in estado
    assert "mapa_limites" not in estado
    assert estado["lugar"] is None


def test_reconfirmar_la_misma_aoi_no_mueve_el_mapa(monkeypatch):
    aoi = (-76.76, 7.62, -76.60, 7.78)
    vista = {"centro": [7.69, -76.66], "zoom": 16, "n": 7}
    encuadre = {"centro": [7.70, -76.64], "zoom": 17}
    estado = {
        "zona": {"limites": aoi, "origen": "busqueda"},
        "vista": vista,
        "mapa_encuadre_usuario": encuadre,
        "mapa_ultimo_destino": 7,
    }
    monkeypatch.setattr(flujo.st, "session_state", estado)
    monkeypatch.setattr(flujo.sesion, "validar_zona", lambda b: tuple(b))

    flujo.confirmar_zona(aoi, "misma zona")

    assert estado["vista"] is vista
    assert estado["mapa_encuadre_usuario"] is encuadre
    assert estado["mapa_ultimo_destino"] == 7


def test_cambio_aoi_remonta_una_vez_pero_pan_zoom_no(monkeypatch):
    a = (-76.8, 5.6, -76.6, 5.8)
    b = (-76.76, 7.62, -76.60, 7.78)
    estado = {"visor_idioma": "en", "zona": {"limites": a}}
    monkeypatch.setattr(mapa.st, "session_state", estado)
    monkeypatch.setattr(mapa, "mapa_fijo", lambda: object())
    monkeypatch.setattr(mapa, "construir_capas", lambda *_: [])
    llamadas = []

    def folium_falso(*_args, **kwargs):
        llamadas.append(kwargs)
        return {"all_drawings": None}

    monkeypatch.setattr(mapa, "st_folium", folium_falso)
    controles = SimpleNamespace(resultados={}, hidrografia=False, vias=False)

    mapa.render(None, None, controles)
    mapa.render(None, None, controles)  # mover mapa sin nuevo AOI
    estado["zona"] = {"limites": b}
    mapa.render(None, None, controles)
    mapa.render(None, None, controles)  # zoom tras nueva AOI
    assert llamadas[0]["key"] == llamadas[1]["key"]
    assert llamadas[1]["key"] != llamadas[2]["key"]
    assert llamadas[2]["key"] == llamadas[3]["key"]
    assert all(c["returned_objects"] == ["all_drawings"] for c in llamadas)


def test_almacenamiento_del_viewport_por_aoi_y_navegacion_explicita():
    a = mapa._identificador_vista_zona({"limites": (-76.8, 5.6, -76.6, 5.8)})
    b = mapa._identificador_vista_zona({"limites": (-76.76, 7.62, -76.6, 7.78)})
    assert a != b
    assert a == mapa._identificador_vista_zona(
        {"limites": [-76.8000000001, 5.6, -76.6, 5.8]})

    m = folium.Map(location=[7.67, -76.67])
    mapa.RecordarVistaNavegador(a, ignorar_restauracion=True).add_to(m)
    script = m.get_root().render()
    assert "visor-mapa-vista:" + a in script
    assert "if (!true)" in script
    assert "visor-mapa-vista:{{" not in script
