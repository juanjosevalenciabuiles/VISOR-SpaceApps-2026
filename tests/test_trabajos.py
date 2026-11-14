"""Registro persistente de trabajos, ejecución en segundo plano, procesadores y diagnóstico.

Los hilos son reales (no se usa el modo síncrono). Los RTC son SINTÉTICOS (ver test_flujo_sar).
"""
import json
import sys
import threading
import time
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from tests.test_flujo_sar import buscar_sin_red, rtc  # noqa: E402
from utils import diagnostico, ejecucion_sar, flujo_sar, mapas_base, procesadores, sesion, trabajos  # noqa: E402
from utils.config import AOI_CHIGORODO  # noqa: E402

PARAMS = {"VV": {"umbral_disminucion_db": 3.0, "ventana_speckle": 1},
          "VH": {"umbral_disminucion_db": 3.0, "ventana_speckle": 1}}


@pytest.fixture(autouse=True)
def almacen(tmp_path, monkeypatch):
    monkeypatch.setenv("VISOR_TRABAJOS_DIR", str(tmp_path / "trabajos"))
    yield tmp_path / "trabajos"


def _nuevo(run_id="r1", **extra):
    return trabajos.crear(run_id, {"tipo": "prueba", **extra}, {"zona": "z", "escenas": "e"})


def _por_fase(t):
    return {f["clave"]: f["estado"] for f in t["fases"]}


# ---------------------------------------------------------------------------
# Registro y ejecución
# ---------------------------------------------------------------------------

def test_registro_persistente_y_atomico(almacen):
    t = _nuevo(aoi={"crs": "EPSG:4326"})
    ruta = almacen / f"{t['job_id']}.json"
    guardado = json.loads(ruta.read_text("utf-8"))
    assert guardado["estado"] == "PENDIENTE" and guardado["run_id"] == "r1" and guardado["aoi"]["crs"] == "EPSG:4326"
    assert _por_fase(guardado)["zona"] == "APTO" and _por_fase(guardado)["calculo"] == "PENDIENTE"
    assert [f["nombre"] for f in guardado["fases"]] == ["Zona definida", "Buscando escenas", "Verificando datos",
                                                        "Preparando datos", "Calculando", "Verificando", "Listo"]
    assert not list(almacen.glob("*.tmp")), "sin temporales a medias"
    assert trabajos.leer("../../etc/passwd") is None, "un identificador con rutas no se abre"
    with pytest.raises(ValueError):
        trabajos.guardar({"job_id": "../x"})


def test_ejecucion_en_segundo_plano_no_bloquea_y_termina_apto():
    t = _nuevo()
    soltar = threading.Event()

    def funcion(ctx):
        ctx.fase("datos", trabajos.EN_CURSO, "esperando")
        soltar.wait(5)
        ctx.fase("datos", trabajos.APTO, "ok")

    inicio = time.monotonic()
    trabajos.lanzar(t["job_id"], funcion, sincrono=False)
    assert time.monotonic() - inicio < 1, "lanzar no espera al cálculo"
    time.sleep(0.3)
    en_marcha = trabajos.leer(t["job_id"])
    assert en_marcha["estado"] == "EN CURSO" and _por_fase(en_marcha)["datos"] == "EN CURSO"
    soltar.set()
    fin = trabajos.esperar(t["job_id"], 10)
    assert fin["estado"] == "APTO" and _por_fase(fin)["listo"] == "APTO" and fin["terminado_utc"]


def test_un_trabajo_no_se_lanza_dos_veces():
    t = _nuevo()
    llamadas = []
    soltar = threading.Event()

    def funcion(ctx):
        llamadas.append(1)
        soltar.wait(5)

    trabajos.lanzar(t["job_id"], funcion, sincrono=False)
    trabajos.lanzar(t["job_id"], funcion, sincrono=False)
    assert trabajos.activo_con_run_id("r1")["job_id"] == t["job_id"], "la misma huella se reutiliza"
    soltar.set()
    trabajos.esperar(t["job_id"], 10)
    assert llamadas == [1]


