"""Recorrido real de extremo a extremo en el navegador (orden del 13-nov-2026, P0-01…P0-24).

Escenarios: A «todavía no analicé» · B «acabo de analizar» · C «cambié de zona» ·
D «me equivoqué o no hay datos» · E «quiero revisar lo anterior».

El catálogo de ASF es una respuesta real guardada (la app lo rotula CATÁLOGO SIMULADO) y los RTC
son sintéticos con nombres de HyP3: aquí se prueba el FLUJO, no la ciencia. La reproducción con
los RTC auténticos de Chigorodó está en tests/test_recorrido.py (se ejecuta donde existan).
"""
import hashlib
import json
import re

import pytest

from conftest import Servidor, preparar_datos

REPRODUCIBLE = "coincidencia_vv_vh_20260924_20261006"
EXPLORATORIO = "coincidencia_vv_vh_chigorodo"


@pytest.fixture(scope="module")
def servidor_propio(tmp_path_factory):
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("recorrido") / "data"))
    yield s
    s.cerrar()


def huellas(carpeta):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in carpeta.iterdir() if p.is_file()}


def sin_resultado(p) -> bool:
    barra, info = p.texto("barra_superior"), p.texto("panel_info")
    return (p.capas_resultado() == [] and "SIN RESULTADO" in barra and "Cómo empezar" in info
            and "Píxeles" not in info and not re.search(r"\d ha\b", info) and "DEMO · DATOS" not in barra)


def buscar_par(p):
    p.pestana_sar(1)
    p.clic("sar_buscar")


def test_a_todavia_no_analice(abrir, servidor_propio):
    """P0-01/02/03/04/06/14/15: sin pulsar «Analizar» no hay ráster, cifras ni DEMO, pase lo que pase."""
    analisis = servidor_propio.datos / "analisis"
    previas = huellas(analisis)
    p = abrir(url=servidor_propio.url)
    p.marcar_mapa()
    assert sin_resultado(p), "primera carga"
    assert len(list(analisis.glob("*.tif"))) >= 3, "hay archivos en disco y aun así no se dibujan"
    assert "CONCEPTUAL" in p.texto("linea_temporal").upper()

    # Buscar un lugar: mueve el mapa y pone un marcador; no crea zona ni resultado.
    p.escribir("lugar_texto", "rionegro")
    p.clic("lugar_buscar")
    assert "varias coincidencias" in p.texto("panel_explorador") and p.vista()[0] == 8, "ambiguo: no elige solo"
    p.clic("lugar_ir_0")
    assert p.vista() == [12, 6.15, -75.37] and "UBICADO" in p.texto("panel_explorador")
    p.escribir("lugar_texto", "Chigorodó")
    p.clic("lugar_buscar")
    assert p.vista() == [11, 7.67, -76.68] and p.trazos() >= 1 and sin_resultado(p)

    # Mover el mapa y cambiar el fondo.
    p.page.mouse.move(700, 450)
    p.page.mouse.wheel(0, -300)
    p.page.wait_for_timeout(1000)
    p.page.locator(".st-key-mapa_base [role=combobox]").first.click()
    p.page.locator("[role=option]").nth(2).click()
    p.esperar()
    assert sin_resultado(p) and p.mapa_intacto()

    # Dibujar no es confirmar: hasta «Usar esta zona» no hay zona y el catálogo sigue bloqueado.
    p.clic("lugar_definir_zona")
    assert "Aún no hay zona" in p.texto("panel_sar")
    p.dibujar_rectangulo()
    panel = p.texto("panel_sar")
    assert "Dibujo actual" in panel and "ZONA CONFIRMADA" not in panel
    p.pestana_sar(1)
    assert "Primero define y confirma la zona" in p.texto("panel_sar")
    p.pestana_sar(0)
    p.clic("zona_usar_dibujo")
    panel = p.texto("panel_sar")
    assert "ZONA CONFIRMADA" in panel and "dibujo en el mapa" in panel and sin_resultado(p)

    # Catálogo: imágenes y huellas de ENTRADA, ningún ráster de resultado.
    antes = p.trazos()
    buscar_par(p)
    panel = p.texto("panel_sar")
    assert "CATÁLOGO SIMULADO" in panel and "pares compatibles" in panel and "Imágenes encontradas" in panel
    assert p.trazos() > antes, "huellas de entrada"
    assert "no es un resultado" in p.mapa.evaluate(
        "()=>{const o=[];map.eachLayer(l=>{const t=l.getTooltip&&l.getTooltip();if(t)o.push(t.getContent())});"
        "return o.join('|')}")
    p.pestana_sar(2)
    p.pestana_sar(3)
    assert "No hay ningún resultado en el mapa" in p.texto("panel_sar"), p.texto("panel_sar")[-600:]
    assert sin_resultado(p) and p.mapa_intacto() and not p.errores
    assert huellas(analisis) == previas, "nada se calculó ni se escribió"


