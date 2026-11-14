"""Pruebas de navegador de Mission Control (Playwright + Chromium).

Cada sesión arranca la app real (`streamlit run app.py`) sobre una COPIA
temporal de los datos (VISOR_DATA_DIR): capas demostrativas de data/, más
resultados y RTC sintéticos. data/ del repositorio nunca se toca.

Sin red: ASF se sustituye por su respuesta real guardada (VISOR_ASF_SIMULADO,
la app lo rotula «CATÁLOGO SIMULADO») y las teselas de mapa por una tesela gris.
Leaflet y jQuery se cargan de Internet; donde no hay salida (p. ej. una caja
de pruebas) se pueden servir locales con VISOR_E2E_RECURSOS=<carpeta con
leaflet/dist y jquery/dist>.

Si Playwright o Chromium no están, todas se omiten (Replit sin
requirements-dev.txt). En GitHub Actions corren siempre.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

if os.environ.get("VISOR_E2E_EXIGIR") == "1" or os.environ.get("CI") == "true":
    from playwright import sync_api      # en CI, sin Playwright la recolección falla (no se omite)
else:
    sync_api = pytest.importorskip("playwright.sync_api")

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))
CATALOGO = RAIZ / "tests" / "datos" / "asf_chigorodo_20260920_20261010.json"
RECURSOS = os.environ.get("VISOR_E2E_RECURSOS")
CAPTURAS = RAIZ / "informes" / "e2e"


def pytest_collection_modifyitems(items):
    for item in items:
        if "e2e" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.navegador)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    resultado = yield
    informe = resultado.get_result()
    setattr(item, f"rep_{informe.when}", informe)


# ---------------------------------------------------------------------------
# Datos y servidor
# ---------------------------------------------------------------------------

def preparar_datos(destino: Path) -> Path:
    """Copia de las capas demostrativas + resultados y RTC sintéticos."""
    from test_flujo_sar import rtc
    from test_resultados import exploratorio, reproducible

    destino.mkdir(parents=True, exist_ok=True)
    for p in (RAIZ / "data").glob("*"):
        if p.is_file() and p.suffix.lower() in (".tif", ".json"):
            shutil.copy2(p, destino / p.name)
    if (RAIZ / "data" / "contexto").is_dir():
        shutil.copytree(RAIZ / "data" / "contexto", destino / "contexto", dirs_exist_ok=True)
    analisis = destino / "analisis"
    analisis.mkdir(exist_ok=True)
    exploratorio(analisis / "coincidencia_VV_VH_Chigorodo.tif")
    reproducible(analisis)                     # coincidencia_VV_VH_20260924_20261006.tif + .json
    sar = destino / "sar"
    sar.mkdir(exist_ok=True)
    for pol, baja in (("VV", (10, 20)), ("VH", (15, 30))):
        rtc(sar, "20260924T232218", pol)
        rtc(sar, "20261006T232218", pol, baja=baja, ident="3C4D")
    # Diferencia continua en dB generada por el motor (como cambio_VV_…_dif_db.tif en Replit).
    from utils.analisis_sar import ParametrosCambio, analizar_par
    temporal = destino.parent / "motor_tmp"
    r = analizar_par(sar / "S1C_IW_20260924T232218_DVP_RTC30_G_gpuned_1A2B_VV.tif",
                     sar / "S1C_IW_20261006T232218_DVP_RTC30_G_gpuned_3C4D_VV.tif", temporal,
                     parametros=ParametrosCambio(ventana_speckle=1))
    for p in (r.diferencia, r.diferencia.with_suffix(".json")):
        shutil.copy2(p, analisis / p.name)
    return destino


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Servidor:
    def __init__(self, datos: Path, entorno_extra: dict | None = None):
        self.datos = datos
        self.puerto = _puerto_libre()
        self.url = f"http://localhost:{self.puerto}"
        # Sin red en las pruebas: la búsqueda de lugares usa solo el catálogo local.
        # Servidor real: el análisis corre en segundo plano (sin VISOR_TRABAJOS_SINCRONOS) y sus trabajos
        # se registran en la carpeta temporal de esta prueba.
        entorno = {**os.environ, "VISOR_DATA_DIR": str(datos), "VISOR_ASF_SIMULADO": str(CATALOGO),
                   "VISOR_GEOCODIFICADOR_URL": "desactivado", "VISOR_TRABAJOS_SINCRONOS": "0",
                   "VISOR_TRABAJOS_DIR": str(datos / "trabajos"), "VISOR_DIAGNOSTICO": "desactivado",
                   **(entorno_extra or {})}
        entorno = {k: v for k, v in entorno.items() if v is not None}   # None = quitar la variable
        self.registro = open(datos.parent / f"streamlit_{self.puerto}.log", "w")
        self.proceso = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(self.puerto),
             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
            cwd=RAIZ, env=entorno, stdout=self.registro, stderr=subprocess.STDOUT)
        limite = time.time() + 90
        while time.time() < limite:
            try:
                with urllib.request.urlopen(f"{self.url}/_stcore/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except OSError:
                time.sleep(0.5)
        self.cerrar()
        raise RuntimeError("Streamlit no arrancó en 90 s")

    def cerrar(self):
        self.proceso.terminate()
        try:
            self.proceso.wait(15)
        except subprocess.TimeoutExpired:
            self.proceso.kill()
        self.registro.close()


# Motor del navegador: chromium (predeterminado), firefox o webkit.
NAVEGADOR = os.environ.get("VISOR_E2E_NAVEGADOR", "chromium").strip().lower()
# En GitHub Actions (CI=true) o con VISOR_E2E_EXIGIR=1, un navegador que no
# arranca es un FALLO: nunca se omiten en silencio todas las pruebas.
EXIGIR = os.environ.get("VISOR_E2E_EXIGIR") == "1" or os.environ.get("CI") == "true"


@pytest.fixture(scope="session")
def navegador():
    if NAVEGADOR not in ("chromium", "firefox", "webkit"):
        pytest.fail(f"VISOR_E2E_NAVEGADOR={NAVEGADOR!r} no es chromium, firefox ni webkit")
    with sync_api.sync_playwright() as p:
        try:
            b = getattr(p, NAVEGADOR).launch()
        except Exception as e:  # noqa: BLE001
            mensaje = f"{NAVEGADOR} no disponible: {str(e).splitlines()[0][:200]}"
            if EXIGIR:
                pytest.fail(mensaje)
            pytest.skip(mensaje)
        yield b
        b.close()


@pytest.fixture(scope="session")
def servidor(tmp_path_factory):
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("visor") / "data"))
    yield s
    s.cerrar()


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

def _tesela() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), (40, 44, 52)).save(buf, "PNG")
    return buf.getvalue()


TESELA = None
TESELA_RE = re.compile(r"(\.(png|jpe?g|webp)$)|(/tile/\d+/\d+/\d+$)|(/\d+/\d+/\d+$)")


def enrutar(route):
    global TESELA
    url = route.request.url.split("?")[0]
    if RECURSOS and "spritesheet" in url:                       # iconos de las herramientas de dibujo
        return route.fulfill(path=str(Path(RECURSOS) / "leaflet-draw/dist/images" / url.rsplit("/", 1)[-1]))
    if TESELA_RE.search(url):
        TESELA = TESELA or _tesela()
        return route.fulfill(body=TESELA, content_type="image/png")
    if not RECURSOS:
        return route.continue_()
    base = Path(RECURSOS)
    if "leaflet.fullscreen" in url or "Control.FullScreen" in url:
        archivo = "Control.FullScreen.css" if url.endswith(".css") else (
            "icon-fullscreen.svg" if url.endswith(".svg") else "Control.FullScreen.js")
        return route.fulfill(path=str(base / "leaflet.fullscreen" / archivo))
    for nombre, ruta in (("leaflet.draw.js", "leaflet-draw/dist/leaflet.draw.js"),
                         ("leaflet.draw.css", "leaflet-draw/dist/leaflet.draw.css"),
                         ("leaflet.js", "leaflet/dist/leaflet.js"), ("leaflet.css", "leaflet/dist/leaflet.css")):
        if url.endswith(nombre):
            return route.fulfill(path=str(base / ruta))
    if "jquery" in url and url.endswith(".js"):
        return route.fulfill(path=str(base / "jquery/dist/jquery.min.js"))
    if url.endswith(".js"):
        return route.fulfill(body="", content_type="application/javascript")
    if url.endswith(".css"):
        return route.fulfill(body="", content_type="text/css")
    return route.abort()


class Pagina:
    """Página de Mission Control cargada, con ayudas para el mapa y los paneles."""

    def __init__(self, page, url: str, red_real: bool = False):
        self.page = page
        self.errores: list[str] = []
        page.on("pageerror", lambda e: self.errores.append(str(e)))
        if not red_real:      # por defecto, teselas y recursos externos simulados (sin red)
            page.route(re.compile(r"https?://(?!localhost|127\.0\.0\.1).*"), enrutar)
        page.goto(url)
        self.esperar_mapa()
        page.locator(".st-key-barra_superior").wait_for(timeout=60_000)

    @property
    def mapa(self):
        for f in self.page.frames:
            if "streamlit_folium" in f.url:
                return f
        raise AssertionError("No está el marco del mapa")

    def esperar_mapa(self, segundos: int = 90):
        limite = time.time() + segundos
        while time.time() < limite:
            try:
                if self.mapa.evaluate("()=>typeof map!=='undefined' && !!map.getZoom"):
                    self.page.wait_for_timeout(600)
                    return
            except Exception:  # noqa: BLE001 — el marco aún se está creando
                pass
            self.page.wait_for_timeout(500)
        raise AssertionError("El mapa no cargó")

    def esperar(self, ms: int = 2500):
        """Espera a que Streamlit termine la ejecución en curso."""
        self.page.wait_for_timeout(400)
        try:
            self.page.locator("[data-testid=stStatusWidget]").wait_for(state="detached", timeout=60_000)
        except Exception:  # noqa: BLE001
            pass
        self.page.wait_for_timeout(ms)

    def marcar_mapa(self):
        self.mapa.evaluate("()=>{window.__marca_e2e = 7}")

    def mapa_intacto(self) -> bool:
        return self.mapa.evaluate("()=>window.__marca_e2e") == 7

    def vista(self):
        return self.mapa.evaluate("()=>[map.getZoom(), +map.getCenter().lat.toFixed(4), +map.getCenter().lng.toFixed(4)]")

    def clic(self, clave: str):
        self.page.locator(f".st-key-{clave} button:visible").first.click()
        self.esperar()

    def analizar(self, segundos: int = 180) -> str:
        """Pulsa «Analizar» y espera a que el trabajo (en segundo plano) termine y se publique."""
        leer = "()=>{const e=document.querySelector('#trabajo-estado');return e?[e.dataset.estado,e.dataset.job]:[null,null]}"
        anterior = self.page.evaluate(leer)[1]
        self.clic("sar_analizar")
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            estado, job = self.page.evaluate(leer)
            if job and job != anterior and estado in ("APTO", "ERROR", "CANCELADO", "BLOQUEADO"):
                self.esperar(1500)
                return estado
            self.page.wait_for_timeout(500)
        raise AssertionError("el trabajo no terminó a tiempo")

    def alternar(self, clave: str):
        self.page.locator(f".st-key-{clave} label").first.click()
        self.esperar()

    def visible(self, clave: str) -> bool:
        return self.page.locator(f".st-key-{clave}").first.is_visible()

    def texto(self, clave: str) -> str:
        return self.page.locator(f".st-key-{clave}").first.inner_text()

    # --- Recorrido: resultados, historial, DEMO y zona -------------------------------------

    def capas_resultado(self) -> list[dict]:
        """Rásteres superpuestos en el mapa (resultados o DEMO). Al abrir la app debe ser []."""
        return self.mapa.evaluate("()=>[...document.querySelectorAll('img.leaflet-image-layer')]"
                                  ".map(i=>({op:+getComputedStyle(i).opacity, src:i.src}))")

    def trazos(self) -> int:
        return self.mapa.evaluate("()=>document.querySelectorAll('path.leaflet-interactive').length")

    def expandir(self, clave: str):
        cab = self.page.locator(f".st-key-{clave} summary").first
        cab.scroll_into_view_if_needed()
        if self.page.locator(f".st-key-{clave} details").first.get_attribute("open") is None:
            cab.click()
            self.page.wait_for_timeout(500)

    def ver_historico(self, id_resultado: str):
        self.expandir("historial")
        boton = self.page.locator(f".st-key-hist_ver_{id_resultado} button").first
        boton.scroll_into_view_if_needed()
        boton.click()
        self.esperar()

    def demo(self, fenomeno: str | None = None):
        """Enciende a propósito la capa DEMO (y, si se indica, cambia de fenómeno)."""
        self.expandir("demo")
        if not self.page.locator(".st-key-capa_sar input").first.is_checked():
            self.alternar("capa_sar")
        if fenomeno:
            self.page.locator(".st-key-fenomeno label").filter(has_text=fenomeno).first.click()
            self.esperar()

    def pestana_sar(self, n: int):
        self.page.locator(".st-key-panel_sar [role=tab]").nth(n).click()
        self.esperar(800)

    def escribir(self, clave: str, texto: str):
        campo = self.page.locator(f".st-key-{clave} input").first
        campo.scroll_into_view_if_needed()
        campo.fill(texto)
        campo.press("Enter")
        self.page.wait_for_timeout(400)

    def confirmar_zona(self, oeste="-76.80", sur="7.55", este="-76.55", norte="7.80"):
        """Abre Herramientas SAR y confirma una zona por coordenadas (ruta «Avanzado»)."""
        if not self.visible("panel_sar"):
            self.clic("btn_sar")
        self.pestana_sar(0)
        self.expandir("zona_avanzado")
        for clave, valor in (("sar_oeste", oeste), ("sar_sur", sur), ("sar_este", este), ("sar_norte", norte)):
            self.escribir(clave, valor)
        self.esperar(600)
        self.clic("zona_usar_coordenadas")

    def dibujar_rectangulo(self, x=640, y=330, ancho=120, alto=110):
        """Dibuja un rectángulo con la herramienta del mapa, como lo haría una persona."""
        marco = self.page.frame_locator("iframe[title*='streamlit_folium']").first
        marco.locator(".leaflet-draw-draw-rectangle").click()
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x + ancho, y + alto, steps=8)
        self.page.mouse.up()
        self.esperar(1200)

    def superposiciones(self) -> list[str]:
        cajas = self.page.evaluate("""()=>{const o={};for(const k of ['barra_superior','panel_explorador','panel_info',
          'linea_temporal','panel_sar','sar_minimizado']){const e=document.querySelector('.st-key-'+k);
          if(!e||getComputedStyle(e).display==='none') continue; const r=e.getBoundingClientRect();
          if(r.width&&r.height) o[k]=[r.left,r.top,r.right,r.bottom]} return o}""")
        cajas.update(self.mapa.evaluate("""()=>{const o={};for(const [k,s] of [['zoom','.leaflet-control-zoom'],
          ['escala','.leaflet-control-scale'],['atribucion','.leaflet-control-attribution']]){
          const e=document.querySelector(s); if(!e||getComputedStyle(e).display==='none') continue;
          const r=e.getBoundingClientRect(); if(r.width&&r.height) o[k]=[r.left,r.top,r.right,r.bottom]} return o}"""))
        nombres = list(cajas)
        return [f"{a}×{b}" for i, a in enumerate(nombres) for b in nombres[i + 1:]
                if cajas[a][0] < cajas[b][2] - 1 and cajas[b][0] < cajas[a][2] - 1
                and cajas[a][1] < cajas[b][3] - 1 and cajas[b][1] < cajas[a][3] - 1]


@pytest.fixture
def abrir(navegador, servidor, request):
    """abrir(ancho=1440, alto=900, movil=False) → Pagina. Captura si la prueba falla."""
    contextos = []

    def _abrir(ancho=1440, alto=900, movil=False, url=None, descargas=False):
        movilidad = {"is_mobile": movil} if NAVEGADOR != "firefox" else {}   # Firefox no emula is_mobile
        ctx = navegador.new_context(viewport={"width": ancho, "height": alto}, has_touch=movil,
                                    accept_downloads=descargas, **movilidad)
        contextos.append(ctx)
        return Pagina(ctx.new_page(), url or servidor.url)

    yield _abrir
    fallo = getattr(request.node, "rep_call", None)
    if fallo is not None and fallo.failed:
        CAPTURAS.mkdir(parents=True, exist_ok=True)
        for i, ctx in enumerate(contextos):
            for j, pg in enumerate(ctx.pages):
                try:
                    pg.screenshot(path=str(CAPTURAS / f"{request.node.name}_{i}{j}.png"))
                except Exception:  # noqa: BLE001
                    pass
    for ctx in contextos:
        ctx.close()