def test_cola_cancelacion_en_cola_y_en_curso():
    primero, segundo = _nuevo("a"), _nuevo("b")
    soltar = threading.Event()

    def lento(ctx):
        ctx.fase("calculo", trabajos.EN_CURSO, "paso 1")
        while not soltar.is_set():
            time.sleep(0.05)
            ctx.comprobar("paso 2")

    trabajos.lanzar(primero["job_id"], lento, sincrono=False)
    time.sleep(0.2)
    trabajos.lanzar(segundo["job_id"], lento, sincrono=False)
    time.sleep(0.6)
    en_cola = trabajos.leer(segundo["job_id"])
    assert en_cola["estado"] == "PENDIENTE" and en_cola.get("en_cola"), "con un cupo, el segundo espera"
    assert trabajos.cancelar(segundo["job_id"])
    assert trabajos.esperar(segundo["job_id"], 5)["estado"] == "CANCELADO"
    assert trabajos.cancelar(primero["job_id"])
    fin = trabajos.esperar(primero["job_id"], 5)
    assert fin["estado"] == "CANCELADO" and _por_fase(fin)["calculo"] == "CANCELADO" and fin["cancelacion_pedida"]
    assert not trabajos.cancelar(primero["job_id"]), "un trabajo terminado no se cancela"


def test_limite_de_tiempo_y_errores_quedan_registrados():
    t = trabajos.crear("lento", {"limite_s": 1})
    t["limite_s"] = 1
    trabajos.guardar(t)

    def lento(ctx):
        for _ in range(100):
            time.sleep(0.05)
            ctx.comprobar("bucle")

    trabajos.lanzar(t["job_id"], lento, sincrono=False)
    fin = trabajos.esperar(t["job_id"], 10)
    assert fin["estado"] == "ERROR" and "límite de 1 s" in fin["error"]

    roto = _nuevo("roto")

    def falla(ctx):
        ctx.fase("datos", trabajos.EN_CURSO)
        raise RuntimeError("disco desconectado")

    trabajos.lanzar(roto["job_id"], falla, sincrono=False)
    fin = trabajos.esperar(roto["job_id"], 5)
    assert fin["estado"] == "ERROR" and "RuntimeError: disco desconectado" in fin["error"]
    assert _por_fase(fin)["datos"] == "ERROR"


def test_reinicio_del_servidor_marca_interrumpido_y_se_reintenta(almacen):
    t = _nuevo()
    datos = json.loads((almacen / f"{t['job_id']}.json").read_text("utf-8"))
    datos.update(estado="EN CURSO", proceso="otro-proceso")
    datos["fases"][4]["estado"] = "EN CURSO"
    (almacen / f"{t['job_id']}.json").write_text(json.dumps(datos), "utf-8")
    leido = trabajos.leer(t["job_id"])
    assert leido["estado"] == "ERROR" and "se reinició" in leido["error"] and _por_fase(leido)["calculo"] == "ERROR"

    otra = trabajos.reintentar(t["job_id"], lambda ctx: None, sincrono=True)
    assert otra["estado"] == "APTO" and otra["intentos"] == 2
    assert otra["historial_intentos"][0]["estado"] == "ERROR"
    assert _por_fase(otra)["zona"] == "APTO", "las fases de interfaz se conservan"
    with pytest.raises(ValueError):
        trabajos.reintentar(t["job_id"], lambda ctx: None)


def test_listar_ordena_por_fecha():
    a = _nuevo("a")
    time.sleep(1.1)
    b = _nuevo("b")
    assert [t["job_id"] for t in trabajos.listar()][:2] == [b["job_id"], a["job_id"]]


# ---------------------------------------------------------------------------
# Trabajo Sentinel-1 con RTC (sintéticos): fases reales y huellas
# ---------------------------------------------------------------------------

@pytest.fixture
def par_y_disponibles(tmp_path):
    sar = tmp_path / "sar"
    sar.mkdir()
    for pol in ("VV", "VH"):
        rtc(sar, "20260924T232218", pol)
        rtc(sar, "20261006T232218", pol, baja=(10, 30))
    par = buscar_sin_red().recomendado
    rtcs, _ = flujo_sar.rtc_locales(sar)
    return par, flujo_sar.disponibilidad(par, rtcs)


