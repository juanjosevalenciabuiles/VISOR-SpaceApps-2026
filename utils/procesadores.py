"""Procesadores de datos SAR disponibles y por qué sí o no se pueden usar aquí.

Orden de preferencia (no se gastan recursos sin necesidad):
1. RTC existentes  — GeoTIFF gamma0 en potencia de ASF HyP3 ya en data/sar/: se usan tal cual.
2. SNAP gpt        — solo para Sentinel-1 GRD sin RTC, y solo en un worker aislado
                     (`VISOR_SNAP_WORKER`). Nunca dentro del proceso web de Streamlit.
3. NISAR Harmony   — recorte COG de GCOV L2 vía ASF Harmony con token Earthdata.
4. HyP3            — DESHABILITADO en la app: no se envían trabajos sin autorización expresa.

Ningún procesador se declara APTO sin comprobar lo que necesita. Las credenciales se
leen solo para saber si EXISTEN; nunca se muestran ni se registran.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from utils.config import DATA_DIR

APTO, NO_DISPONIBLE, DESHABILITADO = "APTO", "NO DISPONIBLE", "DESHABILITADO"
RAM_MINIMA_SNAP = 16 * 1024 ** 3      # SNAP con Terrain-Correction en una escena IW completa
DISCO_MINIMO_SNAP = 20 * 1024 ** 3    # GRD (~1–2 GB) + intermedios + DEM


class NoDisponible(Exception):
    """El procesador no se puede usar en este entorno."""


@dataclass
class Diagnostico:
    clave: str
    nombre: str
    estado: str
    motivo: str
    sensor: str
    comprobaciones: list[tuple[str, bool, str]] = field(default_factory=list)   # (qué, ok, detalle)


def _ram_total() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def _hay(variable: str) -> bool:
    return bool(os.environ.get(variable, "").strip())


def diagnostico_rtc() -> Diagnostico:
    from utils import flujo_sar
    rtcs, _ = flujo_sar.rtc_locales()
    ok = bool(rtcs)
    return Diagnostico(
        "rtc", "RTC existentes (ASF HyP3)", APTO if ok else NO_DISPONIBLE,
        "Usa directamente los RTC gamma0 en potencia; no requiere SNAP ni credenciales." if ok
        else "No hay productos RTC en data/sar/.",
        "Sentinel-1 · banda C",
        [("RTC en data/sar/", ok, f"{len(rtcs)} archivos")])


def diagnostico_snap() -> Diagnostico:
    gpt = os.environ.get("VISOR_SNAP_GPT") or shutil.which("gpt")
    java = shutil.which("java")
    ram = _ram_total()
    try:
        disco = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else Path.cwd()).free
    except OSError:
        disco = None
    worker = _hay("VISOR_SNAP_WORKER")
    comprobaciones = [
        ("Worker aislado (VISOR_SNAP_WORKER)", worker, "configurado" if worker else "no configurado"),
        ("Ejecutable gpt de SNAP", bool(gpt), "encontrado" if gpt else "no instalado en este entorno"),
        ("Java", bool(java), "encontrado" if java else "no instalado en este entorno"),
        ("Memoria ≥ 16 GB", ram is not None and ram >= RAM_MINIMA_SNAP,
         f"{ram / 1024 ** 3:.1f} GB" if ram else "desconocida"),
        ("Disco libre ≥ 20 GB", disco is not None and disco >= DISCO_MINIMO_SNAP,
         f"{disco / 1024 ** 3:.1f} GB" if disco is not None else "desconocido"),
    ]
    if not worker:
        motivo = ("No hay un worker SNAP aislado configurado. SNAP no se ejecuta dentro del servidor web; "
                  "la ruta disponible es usar RTC ya procesados.")
    else:
        motivo = ("Hay un worker configurado, pero la app aún no tiene cliente probado contra un worker real; "
                  "no se envían trabajos.")
    return Diagnostico("snap", "SNAP gpt (Sentinel-1 GRD → RTC gamma0)", NO_DISPONIBLE, motivo,
                       "Sentinel-1 · banda C", comprobaciones)


def diagnostico_nisar() -> Diagnostico:
    token = _hay("EARTHDATA_TOKEN") or _hay("EDL_TOKEN")
    try:
        import importlib.util
        lector = importlib.util.find_spec("utils.nisar_gcov") is not None
    except (ImportError, ValueError):
        lector = False
    comprobaciones = [
        ("Token Earthdata en el entorno", token, "presente (no se muestra)" if token else "ausente"),
        ("Lector GCOV integrado", lector, "sí" if lector else "en la PR #6, sin integrar en esta versión"),
    ]
    motivo = ("Falta " + " y ".join(q for q, ok, _ in comprobaciones if not ok).lower() + ". "
              "No se declara validado ningún GCOV sin abrir un HDF5 o COG auténtico.")
    return Diagnostico("nisar", "NISAR GCOV vía ASF Harmony", NO_DISPONIBLE, motivo, "NISAR · banda L",
                       comprobaciones)


def diagnostico_hyp3() -> Diagnostico:
    return Diagnostico(
        "hyp3", "ASF HyP3 (RTC bajo demanda)", DESHABILITADO,
        "La app no envía trabajos HyP3: consumen cuota y requieren autorización expresa del equipo. "
        "Los RTC de la demo ya se generaron fuera de la app.",
        "Sentinel-1 · banda C",
        [("Autorización del equipo", False, "no concedida para envíos desde la app")])


def diagnosticos() -> list[Diagnostico]:
    return [diagnostico_rtc(), diagnostico_snap(), diagnostico_nisar(), diagnostico_hyp3()]


def elegir(tiene_rtc: bool) -> Diagnostico:
    """Procesador para un par Sentinel-1. Con RTC existentes nunca se reprocesa."""
    if tiene_rtc:
        d = diagnostico_rtc()
        d.estado, d.motivo = APTO, "RTC gamma0 ya corregidos por terreno; no se reprocesan ni requieren SNAP."
        return d
    snap = diagnostico_snap()
    if snap.estado == APTO:
        return snap
    raise NoDisponible("Este par no tiene RTC locales y no hay procesador disponible para generarlos: "
                       + snap.motivo + " HyP3 está deshabilitado en la app.")


# ---------------------------------------------------------------------------
# Grafo SNAP (preparado, NO EJECUTADO: no hay SNAP en ningún entorno accesible)
# ---------------------------------------------------------------------------

def grafo_grd_a_rtc(entrada: str, salida: str, crs: str = "AUTO:42001", espaciado_m: float = 30.0,
                    dem: str = "Copernicus 30m Global DEM", polarizaciones: str = "VV,VH") -> str:
    """Grafo gpt para obtener gamma0 corregido por terreno (RTC) en potencia lineal.

    Orden y motivo: órbita precisa → ruido térmico → calibración a BETA0 (Terrain-Flattening
    la exige para producir gamma0 «flattened», comparable con HyP3 gamma0) → aplanado de
    terreno → speckle sobre potencia → corrección geométrica a UTM automática (AUTO:42001,
    no EPSG:32618 fijo). Sin conversión a dB: el motor espera potencia.
    ESTADO: no ejecutado ni comparado con HyP3; los nombres de operadores y parámetros deben
    comprobarse con `gpt <Operador> -h` en el worker antes de usarlo."""
    def nodo(id_, op, fuente, parametros):
        cuerpo = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in parametros.items())
        src = f"<sources><sourceProduct refid=\"{fuente}\"/></sources>" if fuente else "<sources/>"
        return f'<node id="{id_}"><operator>{op}</operator>{src}<parameters>{cuerpo}</parameters></node>'
    nodos = [
        nodo("Read", "Read", None, {"file": entrada}),
        nodo("Orbit", "Apply-Orbit-File", "Read", {"orbitType": "Sentinel Precise (Auto Download)",
                                                    "continueOnFail": "false"}),
        nodo("Noise", "ThermalNoiseRemoval", "Orbit", {"selectedPolarisations": polarizaciones,
                                                        "removeThermalNoise": "true"}),
        nodo("Cal", "Calibration", "Noise", {"selectedPolarisations": polarizaciones, "outputBetaBand": "true",
                                              "outputSigmaBand": "false", "outputGammaBand": "false"}),
        nodo("TF", "Terrain-Flattening", "Cal", {"demName": dem, "demResamplingMethod": "BILINEAR_INTERPOLATION",
                                                 "outputSigma0": "false"}),
        nodo("Speckle", "Speckle-Filter", "TF", {"filter": "Lee", "filterSizeX": "5", "filterSizeY": "5"}),
        nodo("TC", "Terrain-Correction", "Speckle", {"demName": dem, "pixelSpacingInMeter": espaciado_m,
                                                     "mapProjection": crs, "nodataValueAtSea": "false",
                                                     "saveSelectedSourceBand": "true"}),
        nodo("Write", "Write", "TC", {"file": salida, "formatName": "GeoTIFF-BigTIFF"}),
    ]
    return '<graph id="VISOR_GRD_a_RTC_gamma0"><version>1.0</version>' + "".join(nodos) + "</graph>"


def comando_gpt(grafo: Path, hilos: int = 4, cache_gb: int = 8, gpt: str = "gpt") -> list[str]:
    """Línea de órdenes para el worker. Sin shell, sin credenciales en argumentos."""
    return [gpt, str(grafo), "-q", str(int(hilos)), "-c", f"{int(cache_gb)}G", "-e"]


def ejecutar_snap(*_args, **_kwargs):
    """Punto de entrada del adaptador. Hoy siempre NoDisponible, con el motivo exacto."""
    raise NoDisponible(diagnostico_snap().motivo)
