"""Panel derecho «Conozcamos esta zona»: contexto de la zona confirmada, para cualquier persona.

Aparece SOLO cuando hay una zona confirmada, sin pulsar nada:
- Lo principal: frases simples generadas a partir de datos comprobados (nunca por IA).
- Ríos y territorio: cartografía local (MGN 2025 del DANE y Natural Earth), sin red.
- Alertas oficiales de hoy: IDEAM, Alertas Hidrológicas (capa 2), vigentes al consultar.
- Eventos en las fechas seleccionadas: NASA EONET v3, ±15 días alrededor de las fechas.
- Qué encontró el radar: solo tras «Analizar» o al abrir el historial.

Las consultas externas se lanzan en segundo plano al confirmar la zona (una vez por zona, período y
fuente, con caché) y nunca bloquean el mapa ni «Analizar». Al cambiar de zona, lo anterior desaparece:
todo se indexa por la huella de la geometría. Nada de esto toca data/sar, data/analisis ni los trabajos.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from html import escape

import streamlit as st

from components import flujo
from utils import contexto_ambiental as externo
from utils import contexto_local

NIVEL_COLOR = {3: "roja", 2: "naranja", 1: "amarilla", 0: "otra"}
NO_CONFIRMA = ("Las alertas y los eventos son contexto: no confirman lo que muestre el radar, ni el radar los "
               "confirma a ellos.")


def externo_activo() -> bool:
    return os.environ.get("VISOR_CONTEXTO_EXTERNO", "").strip().lower() != "desactivado"


def _sincrono() -> bool:
    return os.environ.get("VISOR_CONTEXTO_SINCRONO") == "1"


def _huella(objeto) -> str:
    return hashlib.sha256(json.dumps(objeto, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


def zona_actual() -> dict | None:
    """Geometría real de la zona confirmada (polígono dibujado o rectángulo) y su huella."""
    zona = st.session_state.get("zona")
    if not zona or not flujo.zona_confirmada():
        return None
    geometria = contexto_local.geometria_de_zona(zona)
    return {"geometria": geometria, "clave": _huella(geometria), "limites": tuple(zona["limites"])}


def periodo_actual() -> tuple[date, date, str]:
    """Fechas en estudio: las del par elegido; si no hay par, el período de búsqueda."""
    par = flujo.par_actual()
    if par is not None:
        a, b = sorted((par.antes.inicio.date(), par.despues.inicio.date()))
        return a, b, "fechas de las dos imágenes elegidas"
    inicio, fin = flujo.periodo_por_defecto()
    inicio = st.session_state.get("sar_inicio") or inicio
    fin = st.session_state.get("sar_fin") or fin
    return inicio, fin, "período de búsqueda de imágenes"


@lru_cache(maxsize=32)
def _local(geometria_texto: str) -> contexto_local.ContextoLocal:
    return contexto_local.contexto(json.loads(geometria_texto))


def consultas(zona: dict, inicio: date, fin: date) -> dict[str, dict]:
    """Estado de cada fuente externa para ESTA zona y ESTE período (lanza la consulta si falta)."""
    if not externo_activo():
        apagado = {"estado": "DESACTIVADO", "items": []}
        return {"ideam": apagado, "eonet": apagado}
    geometria = zona["geometria"]
    hoy = datetime.now(timezone.utc).date().isoformat()
    desde, hasta = externo.ventana(inicio, fin)
    ideam = externo.pedir("ideam", f"{zona['clave']}|{hoy}",
                          lambda: externo.consultar_ideam(geometria), sincrono=_sincrono())
    eonet = externo.pedir("eonet", f"{zona['clave']}|{desde}|{hasta}",
                          lambda: externo.consultar_eonet(geometria, desde, hasta), sincrono=_sincrono())
    return {"ideam": ideam, "eonet": {**eonet, "ventana": (desde, hasta)}}


# ---------------------------------------------------------------------------
# Frases (deterministas, a partir de datos comprobados)
# ---------------------------------------------------------------------------

def frases_principales(local: contexto_local.ContextoLocal, inicio: date, fin: date, origen_fechas: str,
                       fuentes: dict[str, dict]) -> list[str]:
    frases = []
    frases.append(f"Está en {local.lugar}." if local.lugar else "No se pudo comprobar a qué municipio pertenece.")
    if local.area_km2 is not None:
        frases.append(f"Mide unos {local.area_km2:,.0f} km².".replace(",", "."))
    frases.append(f"Fechas en estudio: {inicio:%d/%m/%Y} a {fin:%d/%m/%Y} ({origen_fechas}).")
    if local.rios:
        frases.append("La cruzan ríos principales de la cartografía de referencia: " + ", ".join(local.rios[:4]) + ".")
    ideam = fuentes["ideam"]
    if ideam["estado"] == "CON_RESULTADOS":
        alertas = [i for i in ideam["items"] if i.get("gravedad", 0) > 0]
        if alertas:
            mayor = NIVEL_COLOR[max(i["gravedad"] for i in alertas)]
            frases.append(f"Hoy el IDEAM tiene {len(alertas)} alerta(s) hidrológica(s) en zonas que tocan esta área; "
                          f"la más alta es {mayor}.")
        else:
            frases.append("Hoy el IDEAM no tiene alertas hidrológicas amarillas, naranjas ni rojas en zonas que toquen "
                          "esta área.")
    elif ideam["estado"] == "SIN_COINCIDENCIAS":
        frases.append("Hoy el IDEAM no tiene alertas hidrológicas que toquen esta área.")
    eonet = fuentes["eonet"]
    if eonet["estado"] == "CON_RESULTADOS":
        frases.append(f"NASA EONET registra {len(eonet['items'])} evento(s) natural(es) en esta zona cerca de esas fechas.")
    elif eonet["estado"] == "SIN_COINCIDENCIAS":
        frases.append("NASA EONET no registra eventos naturales en esta zona cerca de esas fechas (no significa que "
                      "no haya pasado nada: EONET solo cataloga eventos seleccionados).")
    return frases


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------

def _estado_fuente(datos: dict, nombre: str) -> str | None:
    """Texto para los estados sin datos que mostrar; None si hay resultados."""
    e = datos.get("estado")
    if e == "CONSULTANDO":
        return f'<div class="mc-ctx-estado" data-estado="CONSULTANDO">Consultando {escape(nombre)}…</div>'
    if e == "DESACTIVADO":
        return ('<div class="mc-ctx-estado" data-estado="DESACTIVADO">Consulta externa desactivada en este '
                "entorno (VISOR_CONTEXTO_EXTERNO=desactivado).</div>")
    if e == "ERROR_FUENTE":
        return (f'<div class="mc-ctx-estado mc-aviso" data-estado="ERROR_FUENTE">Fuente no disponible: '
                f"{escape(nombre)} no respondió o entregó datos no válidos ({escape(str(datos.get('error') or ''))}). "
                "Esto no significa que no haya alertas o eventos. El análisis de radar sigue disponible.</div>")
    if e == "SIN_COINCIDENCIAS":
        return (f'<div class="mc-ctx-estado" data-estado="SIN_COINCIDENCIAS">Sin registros: la consulta a '
                f"{escape(nombre)} fue correcta y no hay elementos que toquen esta zona.</div>")
    return None


def _hora(iso: str | None) -> str:
    if not iso:
        return "—"
    try:     # Colombia: UTC−5 todo el año (sin horario de verano); no depende de la base tzdata del sistema
        colombia = timezone(timedelta(hours=-5))
        return datetime.fromisoformat(iso).astimezone(colombia).strftime("%d/%m/%Y %H:%M") + " (hora de Colombia)"
    except ValueError:
        return iso


def _seccion_ideam(datos: dict) -> str:
    cuerpo = _estado_fuente(datos, "el IDEAM")
    if cuerpo is None:
        filas = []
        for i in datos["items"][:8]:
            nivel = i.get("value") or "nivel no indicado"
            filas.append(
                f'<li class="mc-alerta mc-alerta-{NIVEL_COLOR[i.get("gravedad", 0)]}" data-nivel="{escape(nivel)}">'
                f"<b>{escape(nivel.capitalize())}</b> · subzona hidrográfica {escape(i['title'])}"
                f"{' (zona ' + escape(i['zona_hidrografica']) + ')' if i.get('zona_hidrografica') else ''}"
                f"<div class='visor-leyenda-nota'>{escape(i['spatial_relation'].capitalize())}"
                f"{' · ' + escape(', '.join(i['departamentos'])) if i.get('departamentos') else ''}</div></li>")
        resto = len(datos["items"]) - 8
        cuerpo = (f'<ul class="mc-ctx-lista">{"".join(filas)}</ul>'
                  + (f'<div class="visor-leyenda-nota">y {resto} más.</div>' if resto > 0 else ""))
    nota = ""
    if datos.get("estado") in ("CON_RESULTADOS", "SIN_COINCIDENCIAS"):
        nota = (f'<div class="visor-leyenda-nota">Consultado el {_hora(datos.get("retrieved_at"))}. El servicio no '
                "publica la fecha de emisión de cada alerta: ver el "
                f'<a href="{externo.IDEAM_BOLETIN}" target="_blank">boletín oficial</a>. Son alertas de HOY por zona '
                "hidrográfica, no de las fechas de las imágenes ni una medición en esta zona.</div>")
    return ('<div class="mc-ctx-seccion" id="ctx-ideam"><div class="visor-seccion">Alertas oficiales de hoy · IDEAM'
            f"</div>{cuerpo}{nota}</div>")


def _seccion_eonet(datos: dict) -> str:
    cuerpo = _estado_fuente(datos, "NASA EONET")
    if cuerpo is None:
        filas = []
        for i in datos["items"][:8]:
            enlace = (f' · <a href="{escape(i["url"])}" target="_blank">fuente</a>' if i.get("url") else "")
            filas.append(f"<li><b>{escape(i['title'])}</b><div class='visor-leyenda-nota'>"
                         f"{escape(i.get('phenomenon') or 'Sin categoría')} · {escape(i.get('event_start') or 'fecha no informada')}"
                         f" · la geometría del evento toca la zona{enlace}</div></li>")
        cuerpo = f'<ul class="mc-ctx-lista">{"".join(filas)}</ul>'
    ventana = datos.get("ventana")
    nota = (f'<div class="visor-leyenda-nota">Ventana consultada: {ventana[0]:%d/%m/%Y} a {ventana[1]:%d/%m/%Y} '
            "(±15 días). Fuente: NASA EONET v3.</div>") if ventana else ""
    return ('<div class="mc-ctx-seccion" id="ctx-eonet"><div class="visor-seccion">Eventos en las fechas '
            f"seleccionadas · NASA EONET</div>{cuerpo}{nota}</div>")


def _seccion_territorio(local: contexto_local.ContextoLocal) -> str:
    filas = []
    if local.municipios:
        mun = ", ".join(f"{m.nombre} ({m.fraccion * 100:.0f} %)" for m in local.municipios[:6])
        filas.append(f"<li><b>Municipios</b>: {escape(mun)}"
                     f"{f' y {len(local.municipios) - 6} más' if len(local.municipios) > 6 else ''}</li>")
    if local.rios or local.lagos:
        filas.append("<li><b>Ríos y cuerpos de agua principales</b>: "
                     + escape(", ".join(local.rios + local.lagos)) + "</li>")
    else:
        filas.append("<li><b>Ríos</b>: la cartografía de referencia (solo ríos principales) no registra ríos dentro de "
                     "la zona. Puede haber ríos y quebradas menores.</li>")
    filas.append(f"<li><b>Vías principales</b> que la cruzan: {local.vias}</li>")
    avisos = "".join(f'<div class="mc-aviso">{escape(a)}</div>' for a in local.avisos)
    return ('<div class="mc-ctx-seccion" id="ctx-territorio"><div class="visor-seccion">Ríos y territorio</div>'
            f'<ul class="mc-ctx-lista">{"".join(filas)}</ul>{avisos}'
            f'<div class="visor-leyenda-nota">{escape(contexto_local.ATRIBUCION_MUNICIPIOS)} · '
            f"{escape(contexto_local.ATRIBUCION_CARTOGRAFIA)}. La cercanía a un río no es un riesgo.</div></div>")


def _radar(activos: list) -> str:
    if activos:
        return ('<div class="mc-ctx-seccion" id="ctx-radar"><div class="visor-seccion">Qué encontró el radar</div>'
                '<div class="visor-leyenda-nota">El resultado está abajo, con su ficha. Es un cambio en la señal de '
                "radar, no una inundación confirmada.</div></div>")
    return ('<div class="mc-ctx-seccion" id="ctx-radar"><div class="visor-seccion">Qué encontró el radar</div>'
            '<div class="mc-ctx-estado" data-estado="SIN_ANALISIS">Aún no has realizado un análisis. Pulsa '
            "«Analizar» en Herramientas SAR cuando elijas las fechas.</div></div>")


def _contenido(zona: dict, activos: list) -> bool:
    """Dibuja el panel; devuelve True si alguna fuente sigue consultándose."""
    inicio, fin, origen = periodo_actual()
    local = _local(json.dumps(zona["geometria"], sort_keys=True))
    fuentes = consultas(zona, inicio, fin)
    frases = "".join(f"<li>{escape(f)}</li>" for f in frases_principales(local, inicio, fin, origen, fuentes))
    st.markdown(
        f'<div class="mc-ctx" id="ctx-zona" data-zona="{zona["clave"]}">'
        '<div class="mc-ctx-titulo">Conozcamos esta zona</div>'
        f'<div class="mc-ctx-seccion" id="ctx-principal"><div class="visor-seccion">Lo principal</div>'
        f'<ul class="mc-ctx-lista">{frases}</ul></div>'
        f"{_radar(activos)}{_seccion_territorio(local)}{_seccion_ideam(fuentes['ideam'])}"
        f"{_seccion_eonet(fuentes['eonet'])}"
        f'<div class="mc-aviso" id="ctx-no-confirma">{escape(NO_CONFIRMA)}</div></div>',
        unsafe_allow_html=True)
    return any(f.get("estado") == "CONSULTANDO" for f in fuentes.values())


@st.fragment(run_every=2.0)
def _vigilar(clave: str, con_resultado: bool) -> None:
    """Mientras alguna fuente consulta, se refresca cada 2 s; al terminar, vuelve a la vista normal."""
    zona = zona_actual()
    if zona is None or zona["clave"] != clave:
        st.rerun(scope="app")
        return
    if not _contenido(zona, [True] if con_resultado else []):
        st.rerun(scope="app")


def render(activos: list) -> bool:
    """Dibuja el contexto en el panel derecho. Devuelve True si hay zona confirmada."""
    zona = zona_actual()
    if zona is None:
        st.markdown('<div class="mc-ctx mc-ctx-vacio" id="ctx-sin-zona">Selecciona una zona para conocer qué sucede '
                    "allí.</div>", unsafe_allow_html=True)
        return False
    inicio, fin, _ = periodo_actual()
    estados = consultas(zona, inicio, fin)
    if any(f.get("estado") == "CONSULTANDO" for f in estados.values()):
        _vigilar(zona["clave"], bool(activos))
    else:
        _contenido(zona, activos)
    return True
