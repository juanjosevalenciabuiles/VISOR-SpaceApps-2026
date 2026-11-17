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
import math
import os
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from html import escape
import unicodedata

import streamlit as st
from shapely.geometry import Point, shape

from components import flujo
from utils.i18n import tr
from utils import contexto_ambiental as externo
from utils import contexto_local, wikipedia_lugar, verificacion_multifuente

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


def local_de(zona: dict) -> contexto_local.ContextoLocal:
    return _local(json.dumps(zona["geometria"], sort_keys=True))



def _normalizar_nombre(valor: str) -> str:
    return " ".join(unicodedata.normalize("NFKD", valor).encode("ascii", "ignore")
                    .decode("ascii").casefold().split())


def municipio_de_busqueda(zona: dict, local: contexto_local.ContextoLocal,
                         lugar: dict | None) -> contexto_local.Municipio | None:
    """Referente administrativo del LUGAR BUSCADO, solo si su punto está en la AOI.

    No se sustituye el municipio buscado por el que tenga mayor fracción del
    polígono. Tampoco se atribuye una búsqueda anterior a una nueva AOI.
    """
    if not isinstance(lugar, dict):
        return None
    etiqueta = str(lugar.get("etiqueta") or "")
    campos = [v.strip() for v in etiqueta.split(",")]
    if len(campos) < 2:
        return None
    try:
        latitud, longitud = float(lugar["latitud"]), float(lugar["longitud"])
        punto = Point(longitud, latitud)
        if not shape(zona["geometria"]).covers(punto):
            return None
        hallado = contexto_local.municipio_en_punto(longitud, latitud)
    except (KeyError, TypeError, ValueError):
        return None
    if hallado is None or _normalizar_nombre(campos[0]) != _normalizar_nombre(hallado.nombre):
        return None
    if _normalizar_nombre(campos[1]) != _normalizar_nombre(hallado.departamento):
        return None
    # Si ocupa menos del 1 % de la AOI, puede no aparecer entre los principales.
    return next((m for m in local.municipios if m.divipola == hallado.divipola), hallado)


def consultando(fuentes: dict[str, dict]) -> bool:
    return any(f.get("estado") == "CONSULTANDO" for f in fuentes.values())


def consultas(zona: dict, inicio: date, fin: date) -> dict[str, dict]:
    """Estado de cada fuente externa para ESTA zona y ESTE período (lanza la consulta si falta)."""
    if not externo_activo():
        apagado = {"estado": "DESACTIVADO", "items": []}
        return {"ideam": apagado, "eonet": apagado, "wiki": apagado}
    geometria = zona["geometria"]
    hoy = datetime.now(timezone.utc).date().isoformat()
    desde, hasta = externo.ventana(inicio, fin)
    ideam = externo.pedir("ideam", f"{zona['clave']}|{hoy}",
                          lambda: externo.consultar_ideam(geometria), sincrono=_sincrono())
    eonet = externo.pedir("eonet", f"{zona['clave']}|{desde}|{hasta}",
                          lambda: externo.consultar_eonet(geometria, desde, hasta), sincrono=_sincrono())
    wiki = wikipedia_zona(zona)
    return {"ideam": ideam, "eonet": {**eonet, "ventana": (desde, hasta)}, "wiki": wiki}


# ---------------------------------------------------------------------------
# Frases (deterministas, a partir de datos comprobados)
# ---------------------------------------------------------------------------

