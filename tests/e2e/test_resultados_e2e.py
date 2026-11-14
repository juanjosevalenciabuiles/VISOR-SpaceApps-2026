"""Resultados SAR como capas opcionales, ficha científica, insignias y exportación QGIS."""
import base64
import hashlib
import io

import numpy as np
from PIL import Image

from utils.combinacion_sar import CLASES_COINCIDENCIA
from utils.qgis import verificar_paquete

EXPLORATORIO = "res_coincidencia_vv_vh_chigorodo"
REPRODUCIBLE = "res_coincidencia_vv_vh_20260924_20261006"
COLORES = {(0, 240, 255, 255), (255, 159, 10, 255), (125, 122, 255, 255)}


def capas_imagen(p):
    return p.mapa.evaluate("()=>[...document.querySelectorAll('img.leaflet-image-layer')]"
                           ".map(i=>({op:+getComputedStyle(i).opacity, src:i.src}))")


def colores_opacos(src: str) -> set:
    im = np.array(Image.open(io.BytesIO(base64.b64decode(src.split(",", 1)[1]))).convert("RGBA"))
    return {tuple(int(v) for v in c) for c in np.unique(im.reshape(-1, 4), axis=0) if c[3] > 0}


def test_resultado_exploratorio_desde_el_historial(abrir):
    p = abrir()
    p.marcar_mapa()
    assert capas_imagen(p) == []                           # nada al abrir
    p.ver_historico(EXPLORATORIO.removeprefix("res_"))
    capas = capas_imagen(p)
    assert len(capas) == 1 and p.mapa_intacto()
    assert colores_opacos(capas[0]["src"]) <= COLORES    # clases 1–3; 0 y NoData transparentes

    barra = p.texto("barra_superior")
    assert "HISTÓRICO" in barra and "PROCEDENCIA NO DECLARADA" in barra and "DEMO" not in barra
    info = p.texto("panel_info")
    assert "No es una inundación confirmada" in info and "No declarado en el archivo" in info
    assert "no se ejecutó un análisis nuevo" in info
    assert "CONCEPTUAL" in p.texto("linea_temporal").upper()

    deslizador = p.page.locator(".st-key-res_opacidad input[type=range]").first
    deslizador.focus()
    for _ in range(6):
        p.page.keyboard.press("ArrowLeft")
    p.esperar()
    assert abs(capas_imagen(p)[0]["op"] - 0.55) < 0.01
    # La DEMO, encendida a propósito, se dibuja DEBAJO y en su propio grupo; el resultado conserva su opacidad.
    p.demo("Deforestación")
    capas = capas_imagen(p)
    assert len(capas) == 2 and abs(capas[1]["op"] - 0.55) < 0.01 and p.mapa_intacto()
    barra = p.texto("barra_superior")
    assert barra.index("DEMO") < barra.index("PROCEDENCIA NO DECLARADA")
    assert not p.errores


def test_resultado_reproducible_real_sin_validar(abrir):
    p = abrir()
    p.ver_historico(REPRODUCIBLE.removeprefix("res_"))
    p.demo()
    barra = p.texto("barra_superior")
    assert "REAL SIN VALIDAR" in barra and "DEMO" in barra
    info = p.texto("panel_info")
    for frase in ("REAL SIN VALIDAR", "VV −7,5 dB · VH −3 dB", "Sentinel-1C", "2026-09-24 → 2026-10-06",
                  "según la ficha de procedencia", "No es una inundación confirmada"):
        assert frase in info, frase
    linea = p.texto("linea_temporal")
    assert "2026-09-24" in linea and "2026-10-06" in linea
    # REAL SIN VALIDAR y DEMO no comparten color.
    colores = p.page.evaluate("""()=>[...document.querySelectorAll('.st-key-barra_superior .mc-insignia')]
        .map(e=>[e.innerText, getComputedStyle(e).backgroundColor, getComputedStyle(e).color])""")
    demo = next(c for c in colores if "DEMO" in c[0])
    real = next(c for c in colores if "REAL" in c[0])
    assert demo[1:] != real[1:]


def test_exportar_para_qgis(abrir, servidor):
    origen = servidor.datos / "analisis" / "coincidencia_VV_VH_20260924_20261006.tif"
    huella = hashlib.sha256(origen.read_bytes()).hexdigest()
    p = abrir(descargas=True)
    p.marcar_mapa()
    assert p.page.locator("[class*='st-key-qgis_']").count() == 0, "sin resultado activo no se exporta nada"
    p.ver_historico(REPRODUCIBLE.removeprefix("res_"))
    with p.page.expect_download() as d:
        p.page.locator(".st-key-qgis_coincidencia_vv_vh_20260924_20261006 button").first.click()
    descarga = d.value
    assert descarga.suggested_filename == "coincidencia_VV_VH_20260924_20261006_QGIS.zip"
    with open(descarga.path(), "rb") as f:
        assert verificar_paquete(f.read(), origen, CLASES_COINCIDENCIA) == []
    assert hashlib.sha256(origen.read_bytes()).hexdigest() == huella
    p.page.wait_for_timeout(1500)
    assert p.mapa_intacto()


def test_diferencia_db_continua(abrir, servidor):
    origen = servidor.datos / "analisis" / "cambio_VV_20260924_20261006_dif_db.tif"
    huella = hashlib.sha256(origen.read_bytes()).hexdigest()
    p = abrir(descargas=True)
    p.marcar_mapa()
    p.ver_historico("cambio_vv_20260924_20261006_dif_db")
    capas = capas_imagen(p)
    assert len(capas) == 1 and p.mapa_intacto()
    im = np.array(Image.open(io.BytesIO(base64.b64decode(capas[0]["src"].split(",", 1)[1]))).convert("RGBA"))
    visibles = im[im[..., 3] > 0]
    azules = (visibles[:, 2] > 200) & (visibles[:, 0] < 120)
    assert azules.any(), "la disminución (−10 dB) se ve en azul"
    assert (im[..., 3] == 0).any(), "NoData / fuera de la huella transparente"
    info = p.texto("panel_info").upper()
    for frase in ("Diferencia de retrodispersión (dB)", "Estadísticas de Δ", "No aplica: dato continuo sin umbral",
                  "PROCEDENCIA NO DECLARADA", "No es una inundación confirmada"):
        assert frase.upper() in info, frase
    with p.page.expect_download() as d:
        p.page.locator(".st-key-qgis_cambio_vv_20260924_20261006_dif_db button").first.click()
    with open(d.value.path(), "rb") as f:
        assert verificar_paquete(f.read(), origen, (), continuo=True) == []
    assert hashlib.sha256(origen.read_bytes()).hexdigest() == huella and not p.errores
