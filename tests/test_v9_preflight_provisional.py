"""Preflight de Chigorodó octubre 2026: CMR solamente, nunca descarga SAR."""
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import pytest

from components import v9_experiencia as ui


AOI = (-76.83, 7.50, -76.45, 7.90)


def _par(a, b):
    def toma(fecha):
        return NS(nombre=NS(
            inicio=datetime.fromisoformat(fecha).replace(tzinfo=timezone.utc),
            track=123, frame=456,
        ))
    return NS(antes=toma(a), despues=toma(b))


def test_provisional_octubre_consulta_solo_metadatos(monkeypatch):
    llamadas = []
    par = _par("2026-09-27", "2026-10-13")

    def catalogo_falso(*args, **kwargs):
        llamadas.append((args, kwargs))
        return NS(pares=[par], candidatos=[par.antes, par.despues], total_catalogo=2)

    monkeypatch.setattr(ui.cat, "buscar", catalogo_falso)
    # Fecha de entorno real controlada indirectamente: intervalo elegido está en el pasado.
    resultado, pares = ui._explorar_provisional(
        AOI, date(2026, 10, 1), date(2026, 10, 9))
    assert resultado.total_catalogo == 2
    assert pares == [par]
    assert len(llamadas) == 1
    args, kwargs = llamadas[0]
    assert args[:4] == AOI
    assert kwargs == {"madurez": "PROVISIONAL"}
    assert args[4] == date(2026, 8, 17)
    assert args[5] == date(2026, 10, 23)


def test_no_consulta_provisional_fuera_de_su_ventana(monkeypatch):
    def sin_red(*_args, **_kwargs):
        raise AssertionError("No debe consultar catálogo fuera de PROVISIONAL")
    monkeypatch.setattr(ui.cat, "buscar", sin_red)
    with pytest.raises(ValueError, match="fuera de las fechas"):
        ui._explorar_provisional(AOI, date(2026, 3, 1), date(2026, 3, 9))


def test_modo_jurado_usa_solo_archivos_existentes(monkeypatch):
    estado = {"visor_modo_muestra_real": False}
    monkeypatch.setattr(ui.st, "session_state", estado)
    ui._abrir_modo_jurado()
    assert estado["visor_modo_muestra_real"] is True
