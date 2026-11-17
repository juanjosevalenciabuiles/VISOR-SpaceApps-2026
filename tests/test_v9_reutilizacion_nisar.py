"""Recuperación de preparaciones NISAR reales registradas, sin red ni descargas."""
from datetime import date

from components import v9_experiencia as ui


INI = date(2026, 10, 29)
FIN = date(2026, 11, 2)
AOI = (-76.8, 7.55, -76.55, 7.8)


def _job(job_id, aoi=AOI, estado="APTO", tipo="adquisicion_nisar_gcov",
         procesador="harmony_cog"):
    return {"job_id": job_id, "estado": estado, "tipo": tipo,
            "procesador": procesador, "aoi": {"limites": list(aoi)}}


def test_reutiliza_otro_trabajo_anterior_sin_depender_de_session_state(monkeypatch):
    trabajos = [_job("1111111111111111", estado="ERROR"),
                _job("2222222222222222")]
    monkeypatch.setattr(ui.trabajos, "listar", lambda limite: trabajos)
    monkeypatch.setattr(ui, "_fechas_de_preparacion",
                        lambda _: (date(2026, 10, 22), date(2026, 11, 3)))
    assert ui._preparacion_existente(AOI, INI, FIN)["job_id"] == "2222222222222222"


def test_solo_recupera_mismo_aoi_y_periodo_con_dos_fechas(monkeypatch):
    trabajos = [_job("1111111111111111", aoi=(-75.5, 6.0, -75.3, 6.2)),
                _job("2222222222222222", procesador="nisar_gcov_hdf5"),
                _job("3333333333333333")]
    monkeypatch.setattr(ui.trabajos, "listar", lambda limite: trabajos)
    monkeypatch.setattr(ui, "_fechas_de_preparacion",
                        lambda _: (date(2026, 10, 22), date(2026, 10, 24)))
    assert ui._preparacion_existente(AOI, INI, FIN) is None


def test_reutiliza_par_preparado_dentro_del_periodo(monkeypatch):
    monkeypatch.setattr(ui.trabajos, "listar", lambda limite: [_job("4444444444444444")])
    monkeypatch.setattr(ui, "_fechas_de_preparacion",
                        lambda _: (date(2026, 10, 30), date(2026, 11, 1)))
    assert ui._preparacion_existente(AOI, INI, FIN)["job_id"] == "4444444444444444"
