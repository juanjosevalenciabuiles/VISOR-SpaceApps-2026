"""Smoke E2E del modo público Colombia; sin llamadas a EONET ni analizar SAR."""
from __future__ import annotations

import pytest

from conftest import Pagina, Servidor, preparar_datos

pytestmark = pytest.mark.navegador


def test_modo_colombia_pantalla_inicial(tmp_path, navegador):
    datos = preparar_datos(tmp_path / "datos")
    servidor = Servidor(datos, {"VISOR_REGION_MODE": "CO"})
    contexto = navegador.new_context(viewport={"width": 1280, "height": 800})
    try:
        pagina = Pagina(contexto.new_page(), servidor.url)
        assert pagina.page.get_by_text("MODO COLOMBIA", exact=False).count() >= 1
        assert pagina.page.locator("#sin-resultado").count() >= 1
        pagina.clic("btn_sar")
        assert pagina.page.locator("#ctx-sin-zona").count() >= 1
    finally:
        contexto.close()
        servidor.cerrar()
