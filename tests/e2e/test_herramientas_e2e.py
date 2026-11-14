"""Herramientas SAR de punta a punta: AOI → catálogo (simulado) → RTC → motor → resultado.

Usa su propio servidor y su propia copia de datos, porque el análisis crea archivos.
"""
import hashlib

import pytest

from conftest import Servidor, preparar_datos


@pytest.fixture(scope="module")
def servidor_propio(tmp_path_factory):
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("flujo") / "data"))
    yield s
    s.cerrar()


def huellas(carpeta):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in carpeta.iterdir() if p.is_file()}


def test_flujo_completo(abrir, servidor_propio):
    analisis = servidor_propio.datos / "analisis"
    previas = huellas(analisis)
    p = abrir(url=servidor_propio.url)
    p.marcar_mapa()
    antes = p.trazos()

    p.clic("btn_sar")
    assert p.trazos() == antes, "sin zona confirmada no se dibuja ningún AOI"
    p.confirmar_zona()
    assert p.trazos() > antes, "zona dibujada"
    p.clic("sar_centrar")
    assert p.vista() == [11, 7.675, -76.675]

    p.pestana_sar(1)
    p.clic("sar_buscar")
    panel = p.texto("panel_sar")
    assert "CATÁLOGO SIMULADO" in panel and "RECOMENDADO (SIN VALIDAR)" in panel and "6 pares compatibles" in panel
    assert p.page.locator(".st-key-sar_par input").first.input_value().startswith("★ 2026-09-24 → 2026-10-06 · S1C")
    con_huellas = p.trazos()
    assert con_huellas >= antes + 3, "zona y huellas del par"

    p.pestana_sar(2)
    panel = p.texto("panel_sar")
    assert "S1C_IW_20260924T232218_DVP_RTC30" in panel and "falta" not in panel
    assert p.capas_resultado() == []
    assert p.analizar() == "APTO"
    assert len(p.capas_resultado()) == 1
    p.pestana_sar(3)
    panel = p.texto("panel_sar")
    assert "coincidencia_VV_VH_20260924_20261006_r2.tif" in panel and "Ningún archivo existente" in panel

    despues = huellas(analisis)
    assert all(despues[n] == h for n, h in previas.items()), "los archivos previos no cambian"
    assert "coincidencia_VV_VH_20260924_20261006_r2.json" in despues
    p.clic("sar_ir_explorador")
    assert "ANÁLISIS DE ESTA SESIÓN" in p.texto("panel_explorador")
    assert p.mapa_intacto() and not p.errores
