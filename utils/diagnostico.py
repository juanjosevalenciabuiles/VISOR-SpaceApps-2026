"""Comprobación de los servicios externos que usa V.I.S.O.R.

Hace UNA petición ligera por servicio (una tesela de zoom 2 por mapa base, el estado de
Nominatim, un conteo de ASF, la página de Earthdata Login) con User-Agent propio y
tiempo máximo corto. El resultado se guarda en memoria del proceso y se reutiliza durante
`VIGENCIA_S`; no hay sondeo continuo ni descarga masiva.

Un mapa base que falla la comprobación deja de ofrecerse (se lista en «No disponibles
aquí» con el motivo) hasta la siguiente comprobación correcta. Las URL con clave
(CARTO) nunca aparecen en el resultado.
"""
from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

AGENTE = "VISOR-SpaceApps-2026 (diagnostico; https://github.com/juanjosevalenciabuiles/VISOR-SpaceApps-2026)"
VIGENCIA_S = 900
TIEMPO_S = 6

OK, FALLA, OMITIDO = "APTO", "ERROR", "NO COMPROBADO"


@dataclass
class Estado:
    clave: str
    nombre: str
    estado: str
    detalle: str
    ms: int | None = None


_cerrojo = threading.Lock()
_ultimo: dict = {"cuando": None, "resultados": [], "en_curso": False}


def desactivado() -> bool:
    return os.environ.get("VISOR_DIAGNOSTICO", "").strip().lower() == "desactivado"


def _url_tesela(mapa) -> str:
    from utils.mapas_base import url_teselas
    return (url_teselas(mapa).replace("{s}", "a").replace("{r}", "").replace("{z}", "2")
            .replace("{x}", "1").replace("{y}", "1"))


def _pedir(url: str, abrir) -> tuple[int, str, bytes, int]:
    inicio = time.monotonic()
    peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with abrir(peticion, timeout=TIEMPO_S) as r:
        cuerpo = r.read(65536)
        tipo = r.headers.get("Content-Type", "") if hasattr(r, "headers") else ""
        return getattr(r, "status", 200), tipo, cuerpo, int((time.monotonic() - inicio) * 1000)


def _probar(clave: str, nombre: str, url: str, abrir, valida) -> Estado:
    try:
        codigo, tipo, cuerpo, ms = _pedir(url, abrir)
    except urllib.error.HTTPError as e:
        motivo = {401: "requiere credenciales (401)", 403: "acceso denegado (403)",
                  429: "demasiadas peticiones (429)"}.get(e.code, f"HTTP {e.code}")
        return Estado(clave, nombre, FALLA, motivo)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        razon = getattr(e, "reason", e)
        return Estado(clave, nombre, FALLA, f"sin conexión o tiempo agotado ({type(razon).__name__})")
    if codigo != 200 or not valida(tipo, cuerpo):
        return Estado(clave, nombre, FALLA, f"respuesta inesperada (HTTP {codigo}, {tipo or 'sin tipo'})", ms)
    return Estado(clave, nombre, OK, f"responde en {ms} ms", ms)


def _es_imagen(tipo: str, cuerpo: bytes) -> bool:
    return tipo.startswith("image/") or cuerpo[:8] == b"\x89PNG\r\n\x1a\n" or cuerpo[:3] == b"\xff\xd8\xff"


def comprobar(abrir=None) -> list[Estado]:
    """Comprueba todos los servicios ahora. `abrir` permite sustituir la red en pruebas."""
    from utils import lugares, mapas_base
    abrir = abrir or urllib.request.urlopen
    resultados: list[Estado] = []
    for clave in mapas_base.MAPAS_BASE:
        mapa = mapas_base.MAPAS_BASE[clave]
        ok, motivo = mapas_base.disponible(mapa, considerar_diagnostico=False)
        if not ok:
            resultados.append(Estado(f"base:{clave}", f"Mapa base · {mapa.nombre}", OMITIDO, motivo))
            continue
        resultados.append(_probar(f"base:{clave}", f"Mapa base · {mapa.nombre}", _url_tesela(mapa), abrir,
                                  _es_imagen))
    url = lugares.proveedor()
    if url:
        resultados.append(_probar("lugares", "Búsqueda de lugares (Nominatim)", url + "/status?format=json", abrir,
                                  lambda t, c: b"status" in c or b"OK" in c))
    else:
        resultados.append(Estado("lugares", "Búsqueda de lugares en línea", OMITIDO,
                                 "desactivada: solo catálogo local"))
    resultados.append(_probar(
        "asf", "Catálogo ASF (Sentinel-1)",
        "https://api.daac.asf.alaska.edu/services/search/param?platform=SENTINEL-1&output=count&maxResults=1",
        abrir, lambda t, c: c.strip().isdigit()))
    resultados.append(_probar("earthdata", "NASA Earthdata Login", "https://urs.earthdata.nasa.gov/", abrir,
                              lambda t, c: True))
    with _cerrojo:
        _ultimo.update(cuando=datetime.now(timezone.utc), resultados=resultados, en_curso=False)
    mapas_base.registrar_caidos({e.clave.split(":", 1)[1]: e.detalle for e in resultados
                                 if e.clave.startswith("base:") and e.estado == FALLA})
    return resultados


def ultimo() -> tuple[datetime | None, list[Estado], bool]:
    with _cerrojo:
        return _ultimo["cuando"], list(_ultimo["resultados"]), _ultimo["en_curso"]


def comprobar_en_segundo_plano(abrir=None) -> bool:
    """Lanza una comprobación si no hay una vigente ni en curso. No bloquea la interfaz."""
    if desactivado():
        return False
    with _cerrojo:
        vigente = _ultimo["cuando"] and (datetime.now(timezone.utc) - _ultimo["cuando"]).total_seconds() < VIGENCIA_S
        if vigente or _ultimo["en_curso"]:
            return False
        _ultimo["en_curso"] = True

    def correr():
        try:
            comprobar(abrir)
        finally:
            with _cerrojo:
                _ultimo["en_curso"] = False

    threading.Thread(target=correr, name="visor-diagnostico", daemon=True).start()
    return True
