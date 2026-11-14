"""Estado de sesión del recorrido: lugar → zona → escenas → análisis → resultado.

Todo vive en `st.session_state` de la sesión del navegador: nada de aquí se comparte entre
personas ni se restaura al abrir una sesión nueva. La lógica pura está en utils/sesion.py.

Claves:
    lugar             {"etiqueta", "latitud", "longitud"} — marcador de la última búsqueda
    zona              {"limites", "origen", "geometria"} — zona CONFIRMADA; None si no hay
    resultado_activo  {"id", "origen", "contexto", "run_id", "abierto"} — único resultado en el mapa
    sel_par           índice del par elegido en la búsqueda vigente
    sel_parametros    polarización → {umbral, ventana} elegidos

`sel_par` y `sel_parametros` son copias propias de lo elegido en los controles. No se lee el valor
de un control antes de dibujarlo: al empezar una ejecución Streamlit todavía lo guarda en su forma
de interfaz (un selector, como el texto de la opción) y el par parecería haber cambiado.
    aviso_resultado   texto que explica por qué se retiró un resultado (se muestra una vez)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import streamlit as st

from utils import sesion
from utils.resultados import ResultadoSAR

UMBRAL_DEFECTO, VENTANA_DEFECTO = 3.0, 5
POLARIZACIONES = ("VV", "VH", "HH", "HV")
ESTADO_INICIAL = {"lugar": None, "zona": None, "resultado_activo": None, "aviso_resultado": None,
                  "lugares_encontrados": None, "sel_par": None, "sel_parametros": None}


def inicializar() -> None:
    for clave, valor in ESTADO_INICIAL.items():
        st.session_state.setdefault(clave, valor)


def periodo_por_defecto() -> tuple[date, date]:
    """Últimos 60 días: ninguna fecha de un caso concreto queda escrita en el código."""
    hoy = datetime.now(timezone.utc).date()
    return hoy - timedelta(days=60), hoy


# --- Zona -------------------------------------------------------------------

def zona_confirmada() -> tuple[float, float, float, float] | None:
    zona = st.session_state.get("zona")
    return tuple(zona["limites"]) if zona else None


def confirmar_zona(limites, origen: str, geometria: dict | None = None) -> None:
    """Fija la zona de análisis. Lo anterior (catálogo, par, resultado) deja de corresponder."""
    st.session_state["zona"] = {"limites": sesion.validar_zona(limites), "origen": origen, "geometria": geometria}
    st.session_state.update(sar_busqueda=None, sar_error_busqueda=None, mc_informe_sar=None, error_zona=None)
    st.session_state["sel_par"] = None


def quitar_zona() -> None:
    st.session_state["zona"] = None
    st.session_state.update(sar_busqueda=None, sar_error_busqueda=None, mc_informe_sar=None, error_zona=None)
    st.session_state["sel_par"] = None


# --- Contexto y resultado activo ----------------------------------------------

def par_actual():
    busqueda = st.session_state.get("sar_busqueda")
    if busqueda is None or not busqueda.pares:
        return None
    i = st.session_state.get("sel_par")
    return busqueda.pares[i] if isinstance(i, int) and 0 <= i < len(busqueda.pares) else None


def parametros_actuales(polarizaciones=POLARIZACIONES) -> dict[str, dict]:
    """Umbral y ventana elegidos por polarización (o los valores por defecto si aún no se tocaron)."""
    elegidos = st.session_state.get("sel_parametros") or {}
    return {p: {"umbral_disminucion_db": float((elegidos.get(p) or {}).get("umbral_disminucion_db", UMBRAL_DEFECTO)),
                "ventana_speckle": int((elegidos.get(p) or {}).get("ventana_speckle", VENTANA_DEFECTO))}
            for p in polarizaciones}


def fijar_parametro(polarizacion: str, clave: str, valor) -> None:
    elegidos = dict(st.session_state.get("sel_parametros") or {})
    elegidos[polarizacion] = {**(elegidos.get(polarizacion) or {}), clave: valor}
    st.session_state["sel_parametros"] = elegidos


def contexto_actual() -> str:
    par = par_actual()
    return sesion.contexto(zona_confirmada(), sesion.clave_par(par.antes.nombre, par.despues.nombre) if par else None,
                           parametros_actuales())


def activar(id_resultado: str, origen: str, run_id: str | None = None) -> None:
    st.session_state["resultado_activo"] = {
        "id": id_resultado, "origen": origen, "contexto": contexto_actual(), "run_id": run_id,
        "abierto": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    st.session_state["aviso_resultado"] = None


def limpiar_resultado(aviso: str | None = None) -> None:
    st.session_state["resultado_activo"] = None
    st.session_state["aviso_resultado"] = aviso


def sincronizar(resultados: list[ResultadoSAR]) -> ResultadoSAR | None:
    """Resultado que el mapa puede mostrar AHORA, o None. Se llama una vez por ejecución, antes de
    dibujar nada: si la zona, el par o los parámetros ya no son los del resultado, se retira."""
    activo = st.session_state.get("resultado_activo")
    if not activo:
        return None
    res = next((r for r in resultados if r.id == activo["id"] and r.dibujable), None)
    if res is None:
        limpiar_resultado("El resultado que estaba en el mapa ya no se puede leer; se retiró.")
        return None
    if activo["contexto"] != contexto_actual():
        limpiar_resultado("Cambiaste la zona, el par de imágenes o los parámetros: el resultado anterior ya no "
                          "corresponde y se retiró del mapa. Sigue guardado en el historial.")
        return None
    return res


def es_historico() -> bool:
    return (st.session_state.get("resultado_activo") or {}).get("origen") == sesion.HISTORICO


def etiqueta_origen() -> str:
    return "HISTÓRICO" if es_historico() else "ANÁLISIS DE ESTA SESIÓN"
