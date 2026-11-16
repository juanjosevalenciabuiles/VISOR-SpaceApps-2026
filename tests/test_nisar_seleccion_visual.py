"""NISAR selection by common footprint: offline, no NASA token, no downloads."""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import folium
import pytest
from shapely.geometry import box

from components import cobertura_nisar as visual
from components import v9_experiencia as ui
from utils import nisar_catalogo as cat, nisar_coberturas as geo

AOI = (-76.80, 7.55, -76.55, 7.80)
INI, FIN = date(2026, 10, 20), date(2026, 11, 10)


def _par(a: str, b: str, region, *, dias=12, bytes_por_escena=150_000_000):
    d1, d2 = datetime(2026, 10, 28, tzinfo=timezone.utc), datetime(2026, 11, 9, tzinfo=timezone.utc)

    def escena(nombre, fecha, huella):
        return NS(
            granule=nombre, huella=huella, tamano_bytes=bytes_por_escena,
            url_h5=f"https://nisar.asf.earthdatacloud.nasa.gov/{nombre}.h5",
            madurez="VALIDATED",
            nombre=NS(inicio=fecha, track=148, frame=5, pol_a=("HH", "HV")),
        )

    pre = escena(a, d1, region)
    post = escena(b, d2, region)
    return cat.ParNISAR(pre, post, dias, 0.5, ("HH", "HV"), [], [])


def _resultado(pares):
    return cat.ResultadoNISAR(
        region=NS(limites=AOI), inicio=INI, fin=FIN, madurez="VALIDATED",
        url="https://cmr.earthdata.nasa.gov/search/granules.umm_json",
        total_catalogo=2 * len(pares), candidatos=[x for p in pares for x in (p.antes, p.despues)],
        descartes=[], pares=pares, bloqueos=[], avisos=[],
    )


def test_area_geodesica_elige_interseccion_de_ambas_fechas_no_la_mayor_escena():
    a = _par("A1", "A2", box(-76.8, 7.55, -76.56, 7.8))
    # Ambas huellas no son iguales: T2 recorta casi todo T1.
    a.despues.huella = box(-76.8, 7.55, -76.74, 7.8)
    b = _par("B1", "B2", box(-76.76, 7.55, -76.56, 7.8))
    r = _resultado([a, b])
    candidatos = geo.opciones(r, r.pares, punto_prioritario=None)
    assert candidatos[0]["id"] == geo.identificador(b)
    assert candidatos[0]["cobertura"] > candidatos[1]["cobertura"]
    assert candidatos[0]["cobertura"] == pytest.approx(0.8, abs=0.015)
    assert candidatos[1]["cobertura"] == pytest.approx(0.24, abs=0.015)
    assert candidatos[0]["plan"].granules == ("B1", "B2")
    assert candidatos[1]["plan"] is None, "par menor al umbral de 40% no es analizable"


def test_punto_prioritario_evitan_par_que_no_cubre_pueblo():
    oeste = _par("O1", "O2", box(-76.8, 7.55, -76.68, 7.8))
    este = _par("E1", "E2", box(-76.70, 7.55, -76.55, 7.8))
    r = _resultado([oeste, este])
    candidatos = geo.opciones(r, r.pares, punto_prioritario=(-76.62, 7.67))
    assert candidatos[0]["id"] == geo.identificador(este)
    assert candidatos[0]["cubre_punto"] is True
    assert candidatos[1]["cubre_punto"] is False
    assert candidatos[0]["plan"] is not None


def test_busqueda_solo_cmr_sin_descarga_ni_token(monkeypatch):
    r = _resultado([_par("A1", "A2", box(*AOI))])
    estado = {}
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    llamadas = []
    monkeypatch.setattr(ui.cat, "buscar", lambda *a, **k: llamadas.append((a, k)) or r)
    import components.nisar_auto_ui as auto_ui
    monkeypatch.setattr(auto_ui, "_ejecutar_en_cola",
                        lambda *_args: pytest.fail("Buscar metadatos NO descarga"))
    salida = ui._consultar_coberturas(AOI, INI, FIN)
    assert len(llamadas) == 1
    assert salida["seleccionado"] == geo.identificador(r.pares[0])
    assert salida["firma"] == ui._firma(AOI, INI, FIN)
    assert salida["opciones"][0]["plan"].tipo == "PAR"
    assert "v9_preparacion" not in estado
    assert "nisar_auto_job" not in estado