def frases_principales(local: contexto_local.ContextoLocal, inicio: date, fin: date, origen_fechas: str,
                       fuentes: dict[str, dict], referencia: contexto_local.Municipio | None = None) -> list[str]:
    frases = []
    if referencia is not None:
        frases.append(f"Lugar buscado: {referencia.nombre}, {referencia.departamento}.")
        if local.lugar:
            frases.append(f"El área de análisis abarca {local.lugar}. Puede incluir otros municipios.")
    else:
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
        return ('<div class="mc-ctx-seccion mc-ctx-tarjeta mc-ctx-radar-listo" id="ctx-radar"><div class="visor-seccion">'
                'Qué encontró el radar</div><div class="visor-leyenda-nota">El resultado está abajo, con su ficha. Es un '
                "cambio en la señal de radar, no una inundación confirmada.</div></div>")
    return ('<div class="mc-ctx-seccion mc-ctx-tarjeta" id="ctx-radar"><div class="visor-seccion">Qué encontró el radar'
            '</div><div class="mc-ctx-estado" data-estado="SIN_ANALISIS">Aún no has realizado un análisis. Pulsa '
            "«Analizar» en esta ficha cuando quieras comparar dos fechas.</div></div>")


def wikipedia_zona(zona: dict, local: contexto_local.ContextoLocal | None = None) -> dict:
    """Consulta únicamente Wikipedia para la ficha resumida y conserva el caché."""
    if not externo_activo():
        return {"estado": "DESACTIVADO", "items": []}
    local = local if local is not None else local_de(zona)
    principal = municipio_de_busqueda(zona, local, st.session_state.get("lugar")) or (
        (local.municipios or [None])[0])
    if principal is None:
        return {"estado": "SIN_COINCIDENCIAS", "items": []}
    return externo.pedir("wiki", principal.divipola or principal.nombre,
                         lambda: wikipedia_lugar.consultar(principal.nombre, principal.departamento),
                         sincrono=_sincrono())


# ---------------------------------------------------------------------------
# Ficha del lugar (estilo Google Maps): imagen, nombre, chips y acciones
# ---------------------------------------------------------------------------

SATELITE = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg"
CREDITO_SATELITE = "Imagen satelital: Sentinel-2 cloudless 2016 · EOX (CC BY 4.0, datos Copernicus)"


def tesela_satelital(limites) -> str:
    """Una tesela del mosaico satelital (EOX, la misma del mapa base) que contiene el centro de la zona."""
    o, s_, e, n = limites
    ancho = max(abs(e - o), abs(n - s_), 1e-3)
    z = int(max(5, min(13, math.floor(math.log2(360 / ancho)))))
    lat, lon = (s_ + n) / 2, (o + e) / 2
    x = int((lon + 180) / 360 * 2 ** z)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z)
    return SATELITE.format(z=z, x=x, y=y)


def _foto(zona: dict, wiki: dict) -> str:
    """Foto del lugar (Wikimedia Commons, con autor y licencia) o, si no hay, la vista satelital."""
    ficha = (wiki.get("items") or [None])[0] if wiki.get("estado") == "CON_RESULTADOS" else None
    if ficha and ficha.get("imagen") and ficha.get("credito"):
        c = ficha["credito"]
        return (f'<div class="mc-ficha-foto" id="ctx-foto" data-origen="wikimedia">'
                f'<img class="mc-ficha-img" src="{escape(ficha["imagen"])}" alt="Foto de {escape(ficha["title"])}" '
                'referrerpolicy="no-referrer">'
                f'<a class="mc-ficha-credito" href="{escape(c["pagina"])}" target="_blank" rel="noopener">Foto: '
                f'{escape(c["autor"])} · {escape(c["licencia"])} · Wikimedia Commons</a></div>')
    return (f'<div class="mc-ficha-foto mc-ficha-satelite" id="ctx-foto" data-origen="satelite">'
            f'<img class="mc-ficha-img" src="{tesela_satelital(zona["limites"])}" alt="Vista satelital de la zona">'
            f'<span class="mc-ficha-credito">{escape(CREDITO_SATELITE)}</span></div>')


def _subtitulo(local: contexto_local.ContextoLocal, referencia: contexto_local.Municipio | None = None) -> str:
    if not local.municipios and referencia is None:
        return "Zona en Colombia"
    m = referencia or local.municipios[0]
    tipo = "Lugar buscado" if referencia else ("Distrito capital" if "D.C." in m.nombre else "Municipio")
    otros = len([x for x in local.municipios if x.divipola != m.divipola])
    extra = f" · zona incluye {otros} municipio{'s' if otros != 1 else ''} más" if otros else ""
    return f"{tipo} · {m.departamento}, Colombia{extra}"


