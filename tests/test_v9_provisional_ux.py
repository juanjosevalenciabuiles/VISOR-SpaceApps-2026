"""Regresiones V9: dos madureces sin mezclarlas, fechas reales cercanas y UX."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import pytest

from components import v9_experiencia as ui
from utils import nisar_auto, nisar_harmony as harmony


AOI = (-76.83, 7.50, -76.45, 7.90)


def _par(a, b):
    def escena(d):
        return NS(nombre=NS(inicio=datetime.fromisoformat(d).replace(tzinfo=timezone.utc),
                            track=123, frame=456))
    return NS(antes=escena(a), despues=escena(b))


@dataclass
class CatalogoFalso:
    pares: list


def test_seleccion_madurez_no_mezcla_fechas():
    assert ui._madurez_del_periodo(date(2026, 10, 1), date(2026, 10, 9)) == "PROVISIONAL"
    assert ui._madurez_del_periodo(date(2026, 10, 22), date(2026, 11, 3)) == "VALIDATED"
    assert ui._madurez_del_periodo(date(2026, 10, 20), date(2026, 10, 25)) == "VALIDATED"


def test_sugerencias_reales_ordenadas_por_cercania():
    lejos = _par("2026-08-01", "2026-08-13")
    cerca = _par("2026-10-12", "2026-10-24")
    medio = _par("2026-09-05", "2026-09-17")
    sugeridos = ui._sugerencias_cercanas(
        [lejos, medio, cerca, medio], date(2026, 10, 1), date(2026, 10, 9))
    assert sugeridos == [cerca, medio, lejos]


def test_busqueda_provisional_un_clic_envia_solo_par_compatible(monkeypatch):
    import components.nisar_auto_ui as auto_ui
    p = _par("2026-09-27", "2026-10-13")
    madureces = []
    estado = {}
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.setenv("EARTHDATA_TOKEN", "solo-token-falso-pruebas")
    def buscar(*_a, **kwargs):
        madureces.append(kwargs["madurez"])
        return CatalogoFalso([p])
    monkeypatch.setattr(ui.cat, "buscar", buscar)
    monkeypatch.setattr(nisar_auto, "planear", lambda r, **_k: NS(pares=r.pares))
    monkeypatch.setattr(auto_ui, "_ejecutar_en_cola",
                        lambda r, _p, _m, _limite: {"job_id": "1234567890abcdef"})
    job_id = ui._solicitar(AOI, date(2026, 10, 1), date(2026, 10, 9))
    assert job_id == "1234567890abcdef"
    assert madureces == ["PROVISIONAL"]


def test_sin_par_sugiere_fechas_no_descarga(monkeypatch):
    cerca = _par("2026-10-12", "2026-10-24")
    llamadas = []
    estado = {}
    monkeypatch.setattr(ui.st, "session_state", estado)
    def buscar(*_a, **_k):
        llamadas.append("catalogo")
        return CatalogoFalso([cerca])
    monkeypatch.setattr(ui.cat, "buscar", buscar)
    with pytest.raises(ValueError, match="fechas"):
        ui._solicitar(AOI, date(2026, 10, 1), date(2026, 10, 9))
    assert len(llamadas) == 2  # consulta base + ampliación de metadatos
    item = estado["v9_sugerencias"]
    assert item["madurez"] == "PROVISIONAL"
    assert item["pares"] == [cerca]
    assert item["firma"] == ui._firma(AOI, date(2026, 10, 1), date(2026, 10, 9))


def test_nueva_zona_preserva_historial_y_limpia_sesion(monkeypatch):
    from components import flujo
    estado = {
        "zona": {"limites": list(AOI)}, "lugar": "Chigorodó",
        "v9_inicio_periodo": date(2026, 10, 1),
        "v9_fin_periodo": date(2026, 10, 9),
        "v9_preparacion": "1234567890abcdef",
        "resultado_activo": {"id": "anterior"},
    }
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.setattr(flujo.st, "session_state", estado)
    ui._nuevo_analisis(True)
    assert estado["zona"] is None and estado["lugar"] is None
    assert estado["resultado_activo"] is None
    assert "v9_preparacion" not in estado and "v9_inicio_periodo" not in estado
    assert estado["ui_explorador"] and estado["ui_sar"] == "minimizado"


def test_progreso_se_basa_en_fases_no_en_tiempo(monkeypatch):
    valores = []
    monkeypatch.setattr(ui.st, "progress", lambda n, text: valores.append((n, text)))
    monkeypatch.setattr(ui.st, "caption", lambda *_: None)
    trabajo = {
        "estado": "EN CURSO", "fases": [
            {"clave": "zona", "estado": "APTO", "nombre": "Zona"},
            {"clave": "escenas", "estado": "APTO", "nombre": "Escenas"},
            {"clave": "datos", "estado": "EN CURSO", "nombre": "Datos", "detalle": "Descargando COG"},
        ],
    }
    ui._mostrar_progreso(trabajo, "preparacion")
    assert valores[0][0] == 31
    assert "Descargando COG" in valores[0][1]


def test_harmony_provisional_usa_coleccion_correcta(monkeypatch):
    datos = {
        "conceptId": "C2854338529-ASF",
        "shortName": "NISAR_L2_GCOV_PROVISIONAL_V1",
        "variables": [{"name": "/science/LSAR/GCOV/grids/frequencyA/HHHH"}],
    }
    urls = []
    monkeypatch.setattr(harmony, "_json_publico",
                        lambda url, abrir=None: urls.append(url) or datos)
    caps = harmony.capacidades(madurez="PROVISIONAL")
    assert caps["madurez"] == "PROVISIONAL"
    assert caps["coleccion"] == datos["conceptId"]
    assert "NISAR_L2_GCOV_PROVISIONAL_V1" in urls[0]
    candidato = NS(granule="NISAR_" + "X" * 55,
                   nombre=NS(pol_a=("HH",)), madurez="PROVISIONAL")
    with pytest.raises(harmony.ErrorHarmony, match="otra madurez"):
        harmony.especificar(candidato, AOI, {"madurez": "VALIDATED", **{
            "coleccion": "C0000000000-ASF", "variables": set()
        }})


def test_preparar_harmony_no_mezcla_madureces(monkeypatch, tmp_path):
    monkeypatch.setenv("EARTHDATA_TOKEN", "solo-token-falso-pruebas")
    a = NS(madurez="PROVISIONAL")
    b = NS(madurez="VALIDATED")
    plan = nisar_auto.Plan("PAR", (a, b), AOI, 1.0, 2000, "HHHH", ())
    with pytest.raises(nisar_auto.ErrorAutoNISAR, match="madurez distinta"):
        nisar_auto.preparar_harmony(plan, carpeta=tmp_path)
