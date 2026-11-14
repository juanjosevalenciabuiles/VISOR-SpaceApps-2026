"""Verificación integral de V.I.S.O.R. en una sola ejecución, con informe y veredicto.

    bash verificar.sh                     # Replit o Linux: todo lo posible aquí
    bash verificar.sh --navegador         # exige además las pruebas de navegador (Playwright)
    bash verificar.sh --red               # añade una consulta REAL a ASF (necesita Internet)
    .venv/bin/python scripts/verificar_visor.py --ci   # lo que corre GitHub Actions

Qué comprueba: entorno y dependencias, estado de Git (cambios locales, p. ej. del
agente de Replit; operaciones a medio terminar), pytest, ruff, navegador
(Playwright, si está disponible), arranque de la app con los datos reales y con
cada resultado activado, los GeoTIFF reales de data/analisis/ (CRS, tamaño,
NoData, clases, superficies, procedencia y SHA-256, paquete QGIS) frente a la
referencia verificada del 12-nov, incluida la diferencia documentada de 15.860
píxeles entre los dos productos VV/VH (no se exige equivalencia).

SOLO LECTURA sobre data/: huella de cada archivo antes y después; cualquier
cambio hace el resultado NO APTO. No usa HyP3, no descarga ni procesa NISAR,
no publica ni fusiona. El informe va a informes/ (fuera de Git).
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata as metadata
import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
# Sin avisos de caché de Streamlit al leer resultados fuera de la app (ruido en el informe).
os.environ.setdefault("STREAMLIT_LOGGER_LEVEL", "error")

from utils.verificacion import (  # noqa: E402
    ADVERTENCIA, APROBADA, CRITICO, FALLIDA, IMPORTANTE, INFORMATIVO, NO_APTO, OMITIDA,
    Informe, auditar_resultados, diferencias_huellas, huellas, leer_referencia,
)

DEPENDENCIAS = ("streamlit", "folium", "streamlit-folium", "rasterio", "numpy", "geopandas", "pytest")


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def entorno(inf: Informe) -> None:
    cat = "Entorno"
    inf.si(sys.version_info[:2] >= (3, 11), "ENT-01", cat, "Versión de Python", "≥ 3.11", CRITICO,
           platform.python_version(), platform.python_version())
    pedidos = {}
    for linea in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)~=(\d+\.\d+)", linea.strip())
        if m:
            pedidos[m.group(1).lower()] = m.group(2)
    faltan, distintas = [], []
    for dep in DEPENDENCIAS:
        try:
            v = metadata.version(dep)
        except metadata.PackageNotFoundError:
            faltan.append(dep)
            continue
        serie = pedidos.get(dep)
        if serie and not v.startswith(serie + "."):
            distintas.append(f"{dep} {v} (pedido {serie}.x)")
    inf.si(not faltan, "ENT-02", cat, "Dependencias instaladas", "Todas las de requirements.txt", CRITICO,
           "todas presentes", "faltan: " + ", ".join(faltan))
    if distintas:
        inf.agregar("ENT-03", cat, "Versiones de requirements.txt", "Misma serie (~=)", INFORMATIVO, ADVERTENCIA,
                    "; ".join(distintas))


def estado_git(inf: Informe) -> None:
    cat = "Git"
    rama = _git("rev-parse", "--abbrev-ref", "HEAD")
    if rama is None:
        inf.agregar("GIT-01", cat, "Repositorio Git", "Carpeta con Git", INFORMATIVO, OMITIDA, "sin Git aquí")
        return
    inf.contexto["Rama"] = rama
    inf.contexto["Commit"] = _git("rev-parse", "--short", "HEAD")
    en_curso = [n for n in ("MERGE_HEAD", "REBASE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD")
                if (RAIZ / ".git" / n).exists()]
    inf.si(not en_curso, "GIT-02", cat, "Sin operación de Git a medio terminar", "Ni merge ni rebase en curso",
           IMPORTANTE, "ninguna", "en curso: " + ", ".join(en_curso))
    cambios = [ln for ln in (_git("status", "--porcelain") or "").splitlines() if ln.strip()]
    inf.si(not cambios, "GIT-03", cat, "Cambios locales sin commit (p. ej. del agente de Replit)",
           "Árbol limpio (data/ y otros ignorados no cuentan)", IMPORTANTE, "árbol limpio",
           f"{len(cambios)} cambio(s): " + "; ".join(cambios[:12]) + (" …" if len(cambios) > 12 else ""),
           estado_mal=ADVERTENCIA)
    seguimiento = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if seguimiento:
        detras_delante = _git("rev-list", "--left-right", "--count", f"{seguimiento}...HEAD")
        if detras_delante:
            detras, delante = detras_delante.split()
            inf.si(detras == "0" and delante == "0", "GIT-04", cat,
                   f"Sincronía con {seguimiento} (última consulta local)", "0 detrás, 0 delante", INFORMATIVO,
                   "sincronizada", f"{detras} detrás, {delante} delante", estado_mal=ADVERTENCIA)


def _junit(ruta: Path) -> dict:
    datos = {"pruebas": 0, "fallidas": [], "omitidas": []}
    try:
        raiz = ET.parse(ruta).getroot()
    except (OSError, ET.ParseError):
        return datos
    for caso in raiz.iter("testcase"):
        datos["pruebas"] += 1
        nombre = f"{caso.get('classname', '').split('.')[-1]}::{caso.get('name')}"
        if caso.find("failure") is not None or caso.find("error") is not None:
            datos["fallidas"].append(nombre)
        elif caso.find("skipped") is not None:
            motivo = (caso.find("skipped").get("message") or "").replace("Skipped: ", "")
            datos["omitidas"].append(f"{nombre} ({motivo[:90]})")
    return datos


def pytest_(inf: Informe, id_: str, descripcion: str, marcas: str, nivel: str, tiempo: int,
            entorno_extra: dict | None = None) -> dict | None:
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "junit.xml"
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-m", marcas, f"--junitxml={junit}",
                                "-p", "no:cacheprovider"], cwd=RAIZ, capture_output=True, text=True,
                               timeout=tiempo, env={**os.environ, **(entorno_extra or {})})
        except subprocess.TimeoutExpired:
            inf.agregar(id_, "Pruebas", descripcion, "0 fallidas", nivel, FALLIDA, f"superó {tiempo} s")
            return None
        d = _junit(junit)
    if d["pruebas"] == 0:
        # Estas baterías nunca están vacías: 0 pruebas (o un junit ilegible) es un fallo, no una omisión.
        inf.agregar(id_, "Pruebas", descripcion, "0 fallidas y al menos una prueba ejecutada", nivel, FALLIDA,
                    (r.stdout + r.stderr)[-400:] or "no se recogió ninguna prueba")
        return d
    ok = r.returncode == 0 and not d["fallidas"]
    aprobadas = d["pruebas"] - len(d["fallidas"]) - len(d["omitidas"])
    inf.si(ok, id_, "Pruebas", descripcion, "0 fallidas", nivel,
           f"{aprobadas} aprobadas, {len(d['omitidas'])} omitidas",
           f"{len(d['fallidas'])} fallidas: " + "; ".join(d["fallidas"][:10]))
    for i, omitida in enumerate(d["omitidas"][:10], 1):
        inf.agregar(f"{id_}-O{i}", "Pruebas", "Prueba omitida", "Se ejecuta donde existan sus requisitos",
                    INFORMATIVO, OMITIDA, omitida)
    return d


def ruff(inf: Informe) -> None:
    import shutil
    orden = [shutil.which("ruff")] if shutil.which("ruff") else [sys.executable, "-m", "ruff"]
    try:
        r = subprocess.run([*orden, "check", "--select", "F,E9,B", "."], cwd=RAIZ,
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        r = None
    if r is None or "No module named ruff" in (r.stderr or ""):
        inf.agregar("LNT-01", "Calidad", "ruff (errores, nombres indefinidos, bugs típicos)", "Sin hallazgos",
                    INFORMATIVO, OMITIDA, "ruff no instalado aquí (lo corre GitHub Actions)")
        return
    inf.si(r.returncode == 0, "LNT-01", "Calidad", "ruff (errores, nombres indefinidos, bugs típicos)",
           "Sin hallazgos", IMPORTANTE, "sin hallazgos", (r.stdout or r.stderr)[-500:])


def navegador_disponible() -> str | None:
    """None si Playwright y Chromium funcionan; si no, el motivo."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright no instalado (pip install -r requirements-dev.txt)"
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as e:  # noqa: BLE001 — cualquier fallo de arranque significa «no disponible»
        return f"Chromium no arranca: {str(e).splitlines()[0][:120]}"
    return None


