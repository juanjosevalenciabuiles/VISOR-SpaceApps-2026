"""Selección temporal desde periodo de interés; solo metadatos, sin raster."""
from datetime import date, datetime

from .planificador_stack import planificar_stack


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def planificar_periodo(escenas, aoi, inicio, fin=None, *,
                      margen_dias=30, presupuesto_bytes=200_000_000):
    """Plan pre/post para fecha aproximada o intervalo inclusivo.

    La referencia pre debe ser anterior al inicio del periodo, y la post
    posterior al final. El planificador base no permite inferir cobertura QA.
    """
    principio = _fecha(inicio)
    cierre = _fecha(fin) if fin is not None else principio
    if cierre < principio or margen_dias < 0:
        raise ValueError("Periodo o margen inválidos")
    filtradas = []
    fuera = 0
    for escena in escenas:
        try:
            fecha = _fecha(escena["observed_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if principio <= fecha <= cierre:
            continue  # Una toma durante el evento no es baseline pre ni post.
        if fecha < principio:
            distancia = (principio - fecha).days
            objetivo = principio
        else:
            distancia = (fecha - cierre).days
            objetivo = cierre
        if distancia > margen_dias:
            fuera += 1
            continue
        # Reexpresar el tiempo relativo a un punto de corte sin modificar
        # observed_at ni el linaje real de la escena.
        filtradas.append(escena)
    # El planificador base compara pre/post alrededor de un solo corte.
    # Para intervalos, se usa inicio como corte y se filtra explícitamente
    # cualquier escena dentro del evento antes de llamar.
    plan = planificar_stack(
        filtradas, aoi, principio, dias_antes=margen_dias,
        dias_despues=(cierre - principio).days + margen_dias,
        presupuesto_bytes=presupuesto_bytes,
    )
    plan["periodo_interes"] = [principio.isoformat(), cierre.isoformat()]
    plan["fuera_ventana"] = fuera
    if plan["estado"] != "PLAN_METADATOS":
        plan["advertencia"] += " No hay par pre/post con QA verificado en la ventana."
    return plan
