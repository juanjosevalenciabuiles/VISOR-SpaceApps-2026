"""Leyenda abreviada y científicamente fiel al tipo REAL de GeoTIFF.

Un color SAR nunca codifica por sí solo magnitud de inundación. En particular,
naranja significa aumento en ΔdB/máscara, pero disminución SOLO en VH en
coincidencia VV/VH; no puede existir una leyenda universal por color.
"""
from __future__ import annotations


def entradas(perfil: str, lenguaje: str = "en") -> list[tuple[str, str]]:
    """(color hexadecimal o transparente, descripción). Sin acceso a ráster ni red."""
    en = lenguaje != "es"
    if perfil == "diferencia_db":
        return [
            ("#00BFEF", "Blue — Lower radar backscatter; possible surface water (unconfirmed)" if en
             else "Azul — Menor señal radar; posible agua superficial (sin confirmar)"),
            ("#FF9F0A", "Orange — Higher radar backscatter; NOT a measure of flood size" if en
             else "Naranja — Mayor señal radar; NO mide el tamaño de una inundación"),
            ("transparent", "Transparent — NoData or hidden small variations" if en
             else "Transparente — Sin datos o pequeñas variaciones ocultas"),
        ]
    if perfil == "coincidencia_vv_vh":
        return [
            ("#00F0FF", "Cyan — Significant decrease in VV only" if en
             else "Cian — Disminución significativa solo en VV"),
            ("#FF9F0A", "Orange — Significant decrease in VH only" if en
             else "Naranja — Disminución significativa solo en VH"),
            ("#7D7AFF", "Purple — Significant decrease in both VV and VH" if en
             else "Violeta — Disminución significativa en VV y VH"),
            ("transparent", "Transparent — Neither polarization decreased, or NoData" if en
             else "Transparente — Sin disminución en VV/VH, o sin datos"),
        ]
    if perfil == "mascara_cambios":
        return [
            ("#00F0FF", "Cyan — Significant decrease in radar signal" if en
             else "Cian — Disminución significativa de señal radar"),
            ("#FF9F0A", "Orange — Significant increase in radar signal" if en
             else "Naranja — Aumento significativo de señal radar"),
            ("#7D7AFF", "Purple — Low radar backscatter on both dates" if en
             else "Violeta — Señal radar baja en ambas fechas"),
            ("transparent", "Transparent — No significant change, or NoData" if en
             else "Transparente — Sin cambio significativo, o sin datos"),
        ]
    return []


def aviso(lenguaje: str = "en") -> str:
    return ("SAR colors indicate signal characteristics, not confirmed flooding or flood severity."
            if lenguaje != "es" else
            "Los colores SAR describen la señal, no inundaciones confirmadas ni su gravedad.")