def _chip(texto: str, clase: str = "", titulo: str = "") -> str:
    return f'<span class="mc-chip-ficha {clase}" title="{escape(titulo)}">{escape(texto)}</span>'


def chips(local: contexto_local.ContextoLocal, fuentes: dict[str, dict]) -> str:
    """Datos clave de un vistazo; cada chip dice el estado real de su fuente (nunca un valor supuesto)."""
    c = []
    if local.area_km2 is not None:
        c.append(_chip(f"{local.area_km2:,.0f} km²".replace(",", "."), titulo="Área de la zona"))
    if local.municipios:
        c.append(_chip(f"{len(local.municipios)} municipio{'s' if len(local.municipios) != 1 else ''}",
                       titulo="Municipios que toca la zona (DANE, MGN 2025)"))
    ideam = fuentes["ideam"]
    alertas = [i for i in ideam.get("items") or [] if i.get("gravedad", 0) > 0]
    if ideam["estado"] == "CON_RESULTADOS" and alertas:
        mayor = max(i["gravedad"] for i in alertas)
        color = NIVEL_COLOR[mayor] if len(alertas) == 1 or mayor == 2 else NIVEL_COLOR[mayor] + "s"
        c.append(_chip(f"{len(alertas)} alerta{'s' if len(alertas) != 1 else ''} {color}",
                       f"mc-chip-alerta mc-alerta-{NIVEL_COLOR[mayor]}", "Alertas hidrológicas del IDEAM vigentes hoy"))
    elif ideam["estado"] in ("CON_RESULTADOS", "SIN_COINCIDENCIAS"):
        c.append(_chip("Sin alertas IDEAM hoy", "mc-chip-ok", "IDEAM: ninguna alerta amarilla, naranja o roja toca la zona"))
    else:
        c.append(_chip({"CONSULTANDO": "IDEAM: consultando…", "DESACTIVADO": "IDEAM: sin consulta"}.get(
            ideam["estado"], "IDEAM no disponible"), "mc-chip-tenue"))
    eonet = fuentes["eonet"]
    if eonet["estado"] in ("CON_RESULTADOS", "SIN_COINCIDENCIAS"):
        n = len(eonet.get("items") or [])
        c.append(_chip(f"{n} evento{'s' if n != 1 else ''} NASA", titulo="NASA EONET cerca de las fechas en estudio"))
    else:
        c.append(_chip({"CONSULTANDO": "NASA: consultando…", "DESACTIVADO": "NASA: sin consulta"}.get(
            eonet["estado"], "NASA no disponible"), "mc-chip-tenue"))
    return f'<div class="mc-chips-ficha" id="ctx-chips">{"".join(c)}</div>'