def test_b_c_e_analizar_cambiar_zona_e_historial(abrir, servidor_propio):
    """P0-05/08/09/11/12/13/17: un resultado tras «Analizar»; se retira al cambiar; el historial es explícito."""
    analisis = servidor_propio.datos / "analisis"
    previas = huellas(analisis)
    p = abrir(url=servidor_propio.url, descargas=True)
    p.marcar_mapa()
    p.confirmar_zona()
    buscar_par(p)
    assert p.page.locator(".st-key-sar_par input").first.input_value().startswith("★ 2026-09-24 → 2026-10-06 · S1C")
    p.pestana_sar(2)
    assert "S1C_IW_20260924T232218_DVP_RTC30" in p.texto("panel_sar") and sin_resultado(p)

    # B · Analizar: exactamente un resultado, ligado a esta ejecución.
    assert p.analizar() == "APTO"
    capas = p.capas_resultado()
    assert len(capas) == 1, "un único ráster de resultado"
    barra = p.texto("barra_superior")
    assert "ANÁLISIS DE ESTA SESIÓN" in barra and "REAL SIN VALIDAR" in barra and "HISTÓRICO" not in barra
    info = p.texto("panel_info")
    assert "RESULTADO DE ESTE ANÁLISIS" in info.upper() and "No es una inundación confirmada" in info
    nuevos = {n for n in huellas(analisis) if n not in previas}
    registro = json.loads(next(analisis / n for n in nuevos if n.endswith("_registro.json")).read_text("utf-8"))
    assert registro["run_id"] and registro["aoi_lonlat"] == [-76.8, 7.55, -76.55, 7.8]
    assert "coincidencia_VV_VH_20260924_20261006_r2.tif" in registro["salidas"]
    assert all(huellas(analisis)[n] == h for n, h in previas.items()), "los archivos previos no cambian"
    p.pestana_sar(3)
    assert registro["run_id"] in p.texto("panel_sar"), p.texto("panel_sar")[-500:]

    # P0-08/15: opacidad, fondo y pestañas no recalculan ni duplican.
    p.clic("btn_explorador")
    deslizador = p.page.locator(".st-key-res_opacidad input[type=range]").first
    deslizador.focus()
    for _ in range(4):
        p.page.keyboard.press("ArrowLeft")
    p.esperar()
    capas = p.capas_resultado()
    assert len(capas) == 1 and abs(capas[0]["op"] - 0.65) < 0.01
    assert {n for n in huellas(analisis) if n not in previas} == nuevos, "mover la opacidad no vuelve a analizar"

    # P0-17: exportación QGIS solo del resultado activo, GeoTIFF idéntico.
    activo = analisis / "coincidencia_VV_VH_20260924_20261006_r2.tif"
    with p.page.expect_download() as d:
        p.page.locator(".st-key-qgis_coincidencia_vv_vh_20260924_20261006_r2 button").first.click()
    assert d.value.suggested_filename == "coincidencia_VV_VH_20260924_20261006_r2_QGIS.zip"
    assert p.page.locator("[class*='st-key-qgis_']").count() == 1

    # P0-13: la misma configuración no se repite sola; el par elegido sigue ahí, marcado ✓.
    p.clic("btn_sar")
    p.pestana_sar(2)
    assert "ya se analizó" in p.texto("panel_sar") and p.page.locator(".st-key-sar_analizar button").first.is_disabled()
    p.pestana_sar(1)
    assert "1 ya analizados en esta zona" in p.texto("panel_sar")
    assert p.page.locator(".st-key-sar_par input").first.input_value().startswith("✓ ★ 2026-09-24 → 2026-10-06")
    assert len(p.capas_resultado()) == 1, "revisar los pasos no retira el resultado"

    # C · Cambiar de zona: el resultado y sus cifras desaparecen; nada se analiza solo; el archivo sigue.
    p.confirmar_zona("-75.45", "6.10", "-75.30", "6.22")
    assert p.capas_resultado() == [] and "SIN RESULTADO" in p.texto("barra_superior")
    p.clic("btn_explorador")
    assert "ya no corresponde" in p.texto("panel_explorador")
    assert activo.is_file() and {n for n in huellas(analisis) if n not in previas} == nuevos

    # P0-13: de vuelta en la zona original, una búsqueda nueva ya no propone ese par como pendiente…
    p.confirmar_zona()
    buscar_par(p)
    panel = p.texto("panel_sar")
    assert "1 ya analizados en esta zona" in panel
    assert not p.page.locator(".st-key-sar_par input").first.input_value().startswith("★ 2026-09-24 → 2026-10-06")
    # …pero se puede recuperar a propósito.
    # Filtro «Nuevas / Usadas / Todas»: el par usado está en «Usadas».
    assert "Nuevas (5)" in p.texto("sar_filtro_pares") and "Usadas (1)" in p.texto("sar_filtro_pares")
    p.page.locator(".st-key-sar_filtro_pares label").filter(has_text="Usadas").first.click()
    p.esperar()
    p.page.locator(".st-key-sar_par [role=combobox]").first.click()
    p.page.locator("[role=option]").filter(has_text="✓ ★ 2026-09-24 → 2026-10-06").first.click()
    p.esperar()
    p.clic("sar_ver_anterior")
    assert len(p.capas_resultado()) == 1 and "HISTÓRICO" in p.texto("barra_superior")
    assert {n for n in huellas(analisis) if n not in previas} == nuevos, "ver el anterior no recalcula"
    p.clic("btn_explorador")

    # E · Historial: cerrado; se abre a propósito y queda rotulado HISTÓRICO, sin recalcular.
    assert p.page.locator(".st-key-historial details").first.get_attribute("open") is None, "historial cerrado"
    p.clic("res_limpiar")
    assert p.capas_resultado() == []
    p.ver_historico(REPRODUCIBLE + "_r2")
    assert len(p.capas_resultado()) == 1
    barra, info = p.texto("barra_superior"), p.texto("panel_info")
    assert "HISTÓRICO" in barra and "ANÁLISIS DE ESTA SESIÓN" not in barra
    assert "no se ejecutó un análisis nuevo" in info
    p.ver_historico(EXPLORATORIO)                       # P0-11: sustituye, no acumula
    assert len(p.capas_resultado()) == 1 and "PROCEDENCIA NO DECLARADA" in p.texto("barra_superior")
    assert p.page.locator(".mc-leyenda-res").count() == 1, "una sola leyenda"
    p.clic("res_limpiar")
    assert p.capas_resultado() == [] and activo.is_file()
    assert {n for n in huellas(analisis) if n not in previas} == nuevos
    assert p.mapa_intacto() and not p.errores


