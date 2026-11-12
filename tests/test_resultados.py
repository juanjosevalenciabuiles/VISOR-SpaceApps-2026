"""Resultados SAR de data/analisis/ como capas opcionales (Fase B2 y B4).

Rásteres sintéticos: el GeoTIFF «exploratorio» de estas pruebas imita las
etiquetas del archivo de Chigorodó, no sus datos.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from components import mapa  # noqa: E402
from components import resultados as ui  # noqa: E402
from components.barra_lateral import Controles  # noqa: E402
from utils import procedencia  # noqa: E402
from utils import resultados as r  # noqa: E402
from utils.combinacion_sar import TIPO_PRODUCTO, combinar_vv_vh  # noqa: E402
from utils.config import FENOMENOS  # noqa: E402
from utils.geotiff import colorizar_categorico, leer_geotiff  # noqa: E402

X0, Y0, RES = 301_398.0, 862_610.0, 30.0
ETIQUETAS_EXPLORATORIO = dict(
    descripcion="Coincidencia de cambios SAR VV y VH", clase_0="Sin disminucion conjunta",
    clase_1="Disminucion solo VV", clase_2="Disminucion solo VH", clase_3="Disminucion VV y VH",
    clase_255="Sin dato", advertencia="No confirma inundaciones",
)


def clases_de_prueba() -> np.ndarray:
    c = np.zeros((40, 40), dtype="uint8")
    c[0:5], c[5:10], c[10:15] = 1, 2, 3
    c[39, :] = 255
    return c


def exploratorio(ruta: Path) -> Path:
    with rasterio.open(ruta, "w", driver="GTiff", height=40, width=40, count=1, dtype="uint8",
                       crs="EPSG:32618", transform=from_origin(X0, Y0, RES, RES), nodata=255) as dst:
        dst.write(clases_de_prueba(), 1)
        dst.update_tags(**ETIQUETAS_EXPLORATORIO)
    return ruta


def reproducible(carpeta: Path) -> Path:
    """Combinación con ficha completa a partir de máscaras con las marcas del motor."""
    c = clases_de_prueba()
    entradas = carpeta / "entradas"
    entradas.mkdir(parents=True, exist_ok=True)
    rutas = {}
    for pol, cl in (("VV", (1, 3)), ("VH", (2, 3))):
        m = np.where(np.isin(c, cl), 1, 0).astype("uint8")
        m[c == 255] = 255
        ruta = entradas / f"cambio_{pol}_20260924_20261006_mascara.tif"
        with rasterio.open(ruta, "w", driver="GTiff", height=40, width=40, count=1, dtype="uint8",
                           crs="EPSG:32618", transform=from_origin(X0, Y0, RES, RES), nodata=255) as dst:
            dst.write(m, 1)
            dst.update_tags(VISOR_ANALISIS="1", MOTOR_VERSION="1.0", POLARIZACION=pol, UNIDADES="clase",
                            FUENTE="Sentinel-1 (S1C), ASF HyP3 RTC gamma0 · derivado por V.I.S.O.R.",
                            FECHA="2026-09-24 / 2026-10-06", ENTRADA_ANTES=f"a_{pol}.tif",
                            ENTRADA_DESPUES=f"d_{pol}.tif", PARAMETROS=json.dumps({"umbral_disminucion_db": 3.0}))
        rutas[pol] = ruta
    return combinar_vv_vh(rutas["VV"], rutas["VH"], carpeta).geotiff


def controles(**kw) -> Controles:
    base = dict(clave="inundacion", mostrar_capa=True, opacidad=0.85, mostrar_huella=False,
                mostrar_referencia=False)
    return Controles(**{**base, **kw})


# ---------------------------------------------------------------------------
# Identificación y carga
# ---------------------------------------------------------------------------

def test_identificar_perfil_por_lo_que_declara_el_archivo():
    tags = {k.upper(): v for k, v in ETIQUETAS_EXPLORATORIO.items()}
    assert r.identificar_perfil(tags) == TIPO_PRODUCTO
    assert r.identificar_perfil({"TIPO_PRODUCTO": TIPO_PRODUCTO}) == TIPO_PRODUCTO
    assert r.identificar_perfil({"VISOR_ANALISIS": "1", "UNIDADES": "clase"}) == "mascara_cambios"
    assert r.identificar_perfil({"VISOR_ANALISIS": "1", "UNIDADES": "dB"}) is None      # continuo: no se dibuja
    assert r.identificar_perfil({}, {"tipo_producto": "otro"}) is None
    assert r.identificar_perfil({"CLASE_1": "algo"}) is None


def test_exploratorio_se_carga_como_no_declarado_con_estadisticas(tmp_path):
    res = r.leer_resultado(exploratorio(tmp_path / "coincidencia_VV_VH_Chigorodo.tif"))
    assert res.dibujable and res.perfil.clave == TIPO_PRODUCTO and res.error is None
    assert res.capa.procedencia.estado == procedencia.NO_DECLARADA
    e = res.estadisticas
    assert e["pixeles_sin_dato"] == 40 and e["pixeles_validos"] == 1560
    assert [e["clases"][k]["pixeles"] for k in "123"] == [200, 200, 200]
    assert e["clases"]["0"]["pixeles"] == 1560 - 600
    assert e["clases"]["3"]["area_ha"] == pytest.approx(200 * 0.09)


def test_no_reconocido_se_lista_pero_no_se_dibuja(tmp_path):
    ruta = tmp_path / "otro.tif"
    with rasterio.open(ruta, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32",
                       crs="EPSG:32618", transform=from_origin(X0, Y0, RES, RES)) as dst:
        dst.write(np.ones((4, 4), dtype="float32"), 1)
    res = r.leer_resultado(ruta)
    assert not res.dibujable and "no reconocido" in res.error


def test_listar_y_cargar_desde_la_carpeta(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "CARPETA_ANALISIS", tmp_path / "no_existe")
    assert r.listar() == [] and r.cargar_resultados() == []
    exploratorio(tmp_path / "b.tif")
    (tmp_path / "nota.txt").write_text("x")
    assert [p.name for p in r.listar(tmp_path)] == ["b.tif"]
    assert r.id_resultado(Path("coincidencia_VV_VH_Chigorodo.tif")) == "coincidencia_vv_vh_chigorodo"


# ---------------------------------------------------------------------------
# Visualización: solo cambia colores
# ---------------------------------------------------------------------------

def test_colores_y_transparencias_sin_alterar_valores(tmp_path):
    ruta = exploratorio(tmp_path / "e.tif")
    res = r.leer_resultado(ruta)
    rgba = colorizar_categorico(res.capa.datos, res.perfil.clases)
    datos = res.capa.datos
    cian, naranja, violeta = (0, 240, 255, 255), (255, 159, 10, 255), (125, 122, 255, 255)
    for valor, color in ((1, cian), (2, naranja), (3, violeta)):
        assert (rgba[np.ma.filled(datos == valor, False)] == color).all()
    assert (rgba[np.ma.filled(datos == 0, False)][:, 3] == 0).all()                  # clase 0 transparente
    assert (rgba[np.ma.getmaskarray(datos)][:, 3] == 0).all()                        # NoData transparente
    # El archivo no cambia: sus valores siguen siendo las clases originales.
    with rasterio.open(ruta) as src:
        assert np.array_equal(src.read(1), clases_de_prueba())
    assert set(np.unique(datos.compressed()).astype(int)) <= {0, 1, 2, 3}


def test_capa_opcional_no_reemplaza_la_del_fenomeno(tmp_path):
    res = r.leer_resultado(exploratorio(tmp_path / "e.tif"))
    fen = FENOMENOS["inundacion"]
    capa = leer_geotiff(fen.ruta)
    apagado = mapa.construir_capas(fen, capa, controles(), [res])
    encendido = mapa.construir_capas(fen, capa, controles(resultados={res.id: 0.4}), [res])
    nombres = [g.layer_name for g in encendido]
    assert len(encendido) == len(apagado) + 1
    assert nombres[1] == "SAR · Inundaciones" and nombres[2] == "Resultado · Coincidencia VV/VH"
    overlay = next(iter(encendido[2]._children.values()))
    assert overlay.options["opacity"] == 0.4
    # Sin la capa del fenómeno, el resultado sigue disponible por sí mismo.
    solo = mapa.construir_capas(fen, capa, controles(mostrar_capa=False, resultados={res.id: 1.0}), [res])
    assert [g.layer_name for g in solo][1] == "Resultado · Coincidencia VV/VH"


def test_el_lienzo_del_mapa_no_cambia_al_activar_resultados(tmp_path):
    from streamlit_folium import _get_map_string, generate_js_hash
    a = generate_js_hash(_get_map_string(mapa.mapa_fijo()), "mapa", True)
    res = r.leer_resultado(exploratorio(tmp_path / "e.tif"))
    mapa.construir_capas(FENOMENOS["inundacion"], None, controles(resultados={res.id: 1.0}), [res])
    assert generate_js_hash(_get_map_string(mapa.mapa_fijo()), "mapa", True) == a


# ---------------------------------------------------------------------------
# Información científica (B4)
# ---------------------------------------------------------------------------

def test_ficha_del_exploratorio_no_inventa_datos(tmp_path):
    res = r.leer_resultado(exploratorio(tmp_path / "coincidencia_VV_VH_Chigorodo.tif"))
    html = ui.ficha_html(res)
    assert "PROCEDENCIA NO DECLARADA" in html and "REAL SIN VALIDAR" not in html
    assert "No es una inundación confirmada" in html
    datos = ui.datos_declarados(res)
    assert datos["sensor"] == (ui.NO_DECLARADO, None) and datos["metodo"] == (ui.NO_DECLARADO, None)
    assert datos["fechas"] == (ui.NO_DECLARADO, None) and datos["umbral"] == (ui.NO_DECLARADO, None)
    assert datos["polarizaciones"] == ("VV y VH", "según las etiquetas del GeoTIFF")
    assert "Sentinel" not in html and "2026" not in html
    assert "200" in html and "Limitaciones" in html and "No documentada" in html


def test_ficha_reproducible_muestra_todo_y_su_origen(tmp_path):
    res = r.leer_resultado(reproducible(tmp_path))
    assert res.capa.procedencia.estado == procedencia.REAL_SIN_VALIDAR
    d = ui.datos_declarados(res)
    assert d["sensor"][0].startswith("Sentinel-1C") and d["sensor"][1] == "según la ficha de procedencia"
    assert d["fechas"][0] == "2026-09-24 → 2026-10-06" and d["polarizaciones"][0] == "VV y VH"
    assert d["umbral"][0] == "−3 dB (disminución)" and "Combinación píxel a píxel" in d["metodo"][0]
    html = ui.ficha_html(res)
    assert "REAL SIN VALIDAR" in html and "SHA-256" in html and "No es una inundación confirmada" in html
    assert "NISAR" not in html


def test_leyenda_diferenciada_por_clase(tmp_path):
    html = ui.leyenda_html(r.leer_resultado(exploratorio(tmp_path / "e.tif")))
    for color in ("#00F0FF", "#FF9F0A", "#7D7AFF"):
        assert color in html
    assert html.count("(transparente)") == 2 and "clase 0" in html.lower()
    assert "solo en VV" in html and "solo en VH" in html and "VV y VH" in html


def test_fechas_de_la_linea_temporal_solo_con_ficha_valida(tmp_path):
    expl = r.leer_resultado(exploratorio(tmp_path / "e.tif"))
    real = r.leer_resultado(reproducible(tmp_path / "real"))
    assert ui.fechas_activas([expl], {expl.id: 1.0}) is None
    assert ui.fechas_activas([real], {}) is None
    assert ui.fechas_activas([real], {real.id: 1.0}) == ["2026-09-24", "2026-10-06"]
    assert ui.fechas_activas([real, expl], {real.id: 1.0, expl.id: 1.0}) is None   # ambiguo: no se elige


# ---------------------------------------------------------------------------
# App completa
# ---------------------------------------------------------------------------

def test_app_activa_resultado_sin_perder_controles(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    exploratorio(tmp_path / "coincidencia_VV_VH_Chigorodo.tif")
    reproducible(tmp_path / "real")
    for p in (tmp_path / "real").glob("coincidencia*"):
        p.rename(tmp_path / p.name)
    monkeypatch.setattr(r, "CARPETA_ANALISIS", tmp_path)
    monkeypatch.chdir(RAIZ)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120).run()
    assert not at.exception and len(at.error) == 0

    clave = "res_coincidencia_vv_vh_chigorodo"
    assert at.toggle(key=clave).value is False
    assert at.slider(key=f"res_op_{clave.removeprefix('res_')}").disabled
    at.radio(key="fenomeno").set_value("deforestacion").run()
    at.toggle(key=clave).set_value(True).run()
    at.slider(key="res_op_coincidencia_vv_vh_chigorodo").set_value(0.5).run()
    assert not at.exception
    texto = " ".join(m.value for m in at.markdown)
    assert "PROCEDENCIA NO DECLARADA" in texto and "No es una inundación confirmada" in texto
    assert "LÍNEA TEMPORAL · CONCEPTUAL" in texto                    # sin ficha: no hay fechas

    # Cambiar de fenómeno no apaga el resultado ni su opacidad.
    at.radio(key="fenomeno").set_value("deslizamiento").run()
    assert at.toggle(key=clave).value is True and at.slider(key="res_op_coincidencia_vv_vh_chigorodo").value == 0.5
    assert at.toggle(key="capa_sar").value is True

    # Con solo el resultado reproducible activo, la línea temporal muestra sus fechas.
    at.toggle(key=clave).set_value(False).run()
    at.toggle(key="res_coincidencia_vv_vh_20260924_20261006").set_value(True).run()
    texto = " ".join(m.value for m in at.markdown)
    assert "T₁ · 2026-09-24" in texto and "T₂ · 2026-10-06" in texto and "REAL SIN VALIDAR" in texto