def test_tarea_sentinel1_en_segundo_plano_con_fases_y_sha256(tmp_path, par_y_disponibles):
    par, disp = par_y_disponibles
    salida = tmp_path / "analisis"
    rid = sesion.run_id(AOI_CHIGORODO, par.antes.nombre, par.despues.nombre, PARAMS)
    t = _nuevo(rid)
    trabajos.lanzar(t["job_id"], ejecucion_sar.tarea_cambio_s1(par, disp, AOI_CHIGORODO, PARAMS, False, rid, salida),
                    sincrono=False)
    fin = trabajos.esperar(t["job_id"], 120)
    assert fin["estado"] == "APTO", fin["error"]
    assert set(_por_fase(fin).values()) == {"APTO"}
    fases = {f["clave"]: f for f in fin["fases"]}
    assert "4 RTC legibles que cubren la zona" in fases["datos"]["detalle"] and "EPSG:32618" in fases["datos"]["detalle"]
    assert "RTC existentes" in fases["preparacion"]["detalle"] and "no se reprocesan" in fases["preparacion"]["detalle"]
    assert fin["principal"].startswith("coincidencia_VV_VH_")
    for a in fin["archivos"]:
        assert trabajos.sha256(salida / a["nombre"]) == a["sha256"] and a["bytes"] > 0
    assert fin["registro"] in {a["nombre"] for a in fin["archivos"]}


def test_tarea_zona_fuera_de_la_imagen_falla_en_verificar_datos(tmp_path, par_y_disponibles):
    par, disp = par_y_disponibles
    lejos = (-75.5, 6.1, -75.3, 6.3)   # Medellín: los RTC sintéticos de Chigorodó no la cubren
    t = _nuevo("lejos")
    trabajos.lanzar(t["job_id"], ejecucion_sar.tarea_cambio_s1(par, disp, lejos, PARAMS, False, "lejos",
                                                               tmp_path / "a"), sincrono=True)
    fin = trabajos.leer(t["job_id"])
    assert fin["estado"] == "ERROR" and "no cubre la zona" in fin["error"]
    assert _por_fase(fin)["datos"] == "ERROR" and _por_fase(fin)["calculo"] == "PENDIENTE"
    assert not (tmp_path / "a").exists() or not any((tmp_path / "a").iterdir()), "nada escrito"


def test_tarea_cancelada_entre_polarizaciones_deja_parciales_anotados(tmp_path, par_y_disponibles, monkeypatch):
    par, disp = par_y_disponibles
    t = _nuevo("cancelar")
    original = flujo_sar.analizar_disponibles

    def con_pausa(*a, al_avanzar=None, **k):
        def avanzar(paso, hechos):
            if hechos:                       # tras la primera polarización, alguien pulsa «Cancelar»
                trabajos.cancelar(t["job_id"])
            al_avanzar(paso, hechos)
        return original(*a, al_avanzar=avanzar, **k)

    monkeypatch.setattr(flujo_sar, "analizar_disponibles", con_pausa)
    trabajos.lanzar(t["job_id"], ejecucion_sar.tarea_cambio_s1(par, disp, AOI_CHIGORODO, PARAMS, False, "cancelar",
                                                               tmp_path / "a"), sincrono=False)
    fin = trabajos.esperar(t["job_id"], 120)
    assert fin["estado"] == "CANCELADO" and _por_fase(fin)["calculo"] == "CANCELADO"
    assert fin["parciales"] and not fin["principal"], "lo escrito queda anotado y no se publica"


# ---------------------------------------------------------------------------
# Procesadores
# ---------------------------------------------------------------------------

def test_procesadores_declaran_su_estado_real(monkeypatch):
    monkeypatch.delenv("VISOR_SNAP_WORKER", raising=False)
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.delenv("EDL_TOKEN", raising=False)
    snap = procesadores.diagnostico_snap()
    assert snap.estado == "NO DISPONIBLE" and "worker" in snap.motivo
    assert [c[0] for c in snap.comprobaciones][:3] == ["Worker aislado (VISOR_SNAP_WORKER)", "Ejecutable gpt de SNAP",
                                                       "Java"]
    with pytest.raises(procesadores.NoDisponible):
        procesadores.ejecutar_snap()
    with pytest.raises(procesadores.NoDisponible):
        procesadores.elegir(tiene_rtc=False)
    assert procesadores.elegir(tiene_rtc=True).clave == "rtc"
    nisar = procesadores.diagnostico_nisar()
    assert nisar.estado == "NO DISPONIBLE" and "token earthdata" in nisar.motivo.lower()
    assert procesadores.diagnostico_hyp3().estado == "DESHABILITADO"


