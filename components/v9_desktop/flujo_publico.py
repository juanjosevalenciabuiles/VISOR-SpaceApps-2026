"""Entrada única de escritorio V9; sin red, raster ni inferencias al renderizar."""
from __future__ import annotations

from datetime import date

from components.v9_desktop.estados import describir_estado

SENSORES = ("NISAR L (preferido)", "Sentinel-1 C (respaldo)")
TERMINALES = frozenset({"apto", "sin_cobertura", "qa_insuficiente", "solo_catalogo", "sin_par", "error"})
INTERMEDIOS = frozenset({"buscando", "descargando", "preparando", "procesando"})


def solicitud_publica(zona: str, inicio: date, fin: date, *, sensor: str = SENSORES[0]) -> dict:
    """Solo metadatos del usuario; el backend decide si existen escenas comparables."""
    if not isinstance(zona, str) or not zona.strip():
        raise ValueError("Indica una zona de estudio.")
    if not isinstance(inicio, date) or not isinstance(fin, date) or fin < inicio:
        raise ValueError("El periodo de interés es inválido.")
    if sensor not in SENSORES:
        raise ValueError("Sensor no permitido.")
    return {"zona": zona.strip(), "inicio": inicio.isoformat(), "fin": fin.isoformat(),
            "sensor_preferido": sensor, "respaldo": SENSORES[1]}


def estado_backend(respuesta: dict | None) -> dict:
    """No se eleva una preparación de COG o catálogo a resultado publicado."""
    if not isinstance(respuesta, dict):
        return describir_estado("solo_catalogo")
    estado = respuesta.get("estado", "solo_catalogo")
    if estado not in TERMINALES | INTERMEDIOS:
        return describir_estado("error")
    if respuesta.get("tipo") in {"HARMONY_COG_SUBSET", "INSUMOS_GCOV_SIN_CLASIFICAR",
                                 "CATALOGO", "RTC_NO_PREPARADO"}:
        return describir_estado("solo_catalogo")
    return describir_estado(estado, ficha=respuesta.get("ficha"))


def render(interfaz=None, *, respuesta=None, lugar_buscado=None, area_analisis=None):
    """Dibuja UI PC; NO inicia análisis. Devuelve solicitud al pulsar botón.

    El integrador toma la solicitud y encola su pipeline fuera de render().
    'respuesta' proviene de un backend real, nunca de fixtures predeterminados.
    """
    if interfaz is None:
        import streamlit as interfaz
    interfaz.subheader("Buscar y analizar cambios")
    zona = interfaz.text_input("Zona de estudio", key="v9_zona")
    columnas = interfaz.columns(2)
    inicio = columnas[0].date_input("Desde", value=date(2026, 10, 1), key="v9_inicio")
    fin = columnas[1].date_input("Hasta", value=date(2026, 11, 14), key="v9_fin")
    with interfaz.expander("Configuración científica avanzada", expanded=False):
        sensor = interfaz.selectbox("Fuente SAR preferida", SENSORES, index=0)
        interfaz.caption("El sistema busca NISAR L y usa Sentinel-1 C como respaldo; "
                         "no combina bandas ni escenas incompatibles.")
    if lugar_buscado:
        interfaz.caption("Lugar buscado: " + str(lugar_buscado))
    if area_analisis:
        interfaz.caption("Área de análisis cruza municipios: " + str(area_analisis))
    solicitud = None
    if interfaz.button("Buscar y analizar cambios", type="primary"):
        try:
            solicitud = solicitud_publica(zona, inicio, fin, sensor=sensor)
        except ValueError as exc:
            interfaz.warning(str(exc))
    estado = estado_backend(respuesta)
    interfaz.info(estado["mensaje"])
    interfaz.caption("ECO: " + estado["eco"])
    interfaz.caption(estado["piloto_ml"])
    if estado["mostrar_mapa"]:
        interfaz.caption("Indicio exploratorio, no predicción. Mostrar solo capa real "
                         "con procedencia y QA verificadas por el backend.")
    return solicitud
