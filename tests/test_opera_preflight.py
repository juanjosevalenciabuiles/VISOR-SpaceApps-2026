"""Pruebas aisladas para consulta OPERA RTC-S1 (sin Internet y sin descargas)."""
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[1] / "scripts" / "verificar_opera_asf.py"
SPEC = spec_from_file_location("verificar_opera_asf", RUTA)
MOD = module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class Producto:
    def __init__(self, identificador, fecha):
        self.properties = {
            "fileID": identificador,
            "startTime": f"{fecha}T23:22:18Z",
            "stopTime": f"{fecha}T23:22:19Z",
            "polarization": "VV+VH",
            "flightDirection": "ASCENDING",
            "pathNumber": 48,
            "additionalUrls": [
                "https://example.org/OPERA_L2_RTC-S1_T048-123456-IW2_20260924T232218Z_S1C_30_v1.0_VV.tif",
                "https://example.org/OPERA_L2_RTC-S1_T048-123456-IW2_20260924T232218Z_S1C_30_v1.0_VH.tif",
                "https://example.org/OPERA_L2_RTC-S1_T048-123456-IW2_20260924T232218Z_S1C_30_v1.0_mask.tif",
            ],
        }


class ClienteASF:
    def __init__(self):
        self.llamadas = []

    def search(self, **kw):
        self.llamadas.append(kw)
        fecha = kw["start"][:10].replace("-", "")
        return [Producto(f"OPERA_L2_RTC-S1_T048-123456-IW2_{fecha}T232218Z_S1C_30_v1.0", kw["start"][:10])]


def test_wkt_y_limites():
    assert MOD.wkt_aoi(MOD.A_O_I).startswith("POLYGON((-76.8 7.55,")
    with pytest.raises(ValueError):
        MOD.wkt_aoi((-80, -5, -60, 16))


def test_solo_consulta_metadatos_ambas_fechas():
    cliente = ClienteASF()
    salida = MOD.ejecutar(cliente, fechas=(date(2026, 9, 24), date(2026, 10, 6)))
    assert len(cliente.llamadas) == 2
    assert all(x["dataset"] == "OPERA-S1" and x["processingLevel"] == "RTC" for x in cliente.llamadas)
    assert salida["status"] == "METADATA_ONLY_NOT_DOWNLOAD_TESTED"
    assert len(salida["rafagas_en_ambas_fechas"]) == 1
    assert salida["por_fecha"]["2026-09-24"]["productos"] == 1
    assert salida["por_fecha"]["2026-09-24"]["candidatos_vv"] == 1
    assert salida["por_fecha"]["2026-10-06"]["mascaras"] == 1


def test_no_se_afirma_cobertura_con_resultado_truncado():
    cliente = ClienteASF()
    salida = MOD.ejecutar(cliente, fechas=(date(2026, 10, 6),), limite=1)
    assert salida["por_fecha"]["2026-10-06"]["posible_truncamiento"] is True


def test_sin_rafaga_no_crea_falsa_pareja():
    uno = {"operaBurstID": None}
    dos = {"operaBurstID": "T048-123456-IW1"}
    assert MOD.comparar_por_rafagas({"2026-09-24": [uno], "2026-10-06": [dos]}) == []
