"""Fase C: catálogo ASF → RTC locales → motor → resultados (sin red ni HyP3).

El catálogo es la respuesta real de ASF guardada en tests/datos/ (solo
metadatos). Los RTC son SINTÉTICOS, con nombres de HyP3 que derivan de las
escenas del par recomendado de Chigorodó.
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils import buscador_sar as bus  # noqa: E402
from utils import flujo_sar as flujo  # noqa: E402
from utils import procedencia  # noqa: E402
from utils.analisis_sar import ErrorSAR  # noqa: E402
from utils.config import AOI_CHIGORODO  # noqa: E402

REAL = json.loads((RAIZ / "tests" / "datos" / "asf_chigorodo_20260920_20261010.json").read_text(encoding="utf-8"))


def buscar_sin_red():
    """`buscar` completo, con la red sustituida por la respuesta guardada."""
    class Respuesta:
        def __init__(self, cuerpo):
            self.cuerpo = cuerpo

        def read(self):
            return self.cuerpo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return bus.buscar(-76.85, 7.40, -76.40, 7.95, "2026-09-20", "2026-10-10",
                      abrir=lambda *a, **k: Respuesta(json.dumps(REAL).encode()), hoy=date(2026, 11, 12))


def rtc(carpeta: Path, inicio: str, pol: str, baja: tuple[int, int] | None = None, ident="1A2B") -> Path:
    """RTC sintético (potencia, 300 m) que cubre el AOI de Chigorodó."""
    o, s, e, n = transform_bounds("EPSG:4326", "EPSG:32618", *AOI_CHIGORODO)
    lado = int((max(e - o, n - s) + 6000) // 300)
    datos = np.full((lado, lado), 0.1, dtype="float32")
    if baja:
        datos[baja[0]:baja[1]] = 0.01                               # −10 dB
    ruta = carpeta / f"S1C_IW_{inicio}_DVP_RTC30_G_gpuned_{ident}_{pol}.tif"
    with rasterio.open(ruta, "w", driver="GTiff", height=lado, width=lado, count=1, dtype="float32",
                       crs="EPSG:32618", transform=from_origin(o - 3000, n + 3000, 300, 300), nodata=0.0) as dst:
        dst.write(datos, 1)
    return ruta


@pytest.fixture
def par():
    r = buscar_sin_red()
    p = r.recomendado
    assert p.antes.inicio.strftime("%Y%m%dT%H%M%S") == "20260924T232218"
    assert p.despues.inicio.strftime("%Y%m%dT%H%M%S") == "20261006T232218"
    return p


def test_sin_rtc_se_informa_y_no_se_analiza(tmp_path, par):
    rtcs, avisos = flujo.rtc_locales(tmp_path / "no_existe")
    assert rtcs == [] and "No existe" in avisos[0]
    disp = flujo.disponibilidad(par, [])
    assert [d.polarizacion for d in disp] == ["VV", "VH"] and not any(d.completa for d in disp)
    with pytest.raises(ErrorSAR, match="faltan productos"):
        flujo.analizar_disponibles(par, disp, AOI_CHIGORODO, {"VV": 3, "VH": 3}, carpeta_salida=tmp_path)


def test_asociacion_exacta_por_dia_y_nunca_entre_satelites(tmp_path, par):
    sar = tmp_path / "sar"
    sar.mkdir()
    rtc(sar, "20260924T232218", "VV")
    rtc(sar, "20261006T232218", "VV")
    rtc(sar, "20260924T231000", "VH")                                 # mismo día, otra hora
    (sar / "otro_nombre.tif").write_bytes((sar / "S1C_IW_20260924T232218_DVP_RTC30_G_gpuned_1A2B_VV.tif").read_bytes())
    s1a = rtc(sar, "20261006T232218", "VH", ident="9999")
    s1a.rename(sar / s1a.name.replace("S1C_", "S1A_"))               # otro satélite: no vale
    rtcs, avisos = flujo.rtc_locales(sar)
    assert any(a.startswith("otro_nombre.tif") for a in avisos)          # se informa, no se asocia
    assert all(r.ruta.name != "otro_nombre.tif" for r in rtcs)
    vv, vh = flujo.disponibilidad(par, rtcs)
    assert vv.completa and (vv.tipo_antes, vv.tipo_despues) == (flujo.EXACTA, flujo.EXACTA)
    assert vh.tipo_antes == flujo.MISMO_DIA and vh.despues is None and not vh.completa


def test_flujo_completo_genera_resultados_sin_sobrescribir(tmp_path, par):
    sar, salida = tmp_path / "sar", tmp_path / "analisis"
    sar.mkdir()
    for pol, baja in (("VV", (10, 20)), ("VH", (15, 30))):
        rtc(sar, "20260924T232218", pol)
        rtc(sar, "20261006T232218", pol, baja=baja, ident="3C4D")
    # Un producto previo con el mismo nombre (como el del equipo en Replit) debe quedar intacto.
    salida.mkdir()
    previo = salida / "coincidencia_VV_VH_20260924_20261006.tif"
    previo.write_bytes(b"producto del equipo")
    huella = procedencia.sha256_archivo(previo)

    rtcs, _ = flujo.rtc_locales(sar)
    disp = flujo.disponibilidad(par, rtcs)
    inf = flujo.analizar_disponibles(par, disp, AOI_CHIGORODO, {"VV": 7.5, "VH": 3.0}, ventana_speckle=1,
                                     carpeta_salida=salida, zona="Prueba sintética")
    assert procedencia.sha256_archivo(previo) == huella
    assert inf.combinado.name == "coincidencia_VV_VH_20260924_20261006_r2.tif"
    assert set(inf.analisis) == {"VV", "VH"}

    ficha = json.loads(inf.combinado.with_suffix(".json").read_text(encoding="utf-8"))
    assert ficha["procedencia"]["estado"] == procedencia.REAL_SIN_VALIDAR
    assert ficha["parametros"]["VV"]["umbral_disminucion_db"] == 7.5
    assert ficha["parametros"]["VH"]["umbral_disminucion_db"] == 3.0
    registro = json.loads(inf.registro.read_text(encoding="utf-8"))
    assert registro["par_catalogo_asf"]["antes"]["nombre"].startswith("S1C_IW_GRDH_1SDV_20260924T232218")
    assert registro["par_catalogo_asf"]["validado_cientificamente"] is False
    assert registro["rtc"][0]["asociacion_antes"] == flujo.EXACTA
    assert registro["parametros"]["VV"]["umbral_disminucion_db"] == 7.5
    assert inf.combinado.name in registro["salidas"]

    # Una segunda ejecución tampoco sobrescribe: crea _r3.
    inf2 = flujo.analizar_disponibles(par, disp, AOI_CHIGORODO, {"VV": 3.0, "VH": 3.0}, ventana_speckle=1,
                                      carpeta_salida=salida)
    assert inf2.combinado.name.endswith("_r3.tif") and inf2.analisis["VV"].name.startswith("cambio_VV_20260924_20261006_r2")


def test_prefijo_libre(tmp_path):
    assert flujo.prefijo_libre(tmp_path, "a") == "a"
    (tmp_path / "a_mascara.tif").write_text("x")
    assert flujo.prefijo_libre(tmp_path, "a") == "a_r2"
    (tmp_path / "a_r2.json").write_text("x")
    assert flujo.prefijo_libre(tmp_path, "a") == "a_r3"


def confirmar_zona(at, limites=AOI_CHIGORODO, inicio=date(2026, 9, 20), fin=date(2026, 10, 10)):
    """Zona por la ruta «Avanzado» (coordenadas) y período fijo del caso de Chigorodó."""
    for clave, valor in zip(("sar_oeste", "sar_sur", "sar_este", "sar_norte"), limites, strict=True):
        at.text_input(key=clave).input(f"{valor:.4f}")
    at.date_input(key="sar_inicio").set_value(inicio)
    at.date_input(key="sar_fin").set_value(fin)
    at.button(key="zona_usar_coordenadas").click().run()
    assert at.session_state["zona"] is not None, at.session_state["error_zona"]
    return at


def test_app_busca_analiza_y_muestra_el_resultado(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from utils import resultados

    sar, salida = tmp_path / "sar", tmp_path / "analisis"
    sar.mkdir()
    for pol, baja in (("VV", (10, 20)), ("VH", (15, 30))):
        rtc(sar, "20260924T232218", pol)
        rtc(sar, "20261006T232218", pol, baja=baja, ident="3C4D")
    monkeypatch.setattr(bus, "consultar_asf", lambda parametros, **k: REAL)        # sin red
    monkeypatch.setattr(flujo, "CARPETA_SAR", sar)
    monkeypatch.setattr(flujo, "CARPETA_ANALISIS", salida)
    monkeypatch.setattr(resultados, "CARPETA_ANALISIS", salida)
    monkeypatch.chdir(RAIZ)

    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180).run()
    at.button(key="btn_sar").click().run()
    # Sin zona confirmada no hay región: nada se busca ni se analiza.
    assert at.text_input(key="sar_oeste").value in ("", None) and at.session_state["zona"] is None
    assert not any(b.key == "sar_buscar" for b in at.button)
    confirmar_zona(at)
    at.button(key="sar_buscar").click().run()
    assert not at.exception and at.session_state["sar_busqueda"] is not None
    par = at.selectbox(key="sar_par")
    assert par.value == 0 and par.options[0].startswith("★ 2026-09-24 → 2026-10-06 · S1C")
    texto = " ".join(m.value for m in at.markdown)
    assert "RECOMENDADO (SIN VALIDAR)" in texto and "S1C_IW_20260924T232218_DVP_RTC30" in texto
    assert at.session_state["resultado_activo"] is None and not salida.exists(), "buscar no analiza"

    at.slider(key="sar_umbral_VV").set_value(7.5)
    at.select_slider(key="sar_ventana_VV").set_value(1)
    at.select_slider(key="sar_ventana_VH").set_value(1)
    at.run()
    assert at.session_state["resultado_activo"] is None and not salida.exists(), "mover un control no analiza"
    at.button(key="sar_analizar").click().run()
    assert not at.exception, at.exception
    inf = at.session_state["mc_informe_sar"]
    assert "coincidencia_VV_VH_20260924_20261006.tif" in inf["archivos"]
    # El resultado nuevo queda en el mapa como resultado de ESTE análisis, ligado a su ejecución.
    activo = at.session_state["resultado_activo"]
    assert activo["id"] == "coincidencia_vv_vh_20260924_20261006" and activo["origen"] == "analisis"
    assert activo["run_id"] == inf["run_id"]
    texto = " ".join(m.value for m in at.markdown)
    assert "REAL SIN VALIDAR" in texto and "VV −7,5 dB · VH −3 dB" in texto and "ANÁLISIS DE ESTA SESIÓN" in texto
    assert len(at.warning) == 0
    archivos = sorted(p.name for p in salida.iterdir())
    for _ in range(3):                                  # reruns: ni repite el análisis ni cambia nada
        at.run()
    assert sorted(p.name for p in salida.iterdir()) == archivos
    assert at.session_state["resultado_activo"]["id"] == activo["id"]
    # Cambiar el umbral retira el resultado: ya no corresponde a lo elegido.
    at.slider(key="sar_umbral_VV").set_value(5.0).run()
    assert at.session_state["resultado_activo"] is None and "ya no corresponde" in (at.session_state["aviso_resultado"] or "")


def test_app_informa_error_de_conexion_sin_romperse(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def sin_red(parametros, **k):
        raise bus.ErrorConexion("No se pudo conectar con el catálogo de ASF. Revisa la conexión a internet.")
    monkeypatch.setattr(bus, "consultar_asf", sin_red)
    monkeypatch.chdir(RAIZ)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180).run()
    at.button(key="btn_sar").click().run()
    confirmar_zona(at)
    at.button(key="sar_buscar").click().run()
    assert not at.exception and at.session_state["resultado_activo"] is None
    assert "No se pudo conectar" in " ".join(m.value for m in at.markdown)


# ---------------------------------------------------------------------------
# Casos excepcionales de la Fase C
# ---------------------------------------------------------------------------

def _carpeta_mismo_dia(tmp_path):
    sar = tmp_path / "sar"
    sar.mkdir()
    rtc(sar, "20260924T232218", "VV")
    rtc(sar, "20261006T231500", "VV", baja=(10, 20), ident="3C4D")    # mismo día, 7 min antes
    return sar


def test_mismo_dia_no_se_analiza_sin_aceptacion_expresa(tmp_path, par):
    sar, salida = _carpeta_mismo_dia(tmp_path), tmp_path / "analisis"
    disp = flujo.disponibilidad(par, flujo.rtc_locales(sar)[0])
    vv = disp[0]
    assert vv.completa and vv.verificar and not vv.confirmada
    with pytest.raises(ErrorSAR, match="no es una coincidencia confirmada|No es una coincidencia confirmada"):
        flujo.analizar_disponibles(par, disp, AOI_CHIGORODO, {"VV": 3.0}, carpeta_salida=salida)
    assert not salida.exists() or not any(salida.iterdir())            # nada escrito


def test_mismo_dia_aceptado_queda_registrado_como_no_confirmado(tmp_path, par):
    sar, salida = _carpeta_mismo_dia(tmp_path), tmp_path / "analisis"
    disp = flujo.disponibilidad(par, flujo.rtc_locales(sar)[0])
    inf = flujo.analizar_disponibles(par, disp, AOI_CHIGORODO, {"VV": 3.0}, ventana_speckle=1,
                                     carpeta_salida=salida, aceptar_mismo_dia=True)
    registro = json.loads(inf.registro.read_text(encoding="utf-8"))
    assert registro["asociaciones_no_confirmadas"] == ["VV"]
    vv = next(r for r in registro["rtc"] if r["polarizacion"] == "VV")
    assert vv["asociacion_despues"] == flujo.MISMO_DIA and vv["asociacion_confirmada"] is False
    assert any("NO confirmada" in a for a in inf.avisos)


def test_asociacion_exacta_queda_confirmada(tmp_path, par):
    sar = tmp_path / "sar"
    sar.mkdir()
    rtc(sar, "20260924T232218", "VV")
    rtc(sar, "20261006T232219", "VV", ident="3C4D")                   # 1 s: dentro de la tolerancia
    vv = flujo.disponibilidad(par, flujo.rtc_locales(sar)[0])[0]
    assert vv.confirmada and not vv.verificar
    assert vv.resumen()["asociacion_confirmada"] is True


@pytest.mark.parametrize("horas", [("20261006T231500", "20261006T233000"),    # dos del mismo día
                                   ("20261006T232218", "20261006T232218")])   # dos exactos (dos trabajos)
def test_varios_candidatos_no_se_elige_ninguno_al_azar(tmp_path, par, horas):
    sar = tmp_path / "sar"
    sar.mkdir()
    rtc(sar, "20260924T232218", "VV")
    rtc(sar, horas[0], "VV", ident="AAAA")
    rtc(sar, horas[1], "VV", ident="BBBB")
    vv = flujo.disponibilidad(par, flujo.rtc_locales(sar)[0])[0]
    assert vv.tipo_despues == flujo.AMBIGUA and vv.despues is None and not vv.completa
    assert len(vv.empatados_despues) == 2
    with pytest.raises(ErrorSAR, match="faltan productos"):
        flujo.analizar_disponibles(par, [vv], AOI_CHIGORODO, {"VV": 3.0}, carpeta_salida=tmp_path / "a")


def test_archivos_danados_o_sin_georreferencia_se_informan_y_no_se_asocian(tmp_path, par):
    sar = tmp_path / "sar"
    sar.mkdir()
    rtc(sar, "20260924T232218", "VV")
    (sar / "S1C_IW_20261006T232218_DVP_RTC30_G_gpuned_3C4D_VV.tif").write_bytes(b"II*\x00corrupto")
    rtcs, avisos = flujo.rtc_locales(sar)
    assert len(rtcs) == 1
    assert any(a.startswith("S1C_IW_20261006T232218") for a in avisos)
    vv = flujo.disponibilidad(par, rtcs)[0]
    assert vv.despues is None and not vv.completa


def test_escenas_incompatibles_no_producen_resultado(tmp_path, par):
    """RTC de las fechas correctas pero que no se superponen con el AOI."""
    sar = tmp_path / "sar"
    sar.mkdir()
    for inicio in ("20260924T232218", "20261006T232218"):
        ruta = sar / f"S1C_IW_{inicio}_DVP_RTC30_G_gpuned_1A2B_VV.tif"
        with rasterio.open(ruta, "w", driver="GTiff", height=20, width=20, count=1, dtype="float32",
                           crs="EPSG:32618", transform=from_origin(800_000, 300_000, 300, 300), nodata=0.0) as f:
            f.write(np.full((20, 20), 0.1, dtype="float32"), 1)
    disp = flujo.disponibilidad(par, flujo.rtc_locales(sar)[0])
    with pytest.raises(ErrorSAR, match="fuera|superponen"):
        flujo.analizar_disponibles(par, disp, AOI_CHIGORODO, {"VV": 3.0}, carpeta_salida=tmp_path / "a")


def _app(tmp_path, monkeypatch, sar):
    from streamlit.testing.v1 import AppTest

    from utils import resultados
    salida = tmp_path / "analisis"
    monkeypatch.setattr(bus, "consultar_asf", lambda parametros, **k: REAL)
    monkeypatch.setattr(flujo, "CARPETA_SAR", sar)
    monkeypatch.setattr(flujo, "CARPETA_ANALISIS", salida)
    monkeypatch.setattr(resultados, "CARPETA_ANALISIS", salida)
    monkeypatch.chdir(RAIZ)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180).run()
    at.button(key="btn_sar").click().run()
    confirmar_zona(at)
    at.button(key="sar_buscar").click().run()
    return at, salida


def test_app_exige_aceptar_la_asociacion_por_dia(tmp_path, monkeypatch):
    at, salida = _app(tmp_path, monkeypatch, _carpeta_mismo_dia(tmp_path))
    assert "no confirmada" in " ".join(m.value for m in at.markdown)
    assert at.button(key="sar_analizar").disabled
    at.checkbox(key="sar_aceptar_mismo_dia").check().run()
    assert not at.button(key="sar_analizar").disabled
    at.button(key="sar_analizar").click().run()
    assert not at.exception, at.exception
    registro = json.loads(next(salida.glob("flujo_*_registro.json")).read_text(encoding="utf-8"))
    assert registro["asociaciones_no_confirmadas"] == ["VV"]


def test_app_busqueda_vacia_no_rompe(tmp_path, monkeypatch):
    sar = tmp_path / "sar"
    sar.mkdir()
    at, _ = _app(tmp_path, monkeypatch, sar)
    monkeypatch.setattr(bus, "consultar_asf", lambda parametros, **k: {"type": "FeatureCollection", "features": []})
    at.button(key="sar_buscar").click().run()
    assert not at.exception
    assert at.session_state["mc_informe_sar"] is None
    assert at.session_state["sar_busqueda"] is not None and not at.session_state["sar_busqueda"].pares
    assert not any(b.key == "sar_analizar" for b in at.button)


def test_estado_de_otra_pagina_no_rompe_mission_control(tmp_path, monkeypatch):
    """La página «Analisis SAR» guarda `sar_informe` como texto; Mission Control
    usa su propia clave y no debe fallar al compartir la sesión."""
    from streamlit.testing.v1 import AppTest
    monkeypatch.chdir(RAIZ)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180)
    at.session_state["sar_informe"] = "cambio_VV_20260924_20261006_analisis.json"
    at.run()
    at.button(key="btn_sar").click().run()
    assert not at.exception, at.exception
