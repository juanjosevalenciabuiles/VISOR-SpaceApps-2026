"""Perfiles de publicación PC: describen capas declaradas, sin abrir rasters.

La verificación del archivo, su SHA-256 y su QA corresponde al backend V8.
Nunca se infiere una clase de inundación a partir de una diferencia en dB.
"""
from __future__ import annotations

from datetime import date

PERFIL_CAMBIO = "diferencia_db"
PERFIL_CLASES = "clases_inundacion_nisar"
CLASES = {
    "agua_persistente": ("Agua persistente", "azul"),
    "agua_nueva": ("Nueva agua observada", "cian"),
    "vegetacion_inundada_posible": ("Posible vegetación inundada", "violeta"),
    "dudoso": ("Dudoso", "amarillo"),
    "sin_datos": ("Sin datos", "transparente"),
}


def perfil_publicable(ficha: dict | None, *, raster_verificado: bool = False) -> dict:
    """Solo autoriza leyenda si backend verificó raster, procedencia y QA.

    real_sin_validar permite una diferencia exploratoria, no una clasificación.
    Una ficha aislada, aunque declare SHA, jamás habilita un mapa.
    """
    base = {"mostrar_mapa": False, "leyenda": {}, "unidad": None,
            "mensaje": "No hay capa científica verificada para visualizar."}
    if not isinstance(ficha, dict) or not raster_verificado:
        return base
    if ficha.get("schema") != "visor.ficha.v1" or not ficha.get("sha256"):
        return base
    if ficha.get("qa_apto") is not True or not ficha.get("fecha_inicio") or not ficha.get("fecha_fin"):
        return base
    try:
        inicio = date.fromisoformat(ficha["fecha_inicio"])
        fin = date.fromisoformat(ficha["fecha_fin"])
    except (TypeError, ValueError):
        return base
    if fin < inicio:
        return base
    estado = ficha.get("estado")
    if estado not in ("real_sin_validar", "validado"):
        return base
    perfil = ficha.get("tipo_producto")
    if perfil == PERFIL_CAMBIO and ficha.get("unidad") == "dB":
        return {"mostrar_mapa": True, "leyenda": {}, "unidad": "dB",
                "mensaje": "Cambio de señal SAR · Indicio exploratorio, no predicción."}
    if perfil == PERFIL_CLASES and estado == "validado" and ficha.get("clases_verificadas") is True:
        return {"mostrar_mapa": True, "leyenda": CLASES.copy(), "unidad": None,
                "mensaje": "Clases observacionales verificadas; no equivale a inundación confirmada."}
    return base
