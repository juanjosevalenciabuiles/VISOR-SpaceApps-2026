"""Registro persistente de trabajos de análisis y su ejecución en segundo plano.

Un TRABAJO es la ejecución de «Analizar»: tiene identificador propio (`job_id`),
huella de entradas (`run_id`), estado, fases con hora, fallos y la lista de
archivos producidos con su SHA-256. Se guarda como un JSON por trabajo en
`data/trabajos/` (escritura atómica: archivo temporal + `os.replace`), así que
sobrevive a recargas del navegador y a reinicios del servidor en una instancia
única. No hay base de datos ni cola distribuida: con varios procesos web cada
uno ejecuta sus propios trabajos (ver docs/).

Ejecución:
- El cálculo corre en un hilo aparte, nunca en la ejecución de Streamlit, para
  que la interfaz siga respondiendo y el trabajo no dependa de la pestaña.
- `MAX_SIMULTANEOS` (por defecto 1) limita los cálculos a la vez en el proceso;
  los demás quedan PENDIENTES «en cola».
- Cancelación y límite de tiempo son COOPERATIVOS: se comprueban entre pasos
  (antes de cada polarización, antes de combinar, antes de verificar). Un paso
  ya en marcha termina antes de que el trabajo se detenga; no se mata el hilo.
- Si el servidor se reinicia con un trabajo PENDIENTE o EN CURSO, al leerlo se
  marca ERROR «interrumpido» (no se finge que terminó); se puede reintentar.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from utils.config import DATA_DIR

PENDIENTE, EN_CURSO, APTO, ERROR, BLOQUEADO, CANCELADO = (
    "PENDIENTE", "EN CURSO", "APTO", "ERROR", "BLOQUEADO", "CANCELADO")
ACTIVOS = (PENDIENTE, EN_CURSO)
FINALES = (APTO, ERROR, CANCELADO, BLOQUEADO)

FASES = (
    ("zona", "Zona definida"),
    ("escenas", "Buscando escenas"),
    ("datos", "Verificando datos"),
    ("preparacion", "Preparando datos"),
    ("calculo", "Calculando"),
    ("verificacion", "Verificando"),
    ("listo", "Listo"),
)
NOMBRE_FASE = dict(FASES)

MAX_SIMULTANEOS = max(1, int(os.environ.get("VISOR_MAX_TRABAJOS", "1") or 1))
LIMITE_S = max(5, int(os.environ.get("VISOR_LIMITE_TRABAJO_S", "900") or 900))
SINCRONO = os.environ.get("VISOR_TRABAJOS_SINCRONOS") == "1"   # pruebas AppTest: mismo código, sin hilo

# Identidad de ESTE proceso: un trabajo activo de otro proceso ya no tiene quien lo ejecute.
PROCESO = uuid.uuid4().hex
_cerrojo = threading.RLock()
_cupo = threading.BoundedSemaphore(MAX_SIMULTANEOS)
_cancelar: dict[str, threading.Event] = {}
_hilos: dict[str, threading.Thread] = {}


class Cancelado(Exception):
    """Cancelación pedida por la persona."""


class TiempoAgotado(Exception):
    """El trabajo superó el límite de tiempo."""


def carpeta() -> Path:
    destino = Path(os.environ["VISOR_TRABAJOS_DIR"]) if os.environ.get("VISOR_TRABAJOS_DIR") else DATA_DIR / "trabajos"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ruta(job_id: str) -> Path:
    if not job_id or not all(c in "0123456789abcdef" for c in job_id):
        raise ValueError("identificador de trabajo no válido")
    return carpeta() / f"{job_id}.json"


def guardar(t: dict) -> dict:
    with _cerrojo:
        t["actualizado_utc"] = _ahora()
        ruta = _ruta(t["job_id"])
        tmp = ruta.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ruta)
    return t


def _recuperar(t: dict) -> dict:
    """Un trabajo activo que no pertenece a este proceso quedó huérfano por un reinicio."""
    if t.get("estado") in ACTIVOS and t.get("proceso") != PROCESO:
        t["estado"] = ERROR
        t["error"] = ("El servidor se reinició mientras el trabajo estaba en marcha; no terminó. "
                      "Pulsa «Reintentar» para ejecutarlo de nuevo.")
        for f in t.get("fases", []):
            if f["estado"] in ACTIVOS:
                f["estado"] = ERROR
        t["terminado_utc"] = _ahora()
        guardar(t)
    return t


def leer(job_id: str) -> dict | None:
    try:
        t = json.loads(_ruta(job_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _recuperar(t)


def listar(limite: int = 20) -> list[dict]:
    salida = []
    for ruta in carpeta().glob("*.json"):
        t = leer(ruta.stem)
        if t:
            salida.append(t)
    salida.sort(key=lambda t: t.get("creado_utc", ""), reverse=True)
    return salida[:limite]


def activo_con_run_id(run_id: str) -> dict | None:
    """Trabajo PENDIENTE o EN CURSO de este proceso con la misma huella (evita duplicarlo)."""
    for t in listar(200):
        if t.get("run_id") == run_id and t.get("estado") in ACTIVOS:
            return t
    return None


def crear(run_id: str, descripcion: dict, fases_previas: dict[str, str] | None = None) -> dict:
    fases = [{"clave": c, "nombre": n, "estado": PENDIENTE, "detalle": "", "inicio_utc": None, "fin_utc": None}
             for c, n in FASES]
    for f in fases:
        if f["clave"] in (fases_previas or {}):
            f.update(estado=APTO, detalle=fases_previas[f["clave"]], inicio_utc=_ahora(), fin_utc=_ahora())
    t = {"job_id": uuid.uuid4().hex[:16], "run_id": run_id, "estado": PENDIENTE, "creado_utc": _ahora(),
         "iniciado_utc": None, "terminado_utc": None, "proceso": PROCESO, "intentos": 1, "error": None,
         "cancelacion_pedida": False, "limite_s": LIMITE_S, "fases": fases, "archivos": [], "registro": None,
         "principal": None, "avisos": [], "historial_intentos": [], **descripcion}
    return guardar(t)


def crear_o_reutilizar(run_id: str, descripcion: dict, funcion: Callable[["Contexto"], None],
                       fases_previas: dict[str, str] | None = None) -> tuple[dict, bool]:
    """Idempotente: si ya hay un trabajo activo con esta huella (otra pestaña, otra sesión), se
    devuelve ese en lugar de crear otro. Devuelve (trabajo, creado)."""
    with _cerrojo:
        existente = activo_con_run_id(run_id)
        if existente is not None:
            return existente, False
        t = crear(run_id, descripcion, fases_previas)
        _cancelar[t["job_id"]] = threading.Event()      # reservado: otra llamada ya lo ve como propio
    lanzar(t["job_id"], funcion)
    return leer(t["job_id"]), True


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


class Contexto:
    """Lo que ve la función del trabajo: marcar fases y comprobar cancelación y tiempo."""

    def __init__(self, job_id: str, inicio: float, limite_s: int):
        self.job_id, self.inicio, self.limite_s = job_id, inicio, limite_s

    def _editar(self, cambio: Callable[[dict], None]) -> None:
        with _cerrojo:
            t = leer(self.job_id)
            cambio(t)
            guardar(t)

    def fase(self, clave: str, estado: str, detalle: str = "") -> None:
        def cambio(t):
            for f in t["fases"]:
                if f["clave"] == clave:
                    f["estado"] = estado
                    f["detalle"] = detalle or f["detalle"]
                    if estado == EN_CURSO and not f["inicio_utc"]:
                        f["inicio_utc"] = _ahora()
                    if estado in FINALES:
                        f["inicio_utc"] = f["inicio_utc"] or _ahora()
                        f["fin_utc"] = _ahora()
        self._editar(cambio)

    def comprobar(self, paso: str = "") -> None:
        evento = _cancelar.get(self.job_id)
        if evento is not None and evento.is_set():
            raise Cancelado(paso)
        if time.monotonic() - self.inicio > self.limite_s:
            raise TiempoAgotado(paso)

    def resultado(self, principal: Path, registro: Path, archivos: list[Path], avisos: list[str]) -> None:
        huellas = [{"nombre": Path(a).name, "bytes": Path(a).stat().st_size, "sha256": sha256(Path(a))}
                   for a in archivos]
        def cambio(t):
            t.update(principal=Path(principal).name, registro=Path(registro).name, archivos=huellas,
                     avisos=list(avisos))
        self._editar(cambio)

    def anotar_parciales(self, archivos: list[Path]) -> None:
        def cambio(t):
            t["parciales"] = sorted({*(t.get("parciales") or []), *(Path(a).name for a in archivos)})
        self._editar(cambio)


def _fase_activa(t: dict) -> dict | None:
    return next((f for f in t["fases"] if f["estado"] == EN_CURSO), None)


def _cerrar(job_id: str, estado: str, error: str | None = None) -> None:
    with _cerrojo:
        t = leer(job_id)
        t["estado"], t["error"], t["terminado_utc"] = estado, error, _ahora()
        en_curso = _fase_activa(t)
        if en_curso:
            en_curso.update(estado=estado if estado != APTO else APTO, fin_utc=_ahora())
        if estado == APTO:
            for f in t["fases"]:
                if f["clave"] == "listo":
                    f.update(estado=APTO, inicio_utc=_ahora(), fin_utc=_ahora(), detalle="Resultado publicado")
        guardar(t)


def _correr(job_id: str, funcion: Callable[[Contexto], None]) -> None:
    evento = _cancelar[job_id]
    t = leer(job_id)
    limite = int(t.get("limite_s") or LIMITE_S)
    while not _cupo.acquire(timeout=0.25):          # en cola mientras otro análisis ocupa el cupo
        if evento.is_set():
            _cerrar(job_id, CANCELADO, "Cancelado antes de empezar (estaba en cola).")
            return
        with _cerrojo:
            t = leer(job_id)
            if not t.get("en_cola"):
                t["en_cola"] = True
                guardar(t)
    try:
        with _cerrojo:
            t = leer(job_id)
            t.update(estado=EN_CURSO, en_cola=False, iniciado_utc=_ahora())
            guardar(t)
        ctx = Contexto(job_id, time.monotonic(), limite)
        ctx.comprobar()
        funcion(ctx)
        _cerrar(job_id, APTO)
    except Cancelado:
        _cerrar(job_id, CANCELADO, "Cancelado por la persona. Lo ya escrito en disco queda anotado como parcial "
                                   "y no se muestra en el mapa.")
    except TiempoAgotado:
        _cerrar(job_id, ERROR, f"Superó el límite de {limite} s; se detuvo al terminar el paso en curso.")
    except Exception as e:  # noqa: BLE001 — cualquier fallo queda registrado y visible, nunca silencioso
        tipo = "" if type(e).__name__ in ("ErrorSAR", "OSError", "ValueError") else f"{type(e).__name__}: "
        _cerrar(job_id, ERROR, f"{tipo}{e}")
    finally:
        _cupo.release()
        with _cerrojo:
            _hilos.pop(job_id, None)


def lanzar(job_id: str, funcion: Callable[[Contexto], None], sincrono: bool | None = None) -> None:
    """Ejecuta el trabajo. En segundo plano salvo VISOR_TRABAJOS_SINCRONOS=1 (pruebas)."""
    with _cerrojo:
        if job_id in _hilos:
            return                                   # ya corre: nunca dos ejecuciones del mismo trabajo
        _cancelar.setdefault(job_id, threading.Event())
        if SINCRONO if sincrono is None else sincrono:
            _hilos[job_id] = threading.current_thread()
        else:
            hilo = threading.Thread(target=_correr, args=(job_id, funcion), name=f"visor-trabajo-{job_id}",
                                    daemon=True)
            _hilos[job_id] = hilo
            hilo.start()
            return
    _correr(job_id, funcion)


def cancelar(job_id: str) -> bool:
    """Pide cancelar. Devuelve False si el trabajo no está activo en este proceso."""
    with _cerrojo:
        t = leer(job_id)
        if not t or t["estado"] not in ACTIVOS or job_id not in _cancelar:
            return False
        t["cancelacion_pedida"] = True
        guardar(t)
        _cancelar[job_id].set()
    return True


def reintentar(job_id: str, funcion: Callable[[Contexto], None], sincrono: bool | None = None) -> dict:
    """Nuevo intento del mismo trabajo (misma huella). Solo desde ERROR o CANCELADO."""
    with _cerrojo:
        t = leer(job_id)
        if not t or t["estado"] not in (ERROR, CANCELADO):
            raise ValueError("Solo se reintenta un trabajo con ERROR o CANCELADO.")
        t["historial_intentos"].append({"intento": t["intentos"], "estado": t["estado"], "error": t["error"],
                                        "terminado_utc": t["terminado_utc"]})
        t.update(intentos=t["intentos"] + 1, estado=PENDIENTE, error=None, terminado_utc=None, iniciado_utc=None,
                 proceso=PROCESO, cancelacion_pedida=False, archivos=[], registro=None, principal=None)
        for f in t["fases"]:
            if f["clave"] not in ("zona", "escenas"):
                f.update(estado=PENDIENTE, detalle="", inicio_utc=None, fin_utc=None)
        guardar(t)
        _cancelar[job_id] = threading.Event()
    lanzar(job_id, funcion, sincrono)
    return leer(job_id)


def esperar(job_id: str, segundos: float = 60) -> dict:
    """Solo para pruebas y scripts: espera a que el trabajo termine."""
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        t = leer(job_id)
        if t and t["estado"] in FINALES:
            return t
        time.sleep(0.1)
    return leer(job_id)
