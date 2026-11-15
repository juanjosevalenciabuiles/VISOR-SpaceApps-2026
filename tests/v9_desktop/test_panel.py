"""Panel sin IO, con UI simulada y sin necesitar navegador móvil."""
from datetime import date

from components.v9_desktop.panel_evidencia import mostrar_panel


class InterfazPrueba:
    def __init__(self):
        self.mensajes = []

    def subheader(self, mensaje):
        self.mensajes.append(("titulo", mensaje))

    def warning(self, mensaje):
        self.mensajes.append(("alerta", mensaje))

    def caption(self, mensaje):
        self.mensajes.append(("nota", mensaje))

    def write(self, mensaje):
        self.mensajes.append(("texto", mensaje))


def test_panel_sin_datos_es_transparente():
    ui = InterfazPrueba()
    r = mostrar_panel([], date(2026, 10, 1), date(2026, 10, 10), ui)
    assert r["estados"] == ["INFORMACION_INSUFICIENTE"]
    assert any(tipo == "alerta" for tipo, _ in ui.mensajes)
    assert any("QA" in texto for _, texto in ui.mensajes)
