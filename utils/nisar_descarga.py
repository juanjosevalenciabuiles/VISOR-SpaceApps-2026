"""Descarga CONTROLADA de un HDF5 NISAR GCOV. Nunca se ejecuta sola.

Reglas (orden de desarrollo N5):
- Solo desde la línea de comandos, un granule cada vez, tomado de un registro
  de búsqueda guardado (así el tamaño y la URL salen del catálogo, no de una
  suposición).
- La persona confirma el tamaño: `confirmo_gb` debe ser ≥ el tamaño real.
- Hace falta espacio libre de sobra en disco; si no, se detiene antes de pedir nada.
- Credencial: token de Earthdata Login en la variable de entorno
  EARTHDATA_TOKEN. Nunca se escribe en disco, en el registro ni en pantalla, y
  no se reenvía a otro servidor si la descarga redirige fuera del original.
- No sobrescribe; escribe `.part` y renombra solo si el tamaño coincide.

NO VERIFICADO contra el servidor real de ASF: desde el entorno de desarrollo
no hay acceso. Las pruebas usan un servidor simulado.
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

VARIABLE_TOKEN = "EARTHDATA_TOKEN"
MARGEN_DISCO = 1.2
BLOQUE = 4 * 1024 * 1024
HOSTS_PERMITIDOS = ("nisar.asf.earthdatacloud.nasa.gov", "datapool.asf.alaska.edu")


class ErrorDescarga(Exception):
    """La descarga no se hizo, con el motivo para el usuario."""


class _SinReenviarCredencial(urllib.request.HTTPRedirectHandler):
    """Al redirigir a otro servidor (p. ej. una URL firmada), quita Authorization."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        nueva = super().redirect_request(req, fp, code, msg, headers, newurl)
        if nueva is not None and urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            nueva.remove_header("Authorization")
        return nueva


def candidato_del_registro(registro: Path, granule: str) -> dict:
    try:
        datos = json.loads(Path(registro).read_text(encoding="utf-8"))
        candidatos = datos["candidatos"]
    except (OSError, ValueError, KeyError) as e:
        raise ErrorDescarga(f"`{Path(registro).name}` no es un registro de búsqueda NISAR válido.") from e
    for c in candidatos:
        if c.get("granule") == granule:
            return c
    raise ErrorDescarga(f"El granule `{granule}` no está en el registro: búscalo primero en el catálogo.")


def comprobar(candidato: dict, carpeta: Path, confirmo_gb: float | None, libre_bytes: int | None = None) -> tuple[str, int, Path]:
    """Valida todo lo que se puede validar SIN red. Devuelve (url, tamaño, destino)."""
    url, tamano = candidato.get("url_h5"), candidato.get("tamano_bytes")
    if not url or not str(url).startswith("https://") or not str(url).endswith(".h5"):
        raise ErrorDescarga("El registro no trae un enlace https a un .h5 para este granule.")
    if urllib.parse.urlsplit(url).hostname not in HOSTS_PERMITIDOS:
        raise ErrorDescarga(f"El enlace no apunta a un servidor de ASF reconocido ({', '.join(HOSTS_PERMITIDOS)}).")
    if not tamano or int(tamano) <= 0:
        raise ErrorDescarga("El catálogo no informa el tamaño del archivo: no se descarga sin saberlo.")
    tamano = int(tamano)
    gb = tamano / 1e9
    if confirmo_gb is None or confirmo_gb < gb:
        raise ErrorDescarga(f"El archivo pesa {gb:.2f} GB. Para descargarlo, confírmalo con --confirmo-gb "
                            f"{gb + 0.01:.2f} (o más).")
    carpeta = Path(carpeta)
    destino = carpeta / f"{candidato['granule']}.h5"
    if destino.exists():
        raise ErrorDescarga(f"`{destino.name}` ya existe; no se sobrescribe.")
    carpeta.mkdir(parents=True, exist_ok=True)
    libre = shutil.disk_usage(carpeta).free if libre_bytes is None else libre_bytes
    if libre < tamano * MARGEN_DISCO:
        raise ErrorDescarga(f"Espacio insuficiente: hacen falta {tamano * MARGEN_DISCO / 1e9:.2f} GB libres "
                            f"y hay {libre / 1e9:.2f} GB.")
    return url, tamano, destino


def descargar(registro: Path, granule: str, carpeta: Path, confirmo_gb: float | None,
              abrir: Callable | None = None, libre_bytes: int | None = None, avance: Callable | None = None) -> Path:
    candidato = candidato_del_registro(registro, granule)
    url, tamano, destino = comprobar(candidato, carpeta, confirmo_gb, libre_bytes)
    token = os.environ.get(VARIABLE_TOKEN, "").strip()
    if not token:
        raise ErrorDescarga(f"Falta el token de Earthdata Login en la variable de entorno {VARIABLE_TOKEN} "
                            "(en Replit: Secrets). No se guarda ni se muestra.")
    abrir = abrir or urllib.request.build_opener(_SinReenviarCredencial).open
    peticion = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                    "User-Agent": "VISOR-SpaceApps-2026 (descarga confirmada)"})
    parcial = destino.with_suffix(".h5.part")
    escritos = 0
    try:
        with abrir(peticion, timeout=120) as respuesta, parcial.open("xb") as salida:
            while bloque := respuesta.read(BLOQUE):
                escritos += len(bloque)
                if escritos > tamano:
                    raise ErrorDescarga("El servidor envió más datos que el tamaño del catálogo; se canceló.")
                salida.write(bloque)
                if avance:
                    avance(escritos, tamano)
    except FileExistsError as e:
        raise ErrorDescarga(f"Ya hay una descarga parcial (`{parcial.name}`); bórrala a mano si quieres reintentar.") from e
    except urllib.error.HTTPError as e:
        parcial.unlink(missing_ok=True)
        motivo = "credencial rechazada o sin permiso (revisa el token y la aceptación del EULA de ASF)" \
            if e.code in (401, 403) else f"HTTP {e.code}"
        raise ErrorDescarga(f"ASF no entregó el archivo: {motivo}.") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        parcial.unlink(missing_ok=True)
        raise ErrorDescarga("No se pudo completar la descarga (red o disco). No quedó ningún archivo parcial.") from e
    except ErrorDescarga:
        parcial.unlink(missing_ok=True)
        raise
    if escritos != tamano:
        parcial.unlink(missing_ok=True)
        raise ErrorDescarga(f"Descarga incompleta ({escritos:,} de {tamano:,} bytes); se descartó.")
    parcial.rename(destino)
    return destino
