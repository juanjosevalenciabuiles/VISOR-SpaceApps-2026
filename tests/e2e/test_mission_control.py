"""Mission Control: mapa único, navegación, paneles, Ir a…, ayuda y Herramientas SAR (estados)."""


def test_mapa_unico_y_superficies(abrir):
    p = abrir()
    assert p.mapa.evaluate("()=>{const r=document.querySelector('.leaflet-container').getBoundingClientRect();"
                           "return r.width>=innerWidth-1 && r.height>=innerHeight-1}")
    for clave in ("barra_superior", "panel_explorador", "panel_info", "linea_temporal"):
        assert p.visible(clave), clave
    assert not p.visible("panel_sar")
    assert p.mapa.evaluate("()=>document.querySelector('.leaflet-control-attribution').offsetHeight>0")
    assert not p.page.evaluate("()=>document.documentElement.scrollWidth>innerWidth")
    # Primera carga: ni resultados ni DEMO; el mapa base sí.
    assert "SIN RESULTADO" in p.texto("barra_superior") and "DEMO" not in p.texto("barra_superior")
    assert p.capas_resultado() == [] and "Cómo empezar" in p.texto("panel_info")
    assert not p.errores


def test_navegacion_y_cambios_sin_recrear_el_mapa(abrir):
    p = abrir()
    p.marcar_mapa()
    z0 = p.vista()[0]
    caja = p.page.viewport_size
    p.page.mouse.move(caja["width"] * 0.6, caja["height"] * 0.5)
    p.page.mouse.wheel(0, -600)
    p.page.wait_for_timeout(1200)
    assert p.vista()[0] > z0, "la rueda sobre el mapa hace zoom"
    v = p.vista()
    explorador = p.page.locator(".st-key-panel_explorador").bounding_box()
    p.page.mouse.move(explorador["x"] + 100, explorador["y"] + 200)
    p.page.mouse.wheel(0, -400)
    p.page.wait_for_timeout(800)
    assert p.vista() == v, "la rueda sobre un panel no mueve el mapa"

    p.demo("Deslizamientos")
    assert p.mapa_intacto() and p.vista() == v
    rgb = p.page.evaluate("()=>getComputedStyle(document.documentElement).getPropertyValue('--theme-rgb')")
    assert rgb.replace(" ", "") == "244,164,99"
    assert "Deslizamientos" in p.texto("barra_superior")
    assert not p.errores


def test_paneles_conservan_su_estado(abrir):
    p = abrir()
    p.demo("Deforestación")
    p.clic("cerrar_explorador")
    assert not p.visible("panel_explorador")
    p.clic("btn_explorador")
    assert p.visible("panel_explorador")
    marcado = p.page.locator(".st-key-fenomeno [data-testid=stRadioOption]:has(input:checked)").inner_text()
    assert "Deforestación" in marcado
    p.clic("cerrar_info")
    assert not p.visible("panel_info")
    p.clic("btn_info")
    assert p.visible("panel_info")


def test_ir_a(abrir):
    p = abrir()
    p.marcar_mapa()
    p.clic("popover_ir")
    campos = p.page.locator("[data-testid=stPopoverBody] input")
    assert [campos.nth(i).input_value() for i in range(2)] == ["7.6750", "-76.6750"]
    campos.nth(0).fill("6,25")
    campos.nth(0).press("Enter")
    campos.nth(1).fill("-75.57")
    campos.nth(1).press("Enter")
    p.esperar(800)
    p.clic("btn_ir")
    assert p.vista()[1:] == [6.25, -75.57] and p.mapa_intacto()
    campos.nth(0).fill("850")
    campos.nth(0).press("Enter")
    p.esperar(800)
    p.clic("btn_ir")
    assert p.vista()[1:] == [6.25, -75.57], "un valor inválido no mueve el mapa"
    assert "entre -85 y 85" in p.page.evaluate("()=>document.body.innerText")
    p.clic("btn_chigorodo")
    assert p.vista() == [11, 7.675, -76.675]
    p.clic("btn_inicio")
    assert p.vista() == [8, 7.0, -75.5] and p.mapa_intacto()


def test_ayuda_explica_procedencia(abrir):
    p = abrir()
    p.clic("btn_ayuda")
    dialogo = p.page.locator("[role=dialog]").inner_text()
    for frase in ("DEMO", "PROCEDENCIA NO DECLARADA", "REAL SIN VALIDAR", "VALIDADO", "NISAR"):
        assert frase in dialogo


def test_herramientas_sar_abrir_minimizar_restaurar_cerrar(abrir):
    p = abrir()
    p.marcar_mapa()
    p.clic("btn_sar")
    assert p.visible("panel_sar") and not p.visible("panel_explorador")
    p.page.locator(".st-key-panel_sar [role=tab]").nth(2).click()
    p.esperar(800)
    p.clic("minimizar_sar")
    assert p.visible("sar_minimizado") and not p.visible("panel_sar")
    p.clic("restaurar_sar")
    seleccionada = p.page.locator(".st-key-panel_sar [role=tab][aria-selected=true]").inner_text()
    assert seleccionada.startswith("03")
    p.clic("cerrar_sar")
    assert not p.visible("panel_sar") and p.visible("panel_explorador") and p.mapa_intacto()