def ficha_breve_html(zona: dict, local: contexto_local.ContextoLocal, wiki: dict,
                     referencia: contexto_local.Municipio | None = None) -> str:
    """Ficha compacta: foto acreditada, lugar y resumen de Wikipedia; sin capas duplicadas."""
    ficha = (wiki.get("items") or [None])[0] if wiki.get("estado") == "CON_RESULTADOS" else None
    municipio = referencia or ((local.municipios or [None])[0])
    nombre = municipio.nombre if municipio else tr("Zona seleccionada", "Selected area")
    ubicacion = (f"{escape(municipio.departamento)}, Colombia" if municipio
                 else tr("Colombia · zona seleccionada", "Colombia · selected area"))
    datos = []
    if local.area_km2 is not None:
        datos.append(f"{local.area_km2:,.1f} km²")
    if local.municipios:
        n = len(local.municipios)
        datos.append(f"{n} " + tr("municipio" if n == 1 else "municipios",
                                  "municipality" if n == 1 else "municipalities"))
    detalle = " · ".join(datos)
    if ficha and ficha.get("extract"):
        resumen = escape(wikipedia_lugar.recortar(str(ficha["extract"]), 220))
        url = ficha.get("url")
        enlace = (f' <a href="{escape(url)}" target="_blank" rel="noopener noreferrer">'
                  "Wikipedia (ES)</a>" if url else "")
        descripcion = f'<p class="mc-ficha-desc" id="ctx-descripcion">{resumen}{enlace}</p>'
    elif wiki.get("estado") == "CONSULTANDO":
        descripcion = f'<p class="mc-ficha-desc">{tr("Consultando Wikipedia…", "Loading Wikipedia…")}</p>'
    else:
        descripcion = (f'<p class="mc-ficha-desc">'
                       f'{tr("No hay una descripción de Wikipedia comprobada para este lugar.",
                             "No verified Wikipedia summary is available for this place.")}</p>')
    return (f'<div class="mc-ficha mc-ficha-breve" id="ctx-ficha" data-zona="{zona["clave"]}">'
            f'{_foto(zona, wiki)}<div class="mc-ficha-cuerpo">'
            f'<div class="mc-ctx-titulo">{tr("Sobre esta zona", "About this area")}</div>'
            f'<h2 class="mc-ficha-nombre">{escape(nombre)}</h2>'
            f'<div class="mc-ficha-sub">{ubicacion}</div>{descripcion}'
            f'<div class="visor-leyenda-nota">{escape(detalle)}</div>'
            '</div></div>')


@st.fragment(run_every=2.0)
def _vigilar_wikipedia_resumen(clave: str) -> None:
    """Actualiza la ficha cuando termina Wikipedia sin reutilizar argumentos del mapa."""
    zona = zona_actual()
    if zona is None or zona["clave"] != clave:
        return
    if wikipedia_zona(zona).get("estado") != "CONSULTANDO":
        st.rerun(scope="app")

def cabecera_html(zona: dict, local: contexto_local.ContextoLocal, fuentes: dict[str, dict],
                  referencia: contexto_local.Municipio | None = None) -> str:
    wiki = fuentes.get("wiki") or {}
    ficha = (wiki.get("items") or [None])[0] if wiki.get("estado") == "CON_RESULTADOS" else None
    municipio = referencia or ((local.municipios or [None])[0])
    nombre = municipio.nombre if municipio else "Zona seleccionada"
    descripcion = ""
    if ficha and ficha.get("extract"):
        enlace = (f' <a href="{escape(ficha["url"])}" target="_blank" rel="noopener">Wikipedia</a>'
                  if ficha.get("url") else "")
        descripcion = f'<p class="mc-ficha-desc" id="ctx-descripcion">{escape(ficha["extract"])}{enlace}</p>'
    nota = ""
    if referencia and local.municipios and local.municipios[0].divipola != referencia.divipola:
        principal = local.municipios[0]
        nota = ('<div class="visor-leyenda-nota" id="ctx-lugar-vs-zona">'
                f'Buscaste {escape(referencia.nombre)}. El área dibujada abarca más superficie de '
                f'{escape(principal.nombre)} ({principal.fraccion * 100:.0f} %). '
                'Los porcentajes de municipios corresponden al área, no al lugar buscado.</div>')
    return (f'<div class="mc-ficha" id="ctx-ficha" data-zona="{zona["clave"]}">{_foto(zona, wiki)}'
            '<div class="mc-ficha-cuerpo"><div class="mc-ctx-titulo">Conozcamos esta zona</div>'
            f'<h2 class="mc-ficha-nombre">{escape(nombre)}</h2>'
            f'<div class="mc-ficha-sub">{escape(_subtitulo(local, referencia))}</div>{descripcion}{nota}'
            f"{chips(local, fuentes)}</div></div>")


