"""Experiencia PC: área + periodo -> COG NISAR -> mapa real de cambio SAR.

No afirma inundaciones ni predicciones; evita volver a descargar COG ya preparados.
Las opciones especializadas continúan en Herramientas SAR por compatibilidad.
"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import streamlit as st

from utils.i18n import tr

from components import flujo
from utils import nisar_auto, nisar_catalogo as cat, nisar_coberturas, nisar_descarga, sesion, trabajos
from utils.config import DATA_DIR
from utils.resultados import id_resultado, leer_resultado
from utils.v9_nisar_puente import QAInsuficiente, escenas_preparadas, leer_preparacion
from utils.v9_trabajo_mapa import iniciar

MAX_HARMONY_MB = 384
MARGEN_DIAS = 45
INICIO_PROVISIONAL = date(2026, 6, 17)
FIN_PROVISIONAL = date(2026, 10, 23)
DISTANCIA_SUGERENCIAS_DIAS = 180


def _madurez_del_periodo(inicio: date, fin: date) -> str:
    """Elegir UNA colección compatible, sin mezclar procesamientos."""
    if inicio > fin:
        raise ValueError("El período debe estar ordenado.")
    if inicio < cat.INICIO_VALIDATED and fin <= FIN_PROVISIONAL:
        return "PROVISIONAL"
    return "VALIDATED"


def _limites_coleccion(madurez: str, inicio: date, fin: date,
                       margen: int = MARGEN_DIAS) -> tuple[date, date]:
    hoy = datetime.now(timezone.utc).date()
    minimo = INICIO_PROVISIONAL if madurez == "PROVISIONAL" else cat.INICIO_VALIDATED
    maximo = FIN_PROVISIONAL if madurez == "PROVISIONAL" else hoy
    primero = max(minimo, inicio - timedelta(days=margen))
    ultimo = min(maximo, hoy, fin + timedelta(days=margen))
    if primero > ultimo:
        raise ValueError("No hay adquisiciones públicas NISAR de esta madurez "
                         "cerca del período seleccionado.")
    return primero, ultimo


def _distancia_fechas(par, inicio: date, fin: date) -> tuple[int, int, int]:
    a = par.antes.nombre.inicio.date()
    b = par.despues.nombre.inicio.date()
    separacion = ((inicio - b).days if b < inicio else
                  (a - fin).days if a > fin else 0)
    return max(0, separacion), abs((a - inicio).days) + abs((b - fin).days), (b - a).days


def _sugerencias_cercanas(pares, inicio: date, fin: date, limite: int = 3) -> list:
    """Ordena PARES documentados por CMR, no inventa fechas ni valida píxeles."""
    unicos = {}
    for par in pares:
        a = par.antes.nombre.inicio.date()
        b = par.despues.nombre.inicio.date()
        if a >= b:
            continue
        unicos.setdefault((a, b), par)
    return sorted(unicos.values(), key=lambda par: _distancia_fechas(par, inicio, fin))[:limite]


def _sugerencias_validas_cmr(resultado, pares, zona, inicio: date, fin: date) -> list[dict]:
    """Pares alternativos CON plan CMR apto, no fechas supuestas ni QA simulado.

    Se aplica la misma validación de cobertura/presupuesto que el selector,
    usando la AOI actual. Una huella válida no certifica píxeles Harmony.
    """
    opciones = nisar_coberturas.opciones(
        resultado, pares, max_gb=15.0, punto_prioritario=_punto_local(zona),
    )
    utilizables = [
        op for op in opciones if op.get("plan") is not None and
        not _pares_del_periodo([op["par"]], inicio, fin)
    ]
    unicas = {}
    for op in utilizables:
        par = op["par"]
        fechas = (par.antes.nombre.inicio.date(), par.despues.nombre.inicio.date())
        previo = unicas.get(fechas)
        if previo is None or op["cobertura"] > previo["cobertura"]:
            unicas[fechas] = op
    return sorted(
        unicas.values(),
        key=lambda op: (
            not op["cubre_punto"],  # priorizar el lugar consultado si existe
            _distancia_fechas(op["par"], inicio, fin),
            -op["cobertura"],
        ),
    )[:3]


def _limpiar_v9(limpiar_fechas: bool = False) -> None:
    for clave in ("v9_firma", "v9_preparacion", "v9_mapa_job", "v9_publicado",
                  "v9_error", "v9_sugerencias", "v9_preflight_provisional",
                  "nisar_auto_job", "v9_coberturas", "v9_coberturas_error",
                  "v9_pares_solapados", "v9_ultimo_click_par"):
        st.session_state.pop(clave, None)
    if limpiar_fechas:
        for clave in ("v9_inicio_periodo", "v9_fin_periodo"):
            st.session_state.pop(clave, None)


def _nuevo_analisis(nueva_zona: bool) -> None:
    """Preparar otra exploración sin borrar archivos ni el historial."""
    _limpiar_v9(limpiar_fechas=nueva_zona)
    flujo.limpiar_resultado()
    if nueva_zona:
        flujo.quitar_zona()
        st.session_state["lugar"] = None
        st.session_state["ui_explorador"] = True
        st.session_state["ui_sar"] = "minimizado"
    else:
        st.session_state["ui_sar"] = "abierto"
        st.session_state["ui_explorador"] = False


def _usar_fechas_sugeridas(inicio: date, fin: date) -> None:
    _limpiar_v9()
    st.session_state["v9_inicio_periodo"] = inicio
    st.session_state["v9_fin_periodo"] = fin



def _firma(zona, inicio: date, fin: date):
    return (tuple(zona), inicio.isoformat(), fin.isoformat())


def _coberturas_actuales() -> dict | None:
    """Rechazar las huellas de otra zona/fechas aun si Streamlit las conserva."""
    estado = st.session_state.get("v9_coberturas")
    zona = flujo.zona_confirmada()
    inicio = st.session_state.get("v9_inicio_periodo")
    fin = st.session_state.get("v9_fin_periodo")
    if (not isinstance(estado, dict) or zona is None
            or not isinstance(inicio, date) or not isinstance(fin, date)):
        return None
    return estado if estado.get("firma") == _firma(zona, inicio, fin) else None


def _resultado_sar_verificado(estado: dict | None) -> bool:
    """Solo ocultar huellas CMR tras publicar el GeoTIFF SAR apto de esta AOI.

    v9_publicado se establece únicamente al superar análisis, QA y procedencia.
    No ocultarlas mientras Harmony procesa ni si falla o el resultado se retira.
    """
    if not estado or st.session_state.get("v9_firma") != estado.get("firma"):
        return False
    mapa_job = st.session_state.get("v9_mapa_job")
    activo = st.session_state.get("resultado_activo") or {}
    return bool(
        mapa_job and st.session_state.get("v9_publicado") == mapa_job
        and activo.get("id") and activo.get("origen") == sesion.ANALISIS
    )


def grupos_mapa():
    """Huellas para elegir par; fuera del mapa cuando ya se muestra SAR verificado."""
    estado = _coberturas_actuales()
    if not estado or _resultado_sar_verificado(estado):
        return []
    from components import cobertura_nisar
    return cobertura_nisar.grupos(estado, estado["firma"])


def modo_seleccion_mapa() -> bool:
    estado = _coberturas_actuales()
    return bool(estado and estado.get("opciones") and
                not _resultado_sar_verificado(estado))


def seleccionar_desde_mapa(click: dict | None, clave_mapa: str) -> bool:
    """Identifica el par por geometría; con solapamientos exige elección explícita."""
    estado = _coberturas_actuales()
    if not estado or not isinstance(click, dict):
        return False
    try:
        lat, lon = float(click["lat"]), float(click["lng"])
    except (KeyError, ValueError, TypeError):
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    firma = (clave_mapa, round(lat, 7), round(lon, 7), estado["firma"])
    if st.session_state.get("v9_ultimo_click_par") == firma:
        return False
    st.session_state["v9_ultimo_click_par"] = firma
    from shapely.geometry import Point
    punto = Point(lon, lat)
    # Solo elegir entre los pares realmente dibujados en esta vista.
    coincidencias = [
        item for item in nisar_coberturas.opciones_mapa(estado, estado["firma"])
        if item["geometria"].covers(punto)
    ]
    if not coincidencias:
        return False
    if len(coincidencias) > 1:
        st.session_state["v9_pares_solapados"] = [item["id"] for item in coincidencias]
        st.session_state["ui_sar"] = "abierto"
        return True
    estado["seleccionado"] = coincidencias[0]["id"]
    st.session_state["v9_pares_solapados"] = None
    return True


def _elegir_par(identificador: str) -> None:
    estado = _coberturas_actuales()
    if estado and any(op["id"] == identificador for op in estado.get("opciones", [])):
        estado["seleccionado"] = identificador
        st.session_state["v9_pares_solapados"] = None


def _clave_aceptacion(firma, identificador: str) -> str:
    """Misma confirmación de cobertura parcial para el formulario y el botón fijo."""
    from hashlib import sha256

    return "v9_aceptar_parcial_" + sha256(
        repr((firma, identificador)).encode("utf-8")
    ).hexdigest()[:12]


def _punto_local(zona) -> tuple[float, float] | None:
    lugar = st.session_state.get("lugar") or {}
    try:
        lon, lat = float(lugar["longitud"]), float(lugar["latitud"])
    except (KeyError, TypeError, ValueError):
        return None
    return (lon, lat) if zona[0] <= lon <= zona[2] and zona[1] <= lat <= zona[3] else None


def _consultar_coberturas(zona, inicio: date, fin: date) -> dict:
    """Solo metadatos NASA CMR. No crea trabajos, descarga ni analiza."""
    hoy = datetime.now(timezone.utc).date()
    if inicio > fin or fin > hoy:
        raise ValueError("El período debe estar ordenado y no contener fechas futuras.")
    madurez = _madurez_del_periodo(inicio, fin)
    desde, hasta = _limites_coleccion(madurez, inicio, fin)
    resultado = cat.buscar(*zona, desde, hasta, madurez=madurez)
    pares = _pares_del_periodo(resultado.pares, inicio, fin)
    opciones = nisar_coberturas.opciones(
        resultado, pares, max_gb=15.0, punto_prioritario=_punto_local(zona),
    )
    estado = {
        "firma": _firma(zona, inicio, fin), "madurez": madurez,
        "resultado": resultado, "opciones": opciones,
        "seleccionado": next((op["id"] for op in opciones if op["plan"] is not None), 
                            opciones[0]["id"] if opciones else None),
    }
    st.session_state["v9_coberturas"] = estado
    st.session_state.pop("v9_coberturas_error", None)
    st.session_state.pop("v9_pares_solapados", None)
    st.session_state.pop("v9_ultimo_click_par", None)
    # Tanto "sin pares en las fechas" como "pares con huella insuficiente"
    # necesitan alternativas. Sugerir SOLO fechas de pares que superen la
    # misma política de cobertura y presupuesto que el botón Analizar.
    if not any(op["plan"] is not None for op in opciones):
        amplia_desde, amplia_hasta = _limites_coleccion(
            madurez, inicio, fin, margen=DISTANCIA_SUGERENCIAS_DIAS)
        catalogo_sugerido = resultado
        consulta_incompleta = False
        if (amplia_desde, amplia_hasta) != (desde, hasta):
            try:
                catalogo_sugerido = cat.buscar(
                    *zona, amplia_desde, amplia_hasta, madurez=madurez
                )
            except (cat.ErrorConexion, cat.ErrorServicio):
                # La búsqueda principal sí funcionó; no descartar sus huellas
                # por un fallo temporal de la consulta adicional de fechas.
                consulta_incompleta = True
        sugeridos = _sugerencias_validas_cmr(
            catalogo_sugerido,
            [*resultado.pares, *catalogo_sugerido.pares],
            zona, inicio, fin,
        )
        st.session_state["v9_sugerencias"] = {
            "firma": estado["firma"], "madurez": madurez,
            "opciones": sugeridos, "consulta_incompleta": consulta_incompleta,
        }
    else:
        st.session_state.pop("v9_sugerencias", None)
    return estado


def _fechas_de_preparacion(job_id: str):
    datos = leer_preparacion(job_id)
    pares = escenas_preparadas(datos)
    return (date.fromisoformat(pares[0]["observed_at"][:10]),
            date.fromisoformat(pares[1]["observed_at"][:10]))


def _fechas_compatibles(pre: date, post: date, inicio: date, fin: date) -> bool:
    """El usuario elige un intervalo: acepta dos tomas dentro de él o que lo rodeen.

    Siempre exige dos observaciones distintas, reales y ordenadas. Las fechas
    efectivas del producto quedan en la ficha; no se inventan observaciones.
    """
    return (pre < post and inicio <= fin and
            ((inicio <= pre and post <= fin) or (pre < inicio and fin < post)))


def _pares_del_periodo(pares, inicio: date, fin: date) -> list:
    """Prioriza adquisiciones dentro del rango y, si faltan, pares pre/post.

    Para intervalos cortos entre pasadas NISAR, una toma anterior y otra
    posterior permiten estudiar el cambio sin fingir fechas intermedias.
    """
    dentro = [p for p in pares if inicio <= p.antes.nombre.inicio.date()
              < p.despues.nombre.inicio.date() <= fin]
    if dentro:
        return dentro
    return [p for p in pares if p.antes.nombre.inicio.date() < inicio
            and p.despues.nombre.inicio.date() > fin]


def _compatible(job: dict | None, zona, inicio: date, fin: date,
                granules: tuple[str, str] | None = None) -> bool:
    if not isinstance(job, dict) or job.get("estado") != trabajos.APTO:
        return False
    if job.get("tipo") != "adquisicion_nisar_gcov" or job.get("procesador") != "harmony_cog":
        return False
    if tuple((job.get("aoi") or {}).get("limites") or ()) != tuple(zona):
        return False
    if granules is not None and (
        (job.get("escenas") or {}).get("antes"),
        (job.get("escenas") or {}).get("despues"),
    ) != tuple(granules):
        return False
    try:
        pre, post = _fechas_de_preparacion(job["job_id"])
    except (QAInsuficiente, OSError, KeyError, ValueError):
        return False
    return _fechas_compatibles(pre, post, inicio, fin)


def _preparacion_existente(zona, inicio: date, fin: date,
                           granules: tuple[str, str] | None = None) -> dict | None:
    """Recuperar el par Harmony compatible más reciente aun en otra sesión.

    Los trabajos se registran en disco; guardar solo el último job_id en
    session_state hacía invisible un par válido preparado previamente.
    """
    for job in trabajos.listar(200):
        if _compatible(job, zona, inicio, fin, granules):
            return job
    return None


def _explorar_provisional(zona, inicio: date, fin: date):
    """Preflight CMR sin descargas: solo metadatos de la madurez PROVISIONAL.

    No envía trabajos Harmony, no calcula ΔdB y no confunde un candidato de
    catálogo con cobertura de píxeles aptos ni con una inundación confirmada.
    """
    hoy = datetime.now(timezone.utc).date()
    if inicio > fin or fin > hoy:
        raise ValueError("El intervalo debe estar ordenado y no incluir fechas futuras.")
    primero = max(date(2026, 6, 17), inicio - timedelta(days=MARGEN_DIAS))
    ultimo = min(date(2026, 10, 23), hoy, fin + timedelta(days=MARGEN_DIAS))
    if primero > ultimo:
        raise ValueError("La consulta queda fuera de las fechas públicas de NISAR PROVISIONAL.")
    resultado = cat.buscar(*zona, primero, ultimo, madurez="PROVISIONAL")
    return resultado, _pares_del_periodo(resultado.pares, inicio, fin)


def _mostrar_preflight(preflight, firma):
    if not isinstance(preflight, dict) or preflight.get("firma") != firma:
        return
    if preflight.get("error"):
        st.warning("No fue posible consultar el catálogo PROVISIONAL: " + preflight["error"])
        return
    resultado, pares = preflight["resultado"], preflight["pares"]
    st.caption(
        f"NASA CMR · colección PROVISIONAL · {resultado.total_catalogo} registros, "
        f"{len(resultado.candidatos)} escenas candidatas en la región · "
        f"{len(pares)} pares que cumplen las fechas. Solo metadatos, sin descargas."
    )
    if not pares:
        st.info(
            "No se identificó un par comparable que encierre o esté dentro de estas fechas "
            "para el área consultada. Esto no demuestra ausencia de inundación ni "
            "autoriza a fabricar un mapa."
        )
        return
    st.warning(
        "Hay candidatos PROVISIONAL por metadatos, NO datos descargados ni "
        "píxeles aptos verificados. Su procesamiento requiere controles científicos "
        "adicionales; no se ha iniciado."
    )
    for par in pares[:3]:
        st.caption(
            f"Posible par: {par.antes.nombre.inicio:%Y-%m-%d} → "
            f"{par.despues.nombre.inicio:%Y-%m-%d} · "
            f"órbita {par.antes.nombre.track}, frame {par.antes.nombre.frame}"
        )


def _abrir_modo_jurado():
    """Abrir solo archivos satelitales locales, nunca crear escenas sintéticas."""
    st.session_state["visor_modo_muestra_real"] = True


def _solicitar(zona, inicio: date, fin: date):
    hoy = datetime.now(timezone.utc).date()
    if inicio > fin or fin > hoy:
        raise ValueError("El intervalo debe estar ordenado y no incluir fechas futuras.")
    madurez = _madurez_del_periodo(inicio, fin)
    desde, hasta = _limites_coleccion(madurez, inicio, fin)
    resultado = cat.buscar(*zona, desde, hasta, madurez=madurez)
    candidatos = _pares_del_periodo(resultado.pares, inicio, fin)
    if not candidatos:
        pares = resultado.pares
        # Buscar también en la ventana ampliada por METADATOS para sugerir
        # un par más cercano, sin descargar ni extrapolar adquisiciones.
        amplio_desde, amplio_hasta = _limites_coleccion(
            madurez, inicio, fin, margen=DISTANCIA_SUGERENCIAS_DIAS)
        if (amplio_desde, amplio_hasta) != (desde, hasta):
            mas = cat.buscar(*zona, amplio_desde, amplio_hasta, madurez=madurez)
            pares = [*pares, *mas.pares]
        st.session_state["v9_sugerencias"] = {
            "firma": _firma(zona, inicio, fin), "madurez": madurez,
            "pares": _sugerencias_cercanas(pares, inicio, fin),
        }
        raise ValueError(
            "No se encontró un par NISAR compatible para estas fechas. "
            "Consulta los intervalos reales más cercanos sugeridos abajo."
        )
    if not os.environ.get(nisar_descarga.VARIABLE_TOKEN, "").strip():
        raise ValueError("Para adquirir nuevos recortes NISAR configura EARTHDATA_TOKEN "
                         "en los Secrets de Replit; no lo pegues en el chat.")
    plan = nisar_auto.planear(
        replace(resultado, pares=candidatos), max_gb=15.0, aceptar_escena_unica=False,
    )
    # Un clic autoriza recortes auténticos de hasta 384 MiB, nunca HDF5 completos.
    from components import nisar_auto_ui
    preparado = nisar_auto_ui._ejecutar_en_cola(
        resultado, plan, nisar_auto_ui.METODOS[0], MAX_HARMONY_MB,
    )
    return preparado["job_id"]


def _solicitar_elegido(zona, inicio: date, fin: date, estado: dict, item: dict) -> str:
    """Procesa SOLO el par elegido y revalida geometría, presupuesto y fecha.

    No vuelve a buscar automáticamente otro par. Buscar no descarga; esta
    función solo se llama tras el clic explícito de confirmación.
    """
    if estado.get("firma") != _firma(zona, inicio, fin) or item["id"] != estado.get("seleccionado"):
        raise ValueError("La selección pertenece a otro período o zona; busca de nuevo.")
    if item.get("plan") is None:
        raise ValueError("Este par no cumple cobertura/presupuesto; elige otro.")
    resultado = estado["resultado"]
    par = item["par"]
    if (not any(p.antes.granule == par.antes.granule and
                p.despues.granule == par.despues.granule for p in resultado.pares)
            or not any(p.antes.granule == par.antes.granule and
                       p.despues.granule == par.despues.granule
                       for p in _pares_del_periodo(resultado.pares, inicio, fin))):
        raise ValueError("El par ya no coincide con el catálogo y las fechas.")
    revalidado = cat.evaluar_par(par.antes, par.despues, resultado.region)
    if not isinstance(revalidado, cat.ParNISAR):
        raise ValueError("NASA CMR no acredita la compatibilidad del par seleccionado.")
    if not os.environ.get(nisar_descarga.VARIABLE_TOKEN, "").strip():
        raise ValueError("Configura EARTHDATA_TOKEN en los Secrets de Replit; no lo compartas.")
    # Volver a ejecutar la política nisar_auto, restringida al par elegido.
    revalidado = replace(revalidado, cobertura_comun=item["cobertura"])
    punto = _punto_local(zona) if item["cubre_punto"] else None
    plan = nisar_auto.planear(
        replace(resultado, pares=[revalidado]), max_gb=15.0,
        aceptar_escena_unica=False, punto_prioritario=punto,
    )
    if plan.granules != (par.antes.granule, par.despues.granule):
        raise ValueError("La selección cambió durante la verificación; no se descarga.")
    plan = replace(
        plan, id_par_seleccionado=item["id"],
        criterio_seleccion="PAR_CONFIRMADO_USUARIO_POR_COBERTURA_CMR",
        avisos=(*plan.avisos,
                "Selección visual de par CMR, no verificación de píxeles; "
                f"id={item['id']}; cobertura geodésica estimada={item['cobertura']:.4f}."),
    )
    from components import nisar_auto_ui
    preparado = nisar_auto_ui._ejecutar_en_cola(
        resultado, plan, nisar_auto_ui.METODOS[0], MAX_HARMONY_MB,
    )
    return preparado["job_id"]


def _mostrar_sugerencias(firma) -> None:
    """Alternativa principal ARRIBA de Analizar, sin repetir avisos más abajo."""
    estado = st.session_state.get("v9_sugerencias") or {}
    if estado.get("firma") != firma:
        return
    opciones = estado.get("opciones") or []
    if not opciones:
        if estado.get("consulta_incompleta"):
            st.warning(tr(
                "No se pudo completar la búsqueda de fechas alternativas "
                "en NASA CMR. Intenta nuevamente.",
                "The alternative-date search could not be completed "
                "through NASA CMR. Please try again.",
            ))
        else:
            st.info(tr(
                "No hay fechas alternativas con cobertura CMR suficiente en la "
                "búsqueda disponible. Reduce la zona o amplía el período.",
                "No alternative dates with sufficient CMR coverage were found "
                "in the available search. Shrink the area or expand the date range.",
            ))
        return
    st.warning(tr(
        "No hay pares aptos para estas fechas. NASA CMR encontró este "
        "período alternativo con cobertura estimada suficiente:",
        "No suitable pair was found for these dates. NASA CMR found "
        "an alternative period with sufficient estimated coverage:",
    ))
    recomendado = opciones[0]
    par = recomendado["par"]
    antes, despues = par.antes.nombre.inicio.date(), par.despues.nombre.inicio.date()
    st.button(
        f"{tr('Usar fechas', 'Use dates')} {antes:%Y-%m-%d} → {despues:%Y-%m-%d} "
        f"· {recomendado['cobertura']:.0%} CMR",
        key="v9_usar_sugerencia_0", on_click=_usar_fechas_sugeridas,
        args=(antes, despues), use_container_width=True,
        help=tr("Aplica las fechas; luego vuelve a comprobar la cobertura. "
                "No descarga ni verifica píxeles automáticamente.",
                "Applies dates; then check coverage again. "
                "Does not download or verify pixels automatically."),
    )
    if len(opciones) > 1:
        with st.expander(tr("Otras fechas", "Other dates"), expanded=False):
            for i, alternativa in enumerate(opciones[1:], 1):
                par = alternativa["par"]
                a, b = par.antes.nombre.inicio.date(), par.despues.nombre.inicio.date()
                st.button(
                    f"{a:%Y-%m-%d} → {b:%Y-%m-%d} · {alternativa['cobertura']:.0%} CMR",
                    key=f"v9_usar_sugerencia_{i}",
                    on_click=_usar_fechas_sugeridas, args=(a, b),
                    use_container_width=True,
                )
    st.caption(tr(
        "Cobertura calculada con huellas CMR; la validez de los píxeles "
        "solo se comprueba después con Harmony.",
        "Coverage estimated from CMR footprints; pixel validity "
        "is verified later through Harmony.",
    ))


def _mostrar_progreso(trabajo: dict, fase: str) -> None:
    """Porcentaje de ETAPAS completadas, nunca ETA o bytes inventados."""
    claves = (("zona", "escenas", "datos", "preparacion", "verificacion")
              if fase == "preparacion" else ("calculo", "verificacion"))
    por_clave = {f["clave"]: f for f in trabajo.get("fases") or []}
    hechos = sum(por_clave.get(c, {}).get("estado") == trabajos.APTO for c in claves)
    activo = next((por_clave.get(c) for c in claves
                   if por_clave.get(c, {}).get("estado") == trabajos.EN_CURSO), None)
    if fase == "preparacion":
        porcentaje = int(5 + 65 * hechos / len(claves))
    else:
        porcentaje = int(72 + 26 * hechos / len(claves))
    porcentaje = 100 if trabajo.get("estado") == trabajos.APTO and fase == "calculo" else porcentaje
    detalle = (activo.get("detalle") or activo["nombre"]) if activo else (
        "En cola para iniciar" if trabajo.get("estado") in trabajos.ACTIVOS else
        "Etapas completadas" if trabajo.get("estado") == trabajos.APTO else
        "Trabajo detenido")
    etapas_en = {"zona": "Area", "escenas": "Scenes", "datos": "Data",
                 "preparacion": "Preparation", "calculo": "SAR computation",
                 "verificacion": "Quality checks"}
    fase_en = etapas_en.get(activo["clave"], "Processing") if activo else "Queued / complete"
    st.progress(min(100, max(0, porcentaje)),
                text=f"{porcentaje}% {tr('de etapas', 'of steps')} · "
                     f"{tr(detalle, fase_en)}")
    estado_en = {
        "EN_CURSO": "RUNNING", "APTO": "COMPLETE", "PENDIENTE": "PENDING",
        "ERROR": "FAILED", "CANCELADO": "CANCELLED",
    }.get(str(trabajo["estado"]), str(trabajo["estado"]))
    st.caption(tr("El porcentaje indica etapas, no tiempo restante.",
                  "Progress is based on completed steps, not remaining time.") +
               f" · {tr('Estado', 'Status')}: {tr(str(trabajo['estado']), estado_en)}")


@st.fragment(run_every=2.0)
def _seguimiento(firma):
    if st.session_state.get("v9_firma") != firma:
        return
    prep_id = st.session_state.get("v9_preparacion")
    if not prep_id:
        return
    preparacion = trabajos.leer(prep_id)
    if preparacion is None:
        st.warning(tr("No se pudo recuperar el trabajo NISAR.", "NISAR job could not be recovered."))
        return
    if preparacion["estado"] in trabajos.ACTIVOS:
        st.info(tr("Preparando observaciones NISAR reales…", "Preparing real NISAR observations…"))
        return
    if preparacion["estado"] != trabajos.APTO:
        st.warning(tr("La preparación NISAR falló", "NISAR preparation failed") + ": " +
                   str(preparacion.get("error") or preparacion["estado"]))
        return
    zona = flujo.zona_confirmada()
    inicio, fin = date.fromisoformat(firma[1]), date.fromisoformat(firma[2])
    if not zona or tuple(zona) != firma[0] or not _compatible(preparacion, zona, inicio, fin):
        st.warning(tr("Los COG no coinciden con la zona y fechas activas; no se publica el mapa.",
                          "Prepared COGs do not match the current AOI and dates; no map is published."))
        return
    mapa_job = st.session_state.get("v9_mapa_job")
    if not mapa_job:
        try:
            mapa_job = iniciar(preparacion)["job_id"]
            st.session_state["v9_mapa_job"] = mapa_job
        except (ValueError, OSError, QAInsuficiente) as exc:
            st.warning(tr("No se pudo iniciar el análisis", "Could not start analysis") + ": " + str(exc))
            return
    cambio = trabajos.leer(mapa_job)
    if not cambio:
        st.warning(tr("El trabajo de comparación no está disponible.", "Change analysis job is unavailable."))
        return
    if cambio["estado"] in trabajos.ACTIVOS:
        st.info(tr("Calculando el cambio SAR de ambas fechas…", "Calculating two-date SAR change…"))
        return
    if cambio["estado"] != trabajos.APTO:
        st.warning(tr("No se pudo construir el mapa", "Could not generate map") + ": " +
                   str(cambio.get("error") or cambio["estado"]))
        st.caption(tr("Sin píxeles válidos y cuadrículas compatibles no se publica nada.",
                      "No layer is published without valid pixels and aligned grids."))
        if st.button(tr("Reintentar el cálculo", "Retry calculation"), key="v9_reintentar"):
            st.session_state["v9_mapa_job"] = None
            st.rerun(scope="app")
        return
    ruta = DATA_DIR / "analisis" / str(cambio.get("principal") or "")
    if not ruta.is_file():
        st.warning(tr("El GeoTIFF del análisis no está disponible.", "Analysis GeoTIFF is unavailable."))
        return
    res = leer_resultado(ruta)
    if not res.dibujable or not res.capa or not res.capa.procedencia.es_real:
        st.warning(tr("El mapa no supera los controles de procedencia y QA.",
                          "The map did not pass provenance and QA checks."))
        return
    st.success(tr("Cambio NISAR preparado: señales, no inundaciones confirmadas.",
                  "NISAR change map ready: signal differences, not confirmed floods."))
    st.caption(tr("Colección", "Collection") + ": " +
               str((leer_preparacion(prep_id).get("madurez") or "VALIDATED")) +
               tr(" · Ver fechas y procedencia en la ficha.", " · See dates and provenance in Information."))
    if st.session_state.get("v9_publicado") != mapa_job:
        flujo.activar(id_resultado(ruta), sesion.ANALISIS, cambio["run_id"])
        st.session_state["v9_publicado"] = mapa_job
        st.session_state["ui_explorador"] = True
        st.rerun(scope="app")


def _panel_coberturas(estado: dict, zona, inicio: date, fin: date) -> None:
    """Elección visible; pulsar la tarjeta jamás inicia Harmony."""
    opciones = estado["opciones"]
    # El aviso técnico detallado se conserva en el desplegable inferior; el
    # panel principal prioriza las acciones y la cobertura del par elegido.
    if not opciones:
        return
    st.caption(tr(
        "Verde: cobertura común · elige en el mapa o la lista.",
        "Green: shared coverage · choose on the map or in the list.",
    ))
    seleccionado = nisar_coberturas.seleccion_actual(estado, estado["firma"])
    st.markdown(tr("**Pares NISAR compatibles**", "**Compatible NISAR pairs**"))
    for indice, item in enumerate(opciones[:nisar_coberturas.MAX_PARES_VISIBLES], 1):
        par = item["par"]
        rotulo = (f"{indice}. {par.antes.nombre.inicio:%Y-%m-%d} → "
                  f"{par.despues.nombre.inicio:%Y-%m-%d} · "
                  f"{item['cobertura']:.0%} CMR")
        st.button(rotulo, key=f"v9_elegir_par_{item['id']}", use_container_width=True,
                  type="primary" if seleccionado and seleccionado["id"] == item["id"] else "secondary",
                  on_click=_elegir_par, args=(item["id"],),
                  help=tr("Seleccionar sin descargar.", "Select without downloading."))
    if len(opciones) > nisar_coberturas.MAX_PARES_VISIBLES:
        with st.expander(tr("Otros pares compatibles", "More compatible pairs"), expanded=False):
            for indice, item in enumerate(opciones[nisar_coberturas.MAX_PARES_VISIBLES:], 4):
                par = item["par"]
                st.button(
                    f"{indice}. {par.antes.nombre.inicio:%Y-%m-%d} → "
                    f"{par.despues.nombre.inicio:%Y-%m-%d} · {item['cobertura']:.0%} CMR",
                    key=f"v9_elegir_par_{item['id']}",
                    on_click=_elegir_par, args=(item["id"],), use_container_width=True,
                )
    solapados = st.session_state.get("v9_pares_solapados") or []
    if solapados:
        st.warning(tr(
            "El punto pulsado pertenece a varios pares. Elige uno explícitamente:",
            "The clicked area belongs to several pairs. Choose one explicitly:",
        ))
        for item in opciones:
            if item["id"] in solapados:
                par = item["par"]
                st.button(
                    f"{par.antes.nombre.inicio:%Y-%m-%d} → "
                    f"{par.despues.nombre.inicio:%Y-%m-%d} · {item['cobertura']:.0%}",
                    key=f"v9_solapado_{item['id']}", on_click=_elegir_par,
                    args=(item["id"],), use_container_width=True,
                )
    if not seleccionado:
        return
    par = seleccionado["par"]
    st.markdown(
        f"**{tr('Par seleccionado', 'Selected pair')}:** "
        f"{par.antes.nombre.inicio:%Y-%m-%d} → {par.despues.nombre.inicio:%Y-%m-%d} "
        f"· **{seleccionado['cobertura']:.1%}** "
        f"{tr('cobertura estimada CMR', 'estimated CMR coverage')}"
    )
    with st.expander(tr("Detalles científicos", "Scientific details"), expanded=False):
        st.caption(
            f"Track {par.antes.nombre.track} · Frame {par.antes.nombre.frame} · "
            f"{'+'.join(par.polarizaciones_A)} · {estado['madurez']} · NASA/ASF"
        )
        st.caption(tr(
            "Cobertura de huellas CMR, no píxeles comprobados. La validación "
            "posterior usa mask, numberOfLooks y cuadrículas.",
            "CMR footprints, not verified pixels. Later QA checks masks, "
            "numberOfLooks and grid alignment.",
        ))
    if not seleccionado["cubre_punto"]:
        st.warning(tr(
            "Las dos huellas no contienen el municipio/punto buscado. "
            "La parte del AOI sin cobertura quedará sin análisis.",
            "The two footprints do not contain the searched town/point. "
            "Uncovered parts of the AOI will remain unanalyzed.",
        ))
    if seleccionado["plan"] is None:
        st.warning(tr(
            "Este par no supera los límites de cobertura mínima o presupuesto; "
            "puedes verlo, pero no analizarlo. Selecciona otro o ajusta AOI/fechas.",
            "This pair does not meet the minimum coverage or size limits; "
            "you can inspect it but not analyze it. Choose another or adjust the AOI/dates.",
        ))
        return
    if seleccionado["cobertura"] < 0.90 or not seleccionado["cubre_punto"]:
        st.checkbox(
            tr("Acepto analizar solo la parte cubierta. El área no observada "
               "NO se considera inundada.",
               "I accept analyzing only the covered area. Unobserved land "
               "is NOT considered flooded."),
            key=_clave_aceptacion(estado["firma"], seleccionado["id"]),
        )


def _reducir_zona_cog(limites, punto=None):
    """Sugiere una AOI cuadrada menor DENTRO de la actual, sin bajar resolución.

    No altera el mapa ni la sesión. Un clic explícito del usuario aplicará
    este recorte y exigirá volver a consultar los pares CMR.
    """
    import math

    o, sur, e, n = sesion.validar_zona(limites)
    ancho, alto = sesion.dimensiones_km((o, sur, e, n))
    lado = min(ancho, alto) * 0.55  # ~30 % del área cuadrada anterior
    if lado < 0.2:
        raise sesion.ErrorZona("La zona ya es demasiado pequeña para otro recorte seguro.")
    centro_lon, centro_lat = (o + e) / 2, (sur + n) / 2
    if punto is not None:
        try:
            lon, lat = map(float, punto)
            if o <= lon <= e and sur <= lat <= n:
                centro_lon, centro_lat = lon, lat
        except (TypeError, ValueError):
            pass
    dlat = lado / 111.32
    dlon = lado / (111.32 * math.cos(math.radians(centro_lat)))
    centro_lon = min(max(centro_lon, o + dlon / 2), e - dlon / 2)
    centro_lat = min(max(centro_lat, sur + dlat / 2), n - dlat / 2)
    recorte = (centro_lon - dlon / 2, centro_lat - dlat / 2,
               centro_lon + dlon / 2, centro_lat + dlat / 2)
    return sesion.validar_zona(recorte)


def _aplicar_zona_menor_cog() -> None:
    """Solo tras pulsar 'Reducir zona': NO reintenta Harmony automáticamente."""
    zona = flujo.zona_confirmada()
    if zona is None:
        return
    estado = _coberturas_actuales()
    elegido = (nisar_coberturas.seleccion_actual(estado, estado["firma"])
               if estado else None)
    punto = None
    if elegido is not None and not elegido["geometria"].is_empty:
        # Si el lugar del usuario no está en la intersección de AMBAS fechas,
        # priorizar un punto realmente cubierto, no una huella aislada.
        prioritario = _punto_local(zona)
        if prioritario is not None:
            from shapely.geometry import Point
            if elegido["geometria"].covers(Point(*prioritario)):
                punto = prioritario
        if punto is None:
            centro = elegido["geometria"].representative_point()
            punto = (centro.x, centro.y)
    nueva = _reducir_zona_cog(zona, punto)
    _limpiar_v9()  # conserva fechas; descarta firmas de CMR y trabajos antiguos
    flujo.limpiar_resultado()
    flujo.confirmar_zona(nueva, tr("zona reducida con confirmación del usuario",
                                  "user-confirmed smaller study area"))
    # No mantener un municipio ajeno al nuevo rectángulo como punto prioritario.
    lugar = st.session_state.get("lugar")
    if lugar and not (nueva[0] <= lugar["longitud"] <= nueva[2]
                      and nueva[1] <= lugar["latitud"] <= nueva[3]):
        st.session_state["lugar"] = None
    st.session_state["recomendacion_aoi_actual"] = None
    st.session_state["recomendacion_aoi_limites"] = None
    st.session_state["mapa_dibujo"] = None
    st.session_state["visor_aoi_recomendacion_seq"] = (
        int(st.session_state.get("visor_aoi_recomendacion_seq", 0)) + 1
    )
    st.session_state["ui_sar"] = "abierto"
    st.session_state["ui_explorador"] = False
    from components import interfaz
    interfaz.centrar_en(nueva)


def _error_cog_grande(error: str) -> bool:
    return "COG_DEMASIADO_GRANDE" in error or (
        "COG supera el límite" in error or "límite de bytes antes de transferir" in error
    )


@st.fragment(run_every=2.0)
def _progreso_pie_sar() -> None:
    """Indicador en pie fijo: seguimiento de fases REALES sin rerun del mapa.

    Solo lee el estado persistido de la AOI actual; NO inicia trabajos,
    descargas, ni actualiza fechas/selecciones. Se actualiza cada 2 segundos.
    """
    zona = flujo.zona_confirmada()
    inicio = st.session_state.get("v9_inicio_periodo")
    fin = st.session_state.get("v9_fin_periodo")
    if zona is None or not isinstance(inicio, date) or not isinstance(fin, date):
        return
    firma = _firma(zona, inicio, fin)
    if st.session_state.get("v9_firma") != firma:
        return
    prep_id = st.session_state.get("v9_preparacion")
    if not prep_id:
        return
    prep = trabajos.leer(prep_id)
    if prep is None:
        st.error(tr("No se puede recuperar el trabajo NISAR. "
                    "No se ha publicado ningún resultado.",
                    "NISAR job cannot be retrieved. "
                    "No result was published."))
        return
    if prep.get("estado") not in (*trabajos.ACTIVOS, trabajos.APTO):
        error = str(prep.get("error") or prep.get("estado"))
        if _error_cog_grande(error):
            st.error(tr(
                "El COG de NASA Harmony supera el límite de descarga. "
                "No se publicó ningún resultado.",
                "The NASA Harmony COG exceeds the download limit. "
                "No result was published.",
            ))
            with st.expander(tr("Detalle del límite", "Size-limit details"), expanded=False):
                st.caption(error.replace("COG_DEMASIADO_GRANDE: ", ""))
            if st.button(
                tr("Reducir zona y revisar cobertura", "Shrink area and check coverage"),
                key="v9_reducir_zona_cog", use_container_width=True,
                help=tr(
                    "Reduce la zona solo si pulsas aquí. Tendrás que buscar "
                    "los pares nuevamente; no inicia descargas.",
                    "Only shrinks the area when you click. You'll need to "
                    "search pairs again; no downloads are started.",
                ),
            ):
                try:
                    _aplicar_zona_menor_cog()
                    st.rerun(scope="app")
                except sesion.ErrorZona as exc:
                    st.error(str(exc))
        else:
            st.error(tr(
                "Falló la preparación de NISAR. No hay un resultado SAR válido.",
                "NISAR preparation failed. There is no valid SAR result.",
            ))
            with st.expander(tr("Ver detalle del error", "Show error details"),
                             expanded=False):
                st.caption(error)
        return
    job_mapa = st.session_state.get("v9_mapa_job")
    if prep.get("estado") == trabajos.APTO and job_mapa:
        cambio = trabajos.leer(job_mapa)
        if cambio and cambio.get("estado") in (*trabajos.ACTIVOS, trabajos.APTO):
            _mostrar_progreso(cambio, "calculo")
            return
        if cambio and cambio.get("estado") not in trabajos.ACTIVOS:
            if cambio.get("estado") != trabajos.APTO:
                st.error(tr(
                    "Falló el cálculo SAR o su verificación. No se publicó el mapa.",
                    "SAR calculation or quality checks failed. No map was published.",
                ))
                with st.expander(tr("Ver detalle del error", "Show error details"),
                                 expanded=False):
                    st.caption(str(cambio.get("error") or cambio["estado"]))
            return
    _mostrar_progreso(prep, "preparacion")


def accion_principal() -> None:
    """Único botón Analizar, arriba de los controles, sin acciones duplicadas.

    Se deshabilita cuando faltan un par válido, permiso de cobertura parcial
    o un job de Harmony activo. La barra QA permanece junto al botón.
    """
    zona = flujo.zona_confirmada()
    estado = _coberturas_actuales()
    item = nisar_coberturas.seleccion_actual(estado, estado["firma"]) if estado else None
    inicio = st.session_state.get("v9_inicio_periodo")
    fin = st.session_state.get("v9_fin_periodo")
    preparado = None
    habilitado = False
    if zona is None:
        mensaje = tr("Primero selecciona una zona.", "First select a study area.")
    elif not estado:
        mensaje = tr("Paso 1: busca las coberturas NISAR.", "Step 1: find NISAR coverage.")
    elif _resultado_sar_verificado(estado):
        mensaje = tr("Análisis verificado y visible en el mapa.",
                     "Verified analysis is visible on the map.")
    elif st.session_state.get("v9_preparacion"):
        job_id = st.session_state.get("v9_mapa_job") or st.session_state["v9_preparacion"]
        job = trabajos.leer(job_id)
        if job and job.get("estado") in (
            trabajos.ERROR, trabajos.BLOQUEADO, trabajos.CANCELADO,
        ):
            mensaje = tr("Trabajo detenido: revisa el error.",
                         "Job stopped: check the error.")
        else:
            mensaje = tr("Estado del análisis:",
                         "Analysis status:")
    elif item is None:
        mensaje = tr("Selecciona un par de imágenes compatible.",
                     "Select a compatible image pair.")
    elif item.get("plan") is None:
        mensaje = tr("Este par no cumple la cobertura mínima o el presupuesto.",
                     "This pair does not meet coverage or download limits.")
    elif item["cobertura"] < 0.90 or not item["cubre_punto"]:
        if not st.session_state.get(_clave_aceptacion(estado["firma"], item["id"]), False):
            mensaje = tr("Acepta la cobertura parcial en la selección de pares.",
                         "Accept partial coverage in the pair selection.")
        else:
            habilitado = True
            mensaje = tr("Par seleccionado y cobertura parcial aceptada.",
                         "Pair selected and partial coverage accepted.")
    else:
        habilitado = True
        mensaje = tr("Par compatible seleccionado. Listo para analizar.",
                     "Compatible pair selected. Ready to analyze.")
    if habilitado and (not isinstance(inicio, date) or not isinstance(fin, date)):
        habilitado = False
        mensaje = tr("Selecciona el período de observación.",
                     "Select the observation date range.")
    if habilitado:
        preparado = _preparacion_existente(zona, inicio, fin, item["plan"].granules)
        if not preparado and not os.environ.get(nisar_descarga.VARIABLE_TOKEN, "").strip():
            habilitado = False
            mensaje = tr("Configura EARTHDATA_TOKEN en Replit Secrets para descargar.",
                         "Set EARTHDATA_TOKEN in Replit Secrets to download.")
        elif preparado:
            mensaje = tr("Par preparado: se reutilizarán sus COG verificados.",
                         "Pair already prepared: existing verified COGs will be reused.")
    with st.container(key="sar_accion_fija"):
        # Los errores se anuncian ANTES del botón principal, no al final del
        # panel. El fragment muestra los errores de tareas asíncronas en vivo.
        error_solicitud = st.session_state.get("v9_error")
        if error_solicitud:
            st.error(tr("No se pudo iniciar el análisis: ",
                        "Could not start analysis: ") + str(error_solicitud))
        error_catalogo = st.session_state.get("v9_coberturas_error")
        if error_catalogo and not estado:
            st.error(tr("No se pudieron buscar coberturas NISAR: ",
                        "Could not search NISAR coverage: ") + str(error_catalogo))
        if estado and not any(op["plan"] is not None for op in estado.get("opciones", [])):
            # El usuario ve primero las fechas alternativas; la lista CMR
            # original permanece debajo para inspeccionar el motivo del bloqueo.
            if isinstance(inicio, date) and isinstance(fin, date) and zona:
                _mostrar_sugerencias(_firma(zona, inicio, fin))
        elif item and item.get("plan") is None:
            st.warning(tr("Este par no cumple la cobertura mínima o el límite "
                          "de tamaño. Selecciona otro par o ajusta el área.",
                          "This pair does not meet the minimum coverage or size "
                          "limit. Choose another pair or adjust the area."))
        # Evitar un temporizador extra si todavía no hay job. El fragment
        # se actualiza cada 2 s solo durante preparación/QA de un resultado.
        if st.session_state.get("v9_preparacion") and not (
            estado and _resultado_sar_verificado(estado)
        ):
            _progreso_pie_sar()
        # Un mensaje estático de «Procesando» se quedaba congelado después
        # de un fallo. Durante el job, el fragment de arriba muestra el
        # progreso o el error ACTUAL cada 2 s, sin recargar el mapa.
        trabajo_actual = (
            zona is not None and isinstance(inicio, date) and isinstance(fin, date)
            and st.session_state.get("v9_firma") == _firma(zona, inicio, fin)
            and bool(st.session_state.get("v9_preparacion"))
            and not (estado and _resultado_sar_verificado(estado))
        )
        if not trabajo_actual:
            st.caption(mensaje)
        if st.button(
            tr("Analizar con este par", "Analyze with this pair"),
            key="v9_analizar", type="primary", icon=":material/play_arrow:",
            use_container_width=True, disabled=not habilitado,
            help=tr("Inicia Harmony y el análisis solo después de tu confirmación.",
                    "Starts Harmony and analysis only after your confirmation."),
        ):
            for clave_estado in ("v9_firma", "v9_preparacion", "v9_mapa_job",
                                 "v9_publicado", "v9_error", "nisar_auto_job"):
                st.session_state.pop(clave_estado, None)
            flujo.limpiar_resultado()
            if preparado:
                st.session_state.update(
                    v9_firma=estado["firma"], v9_preparacion=preparado["job_id"],
                    nisar_auto_job=preparado["job_id"],
                )
            else:
                try:
                    job_id = _solicitar_elegido(zona, inicio, fin, estado, item)
                    st.session_state.update(
                        v9_firma=estado["firma"], v9_preparacion=job_id,
                        nisar_auto_job=job_id,
                    )
                except (ValueError, nisar_auto.ErrorAutoNISAR) as exc:
                    st.session_state["v9_error"] = str(exc)
                except Exception:
                    st.session_state["v9_error"] = tr(
                        "No se pudo iniciar la preparación del par. Comprueba Harmony.",
                        "Could not start pair preparation. Check Harmony.",
                    )
            st.rerun(scope="app")


def render() -> None:
    """Panel principal PC, preserva el editor científico existente sin reemplazarlo."""
    st.markdown(tr("**NISAR · Cambios SAR**", "**NISAR · SAR changes**"))
    zona = flujo.zona_confirmada()
    if zona is None:
        st.info(tr("Elige otro lugar en el buscador y confirma su zona para empezar un nuevo análisis.",
                   "Find a location and confirm your study area to start a new analysis."))
        return
    if (st.session_state.get("v9_preparacion") or st.session_state.get("resultado_activo")):
        c1, c2 = st.columns(2)
        c1.button(tr("Nueva zona", "New area"), key="v9_nueva_zona", type="primary",
                  on_click=_nuevo_analisis, args=(True,), use_container_width=True)
        c2.button(tr("Otro período", "Different period"), key="v9_otro_periodo",
                  on_click=_nuevo_analisis, args=(False,), use_container_width=True)

    st.markdown(tr("**Fechas**", "**Dates**"))
    hoy = datetime.now(timezone.utc).date()
    inicio_def = hoy - timedelta(days=23)
    fin_def = hoy - timedelta(days=16)
    col_a, col_b = st.columns(2)
    inicio = col_a.date_input(tr("Inicio del periodo", "Start date"), value=inicio_def,
                              key="v9_inicio_periodo", format="YYYY-MM-DD")
    fin = col_b.date_input(tr("Fin del periodo", "End date"), value=fin_def,
                           key="v9_fin_periodo", format="YYYY-MM-DD")
    firma = _firma(zona, inicio, fin)
    # La colección se determina automáticamente durante la búsqueda;
    # no hace falta repetir detalles técnicos junto a las fechas.
    st.markdown(tr("**Coberturas NISAR**", "**NISAR coverage**"))
    if st.button(
        tr("Mostrar coberturas NISAR", "Show NISAR coverage"),
        key="v9_buscar_coberturas", type="secondary",
        icon=":material/travel_explore:", use_container_width=True,
        help=tr("Solo consulta metadatos CMR; no descarga archivos.",
                "Queries CMR metadata only; downloads nothing."),
    ):
        with st.spinner(tr(
            "Buscando huellas y pares comparables en NASA CMR…",
            "Searching NASA CMR for comparable observation footprints…",
        )):
            try:
                _consultar_coberturas(zona, inicio, fin)
            except (ValueError, nisar_auto.ErrorAutoNISAR,
                    cat.ErrorConexion, cat.ErrorServicio) as exc:
                st.session_state.pop("v9_coberturas", None)
                st.session_state["v9_coberturas_error"] = str(exc)
            except Exception:
                st.session_state.pop("v9_coberturas", None)
                st.session_state["v9_coberturas_error"] = tr(
                    "No se pudo consultar NASA CMR. Revisa la conexión o las fechas.",
                    "Could not query NASA CMR. Check your connection or dates.",
                )
        st.rerun(scope="app")
    estado = _coberturas_actuales()
    if estado and _resultado_sar_verificado(estado):
        st.caption(tr("Análisis listo · ver mapa.", "Analysis ready · see map."))
    elif estado:
        st.markdown(tr("**Pares disponibles**", "**Available pairs**"))
        _panel_coberturas(estado, zona, inicio, fin)
    # Todos los errores de solicitud/catálogo se muestran arriba del botón
    # Analizar, en accion_principal; no duplicar alertas al final del panel.
    _seguimiento(firma)
    # El acceso al histórico heredado es solo para regresión técnica.
    # No volver a exponerlo en la versión pública que ya lo retiró.
    if os.environ.get("VISOR_MOSTRAR_HISTORIAL") == "1":
        if st.button(
            tr("Ver GeoTIFF anteriores", "View previous GeoTIFFs"),
            key="v9_ver_guardados", on_click=_abrir_modo_jurado,
        ):
            st.rerun(scope="app")
    with st.expander(tr("Nota científica", "Scientific note"), expanded=False):
        st.caption(tr(
            "El resultado ΔdB describe cambios de señal radar, no inundaciones "
            "confirmadas ni predicciones del modelo de IA.",
            "The ΔdB result shows radar-signal changes, not confirmed floods "
            "or machine-learning predictions.",
        ))
