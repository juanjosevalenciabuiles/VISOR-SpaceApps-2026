"""Comodidad visual: buscador con sugerencias locales, coordenadas, y lo técnico plegado (sin red)."""
import inspect
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from components import barra_lateral, herramientas_sar, interfaz, resultados
from utils import lugares


def test_sugerencias_son_locales_e_incluyen_los_municipios_del_dane(monkeypatch):
    monkeypatch.setenv("VISOR_REGION_MODE", "CO")
    s = lugares.sugerencias()
    assert len(s) > 1100, "catálogo + 1122 municipios"
    for etiqueta in ("Chigorodó, Antioquia, Colombia", "Rionegro, Antioquia, Colombia", "Rionegro, Santander, Colombia",
                     "San Benito Abad, Sucre, Colombia", "Providencia, San Andrés y Providencia, Colombia"):
        assert etiqueta in s or any(k.startswith(etiqueta.split(",")[0]) for k in s), etiqueta
    assert not any("Tokio" in k or "Nairobi" in k for k in s), "en Modo Colombia no se sugiere nada de fuera"
    assert len([k for k in s if k.startswith("Chigorodó,")]) == 1, "sin duplicar catálogo y DANE"
    lugar = s["Carepa, Antioquia, Colombia"]
    assert 7.5 < lugar.latitud < 8.0 and -77 < lugar.longitud < -76.4
    # Nada de red al sugerir: Nominatim prohíbe el autocompletado.
    assert "urlopen" not in inspect.getsource(lugares._sugerencias) and "buscar_en_linea" not in inspect.getsource(
        lugares._sugerencias)


@pytest.mark.parametrize("texto,esperado", [
    ("7.67, -76.68", (7.67, -76.68)), ("7,67 -76,68", (7.67, -76.68)), ("7.67,-76.68", (7.67, -76.68)),
    ("Chigorodó", None), ("95, 10", None), ("1 2 3", None), ("", None)])
def test_coordenadas_escritas(texto, esperado):
    assert lugares.coordenadas(texto) == esperado


def test_elegir_una_sugerencia_o_coordenadas_solo_ubica_el_mapa(monkeypatch):
    monkeypatch.setenv("VISOR_REGION_MODE", "CO")
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    caja = at.selectbox(key="lugar_texto")
    assert caja.value is None and "Chigorodó, Antioquia, Colombia" in caja.options
    caja.set_value("Chigorodó, Antioquia, Colombia").run()
    assert not at.exception and at.session_state["lugar"]["etiqueta"] == "Chigorodó, Antioquia, Colombia"
    assert at.session_state["zona"] is None and at.session_state["resultado_activo"] is None


def test_coordenadas_en_el_buscador_respetan_el_alcance(monkeypatch):
    """Texto libre con coordenadas: navega dentro de Colombia y lo rechaza fuera (callback directo)."""
    import streamlit as st
    monkeypatch.setenv("VISOR_REGION_MODE", "CO")
    estado = {"lugar_texto": "6.25, -75.57", "resultado_activo": None, "zona": None}
    monkeypatch.setattr(st, "session_state", estado)
    idas = []
    barra_lateral._buscar_lugar(lambda lat, lon, zoom: idas.append((lat, lon)))      # Medellín
    assert idas == [(6.25, -75.57)] and estado["lugar"]["latitud"] == 6.25 and estado["lugares_encontrados"] is None
    estado["lugar_texto"] = "-0.22, -78.51"                                           # Quito: fuera de Colombia
    barra_lateral._buscar_lugar(lambda lat, lon, zoom: idas.append((lat, lon)))
    assert len(idas) == 1, "no navega"
    assert "Colombia" in estado["lugares_encontrados"]["aviso"]


def test_lo_tecnico_va_plegado_y_el_boton_a_la_vista():
    ficha = inspect.getsource(resultados.ficha_html)
    assert ficha.index("leyenda_html(res)") < ficha.index("res-detalles-tecnicos") < ficha.index("Datos de origen")
    analisis = inspect.getsource(herramientas_sar.paso_analisis)
    assert 'key="sar_avanzado"' in analisis and "expanded=False" in analisis
    explorador = inspect.getsource(barra_lateral.render)
    assert explorador.index('key="nota_mapa_base"') < explorador.index("No disponibles aquí")
    assert all(len(p) <= 13 for p in interfaz.PASOS_SAR), "los nombres de los pasos caben en la pestaña"
    assert "CONCEPTUAL" not in inspect.getsource(interfaz.linea_temporal)
