"""Estados de trabajo del visor PC; jamás inferir una capa desde insumos."""
from __future__ import annotations

from components.v9_desktop.perfiles import perfil_publicable

ESTADOS = {
    "sin_busqueda": "Selecciona zona y periodo para iniciar.",
    "buscando": "Buscando escenas para la zona y el periodo.",
    "descargando": "Preparando descarga recortada a la AOI autorizada.",
    "preparando": "Preparando datos y verificando calidad.",
    "procesando": "Comparando observaciones válidas.",
    "apto": "Resultado exploratorio disponible; revisar QA y procedencia.",
    "sin_cobertura": "Sin cobertura utilizable en la zona y el periodo.",
    "qa_insuficiente": "QA insuficiente: no se puede concluir.",
    "solo_catalogo": "Solo metadatos de catálogo o RTC sin preparar; no hay mapa.",
    "sin_par": "No hay un par temporal válido para comparar.",
    "error": "El análisis no terminó; no hay resultado publicado.",
}

def describir_estado(estado: str, *, ficha: dict | None = None) -> dict:
    """Contrato de visualización sin IO: apto exige ficha y raster validado."""
    if estado not in ESTADOS:
        raise ValueError("Estado de análisis desconocido")
    ficha = ficha or {}
    # La compuerta única valida perfil, fechas y QA; nunca confiar en un
    # estado "apto" aislado ni en un indicador de raster sin ficha coherente.
    perfil = perfil_publicable(
        ficha, raster_verificado=ficha.get("raster_validado") is True
    )
    publicado = estado == "apto" and perfil["mostrar_mapa"]
    if estado == "apto" and not publicado:
        estado = "qa_insuficiente"
    return {
        "estado": estado,
        "mensaje": ESTADOS[estado],
        "mostrar_mapa": publicado,
        "eco": (
            "Hay una observación validada; el cambio de señal SAR no prueba por sí solo inundación."
            if publicado else
            "No hay evidencia suficiente para mostrar una capa de inundación."
        ),
        "piloto_ml": "Experimental: sin modelo entrenado ni predicciones verificadas.",
    }
