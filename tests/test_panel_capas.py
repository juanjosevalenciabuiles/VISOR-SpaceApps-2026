"""Dock persistente de capas: acciones reproducibles sin alterar los GeoTIFF."""
from types import SimpleNamespace as NS

from components import panel_capas
from utils import sesion


def _res(id_, real=True):
    return NS(
        id=id_, dibujable=True, nombre="Diferencia NISAR L",
        ficha={"procedencia": {"fechas": ["2026-10-22", "2026-11-03"],
                               "sensor": "NISAR"}},
        capa=NS(
            limites=(-77.5, 6.5, -76.5, 7.5),
            procedencia=NS(es_real=real)),
    )


def test_dock_se_inicializa_con_capas_ambientales_reales(monkeypatch):
    estado = {}
    monkeypatch.setattr(panel_capas.st, "session_state", estado)
    panel_capas._inicializar()
    assert estado["ui_capas_abierto"] is True
    assert estado["visor_capa_resultado_visible"] is True
    assert estado["visor_mapa_alertas_ideam"] is True
    assert estado["visor_mapa_municipios_dane"] is True
    assert estado["visor_mapa_eventos_eonet"] is False
    assert estado["ctx_hidrografia"] is False
    assert estado["dock_mapa_base"] == estado.get("mapa_base", "osm_oscuro") or (
        estado["dock_mapa_base"] == panel_capas.mapas_base.predeterminado())
    panel_capas._alternar_dock()
    assert estado["ui_capas_abierto"] is False
    panel_capas._alternar_dock()
    assert estado["ui_capas_abierto"] is True


def test_cambiar_a_resultado_historico_centra_y_separa_antigua_aoi(monkeypatch):
    from components import flujo, interfaz

    res = _res("nisar_hist_1")
    estado = {
        "visor_seleccion_resultado": res.id,
        "resultado_activo": {"id": "anterior"},
        "lugar": {"etiqueta": "Lugar anterior"},
        "zona": {"limites": [-1, -1, 1, 1]},
        "capa_sar": True,
        "visor_capa_resultado_visible": False,
    }
    monkeypatch.setattr(panel_capas.st, "session_state", estado)
    acciones = []
    monkeypatch.setattr(flujo, "quitar_zona", lambda: acciones.append("quitar_aoi"))
    monkeypatch.setattr(flujo, "activar", lambda id_, origen: acciones.append((id_, origen)))
    monkeypatch.setattr(interfaz, "centrar_en", lambda limites: acciones.append(("centrar", limites)))

    panel_capas._cambiar_resultado([res])
    assert acciones == ["quitar_aoi", ("nisar_hist_1", sesion.HISTORICO),
                       ("centrar", res.capa.limites)]
    assert estado["lugar"] is None
    assert estado["capa_sar"] is False
    assert estado["visor_capa_resultado_visible"] is True


def test_quitar_resultado_del_mapa_no_borra_ningun_archivo(monkeypatch):
    from components import flujo
    estado = {"visor_seleccion_resultado": None}
    monkeypatch.setattr(panel_capas.st, "session_state", estado)
    acciones = []
    monkeypatch.setattr(flujo, "limpiar_resultado", lambda *a: acciones.append("limpiar"))
    panel_capas._cambiar_resultado([_res("nisar_hist_1")])
    assert acciones == ["limpiar"]


def test_leyenda_de_historial_indica_procedencia_y_fechas():
    real = _res("uno", True)
    no_validado = _res("dos", False)
    assert "AOI" in panel_capas._etiqueta_resultado("uno", {"uno": real})
    assert "2026-10-22" in panel_capas._etiqueta_resultado("uno", {"uno": real})
    assert "2026-11-03" in panel_capas._etiqueta_resultado(
        "dos", {"dos": no_validado})
    assert panel_capas._etiqueta_resultado(None, {}) in ("No result selected", "Ningún resultado seleccionado")


def test_dock_mapa_base_usa_clave_unica_y_sincroniza_fondo(monkeypatch):
    estado = {"dock_mapa_base": "calles", "mapa_base": "osm_oscuro"}
    monkeypatch.setattr(panel_capas.st, "session_state", estado)
    monkeypatch.setattr(panel_capas.mapas_base, "ofrecidos", lambda: ["osm_oscuro", "calles"])
    panel_capas._aplicar_fondo()
    assert estado["mapa_base"] == "calles"
    assert estado["dock_mapa_base"] == "calles"
    from pathlib import Path
    codigo = Path(panel_capas.__file__).read_text(encoding="utf-8")
    assert 'key="dock_mapa_base"' in codigo
    assert 'key="mapa_base"' not in codigo


def test_dock_no_permite_fondo_no_disponible(monkeypatch):
    estado = {"dock_mapa_base": "carto_oscuro", "mapa_base": "calles"}
    monkeypatch.setattr(panel_capas.st, "session_state", estado)
    monkeypatch.setattr(panel_capas.mapas_base, "ofrecidos", lambda: ["calles"])
    monkeypatch.setattr(panel_capas.mapas_base, "predeterminado", lambda: "calles")
    panel_capas._aplicar_fondo()
    assert estado["dock_mapa_base"] == estado["mapa_base"] == "calles"