def test_token_earthdata_nunca_se_muestra(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "secreto-que-no-debe-salir")
    d = procesadores.diagnostico_nisar()
    assert "secreto" not in repr(d) and ("Token Earthdata en el entorno", True, "presente (no se muestra)") in d.comprobaciones


def test_snap_con_worker_sigue_sin_enviar_trabajos(monkeypatch):
    monkeypatch.setenv("VISOR_SNAP_WORKER", "https://worker.invalid")
    d = procesadores.diagnostico_snap()
    assert d.estado == "NO DISPONIBLE" and "no se envían trabajos" in d.motivo


def test_grafo_snap_rtc_gamma0():
    xml = procesadores.grafo_grd_a_rtc("S1C_IW_GRDH.zip", "salida.tif")
    raiz = ET.fromstring(xml)
    ops = [n.findtext("operator") for n in raiz.iter("node")]
    assert ops == ["Read", "Apply-Orbit-File", "ThermalNoiseRemoval", "Calibration", "Terrain-Flattening",
                   "Speckle-Filter", "Terrain-Correction", "Write"]
    cal = next(n for n in raiz.iter("node") if n.findtext("operator") == "Calibration")
    assert cal.find("parameters/outputBetaBand").text == "true", "Terrain-Flattening exige beta0"
    tc = next(n for n in raiz.iter("node") if n.findtext("operator") == "Terrain-Correction")
    assert tc.find("parameters/mapProjection").text == "AUTO:42001", "UTM automática, no EPSG:32618 fijo"
    assert "LinearToFromdB" not in xml, "el motor espera potencia, no dB"
    assert procesadores.comando_gpt(Path("g.xml"), 2, 4) == ["gpt", "g.xml", "-q", "2", "-c", "4G", "-e"]


# ---------------------------------------------------------------------------
# Diagnóstico de servicios
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, cuerpo, tipo="image/png", status=200):
        self.cuerpo, self.status, self.headers = cuerpo, status, {"Content-Type": tipo}

    def read(self, *_):
        return self.cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _red(fallos: dict[str, Exception]):
    vistos = []

    def abrir(peticion, timeout):
        url = peticion.full_url
        vistos.append((url, peticion.get_header("User-agent")))
        for trozo, exc in fallos.items():
            if trozo in url:
                raise exc
        if "asf" in url:
            return _Resp(b"123", "text/plain")
        if "status" in url or "earthdata" in url:
            return _Resp(b'{"status":0,"message":"OK"}', "application/json")
        return _Resp(b"\x89PNG\r\n\x1a\n" + b"0" * 10)
    return abrir, vistos


def test_diagnostico_todo_responde(monkeypatch):
    monkeypatch.delenv("CARTO_API_KEY", raising=False)
    monkeypatch.delenv("VISOR_GEOCODIFICADOR_URL", raising=False)
    abrir, vistos = _red({})
    estados = {e.clave: e.estado for e in diagnostico.comprobar(abrir)}
    assert estados["base:osm_oscuro"] == "APTO" and estados["base:satelital"] == "APTO"
    assert estados["base:carto_oscuro"] == "NO COMPROBADO", "sin clave no se pide nada a CARTO"
    assert estados["lugares"] == estados["asf"] == estados["earthdata"] == "APTO"
    assert all("VISOR-SpaceApps-2026" in ua for _, ua in vistos)
    assert not any("cartocdn" in u for u, _ in vistos)
    assert mapas_base.no_ofrecidos().keys() == {"carto_oscuro", "carto_voyager", "carto_positron"}


