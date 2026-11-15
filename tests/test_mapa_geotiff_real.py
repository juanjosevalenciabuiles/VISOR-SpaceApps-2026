"""Regresiones: GeoTIFF real al mapa principal y recorte visual sin falsos datos."""
from types import SimpleNamespace

import numpy as np
from shapely.geometry import box

from components import exhibicion_real as muestra, mapa
from utils import alcance_geografico as alcance, sesion


def test_capa_real_costera_con_pixeles_colombianos_visible(monkeypatch):
    monkeypatch.setattr(alcance, "restringido", lambda: True)
    monkeypatch.setattr(alcance, "admitida", lambda _limites: False)
    monkeypatch.setattr(alcance, "geometria", lambda: box(0, 0, 2, 2))
    datos = np.ma.array([[1.0, 1.0], [1.0, 1.0]],
                        mask=[[True, False], [True, True]])
    capa = SimpleNamespace(
        limites=(-1.0, -1.0, 1.0, 1.0),
        datos=datos,
        procedencia=SimpleNamespace(es_real=True),
    )
    resultado = SimpleNamespace(capa=capa)
    disponibles, ocultos = alcance.filtrar_resultados([resultado])
    assert disponibles == [resultado] and ocultos == 0
    dentro = alcance.mascara_pixeles_colombia(capa)
    assert dentro.shape == datos.shape
    assert dentro[0, 1] and not dentro[0, 0]


def test_capa_sin_pixeles_colombianos_o_demostrativa_se_oculta(monkeypatch):
    monkeypatch.setattr(alcance, "restringido", lambda: True)
    monkeypatch.setattr(alcance, "admitida", lambda _limites: False)
    monkeypatch.setattr(alcance, "geometria", lambda: box(0, 0, 2, 2))
    datos = np.ma.array([[1.0, 1.0], [1.0, 1.0]],
                        mask=[[False, True], [True, True]])
    real = SimpleNamespace(capa=SimpleNamespace(
        limites=(-1, -1, 1, 1), datos=datos,
        procedencia=SimpleNamespace(es_real=True)))
    demo = SimpleNamespace(capa=SimpleNamespace(
        limites=(-1, -1, 1, 1), datos=np.ma.array([[1.0, 1.0], [1.0, 1.0]]),
        procedencia=SimpleNamespace(es_real=False)))
    visibles, ocultos = alcance.filtrar_resultados([real, demo])
    assert visibles == [] and ocultos == 2


def test_refuerzo_alpha_preserva_color_y_nodata():
    original = np.array([[[0, 0, 0, 0], [50, 110, 230, 38],
                          [200, 100, 70, 255]]], dtype=np.uint8)
    mostrado = mapa.realzar_alpha_delta(original)
    assert mostrado[0, 0, 3] == 0
    assert mostrado[0, 1, 3] == 192
    assert mostrado[0, 2, 3] == 255
    np.testing.assert_array_equal(mostrado[..., :3], original[..., :3])
    assert original[0, 1, 3] == 38


def test_geo_tif_real_se_activa_en_mapa_principal(monkeypatch):
    from components import flujo, interfaz
    estado = {"visor_modo_muestra_real": True, "capa_sar": True}
    llamadas = []
    monkeypatch.setattr(muestra.st, "session_state", estado)
    monkeypatch.setattr(alcance, "filtrar_resultados", lambda x: (x, 0))
    monkeypatch.setattr(flujo, "quitar_zona", lambda: llamadas.append("zona"))
    monkeypatch.setattr(flujo, "activar", lambda id_, origen: llamadas.append((id_, origen)))
    monkeypatch.setattr(interfaz, "centrar_en", lambda limites: llamadas.append(("vista", limites)))
    limites = (-77.5, 6.5, -76.5, 7.5)
    res = SimpleNamespace(id="nisar_real_1", dibujable=True, capa=SimpleNamespace(
        limites=limites, procedencia=SimpleNamespace(es_real=True)))
    muestra.abrir_resultado_en_mapa_principal(res, sesion.ANALISIS)
    assert llamadas == ["zona", ("nisar_real_1", sesion.ANALISIS), ("vista", limites)]
    assert estado["visor_modo_muestra_real"] is False
    assert estado["capa_sar"] is False
    assert estado["ui_info"] and estado["ui_explorador"]
    assert estado["ui_sar"] == "cerrado"


def test_exhibicion_rechaza_sinteticos(monkeypatch):
    import pytest
    res = SimpleNamespace(id="sintetico", dibujable=True, capa=SimpleNamespace(
        procedencia=SimpleNamespace(es_real=False)))
    with pytest.raises(ValueError, match="satelital real"):
        muestra.abrir_resultado_en_mapa_principal(res, sesion.HISTORICO)
