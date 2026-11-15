"""Foto y descripción breve del municipio principal de la zona, desde Wikipedia en español.

- Fuente: API REST de resumen de es.wikipedia.org (gratis, sin clave) y, para el crédito de la foto,
  la API de MediaWiki (extmetadata del archivo en Wikimedia Commons).
- Solo se acepta una página que hable de un lugar de Colombia y mencione el departamento esperado;
  si el nombre es ambiguo se prueba primero «Municipio (Departamento)».
- Una foto sin licencia o autor comprobables NO se muestra (la ficha cae a la vista satelital).
- La consulta corre en segundo plano con caché (utils.contexto_ambiental.pedir); nunca bloquea la app.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from html import unescape

from utils.contexto_ambiental import _pedir_json

RESUMEN = "https://es.wikipedia.org/api/rest_v1/page/summary/{}"
MEDIAWIKI = "https://es.wikipedia.org/w/api.php"
ATRIBUCION = "Texto: Wikipedia en español (CC BY-SA 4.0)"
LARGO_RESUMEN = 260
ANCHO_FOTO = 960      # ancho estándar de miniatura de Wikimedia


def candidatos(municipio: str, departamento: str | None) -> list[str]:
    nombres = []
    if departamento:
        nombres.append(f"{municipio} ({departamento})")
    nombres.append(municipio)
    return nombres


def _sin_html(texto: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", texto or ""))).strip()


def _normal(texto: str) -> str:
    tabla = str.maketrans("áéíóúüñ", "aeiouun")
    return (texto or "").lower().translate(tabla)


def es_del_lugar(resumen: dict, departamento: str | None) -> bool:
    """La página debe ser un artículo normal sobre un lugar de Colombia (y del departamento esperado)."""
    if resumen.get("type") not in (None, "standard"):
        return False
    texto = _normal(f"{resumen.get('description', '')} {resumen.get('extract', '')}")
    if "colombia" not in texto:
        return False
    return not departamento or _normal(departamento.split(",")[0]) in texto


def recortar(texto: str, largo: int = LARGO_RESUMEN) -> str:
    """Primeras frases completas hasta ~largo caracteres (nunca corta una palabra)."""
    texto = _sin_html(texto)
    if len(texto) <= largo:
        return texto
    frases = re.split(r"(?<=[.!?])\s+", texto)
    salida = ""
    for f in frases:
        if salida and len(salida) + len(f) + 1 > largo:
            break
        salida = f"{salida} {f}".strip()
    if len(salida) > largo:
        salida = salida[:largo].rsplit(" ", 1)[0] + "…"
    return salida


def _archivo_de_url(url: str) -> str | None:
    """upload.wikimedia.org/.../thumb/a/ab/Nombre.jpg/640px-Nombre.jpg → «Nombre.jpg»."""
    partes = urllib.parse.urlparse(url).path.split("/")
    if "thumb" in partes and len(partes) >= 2:
        return urllib.parse.unquote(partes[-2])
    return urllib.parse.unquote(partes[-1]) if partes and partes[-1] else None


def credito_imagen(archivo: str, abrir=None) -> dict | None:
    """Autor y licencia del archivo de Commons; None si no están declarados."""
    q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "extmetadata",
                                "titles": f"File:{archivo}", "iiextmetadatafilter": "Artist|LicenseShortName"})
    datos = _pedir_json(f"{MEDIAWIKI}?{q}", abrir=abrir, timeout=8)
    for pagina in (datos.get("query", {}).get("pages", {}) or {}).values():
        meta = ((pagina.get("imageinfo") or [{}])[0]).get("extmetadata", {})
        licencia = _sin_html(meta.get("LicenseShortName", {}).get("value"))
        autor = _sin_html(meta.get("Artist", {}).get("value"))
        if licencia:
            return {"licencia": licencia, "autor": autor[:80] or "autor no indicado",
                    "pagina": "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(archivo.replace(" ", "_"))}
    return None


def consultar(municipio: str, departamento: str | None, abrir=None) -> dict:
    """{"estado": CON_RESULTADOS | SIN_COINCIDENCIAS, "items": [ficha]} (los errores los captura pedir())."""
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for titulo in candidatos(municipio, departamento):
        url = RESUMEN.format(urllib.parse.quote(titulo.replace(" ", "_")))
        try:
            resumen = _pedir_json(url, abrir=abrir, timeout=8)
        except Exception as exc:
            if getattr(exc, "code", None) == 404:
                continue
            raise
        if not es_del_lugar(resumen, departamento):
            continue
        ficha = {"title": resumen.get("title") or municipio, "extract": recortar(resumen.get("extract", "")),
                 "url": ((resumen.get("content_urls") or {}).get("desktop") or {}).get("page"),
                 "imagen": None, "credito": None}
        miniatura = (resumen.get("thumbnail") or {}).get("source")
        if miniatura:
            archivo = _archivo_de_url((resumen.get("originalimage") or {}).get("source") or miniatura)
            credito = credito_imagen(archivo, abrir=abrir) if archivo else None
            if credito:  # sin licencia comprobable, no hay foto
                ancho = (resumen.get("originalimage") or {}).get("width") or 0
                # Wikimedia solo sirve miniaturas en anchos estándar (…330, 500, 960…): otros se rechazan.
                imagen = re.sub(r"/\d+px-", f"/{ANCHO_FOTO}px-", miniatura) if ancho > ANCHO_FOTO else miniatura
                ficha["imagen"] = imagen.replace("'", "%27").replace('"', "%22")
                ficha["credito"] = credito
        return {"estado": "CON_RESULTADOS", "items": [ficha], "retrieved_at": ahora}
    return {"estado": "SIN_COINCIDENCIAS", "items": [], "retrieved_at": ahora}