def test_diagnostico_fondo_caido_deja_de_ofrecerse_y_se_elige_otro(monkeypatch):
    monkeypatch.delenv("CARTO_API_KEY", raising=False)
    abrir, _ = _red({"tile.openstreetmap.org": urllib.error.HTTPError("u", 429, "x", {}, None),
                     "opentopomap": urllib.error.URLError(TimeoutError()),
                     "nominatim": urllib.error.HTTPError("u", 403, "x", {}, None)})
    try:
        estados = {e.clave: (e.estado, e.detalle) for e in diagnostico.comprobar(abrir)}
        assert estados["base:osm_oscuro"] == ("ERROR", "demasiadas peticiones (429)")
        assert estados["base:topografico"][0] == "ERROR" and "tiempo agotado" in estados["base:topografico"][1]
        assert estados["lugares"] == ("ERROR", "acceso denegado (403)")
        assert mapas_base.ofrecidos() == ["satelital"] and mapas_base.predeterminado() == "satelital"
        assert "429" in mapas_base.no_ofrecidos()["calles"]
    finally:
        mapas_base.registrar_caidos({})
    assert "osm_oscuro" in mapas_base.ofrecidos()


def test_diagnostico_no_filtra_la_clave_de_carto(monkeypatch):
    clave = "a" * 32
    monkeypatch.setenv("CARTO_API_KEY", clave)
    abrir, vistos = _red({"cartocdn": urllib.error.HTTPError("u", 401, "x", {}, None)})
    try:
        resultados = diagnostico.comprobar(abrir)
        assert any("cartocdn" in u for u, _ in vistos)
        assert clave not in repr(resultados)
        assert dict((e.clave, e.detalle) for e in resultados)["base:carto_oscuro"] == "requiere credenciales (401)"
    finally:
        mapas_base.registrar_caidos({})


def test_diagnostico_en_segundo_plano_respeta_la_desactivacion(monkeypatch):
    monkeypatch.setenv("VISOR_DIAGNOSTICO", "desactivado")
    assert diagnostico.comprobar_en_segundo_plano() is False


# ---------------------------------------------------------------------------
# En la app (AppTest)
# ---------------------------------------------------------------------------

def test_app_sin_rtc_fases_bloqueadas_filtro_y_estado_del_sistema(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from tests.test_flujo_sar import REAL, confirmar_zona
    from utils import buscador_sar as bus
    from utils import resultados
    sar = tmp_path / "sar"
    sar.mkdir()
    monkeypatch.setattr(bus, "consultar_asf", lambda parametros, **k: REAL)
    monkeypatch.setattr(flujo_sar, "CARPETA_SAR", sar)
    monkeypatch.setattr(flujo_sar, "CARPETA_ANALISIS", tmp_path / "analisis")
    monkeypatch.setattr(resultados, "CARPETA_ANALISIS", tmp_path / "analisis")
    monkeypatch.chdir(RAIZ)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180).run()
    texto = " ".join(m.value for m in at.markdown)
    assert 'id="tabla-procesadores"' in texto and "SNAP gpt" in texto and "NO DISPONIBLE" in texto
    assert "DESHABILITADO" in texto and "VISOR_DIAGNOSTICO=desactivado" in texto
    at.button(key="btn_sar").click().run()
    confirmar_zona(at)
    at.button(key="sar_buscar").click().run()
    at.radio(key="sar_filtro_pares").set_value("Usadas").run()
    texto = " ".join(m.value for m in at.markdown)
    assert "Ningún par de esta zona se ha analizado todavía" in texto
    at.radio(key="sar_filtro_pares").set_value("Todas").run()
    assert len(at.selectbox(key="sar_par").options) == 6
    texto = " ".join(m.value for m in at.markdown)
    assert 'mc-fase-datos" data-estado="BLOQUEADO"' in texto and 'mc-fase-zona" data-estado="APTO"' in texto
    assert 'mc-fase-calculo" data-estado="PENDIENTE"' in texto and "ninguno está disponible" in texto
    assert at.button(key="sar_analizar").disabled and trabajos.listar() == []


def test_crear_o_reutilizar_es_idempotente_entre_hilos():
    soltar = threading.Event()
    creados = []

    def funcion(ctx):
        soltar.wait(5)

    def pulsar():
        creados.append(trabajos.crear_o_reutilizar("misma", {"tipo": "prueba"}, funcion))

    hilos = [threading.Thread(target=pulsar) for _ in range(6)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert len({t["job_id"] for t, _ in creados}) == 1 and sum(c for _, c in creados) == 1
    soltar.set()
    assert trabajos.esperar(creados[0][0]["job_id"], 10)["estado"] == "APTO"
