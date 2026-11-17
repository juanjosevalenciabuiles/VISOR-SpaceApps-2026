"""Regresiones para el panel del jurado con fichas NISAR reales y legacy."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from components import resultados as ui
from utils.procedencia import Procedencia, REAL_SIN_VALIDAR
from utils.resultados import PERFILES


def ficha_resultado_nisar(generado_por):
    """Misma forma de la ficha JSON generada por utils.v9_datos.cambio_cog."""
    ficha = {
        "tipo_producto": "diferencia_db",
        "creado_utc": "2026-11-15T16:00:00+00:00",
        "procedencia": {
            "estado": "real_sin_validar",
            "sensor": "NISAR",
            "fechas": ["2026-10-22", "2026-11-03"],
            "polarizaciones": ["HHHH"],
            "metodo": "10log10(gamma0_post/gamma0_pre), QA=1 y looks; sin remuestreo",
            "entradas": [{"granule": "NISAR_L2_A_UNO"}, {"granule": "NISAR_L2_A_DOS"}],
            "generado_por": generado_por,
            "archivo": {"sha256": "1234567890abcdef1234567890abcdef"},
        },
    }
    capa = SimpleNamespace(
        procedencia=Procedencia(REAL_SIN_VALIDAR, "Producto real con ficha de procedencia"),
        metadatos={},
        forma_original=(10, 12),
        crs_original="EPSG:32618",
        avisos=[],
    )
    return SimpleNamespace(
        ruta=Path("data/analisis/nisar_v9_real_dif_db.tif"),
        archivo="data/analisis/nisar_v9_real_dif_db.tif",
        nombre="Diferencia de retrodispersión (dB)",
        ficha=ficha,
        capa=capa,
        perfil=PERFILES["diferencia_db"],
        estadisticas={},
        dibujable=True,
    )


@pytest.mark.parametrize("generador,esperado", [
    ("VISOR V9 IA1 cambio_cog", "VISOR V9 IA1 cambio_cog"),
    ({"funcion": "cambio_cog", "version_motor": "v9"}, "cambio_cog · motor v9"),
    ({"funcion": "cambio_cog"}, "cambio_cog"),
    (None, ui.NO_DECLARADO),
    (42, ui.NO_DECLARADO),
])
def test_panel_completo_admite_formatos_de_generador(generador, esperado):
    html = ui.ficha_html(ficha_resultado_nisar(generador))
    assert esperado in html
    assert "NISAR" in html and "2026-10-22" in html and "2026-11-03" in html
    assert "REAL · UNVALIDATED" in html or "REAL SIN VALIDAR" in html
    assert "2026-11-15T16:00:00+00:00" in html
    assert "1234567890abcdef" in html
    assert "NISAR_L2_A_UNO" in html and "NISAR_L2_A_DOS" in html
    assert "not confirmed flooding" in html or "No es una inundación confirmada" in html


def test_generado_por_texto_no_inyecta_html():
    html = ui.ficha_html(ficha_resultado_nisar("<script>alert('x')</script>"))
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