APP_REAL = """
import sys
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=180).run()
assert not at.exception, ("arranque", at.exception)
assert len(at.error) == 0, ("st.error", [e.value for e in at.error])
claves = [t.key for t in at.toggle if t.key and t.key.startswith("res_")]
for clave in claves:
    at.toggle(key=clave).set_value(True).run()
    assert not at.exception, (clave, at.exception)
    texto = " ".join(m.value for m in at.markdown)
    assert "No es una inundación confirmada" in texto, (clave, "falta el aviso")
    at.toggle(key=clave).set_value(False).run()
print(len(claves))
"""


def app_real(inf: Informe) -> None:
    try:
        r = subprocess.run([sys.executable, "-c", APP_REAL], cwd=RAIZ, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        inf.agregar("APP-01", "Aplicación", "Arranque con los datos reales", "Sin excepciones", CRITICO, FALLIDA,
                    "superó 600 s")
        return
    n = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else "?"
    inf.si(r.returncode == 0, "APP-01", "Aplicación",
           "Arranque con los datos reales y cada resultado activado", "Sin excepciones ni st.error; aviso científico "
           "en cada ficha", CRITICO, f"{n} resultado(s) activados sin errores", r.stderr[-600:])


def asf_real(inf: Informe) -> None:
    from utils import buscador_sar as bus
    try:
        r = bus.buscar(-76.80, 7.55, -76.55, 7.80, "2026-09-20", "2026-10-10")
        inf.si(len(r.escenas) > 0, "RED-01", "ASF", "Consulta REAL al catálogo de ASF (Chigorodó)",
               "Responde con escenas", IMPORTANTE, f"{len(r.escenas)} escenas, {len(r.pares)} pares", "0 escenas")
    except bus.ErrorBusqueda as e:
        inf.agregar("RED-01", "ASF", "Consulta REAL al catálogo de ASF", "Responde con escenas", IMPORTANTE,
                    FALLIDA, str(e))


def rtc_locales(inf: Informe) -> None:
    from utils.flujo_sar import CARPETA_SAR, rtc_locales as listar
    rtcs, avisos = listar(CARPETA_SAR)
    inf.agregar("SAR-01", "Datos reales", "Productos RTC en data/sar/ para Herramientas SAR",
                "Informativo", INFORMATIVO, APROBADA if rtcs else OMITIDA,
                f"{len(rtcs)} RTC asociables" + (f"; {len(avisos)} aviso(s): " + "; ".join(avisos[:3]) if avisos else ""))


def main(argumentos=None) -> int:
    p = argparse.ArgumentParser(description="Verificación integral de V.I.S.O.R.")
    p.add_argument("--ci", action="store_true", help="modo GitHub Actions: sin datos reales esperados")
    p.add_argument("--navegador", action="store_true", help="exigir las pruebas de navegador")
    p.add_argument("--sin-navegador", action="store_true", help="no intentar las pruebas de navegador")
    p.add_argument("--red", action="store_true", help="añadir una consulta REAL a ASF")
    p.add_argument("--sin-pytest", action="store_true", help="solo entorno, Git, app y datos (más rápido)")
    p.add_argument("--salida", type=Path, default=RAIZ / "informes")
    a = p.parse_args(argumentos)

    logging.getLogger("streamlit").setLevel(logging.ERROR)   # sin avisos de caché fuera de la app
    try:
        import streamlit.logger as registro_streamlit
        registro_streamlit.set_log_level("error")
    except (ImportError, AttributeError):
        pass
    from utils.config import DATA_DIR
    inf = Informe()
    inf.contexto.update({"Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "Python": platform.python_version(),
                         "Sistema": platform.platform(terse=True), "Datos": str(DATA_DIR),
                         "Modo": "GitHub Actions" if a.ci else "local"})
    antes = huellas(DATA_DIR)
    print(f"Verificando V.I.S.O.R. ({len(antes)} archivos en {DATA_DIR}, solo lectura)…", flush=True)

    inf.protegido("ENT-X", "Entorno", "Comprobación del entorno", entorno, inf)
    inf.protegido("GIT-X", "Git", "Estado de Git", estado_git, inf)
    if not a.sin_pytest:
        print("· pytest (unidad e integración)…", flush=True)
        inf.protegido("PYT-X", "Pruebas", "pytest: unidad e integración", pytest_, inf, "PYT-01",
                      "pytest: unidad e integración (sin navegador ni red)", "not navegador and not red", CRITICO, 1800)
        inf.protegido("LNT-X", "Calidad", "ruff", ruff, inf)
    if a.sin_navegador:
        inf.agregar("E2E-01", "Navegador", "Mission Control en Chromium (Playwright)", "0 fallidas", CRITICO,
                    OMITIDA, "desactivado con --sin-navegador")
    else:
        motivo = navegador_disponible()
        if motivo:
            inf.agregar("E2E-01", "Navegador", "Mission Control en Chromium (Playwright)", "0 fallidas", CRITICO,
                        FALLIDA if a.navegador else OMITIDA, motivo + ". GitHub Actions las ejecuta en cada push.")
        else:
            print("· navegador (Playwright)…", flush=True)
            inf.protegido("E2E-X", "Navegador", "Mission Control en Chromium", pytest_, inf, "E2E-01",
                          "Mission Control en Chromium (Playwright)", "navegador", CRITICO, 2400)
    if a.red:
        print("· consulta real a ASF…", flush=True)
        inf.protegido("RED-X", "ASF", "Consulta real a ASF", asf_real, inf)
    print("· aplicación con los datos reales…", flush=True)
    inf.protegido("APP-X", "Aplicación", "Arranque con los datos reales", app_real, inf)
    print("· datos reales…", flush=True)
    referencia = leer_referencia(RAIZ / "tests" / "datos" / "referencia_chigorodo.json")
    inf.protegido("DAT-X", "Datos reales", "Auditoría de data/analisis/", auditar_resultados,
                  inf, DATA_DIR / "analisis", None if a.ci else referencia)
    inf.protegido("SAR-X", "Datos reales", "RTC en data/sar/", rtc_locales, inf)

    cambios = diferencias_huellas(antes, huellas(DATA_DIR))
    inf.si(not cambios, "DAT-RO", "Datos reales", "Ningún archivo de data/ cambió durante la verificación",
           "Huellas idénticas antes y después", CRITICO, f"{len(antes)} archivos intactos", "; ".join(cambios[:20]))

    a.salida.mkdir(parents=True, exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    md, js = a.salida / f"verificacion_{sello}.md", a.salida / f"verificacion_{sello}.json"
    md.write_text(inf.a_markdown(), encoding="utf-8")
    js.write_text(inf.a_json(), encoding="utf-8")
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write(inf.a_markdown())

    n = inf.conteo()
    print(f"\nVEREDICTO: {inf.veredicto}  ({n[APROBADA]} aprobadas · {n[FALLIDA]} fallidas · "
          f"{n[ADVERTENCIA]} advertencias · {n[OMITIDA]} omitidas)")
    for c in inf.comprobaciones:
        if c.estado in (FALLIDA, ADVERTENCIA):
            print(f"  {c.estado:<11} {c.id:<9} {c.descripcion}: {c.detalle[:160]}")
    print(f"\nInforme: {md.relative_to(RAIZ) if md.is_relative_to(RAIZ) else md}")
    return 1 if inf.veredicto == NO_APTO else 0


if __name__ == "__main__":
    importlib.invalidate_caches()
    sys.exit(main())
