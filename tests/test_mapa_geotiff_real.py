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


def test_areas_sin_cambio_y_ruido_aislado_transparentes_sin_tocar_datos():
    # Prueba sintética SOLO del renderizador: tres píxeles negativos vecinos
    # se resaltan; señales aisladas, cambio ≤ 2 y NoData son transparentes.
    datos = np.ma.array(np.zeros((6, 9), dtype="float32"))
    datos[1, 1] = -3.1
    datos[1, 2] = -5.4
    datos[2, 2] = -2.6
    datos[4, 7] = -6.0
    datos[0, 6] = 5.0
    datos[0, 7] = 3.0
    datos[1, 7] = 4.0
    datos[2, 5] = 1.5
    datos[3, 3] = -9999
    datos.mask = np.zeros(datos.shape, dtype=bool)
    datos.mask[3, 3] = True
    original = np.full((6, 9, 4), 120, dtype="uint8")
    copia = datos.copy()
    rgba = mapa.realzar_alpha_delta(original, datos)

    assert tuple(rgba[1, 1]) == (0, 227, 255, 238)
    assert tuple(rgba[1, 2]) == (24, 113, 255, 248)
    assert tuple(rgba[2, 2]) == (76, 190, 255, 115)
    assert tuple(rgba[0, 6]) == (255, 145, 64, 82)
    assert rgba[4, 7, 3] == 0  # disminución aislada
    assert rgba[2, 5, 3] == 0  # variación menor a 2 dB
    assert rgba[3, 3, 3] == 0  # NoData
    assert rgba[0, 0, 3] == 0  # sin cambios
    np.testing.assert_array_equal(original, np.full((6, 9, 4), 120, dtype="uint8"))
    np.testing.assert_array_equal(datos.data, copia.data)
    np.testing.assert_array_equal(np.ma.getmaskarray(datos), np.ma.getmaskarray(copia))


def test_leyenda_declara_transparencia_visual():
    from components import resultados as ui
    from types import SimpleNamespace
    res = SimpleNamespace(dibujable=True, nombre="ΔdB", perfil=SimpleNamespace(
        continuo=True, nota="Valores completos conservados", clases=()))
    texto = ui.leyenda_html(res)
    assert "|Δ| ≤ 2 dB" in texto
    assert "transparente en el mapa" in texto
    assert "disminuciones agrupadas" in texto
    assert "Sin dato (NoData)" in texto


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
