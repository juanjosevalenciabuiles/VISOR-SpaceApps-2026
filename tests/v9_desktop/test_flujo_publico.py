"""Fixtures de UI simulada, no observaciones SAR."""
from datetime import date
import pytest
from components.v9_desktop.flujo_publico import (SENSORES, solicitud_publica,
                                                  estado_backend, render)


def test_solicitud_unica_y_respaldo():
    s = solicitud_publica(" Chigorodó ", date(2026, 10, 1), date(2026, 11, 1))
    assert s["zona"] == "Chigorodó"
    assert s["sensor_preferido"] == SENSORES[0]
    assert s["respaldo"] == SENSORES[1]


@pytest.mark.parametrize("zona,inicio,fin", [
    ("", date(2026, 10, 1), date(2026, 11, 1)),
    ("Chocó", date(2026, 11, 2), date(2026, 11, 1)),
])
def test_entrada_invalida(zona, inicio, fin):
    with pytest.raises(ValueError):
        solicitud_publica(zona, inicio, fin)


@pytest.mark.parametrize("tipo", ["HARMONY_COG_SUBSET", "CATALOGO", "RTC_NO_PREPARADO"])
def test_insumos_no_publican_mapa(tipo):
    r = estado_backend({"estado": "apto", "tipo": tipo, "ficha": {"estado": "validado"}})
    assert r["estado"] == "solo_catalogo"
    assert not r["mostrar_mapa"]


def test_sin_backend_no_hay_resultado():
    assert estado_backend(None)["mostrar_mapa"] is False


class Contexto:
    def __init__(self, ui):
        self.ui = ui
    def __enter__(self):
        return self.ui
    def __exit__(self, *args):
        return False


class UI:
    def __init__(self, click=False):
        self.click = click
        self.textos = []
    def subheader(self, texto):
        self.textos.append(texto)
    def text_input(self, *args, **kwargs):
        return "Rionegro"
    def columns(self, n):
        return [self] * n
    def date_input(self, titulo, **kwargs):
        return date(2026, 10, 1) if titulo == "Desde" else date(2026, 11, 1)
    def expander(self, *args, **kwargs):
        return Contexto(self)
    def selectbox(self, *args, **kwargs):
        return SENSORES[0]
    def caption(self, texto):
        self.textos.append(texto)
    def button(self, *args, **kwargs):
        return self.click
    def info(self, texto):
        self.textos.append(texto)
    def warning(self, texto):
        self.textos.append(texto)


def test_render_pc_no_lanza_backend_ni_inventa_mapa():
    ui = UI(click=True)
    solicitud = render(ui, respuesta={"estado": "apto", "tipo": "HARMONY_COG_SUBSET"},
                       lugar_buscado="Rionegro", area_analisis="San Carlos")
    assert solicitud["zona"] == "Rionegro"
    assert any("Lugar buscado: Rionegro" in s for s in ui.textos)
    assert any("San Carlos" in s for s in ui.textos)
    assert not any("Indicio exploratorio" in s for s in ui.textos)


def test_render_sin_click_no_emite_solicitud():
    assert render(UI()) is None
