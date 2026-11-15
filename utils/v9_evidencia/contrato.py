"""Adaptador prudente V9 entre registros observacionales y evaluador V8.

No produce predicciones ni confirma inundación: consume registros ya verificados.
Una consulta de catálogo nunca puede marcarse como evidencia observacional.
"""
from __future__ import annotations

from datetime import date

from utils.verificacion_multifuente import evaluar_evidencias


_OBSERVACION = frozenset({"agua_satelital", "cambio_agua", "qa_sar"})
_PERMITIDOS = _OBSERVACION | {"lluvia", "hidrologia", "reporte_oficial"}


def normalizar_evidencias(registros, inicio: date, fin: date):
    """Validar contrato de origen/tiempo/QA sin mejorar la validez de las entradas."""
    if not isinstance(inicio, date) or not isinstance(fin, date) or fin < inicio:
        raise ValueError("Fechas de análisis inválidas")
    aceptados, descartados = [], []
    for indice, dato in enumerate(registros):
        razon = None
        if not isinstance(dato, dict):
            razon = "REGISTRO_INVALIDO"
        elif dato.get("tipo") not in _PERMITIDOS:
            razon = "TIPO_INVALIDO"
        elif dato.get("valid") is not True:
            razon = "NO_VALIDADO"
        else:
            try:
                fecha = date.fromisoformat(str(dato.get("observed_at", ""))[:10])
            except ValueError:
                fecha = None
            if fecha is None or not inicio <= fecha <= fin:
                razon = "FECHA_FUERA_DE_VENTANA"
            elif dato.get("relacion_espacial") not in ("aoi", "municipio"):
                razon = "ALCANCE_DESCONOCIDO"
            elif not str(dato.get("origen") or "").strip() or not str(dato.get("fuente") or "").strip():
                razon = "ORIGEN_O_FUENTE_FALTANTE"
            elif dato["tipo"] in _OBSERVACION:
                qa = dato.get("qa")
                if (dato.get("evidencia_observacional") is not True
                        or not isinstance(qa, dict)
                        or type(qa.get("pixeles_validos")) is not int
                        or qa["pixeles_validos"] <= 0):
                    razon = "QA_OBSERVACIONAL_INSUFICIENTE"
                elif dato["tipo"] in {"agua_satelital", "cambio_agua"} and dato["relacion_espacial"] != "aoi":
                    razon = "SIN_EVIDENCIA_EN_AOI"
                elif not str(dato.get("producto") or "").strip() or not str(dato.get("url") or "").strip():
                    razon = "PRODUCTO_SIN_TRAZABILIDAD"
            elif dato["tipo"] == "reporte_oficial" and not str(dato.get("url") or "").strip():
                razon = "REPORTE_SIN_URL"
        if razon:
            descartados.append({"indice": indice, "motivo": razon})
        else:
            aceptados.append(dict(dato))
    return {"aceptados": aceptados, "descartados": descartados}


def evaluar_paquete(registros, inicio: date, fin: date):
    """Evaluar solo registros normalizados; la ausencia de datos no prueba ausencia de agua."""
    limpio = normalizar_evidencias(registros, inicio, fin)
    resultado = evaluar_evidencias(limpio["aceptados"], inicio, fin)
    resultado["descartados_con_motivo"] = limpio["descartados"]
    resultado["fuentes_aceptadas"] = sorted({r["fuente"] for r in limpio["aceptados"]})
    resultado["nota_qa"] = (
        "Observaciones SAR/agua exigen validación previa de píxeles QA. "
        "Huellas de catálogo, lluvia o ausencia de datos no confirman inundación."
    )
    return resultado
