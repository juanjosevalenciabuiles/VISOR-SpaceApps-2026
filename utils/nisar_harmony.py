"""NISAR L2 GCOV vía NASA Harmony: recorte de COG, sin descargar HDF5 completos.

Usa harmony-py oficial para petición y seguimiento; NASA CMR/Harmony público
para descubrir variables; HTTPS firmado para bajar solo GeoTIFFs limitados en
tamaño. Sin interpolar ni cambiar CRS. No evalúa inundaciones.

Una respuesta que no permite identificar intensidad + máscara se RECHAZA: no
se etiqueta arbitrariamente un archivo como HH/HV ni se inventan datos.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CAP_URL = "https://harmony.earthdata.nasa.gov/capabilities?shortName=NISAR_L2_GCOV_V1"
COLECCION = "NISAR_L2_GCOV_V1"
COLECCIONES_AUTORIZADAS = {
    "VALIDATED": "NISAR_L2_GCOV_V1",
    "PROVISIONAL": "NISAR_L2_GCOV_PROVISIONAL_V1",
}
FRECUENCIA = "A"
MAX_ARCHIVOS = 4
MAX_TOTAL_BYTES = 512 * 1024**2
MAX_UN_ARCHIVO = 256 * 1024**2
BLOQUE = 2 * 1024**2
PLAZO_S = 540
INTERVALO_S = 5


class ErrorHarmony(RuntimeError):
    """Una solicitud incompleta o no verificable nunca se interpreta como radar válido."""


@dataclass(frozen=True)
class Especificacion:
    coleccion: str
    variables: tuple[str, ...]
    capas: tuple[str, ...]
    bbox: tuple[float, float, float, float]
    granule: str

    def resumen(self) -> dict:
        return {
            "proveedor": "NASA Harmony · NISAR GCOV (banda L)",
            "granule": self.granule, "bbox": list(self.bbox),
            "capas": list(self.capas), "variables": list(self.variables),
            "resolucion": "nativa (sin reproyección/reescalado)",
        }


def _json_publico(url: str, abrir=None) -> dict:
    abrir = abrir or urllib.request.urlopen
    peticion = urllib.request.Request(url, headers={"Accept": "application/json",
                                                    "User-Agent": "VISOR-NISAR/1.0"})
    with abrir(peticion, timeout=30) as resp:
        datos = json.loads(resp.read(1_500_000).decode("utf-8"))
    if not isinstance(datos, dict):
        raise ErrorHarmony("Las capacidades de Harmony no son un objeto JSON.")
    return datos


def capacidades(abrir=None, madurez: str = "VALIDATED") -> dict:
    """Capacidades Harmony de LA colección elegida; no modifica datos."""
    madurez = madurez.upper()
    if madurez not in COLECCIONES_AUTORIZADAS:
        raise ErrorHarmony("Madurez NISAR no permitida por Harmony.")
    nombre = COLECCIONES_AUTORIZADAS[madurez]
    url = CAP_URL if madurez == "VALIDATED" else (
        "https://harmony.earthdata.nasa.gov/capabilities?shortName=" + nombre)
    try:
        data = _json_publico(url, abrir)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise ErrorHarmony(
            "No se pudo verificar el servicio Harmony para NISAR " + madurez
            + ". La disponibilidad del catálogo no garantiza que Harmony permita recortar "
              "esta colección: no se descargó ningún GeoTIFF."
        ) from exc
    if data.get("shortName") != nombre or not re.fullmatch(r"C\d+-ASF", data.get("conceptId") or ""):
        raise ErrorHarmony("Harmony no identifica la colección NISAR " + madurez + " en ASF.")
    nombres = {
        v["name"] if isinstance(v, dict) else v
        for v in (data.get("variables") or [])
        if isinstance(v, (dict, str)) and (not isinstance(v, dict) or isinstance(v.get("name"), str))
    }
    return {"coleccion": data["conceptId"], "variables": nombres, "madurez": madurez}


def capas_necesarias(polarizaciones, *, solo_cambio: bool = False) -> tuple[str, ...]:
    pols = tuple(polarizaciones)
    if "HH" in pols:
        capas = ("HHHH",)
    elif "VV" in pols:
        capas = ("VVVV",)
    else:
        raise ErrorHarmony("El granule no tiene polarización copolar de banda L (HH o VV).")
    # El cálculo ΔdB V9 consume SOLO copolar + mask + numberOfLooks.
    # No extraer HV/VH si no se utilizarán: reduce las peticiones COG de
    # cuatro a tres por fecha. Mantener el comportamiento científico
    # anterior para otros consumidores que sí necesitan polarización cruzada.
    if not solo_cambio:
        if "HV" in pols:
            capas += ("HVHV",)
        elif "VH" in pols:
            capas += ("VHVH",)
    return (*capas, "mask", "numberOfLooks")


def especificar(candidato, bbox, caps: dict, *,
                solo_cambio: bool = False) -> Especificacion:
    """Solo capas A enumeradas por Harmony. Nunca pedir 'all'."""
    granule = candidato.granule
    madurez = str(getattr(candidato, "madurez", "VALIDATED")).upper()
    if madurez not in COLECCIONES_AUTORIZADAS:
        raise ErrorHarmony("Madurez NISAR desconocida.")
    if (caps.get("madurez", "VALIDATED") != madurez):
        raise ErrorHarmony("Capacidades Harmony de otra madurez: no mezclar colecciones.")
    if not re.fullmatch(r"NISAR_[A-Z0-9_]{55,150}", granule):
        raise ErrorHarmony("Nombre de granule NISAR inválido.")
    o, s, e, n = tuple(float(v) for v in bbox)
    if not (-180 <= o < e <= 180 and -90 <= s < n <= 90):
        raise ErrorHarmony("AOI inválida para Harmony.")
    capas = capas_necesarias(candidato.nombre.pol_a, solo_cambio=solo_cambio)
    variables = tuple(f"/science/LSAR/GCOV/grids/frequencyA/{x}" for x in capas)
    faltantes = [v.rsplit("/", 1)[-1] for v in variables if v not in caps["variables"]]
    if faltantes:
        raise ErrorHarmony("Harmony no ofrece las variables necesarias: " + ", ".join(faltantes))
    if len(variables) > MAX_ARCHIVOS:
        raise ErrorHarmony("Se excedió el máximo de capas autorizadas.")
    return Especificacion(caps["coleccion"], variables, capas, (o, s, e, n), granule)


def construir_solicitud(spec: Especificacion):
    """Usa la firma pública de harmony-py 1.8; no incluye reproject ni scale."""
    try:
        from harmony import BBox, Collection, Request
    except ImportError as exc:
        raise ErrorHarmony("Instala harmony-py para solicitar recortes de NISAR.") from exc
    req = Request(collection=Collection(id=spec.coleccion),
                  granule_name=[spec.granule],
                  spatial=BBox(*spec.bbox),
                  variables=list(spec.variables),
                  format="image/tiff",
                  max_results=1, ignore_errors=False, skip_preview=True)
    if not req.is_valid():
        raise ErrorHarmony("Harmony rechazó la forma de la solicitud NISAR.")
    return req


def _cliente():
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        raise ErrorHarmony("Falta EARTHDATA_TOKEN en los Secrets de Replit.")
    from harmony import Client
    return Client(token=token, check_interval=INTERVALO_S, download_timeout=60)


def _etiqueta(url: str, capas: tuple[str, ...]) -> str:
    """Reconocer exclusivamente la capa indicada en el nombre entregado por Harmony."""
    base = urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
    if not base.lower().endswith((".tif", ".tiff")):
        raise ErrorHarmony("Harmony produjo un resultado que no es GeoTIFF.")
    matches = []
    for c in capas:
        # Soporta ..._frequencyA_HHHH.tif o ..._HHHH.tif, nunca frequencyB.
        if re.search(r"(?i)(?:^|[^A-Za-z0-9])frequencyB(?:[^A-Za-z0-9]|$)", base):
            raise ErrorHarmony("Harmony devolvió una variable de frecuencia B, no L A.")
        if re.search(r"(?i)(?:^|[^A-Za-z0-9])" + re.escape(c) +
                     r"(?:[^A-Za-z0-9]|$)", base):
            matches.append(c)
    if len(matches) != 1:
        raise ErrorHarmony("No se pudo identificar de forma inequívoca la variable del GeoTIFF Harmony.")
    return matches[0]


def _url_datos(url: str) -> None:
    """Sin token en las descargas: URL firmada HTTPS de NASA/Harmony o S3."""
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    if p.scheme != "https" or p.username or p.password or not host:
        raise ErrorHarmony("La descarga no apunta a una URL HTTPS segura.")
    permitidos = (
        host == "harmony.earthdata.nasa.gov"
        or host.endswith(".earthdata.nasa.gov")
        or host.endswith(".amazonaws.com")
        or host.endswith(".cloudfront.net")
    )
    if not permitidos:
        raise ErrorHarmony("Harmony devolvió una descarga fuera de NASA/S3 autorizados.")
    # Nunca resolver explícitamente direcciones privadas aportadas en una URL.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ErrorHarmony("No se permiten direcciones IP directas.")


def _descargar_cota(url, destino: Path, max_bytes: int, abrir=None, comprobar=None,
                    cliente=None) -> tuple[int, str]:
    """Descarga COG con sesión EDL y límite estricto de bytes.

    Una respuesta HTML/JSON (p. ej. login) o bytes sin firma TIFF
    NUNCA se guardan como imagen, aunque el URL acabe en .tif.
    'abrir' queda reservado a pruebas con respuestas simuladas.
    """
    _url_datos(url)
    if abrir is None and cliente is None:
        raise ErrorHarmony("Para descargar se necesita el cliente Harmony autenticado.")
    parcial = destino.with_suffix(".tif.part")
    sha = hashlib.sha256()
    total = 0
    try:
        if abrir is not None:
            req = urllib.request.Request(url, headers={"User-Agent": "VISOR-NISAR-COG/1.0"})
            respuesta = abrir(req, timeout=60)
        else:
            # El cliente oficial conserva el flujo de autenticación Earthdata
            # y gestiona la redirección OAuth sin reenviar la credencial a S3.
            # El bearer de Earthdata SOLO debe salir hacia hosts NASA.
            # Una URL S3/CloudFront ya firmada se pide SIN Authorization.
            host = (urllib.parse.urlsplit(url).hostname or "").lower()
            headers = {"Accept-Encoding": "identity", "User-Agent": "VISOR-NISAR-COG/1.0"}
            if not host.endswith(".earthdata.nasa.gov"):
                headers["Authorization"] = None
            respuesta = cliente.session.get(
                url, stream=True, timeout=60, headers=headers,
            )
        with respuesta as resp:
            destino_final = getattr(resp, "url", None) or resp.geturl()
            _url_datos(destino_final)
            if hasattr(resp, "raise_for_status"):
                resp.raise_for_status()
            tipo = str(resp.headers.get("Content-Type", "")).lower()
            if any(v in tipo for v in ("text/html", "application/json", "text/xml",
                                      "application/xml", "text/plain")):
                raise ErrorHarmony("NASA respondió con texto o página de autenticación, NO un TIFF.")
            cabecera = resp.headers.get("Content-Length")
            if cabecera and int(cabecera) > max_bytes:
                # Solo tamaños, nunca imprimir URL firmadas ni cabeceras auth.
                recibido_mib = int(cabecera) / 1024**2
                permitido_mib = max_bytes / 1024**2
                raise ErrorHarmony(
                    "COG_DEMASIADO_GRANDE: "
                    f"NASA Harmony devolvió {recibido_mib:.1f} MiB; "
                    f"el límite restante autorizado es {permitido_mib:.1f} MiB. "
                    "Selecciona un área más pequeña y vuelve a comprobar su cobertura."
                )
            # requests.Response y urllib HTTPResponse exponen interfaces distintas.
            fragmentos = (resp.iter_content(chunk_size=BLOQUE)
                          if hasattr(resp, "iter_content")
                          else iter(lambda: resp.read(BLOQUE), b""))
            with parcial.open("xb") as out:
                primero = True
                for fragmento in fragmentos:
                    if comprobar:
                        comprobar()
                    if not fragmento:
                        continue
                    if primero:
                        primero = False
                        firmas = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")
                        if not any(fragmento.startswith(firma) for firma in firmas):
                            raise ErrorHarmony(
                                "El archivo remoto no tiene cabecera TIFF; "
                                "posible login HTML o error de acceso."
                            )
                    total += len(fragmento)
                    if total > max_bytes:
                        raise ErrorHarmony(
                            "COG_DEMASIADO_GRANDE: el COG supera el límite "
                            "de transferencia autorizado; no se guardó el archivo. "
                            "Selecciona un área más pequeña."
                        )
                    out.write(fragmento)
                    sha.update(fragmento)
        if total < 1024:
            raise ErrorHarmony("El GeoTIFF remoto es demasiado pequeño o está vacío.")
        os.replace(parcial, destino)
    except Exception:
        parcial.unlink(missing_ok=True)
        raise
    return total, sha.hexdigest()


def _validar_cog(ruta: Path, bbox, capa: str) -> dict:
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds

    try:
        with rasterio.open(ruta) as src:
            if src.driver != "GTiff" or src.count != 1 or src.crs is None:
                raise ErrorHarmony("No es un GeoTIFF científico con CRS y una sola banda.")
            if src.width < 2 or src.height < 2 or not src.crs.is_projected:
                raise ErrorHarmony("El COG carece de cuadrícula proyectada válida.")
            if src.transform.b or src.transform.d or not (src.transform.a > 0 > src.transform.e):
                raise ErrorHarmony("La orientación de cuadrícula GCOV no está soportada.")
            res = (abs(src.transform.a), abs(src.transform.e))
            if min(res) < 5 or max(res) > 100 or abs(res[0] - res[1]) > .1:
                raise ErrorHarmony("Resolución inesperada; no se reproyecta ni interpola en silencio.")
            o, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=10)
            w, y, x, z = bbox
            if e < w or x < o or n < y or z < s:
                raise ErrorHarmony("El COG no intersecta la zona solicitada.")
            if capa in ("HHHH", "VVVV", "HVHV", "VHVH") and src.dtypes[0] not in ("float32", "float64"):
                raise ErrorHarmony("La intensidad GCOV no está en punto flotante.")
            # Inspección acotada: la validez por píxel se verifica después con la máscara.
            ventana = ((0, min(128, src.height)), (0, min(128, src.width)))
            muestra = src.read(1, window=ventana, masked=True)
            return {"crs": str(src.crs), "resolucion_m": list(res),
                    "transform": list(tuple(src.transform)[:6]),
                    "dimensiones": [src.width, src.height], "dtype": src.dtypes[0],
                    "muestra_finitos": int(np.isfinite(muestra.compressed()).sum())}
    except ErrorHarmony:
        raise
    except (OSError, ValueError, rasterio.errors.RasterioError) as exc:
        raise ErrorHarmony("No se pudo verificar el GeoTIFF descargado.") from exc


def obtener(spec: Especificacion, carpeta: Path, *, cliente=None, abrir=None,
            notificar=None, comprobar=None, limite_bytes: int = MAX_TOTAL_BYTES,
            timeout_s: int = PLAZO_S, dormir=time.sleep) -> dict:
    """Solicita y obtiene COG NISAR AOI con trazabilidad; nunca sobrescribe.

    No reenvía EARTHDATA_TOKEN a enlaces firmados, no guarda las URLs con firma.
    Rechaza archivos incompletos o capas equivocadas antes de publicar resultados.
    """
    if limite_bytes <= 0 or limite_bytes > MAX_TOTAL_BYTES:
        raise ErrorHarmony("Presupuesto de datos Harmony fuera del límite permitido.")
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    ident = hashlib.sha256(json.dumps(spec.resumen(), sort_keys=True).encode()).hexdigest()[:16]
    final = carpeta / ident
    if final.exists():
        manifest = final / "manifest.json"
        if manifest.is_file():
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            for item in meta.get("archivos", []):
                p = final / item["archivo"]
                if not p.is_file() or p.stat().st_size != item["bytes"]:
                    raise ErrorHarmony("El caché Harmony existe, pero está incompleto.")
                sha = hashlib.sha256()
                with p.open("rb") as archivo:
                    for bloque in iter(lambda: archivo.read(BLOQUE), b""):
                        sha.update(bloque)
                if sha.hexdigest() != item["sha256"]:
                    raise ErrorHarmony("El caché Harmony fue alterado y no debe reutilizarse.")
            if set(item["capa"] for item in meta["archivos"]) == set(spec.capas):
                return meta
        raise ErrorHarmony("La carpeta de descarga Harmony ya existe y no coincide con el plan.")
    libre = shutil.disk_usage(carpeta).free
    if libre < limite_bytes + 80 * 1024**2:
        raise ErrorHarmony("No hay espacio libre para el límite configurado de COG.")
    if comprobar:
        comprobar()
    cliente = cliente or _cliente()
    solicitud = construir_solicitud(spec)
    temp = carpeta / (".preparando-" + uuid.uuid4().hex[:12])
    temp.mkdir()
    jobid = None
    try:
        jobid = cliente.submit(solicitud)
        if not isinstance(jobid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{10,128}", jobid):
            raise ErrorHarmony("Harmony no devolvió identificador de trabajo seguro.")
        inicio = time.monotonic()
        while True:
            if comprobar:
                comprobar()
            if time.monotonic() - inicio > timeout_s:
                raise ErrorHarmony("Harmony no terminó dentro del límite de procesamiento.")
            estado = cliente.status(jobid)
            status = str(estado.get("status") or "").lower()
            if status in ("successful", "completed"):
                break
            if status in ("failed", "canceled", "cancelled", "completed_with_errors"):
                raise ErrorHarmony("Harmony finalizó sin todas las capas válidas.")
            if notificar:
                notificar("Harmony: preparando recorte", estado.get("progress", 0))
            dormir(INTERVALO_S)
        urls = list(cliente.result_urls(jobid))
        if not 1 <= len(urls) <= len(spec.capas):
            raise ErrorHarmony("Harmony devolvió una cantidad inesperada de archivos.")
        reconocidos = {}
        for url in urls:
            _url_datos(url)
            capa = _etiqueta(url, spec.capas)
            if capa in reconocidos:
                raise ErrorHarmony("Harmony entregó capas duplicadas.")
            reconocidos[capa] = url
        if set(reconocidos) != set(spec.capas):
            raise ErrorHarmony("Faltan capas científicas necesarias: " +
                               ", ".join(sorted(set(spec.capas) - set(reconocidos))))
        archivos = []
        consumido = 0
        for capa in spec.capas:
            if comprobar:
                comprobar()
            destino = temp / (capa + ".tif")
            restante = min(MAX_UN_ARCHIVO, limite_bytes - consumido)
            if restante <= 0:
                raise ErrorHarmony("Se agotó el presupuesto de transferencia.")
            if notificar:
                notificar("Descargando capa", capa)
            try:
                tam, sha = _descargar_cota(
                    reconocidos[capa], destino, restante, abrir=abrir,
                    comprobar=comprobar, cliente=cliente,
                )
            except ErrorHarmony as exc:
                # Identificar la variable científica, no divulgar URLs firmadas.
                raise ErrorHarmony(f"Capa {capa}: {exc}") from None
            consumido += tam
            geo = _validar_cog(destino, spec.bbox, capa)
            archivos.append({"capa": capa, "archivo": destino.name, "bytes": tam,
                             "sha256": sha, "geotiff": geo})
        # La máscara y las intensidades deben describir exactamente la misma cuadrícula.
        origen = archivos[0]["geotiff"]
        for a in archivos[1:]:
            meta = a["geotiff"]
            if (meta["crs"], meta["dimensiones"], meta["resolucion_m"], meta["transform"]) != (
                origen["crs"], origen["dimensiones"], origen["resolucion_m"], origen["transform"]
            ):
                raise ErrorHarmony("Las capas Harmony no comparten CRS, resolución y dimensiones.")
        meta = {
            "estado": "INSUMOS_GCOV_SIN_CLASIFICAR", "sensor": "NISAR", "banda": "L",
            "tipo": "HARMONY_COG_SUBSET", "granule": spec.granule,
            "aoi": list(spec.bbox), "variables": list(spec.variables),
            "job_id": jobid, "bytes_totales": consumido,
            "carpeta_relativa": final.name,
            "archivos": archivos, "creado_utc": datetime.now(timezone.utc).isoformat(),
            "advertencia": "Insumos GCOV gamma0 en potencia; NO son mapas de inundación.",
        }
        (temp / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.rename(final)
        return meta
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        if jobid:
            try:
                cliente.cancel(jobid)
            except Exception:
                pass
        raise