def barra_municipios(local: contexto_local.ContextoLocal) -> str:
    """Proporción de la zona en cada municipio (DANE, MGN 2025)."""
    if not local.municipios:
        return ""
    colores = ("var(--theme-accent)", "#7c9cff", "#c58cff", "#ffb35c", "#7fe0a8", "#9aa4b2")
    partes, leyenda = [], []
    for i, m in enumerate(local.municipios[:6]):
        color = colores[i % len(colores)]
        partes.append(f'<span style="width:{m.fraccion * 100:.1f}%;background:{color}" title="{escape(m.nombre)}"></span>')
        leyenda.append(f'<li><i style="background:{color}"></i>{escape(m.nombre)} <b>{m.fraccion * 100:.0f} %</b></li>')
    return ('<div class="mc-ctx-seccion" id="ctx-municipios"><div class="visor-seccion">Cuánto de la zona cae en cada '
            f'municipio</div><div class="mc-barra-mun">{"".join(partes)}</div>'
            f'<ul class="mc-barra-leyenda">{"".join(leyenda)}</ul></div>')


def alerta_principal(datos: dict) -> str:
    alertas = [i for i in datos.get("items") or [] if i.get("gravedad", 0) > 0]
    if datos.get("estado") != "CON_RESULTADOS" or not alertas:
        return ""
    i = max(alertas, key=lambda a: a["gravedad"])
    return (f'<div class="mc-alerta-principal mc-alerta-{NIVEL_COLOR[i["gravedad"]]}" id="ctx-alerta-principal">'
            f'<span class="mc-alerta-icono" aria-hidden="true">⚠</span><div><b>{escape((i.get("value") or "").capitalize())}'
            f'</b> · {escape(i["title"])}<div class="visor-leyenda-nota">IDEAM, vigente hoy · por zona hidrográfica, no es '
            "una medición en esta zona</div></div></div>")



def _seccion_evidencias(local: contexto_local.ContextoLocal, inicio: date, fin: date) -> str:
    """Caso municipal documentado, separado de observaciones satelitales y de alertas actuales."""
    casos = verificacion_multifuente.casos_documentados(local.municipios, inicio, fin)
    if not casos:
        return ('<div class="mc-ctx-seccion" id="ctx-multifuente"><div class="visor-seccion">'
                'Verificación multifuente</div><div class="visor-leyenda-nota">'
                'No hay un caso histórico incorporado para estas fechas y municipios. '
                'No equivale a ausencia de inundación. La consulta de agua satelital histórica '
                'y lluvia acumulada sigue pendiente de validación.</div></div>')
    bloques = []
    for caso in casos:
        enlaces = "".join(
            f'<li><a href="{escape(f["url"], quote=True)}" target="_blank" rel="noopener noreferrer">'
            f'{escape(f["organismo"])} · {escape(f["publicado"])}</a></li>'
            for f in caso["fuentes"]
        )
        bloques.append(
            '<div class="mc-ctx-tarjeta">'
            '<b>Inundación documentada por autoridad</b>'
            f'<p>{escape(caso["resumen"])}</p>'
            f'<p class="visor-leyenda-nota">{escape(caso["alcance"])}</p>'
            f'<ul>{enlaces}</ul>'
            '<div class="visor-leyenda-nota">Observación satelital: pendiente de verificar '
            'cobertura y clases de agua para estas fechas. Lluvia histórica: no consultada '
            'todavía. Este registro NO delimita píxeles inundados.</div>'
            '</div>'
        )
    return ('<div class="mc-ctx-seccion" id="ctx-multifuente">'
            '<div class="visor-seccion">Verificación multifuente</div>'
            + "".join(bloques) + '</div>')


