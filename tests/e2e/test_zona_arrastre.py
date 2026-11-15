"""Navegador: dibujar desde una esquina y reemplazar la selección anterior."""
def _arrastrar(pagina, x0, y0, x1, y1):
    pagina.page.mouse.move(x0, y0)
    pagina.page.mouse.down()
    pagina.page.mouse.move(x1, y1, steps=12)
    pagina.page.mouse.up()
    pagina.esperar(1200)


def test_dibujo_por_arrastre_reemplaza_la_zona_previa(abrir):
    pagina = abrir()
    pagina.clic("btn_sar")
    marco = pagina.page.locator("iframe[title*='streamlit_folium']").first
    caja = marco.bounding_box()
    assert caja and caja["width"] > 500
    control = pagina.mapa.locator(".visor-zona-drag a")
    assert control.count() == 1 and control.is_visible()

    control.click()
    x = caja["x"] + caja["width"] * .53
    y = caja["y"] + caja["height"] * .46
    _arrastrar(pagina, x, y, x + 85, y + 80)
    assert pagina.page.locator(".st-key-zona_usar_dibujo button").count() == 1
    assert pagina.mapa.evaluate(
        "()=>window.drawnItems && window.drawnItems.getLayers().length") == 1
    pagina.clic("zona_usar_dibujo")
    assert "ZONA CONFIRMADA" in pagina.texto("panel_sar")

    pagina.mapa.locator(".visor-zona-drag a").click()
    _arrastrar(pagina, x + 115, y + 50, x + 185, y + 140)
    assert pagina.mapa.evaluate(
        "()=>window.drawnItems && window.drawnItems.getLayers().length") == 1
    assert pagina.page.locator(".st-key-zona_usar_dibujo button").count() == 1
    assert "ZONA CONFIRMADA" not in pagina.texto("panel_sar")
    assert not pagina.errores