def test_d_sin_datos_zona_invalida_y_demo(abrir, servidor_propio):
    """P0-07/10/14/21/22/24: sin RTC, con zona inválida o enorme, no aparece nada en su lugar."""
    p = abrir(url=servidor_propio.url)
    p.marcar_mapa()
    p.ver_historico(REPRODUCIBLE)                       # un resultado histórico en pantalla
    assert len(p.capas_resultado()) == 1

    # Zona enorme e inválida: se rechazan antes de cargar datos, con explicación.
    p.confirmar_zona("-77", "5", "-74", "9")
    assert "millones de píxeles" in p.texto("panel_sar") and "ZONA CONFIRMADA" not in p.texto("panel_sar")
    p.confirmar_zona("-75", "6", "-76", "7")
    assert "El oeste debe ser menor que el este" in p.texto("panel_sar")
    assert len(p.capas_resultado()) == 1, "un intento fallido no toca el mapa"

    # Otro municipio (Rionegro): hay catálogo pero no RTC → Analizar bloqueado, sin máscara ficticia.
    p.confirmar_zona("-75.45", "6.10", "-75.30", "6.22")
    assert p.capas_resultado() == [], "al confirmar otra zona el histórico se retira"
    buscar_par(p)
    p.pestana_sar(2)
    panel = p.texto("panel_sar")
    if "Primero busca imágenes" not in panel:           # el catálogo guardado cubre esta zona
        assert "todavía no están disponibles" in panel or "RTC" in panel
        assert p.page.locator(".st-key-sar_analizar button").first.is_disabled() or "falta" in panel
    assert p.capas_resultado() == [] and "SIN RESULTADO" in p.texto("barra_superior")

    # DEMO: solo a propósito, y rotulada.
    p.clic("btn_explorador")
    p.demo()
    assert len(p.capas_resultado()) == 1 and "DEMO · DATOS SINTÉTICOS" in p.texto("barra_superior")
    assert "Datos sintéticos" in p.texto("panel_info")
    p.alternar("capa_sar")
    assert p.capas_resultado() == [] and p.mapa_intacto() and not p.errores


def test_sesiones_independientes(abrir, servidor_propio):
    """P0-20: lo que una sesión tiene en el mapa no aparece en otra."""
    uno = abrir(url=servidor_propio.url)
    uno.ver_historico(REPRODUCIBLE)
    assert len(uno.capas_resultado()) == 1
    otro = abrir(url=servidor_propio.url)
    assert sin_resultado(otro)
    otro.clic("btn_sar")
    assert "Aún no hay zona" in otro.texto("panel_sar"), "la zona de otra sesión no se hereda"
    uno.page.reload()
    uno.esperar_mapa()
    uno.page.locator(".st-key-barra_superior").wait_for(timeout=60_000)
    uno.esperar(1500)
    assert sin_resultado(uno), "tras recargar (F5) la sesión empieza vacía"