def test_click_mapa_con_solapamiento_no_selecciona_arbitrariamente(monkeypatch):
    a = _par("A1", "A2", box(-76.80, 7.55, -76.65, 7.8))
    b = _par("B1", "B2", box(-76.73, 7.55, -76.55, 7.8))
    candidatos = geo.opciones(_resultado([a, b]), [a, b])
    estado = {
        "zona": {"limites": list(AOI)}, "v9_inicio_periodo": INI,
        "v9_fin_periodo": FIN,
        "v9_coberturas": {
            "firma": ui._firma(AOI, INI, FIN), "opciones": candidatos,
            "seleccionado": candidatos[0]["id"],
        },
    }
    monkeypatch.setattr(ui.st, "session_state", estado)
    assert ui.seleccionar_desde_mapa({"lat": 7.67, "lng": -76.69}, "mapa_prueba")
    assert set(estado["v9_pares_solapados"]) == {x["id"] for x in candidatos}
    assert estado["v9_coberturas"]["seleccionado"] == candidatos[0]["id"]
    ui._elegir_par(candidatos[1]["id"])
    assert estado["v9_coberturas"]["seleccionado"] == candidatos[1]["id"]
    assert not estado["v9_pares_solapados"]
    assert not ui.seleccionar_desde_mapa({"lat": 7.67, "lng": -76.69}, "mapa_prueba")


def test_cambio_aoi_invalida_seleccion_y_protege_archivos(monkeypatch):
    par = _par("A1", "A2", box(*AOI))
    opciones = geo.opciones(_resultado([par]), [par])
    estado = {
        "zona": {"limites": list(AOI)}, "v9_inicio_periodo": INI, "v9_fin_periodo": FIN,
        "v9_coberturas": {
            "firma": ui._firma(AOI, INI, FIN), "opciones": opciones,
            "seleccionado": opciones[0]["id"],
        },
    }
    monkeypatch.setattr(ui.st, "session_state", estado)
    assert ui._coberturas_actuales() is not None
    estado["zona"] = {"limites": [-76.70, 7.60, -76.61, 7.69]}
    assert ui._coberturas_actuales() is None
    assert ui.grupos_mapa() == []
    assert not ui.seleccionar_desde_mapa({"lat": 7.67, "lng": -76.69}, "mapa_viejo")


def test_coberturas_cmr_t1_t2_y_area_sin_cobertura_no_son_rasters(monkeypatch):
    par = _par("T1", "T2", box(-76.80, 7.55, -76.67, 7.8))
    r = _resultado([par])
    opciones = geo.opciones(r, r.pares)
    firma = ui._firma(AOI, INI, FIN)
    estado = {"firma": firma, "opciones": opciones, "seleccionado": opciones[0]["id"]}
    grupos = visual.grupos(estado, firma)
    assert len(grupos) == 1
    m = folium.Map(location=(7.67, -76.70))
    grupos[0].add_to(m)
    html = m.get_root().render()
    assert "T1" in html and "T2" in html and "NASA CMR" in html
    assert "CMR" in html
    assert not any(isinstance(c, folium.raster_layers.ImageOverlay)
                   for c in grupos[0]._children.values())


def test_no_se_descarga_par_antiguo_o_diferente(monkeypatch):
    par = _par("T1", "T2", box(*AOI))
    resultado = _resultado([par])
    opciones = geo.opciones(resultado, [par])
    item = opciones[0]
    estado = {"firma": ui._firma(AOI, INI, FIN), "resultado": resultado,
              "opciones": opciones, "seleccionado": item["id"]}
    import components.nisar_auto_ui as auto_ui
    llamadas = []
    monkeypatch.setattr(auto_ui, "_ejecutar_en_cola",
                        lambda *_args: llamadas.append(_args) or {"job_id": "1234567890abcdef"})
    monkeypatch.setenv("EARTHDATA_TOKEN", "TOKEN_FICTICIO_SOLO_EN_TEST")
    monkeypatch.setattr(ui.cat, "evaluar_par", lambda *_args: par)
    assert ui._solicitar_elegido(AOI, INI, FIN, estado, item) == "1234567890abcdef"
    assert llamadas[0][1].granules == ("T1", "T2")
    assert llamadas[0][1].resumen()["id_par_seleccionado"] == item["id"]
    assert llamadas[0][1].resumen()["criterio_seleccion"] == "PAR_CONFIRMADO_USUARIO_POR_COBERTURA_CMR"
    with pytest.raises(ValueError, match="otro período o zona"):
        ui._solicitar_elegido((-76.7, 7.6, -76.6, 7.7), INI, FIN, estado, item)
    assert len(llamadas) == 1


def test_sin_qa_dos_fechas_incompatibles_no_se_saltan_filtro(monkeypatch):
    par = _par("T1", "T2", box(*AOI))
    resultado = _resultado([par])
    item = geo.opciones(resultado, [par])[0]
    estado = {"firma": ui._firma(AOI, INI, FIN), "resultado": resultado,
              "opciones": [item], "seleccionado": item["id"]}
    monkeypatch.setenv("EARTHDATA_TOKEN", "TOKEN_FICTICIO_SOLO_EN_TEST")
    monkeypatch.setattr(ui.cat, "evaluar_par",
                        lambda *_args: ["polarizaciones incompatibles"])
    with pytest.raises(ValueError, match="compatibilidad"):
        ui._solicitar_elegido(AOI, INI, FIN, estado, item)
