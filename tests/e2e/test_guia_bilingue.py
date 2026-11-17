"""E2E del panel persistente y del selector Español / English (sin servicios externos)."""


def test_guia_sobrevive_pan_zoom_cambios_y_se_puede_reabrir(abrir):
    p = abrir(1440, 900)
    p.marcar_mapa()
    boton = p.page.locator(".st-key-visor_guia_toggle button").first
    boton.click()
    panel = p.page.locator(".st-key-visor_guia_panel")
    panel.wait_for(state="visible", timeout=15_000)
    assert "Bienvenido a V.I.S.O.R." in panel.inner_text()

    p.mapa.evaluate("()=>{map.panBy([45, 30]);map.setZoom(map.getZoom()+1)}")
    p.esperar(1300)
    assert panel.is_visible(), "el mapa nunca puede cerrar la guía"
    assert p.mapa_intacto(), "mover el mapa no debe recrear Folium"

    vista_antes = p.vista()
    p.page.locator(".st-key-visor_idioma_en button").first.click()
    p.esperar(400)
    p.esperar_mapa()
    vista_despues = p.vista()
    assert abs(vista_despues[1] - vista_antes[1]) < 0.1
    assert abs(vista_despues[2] - vista_antes[2]) < 0.1
    p.marcar_mapa()
    assert panel.is_visible() and "Welcome to V.I.S.O.R." in panel.inner_text()
    assert "Explorer" in p.page.locator(".st-key-barra_superior").inner_text()

    p.page.locator(".st-key-visor_guia_cerrar button").first.click()
    panel.wait_for(state="hidden", timeout=15_000)
    p.page.locator(".st-key-visor_guia_toggle button").first.click()
    panel.wait_for(state="visible", timeout=15_000)
    assert "Welcome to V.I.S.O.R." in panel.inner_text()
    assert p.mapa_intacto()


def test_idiomas_y_busqueda_sin_navegacion_ni_sar(abrir):
    p = abrir(390, 844, movil=True)
    p.marcar_mapa()
    vista_antes = p.vista()
    p.page.locator(".st-key-visor_idioma_en button").first.click()
    p.esperar(400)
    p.esperar_mapa()
    vista_despues = p.vista()
    assert abs(vista_despues[1] - vista_antes[1]) < 0.1
    assert abs(vista_despues[2] - vista_antes[2]) < 0.1
    p.marcar_mapa()
    assert "Explorer" in p.page.locator(".st-key-barra_superior").inner_text()
    p.page.locator(".st-key-visor_guia_toggle button").first.click()
    panel = p.page.locator(".st-key-visor_guia_panel")
    panel.wait_for(state="visible", timeout=15_000)

    busqueda = p.page.locator(".st-key-visor_guia_busqueda input")
    busqueda.fill("NoData")
    p.esperar(450)
    assert "NoData" in panel.inner_text()
    assert panel.is_visible()
    p.page.locator(".st-key-visor_idioma_es button").first.click()
    p.esperar(450)
    p.esperar_mapa()
    p.marcar_mapa()
    assert "Bienvenido a V.I.S.O.R." in panel.inner_text()
    assert p.mapa_intacto()
