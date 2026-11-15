"""Regresión en navegador: ampliar un GeoTIFF no debe reiniciar el mapa."""


def test_zoom_y_centro_geotiff_se_conservan_al_cambiar_panel_y_capas(abrir):
    p = abrir()
    p.ver_historico("cambio_vv_20260924_20261006_dif_db")
    assert len(p.capas_resultado()) == 1
    p.mapa.evaluate("()=>map.setView([7.68, -76.67], 13)")
    p.esperar(1500)
    zoom, lat, lon = p.vista()
    assert zoom == 13, f"El zoom del GeoTIFF se reinició a {zoom}"
    assert abs(lat - 7.68) < .01 and abs(lon + 76.67) < .01
    assert len(p.capas_resultado()) == 1

    # Cambiar una ventana fuerza rerun de Streamlit, nunca debe cambiar mapa.
    p.clic("btn_info")
    zoom, lat, lon = p.vista()
    assert zoom == 13 and abs(lat - 7.68) < .01 and abs(lon + 76.67) < .01
    assert len(p.capas_resultado()) == 1

    # Una segunda ampliación no debe regresar al encuadre anterior.
    p.mapa.evaluate("()=>map.zoomIn()")
    p.esperar(1500)
    assert p.vista()[0] == 14
    assert len(p.capas_resultado()) == 1 and not p.errores