def _contenido(zona: dict, activos: list) -> bool:
    """Dibuja el cuerpo de la ficha; devuelve True si alguna fuente sigue consultándose."""
    inicio, fin, origen = periodo_actual()
    local = local_de(zona)
    fuentes = consultas(zona, inicio, fin)
    referencia = municipio_de_busqueda(zona, local, st.session_state.get("lugar"))
    frases = "".join(f"<li>{escape(f)}</li>" for f in frases_principales(
        local, inicio, fin, origen, fuentes, referencia=referencia))
    st.markdown(
        f'<div class="mc-ctx" id="ctx-zona" data-zona="{zona["clave"]}">'
        f"{alerta_principal(fuentes['ideam'])}{_radar(activos)}"
        f'<div class="mc-ctx-seccion" id="ctx-principal"><div class="visor-seccion">Lo principal</div>'
        f'<ul class="mc-ctx-lista">{frases}</ul></div>'
        f"{_seccion_evidencias(local, inicio, fin)}{barra_municipios(local)}{_seccion_territorio(local)}{_seccion_ideam(fuentes['ideam'])}"
        f"{_seccion_eonet(fuentes['eonet'])}"
        f'<div class="mc-aviso" id="ctx-no-confirma">{escape(NO_CONFIRMA)}</div>'
        f'<div class="visor-leyenda-nota" id="ctx-fuentes">Descripción del lugar: {escape(wikipedia_lugar.ATRIBUCION)}. '
        "Solo se muestran fotos con autor y licencia declarados en Wikimedia Commons; si no, la vista satelital.</div>"
        "</div>",
        unsafe_allow_html=True)
    return consultando(fuentes)


@st.fragment(run_every=2.0)
def _vigilar(clave: str, con_resultado: bool) -> None:
    """Mientras alguna fuente consulta, se refresca cada 2 s; al terminar, vuelve a la vista normal
    (rerun completo: así también se actualizan la foto, los chips y ECO)."""
    zona = zona_actual()
    if zona is None or zona["clave"] != clave:
        st.rerun(scope="app")
        return
    if not _contenido(zona, [True] if con_resultado else []):
        st.rerun(scope="app")


def _acciones(zona: dict, acciones: dict | None) -> None:
    if not acciones:
        return
    with st.container(horizontal=True, key="ctx_acciones", gap="small"):
        st.button("Analizar", key="ctx_analizar", icon=":material/satellite_alt:", type="primary",
                  on_click=acciones["analizar"], help="Abrir el análisis de radar de esta zona")
        st.button("Centrar", key="ctx_centrar", icon=":material/center_focus_strong:",
                  on_click=acciones["centrar"], args=(zona["limites"],), help="Encuadrar la zona en el mapa")
        st.button("Cambiar", key="ctx_cambiar", icon=":material/edit_location_alt:",
                  on_click=acciones["cambiar"], help="Quitar esta zona y elegir otra")


def render(activos: list, acciones: dict | None = None) -> bool:
    """Dibuja la ficha del lugar en el panel derecho. Devuelve True si hay zona confirmada."""
    zona = zona_actual()
    if zona is None:
        st.markdown('<div class="mc-ctx mc-ctx-vacio" id="ctx-sin-zona">Selecciona una zona para conocer qué sucede '
                    "allí.</div>", unsafe_allow_html=True)
        return False
    inicio, fin, _ = periodo_actual()
    estados = consultas(zona, inicio, fin)
    # La cabecera y los botones van fuera del fragmento: sus clics recargan la app completa.
    local = local_de(zona)
    referencia = municipio_de_busqueda(zona, local, st.session_state.get("lugar"))
    st.markdown(cabecera_html(zona, local, estados, referencia=referencia), unsafe_allow_html=True)
    _acciones(zona, acciones)
    # Los interruptores IDEAM/DANE/EONET viven únicamente en el dock
    # permanente; la ficha usa las mismas fuentes pero no duplica widgets.
    st.caption("Las capas ambientales se activan en «CAPAS DEL MAPA» sin cerrar esta ficha.")
    if consultando(estados):
        _vigilar(zona["clave"], bool(activos))
    else:
        _contenido(zona, activos)
    return True
