"""Panel de evidencia para PC; no ejecuta descargas ni operaciones raster."""
from __future__ import annotations

from utils.v9_evidencia import evaluar_paquete


_TITULOS = {
    "INUNDACION_DOCUMENTADA_POR_AUTORIDAD": "Inundación documentada por autoridad (alcance del reporte)",
    "AGUA_OBSERVADA_POR_SATELITE": "Agua observada con QA en la zona",
    "POSIBLE_INUNDACION": "Posible inundación; requiere validación independiente",
    "CONDICIONES_METEOROLOGICAS_O_HIDROLOGICAS": "Condiciones meteorológicas o hidrológicas",
    "INFORMACION_INSUFICIENTE": "Información insuficiente para concluir",
}


def mostrar_panel(registros, inicio, fin, interfaz=None):
    """Renderizado liviano; recibe registros ya obtenidos y permite stub en tests."""
    if interfaz is None:
        import streamlit as interfaz  # Solo en invocación desde la UI.

    resultado = evaluar_paquete(registros, inicio, fin)
    interfaz.subheader("V.I.S.O.R. · Evidencias del territorio")
    if resultado["estados"] == ["INFORMACION_INSUFICIENTE"]:
        interfaz.warning("No hay datos observacionales suficientes para esta zona y fecha.")
    else:
        for estado in resultado["estados"]:
            interfaz.write(_TITULOS[estado])
    interfaz.caption(resultado["nota_qa"])
    interfaz.caption(resultado["limitaciones"])
    if resultado["fuentes_aceptadas"]:
        interfaz.caption("Fuentes registradas: " + ", ".join(resultado["fuentes_aceptadas"]))
    if resultado["descartados_con_motivo"]:
        interfaz.caption(f"Registros no utilizables: {len(resultado['descartados_con_motivo'])}")
    return resultado
