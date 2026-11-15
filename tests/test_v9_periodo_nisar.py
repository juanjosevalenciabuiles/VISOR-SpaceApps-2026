"""Cobertura temporal NISAR V9, sin descargar ni simular un raster real."""
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

from components.v9_experiencia import _fechas_compatibles, _pares_del_periodo


def _par(pre, post):
    def escena(dia):
        return NS(nombre=NS(inicio=datetime.fromisoformat(dia).replace(tzinfo=timezone.utc)))
    return NS(antes=escena(pre), despues=escena(post))


def test_acepta_dos_tomas_dentro_del_intervalo_escogido():
    assert _fechas_compatibles(date(2026, 10, 22), date(2026, 11, 3),
                              date(2026, 10, 22), date(2026, 11, 3))


def test_acepta_tomas_reales_que_rodean_periodo_corto():
    assert _fechas_compatibles(date(2026, 10, 22), date(2026, 11, 3),
                              date(2026, 10, 29), date(2026, 11, 2))


def test_no_fabrica_observaciones_fuera_del_periodo():
    assert not _fechas_compatibles(date(2026, 10, 22), date(2026, 10, 24),
                                   date(2026, 10, 25), date(2026, 11, 2))
    assert not _fechas_compatibles(date(2026, 11, 3), date(2026, 10, 22),
                                   date(2026, 10, 20), date(2026, 11, 5))


def test_prioriza_pares_con_tomas_dentro_del_periodo():
    exterior = _par("2026-10-22", "2026-11-03")
    interior = _par("2026-10-29", "2026-11-01")
    elegidos = _pares_del_periodo([exterior, interior], date(2026, 10, 28), date(2026, 11, 2))
    assert elegidos == [interior]
    assert _pares_del_periodo([exterior], date(2026, 10, 28), date(2026, 11, 2)) == [exterior]
