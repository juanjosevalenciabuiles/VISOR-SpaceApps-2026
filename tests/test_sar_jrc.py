"""Cruce SAR × JRC con datos SINTÉTICOS.

Incluye las matrices del prototipo del equipo (VISOR_automatizacion_regional,
13-nov-2026) y la tabulación de Chigorodó comunicada desde QGIS reconstruida
en un ráster sintético: reproduce los CONTEOS, no las ubicaciones reales. La
comprobación con los GeoTIFF reales la hace `scripts/regional.py reproducir`.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from utils import procedencia, regiones
from utils import sar_jrc as sj
from utils.combinacion_sar import TIPO_PRODUCTO

ORIGEN = (300_000, 860_000)


def escribir(ruta, datos, nodata=None, origen=ORIGEN, res=30, crs="EPSG:32618", mascara_vv_vh=False, tags=None):
    with rasterio.open(ruta, "w", driver="GTiff", height=datos.shape[0], width=datos.shape[1], count=1,
                       dtype=datos.dtype, nodata=nodata, crs=crs, transform=from_origin(*origen, res, res)) as ds:
        ds.write(datos, 1)
        if mascara_vv_vh:
            ds.update_tags(TIPO_PRODUCTO=TIPO_PRODUCTO, UNIDADES="clase", FECHA="2026-09-24 / 2026-10-06",
                           **(tags or {}))
    return ruta


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def entradas(tmp_path):
    sar = np.array([[0, 1, 2, 3], [255, 1, 2, 3], [3, 2, 0, 1]], dtype="uint8")
    jrc = np.array([[0, 1, 20, 60], [0, 255, 0, 30], [10, 3, 0, 255]], dtype="uint8")
    s = escribir(tmp_path / "coincidencia.tif", sar, 255, mascara_vv_vh=True)
    j = escribir(tmp_path / "jrc.tif", jrc, None)          # JRC alineado en QGIS, sin NoData declarado
    return s, j


def test_matrices_del_prototipo_y_entradas_intactas(entradas, tmp_path):
    s, j = entradas
    antes = (sha(s), sha(j))
    r = sj.cruzar(s, j, carpeta=tmp_path / "out")
    with rasterio.open(r.coincidencia) as ds:
        np.testing.assert_array_equal(ds.read(1), [[0, 2, 2, 2], [255, 255, 1, 2], [2, 2, 0, 255]])
        assert ds.nodata == 255 and ds.tags()["TIPO_PRODUCTO"] == "sar_jrc_coincidencia"
    with rasterio.open(r.polarizaciones) as ds:
        np.testing.assert_array_equal(ds.read(1), [[0, 11, 12, 13], [255, 255, 2, 13], [13, 12, 0, 255]])
    assert (sha(s), sha(j)) == antes
    g = r.datos["global"]
    assert (g["pixeles_validos"], g["detecciones"]) == (9, 7)
    assert [u["pixeles_sar_jrc"] for u in g["umbrales_jrc"]] == [6, 4, 2, 1]
    assert g["pixeles_sar_validos_sin_jrc"] == 2 and r.datos["control"]["pixeles_sar_sin_dato_en_aoi"] == 1
    assert r.datos["entradas"]["sar"]["sha256"] == antes[0] and r.datos["entradas"]["jrc"]["sha256"] == antes[1]
    assert g["hectareas_detecciones"] == pytest.approx(7 * 0.09)


def test_nodata_jrc_nunca_es_cero(tmp_path):
    """Un JRC con NoData declarado (0 sería «sin agua») no debe contar como sin agua."""
    sar = np.array([[1, 2, 3]], dtype="uint8")
    jrc = np.array([[0, 250, 40]], dtype="uint8")
    s = escribir(tmp_path / "s.tif", sar, 255, mascara_vv_vh=True)
    j = escribir(tmp_path / "j.tif", jrc, nodata=0)        # aquí 0 es NoData declarado
    r = sj.cruzar(s, j, carpeta=tmp_path / "o")
    g = r.datos["global"]
    assert g["pixeles_validos"] == 1 and g["pixeles_sar_validos_sin_jrc"] == 2
    assert g["umbrales_jrc"][0]["pct_jrc_entre_detecciones"] == 100.0       # 1 de 1, no 1 de 3
    with rasterio.open(r.coincidencia) as ds:
        assert ds.read(1).tolist() == [[255, 255, 2]]


def test_no_sobrescribe_y_cache(entradas, tmp_path):
    s, j = entradas
    a = sj.cruzar(s, j, carpeta=tmp_path / "out")
    b = sj.cruzar(s, j, carpeta=tmp_path / "out")
    assert b.desde_cache and b.informe == a.informe
    c = sj.cruzar(s, j, carpeta=tmp_path / "out", usar_cache=False)
    assert c.informe != a.informe and "_r2" in c.informe.name
    d = sj.cruzar(s, j, carpeta=tmp_path / "out", umbrales=(5,))          # parámetros distintos: no es caché
    assert not d.desde_cache
    a.coincidencia.write_bytes(a.coincidencia.read_bytes() + b"x")      # salida alterada: esa no sirve…
    assert sj.buscar_en_cache(tmp_path / "out", a.datos["clave_cache"]) == c.informe   # …se usa la intacta
    c.coincidencia.write_bytes(c.coincidencia.read_bytes() + b"x")
    assert sj.buscar_en_cache(tmp_path / "out", a.datos["clave_cache"]) is None


def test_jrc_reproyectado_en_memoria_respeta_la_cuadricula_sar(entradas, tmp_path):
    s, j = entradas
    with rasterio.open(j) as src:
        datos = src.read(1)
    desplazado = escribir(tmp_path / "jrc_desplazado.tif", datos, None, origen=(300_015, 860_015))
    r = sj.cruzar(s, desplazado, carpeta=tmp_path / "out")
    with rasterio.open(s) as a, rasterio.open(r.coincidencia) as b:
        assert (a.transform, a.crs, a.shape) == (b.transform, b.crs, b.shape)


def test_jrc_geografico_original(tmp_path):
    """El JRC original viene en EPSG:4326; se lleva a la cuadrícula UTM sin escribir intermedios."""
    sar = np.ones((20, 20), dtype="uint8") * 3
    s = escribir(tmp_path / "s.tif", sar, 255, mascara_vv_vh=True)
    a_wgs = Transformer.from_crs("EPSG:32618", "EPSG:4326", always_xy=True)
    lon, lat = a_wgs.transform(ORIGEN[0] - 300, ORIGEN[1] + 300)
    jrc = np.full((400, 400), 80, dtype="uint8")
    j = escribir(tmp_path / "j.tif", jrc, 255, origen=(lon, lat), res=0.00025, crs="EPSG:4326")
    r = sj.cruzar(s, j, carpeta=tmp_path / "o")
    assert r.datos["global"]["umbrales_jrc"][-1]["pixeles_sar_jrc"] == 400
    assert list(tmp_path.glob("o/*jrc*.tif")) == [] or all("sar_jrc_" in p.name for p in tmp_path.glob("o/*.tif"))


@pytest.mark.parametrize("mal, mensaje", [
    ({"umbrales": (0,)}, "entre 1 y 100"), ({"umbrales": (101,)}, "entre 1 y 100"), ({"bloque": 8}, "bloque"),
])
def test_parametros_invalidos(entradas, tmp_path, mal, mensaje):
    s, j = entradas
    with pytest.raises(sj.ErrorJRC, match=mensaje):
        sj.cruzar(s, j, carpeta=tmp_path / "o", **mal)


def test_entradas_invalidas(entradas, tmp_path):
    s, j = entradas
    with pytest.raises(sj.ErrorJRC, match="mismo archivo"):
        sj.cruzar(s, s, carpeta=tmp_path / "o")
    no_vvvh = escribir(tmp_path / "otra.tif", np.zeros((3, 3), "uint8"), 255)
    with pytest.raises(sj.ErrorJRC, match="no es una combinación VV/VH"):
        sj.cruzar(no_vvvh, j, carpeta=tmp_path / "o")
    flotante = escribir(tmp_path / "jf.tif", np.zeros((3, 4), "float32"), None)
    with pytest.raises(sj.ErrorJRC, match="entero"):
        sj.cruzar(s, flotante, carpeta=tmp_path / "o")
    (tmp_path / "roto.tif").write_bytes(b"II*\x00")
    with pytest.raises(sj.ErrorJRC, match="legible"):
        sj.cruzar(s, tmp_path / "roto.tif", carpeta=tmp_path / "o")


def test_nisar_no_reutiliza_clases_vv_vh(tmp_path):
    s = escribir(tmp_path / "s.tif", np.zeros((2, 2), "uint8"), 255, mascara_vv_vh=True,
                 tags={"SENSOR": "NISAR", "BANDA": "L"})
    j = escribir(tmp_path / "j.tif", np.zeros((2, 2), "uint8"))
    with pytest.raises(sj.ErrorJRC, match="no se aplican a NISAR"):
        sj.cruzar(s, j, carpeta=tmp_path / "o")


def test_area_en_crs_en_pies(tmp_path):
    s = escribir(tmp_path / "s.tif", np.array([[3]], "uint8"), 255, origen=(3_000_000, 10_000_000),
                 crs="EPSG:2277", mascara_vv_vh=True)
    j = escribir(tmp_path / "j.tif", np.array([[50]], "uint8"), None, origen=(3_000_000, 10_000_000), crs="EPSG:2277")
    r = sj.cruzar(s, j, carpeta=tmp_path / "o")
    assert r.datos["cuadricula"]["hectareas_por_pixel"] == pytest.approx((30 * 1200 / 3937) ** 2 / 10_000, rel=1e-6)


# --- zonas -------------------------------------------------------------------------

def _zona_wgs(x0, y0, x1, y1):
    a_wgs = Transformer.from_crs("EPSG:32618", "EPSG:4326", always_xy=True)
    (o, n), (e, s) = a_wgs.transform(x0, y0), a_wgs.transform(x1, y1)
    return {"type": "Polygon", "coordinates": [[[o, n], [e, n], [e, s], [o, s], [o, n]]]}


def _limites(tmp_path, zonas):
    """GeoJSON de municipios SINTÉTICO con campos del MGN de DANE (códigos reales, polígonos inventados)."""
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"MPIO_CDPMP": c, "MPIO_CNMBR": n.upper()}, "geometry": g}
        for c, n, g in zonas]}
    ruta = tmp_path / "mgn_sintetico.geojson"
    ruta.write_text(json.dumps(fc))
    return regiones.cargar_limites(ruta)


def test_estadisticas_por_municipio_con_denominadores_y_nd(entradas, tmp_path):
    s, j = entradas
    lim = _limites(tmp_path, [
        ("05172", "Chigorodó", _zona_wgs(ORIGEN[0], ORIGEN[1], ORIGEN[0] + 60, ORIGEN[1] - 30)),      # 2 px
        ("05147", "Carepa", _zona_wgs(ORIGEN[0], ORIGEN[1] - 30, ORIGEN[0] + 30, ORIGEN[1] - 60)),   # el px 255
        ("05045", "Apartadó", _zona_wgs(ORIGEN[0] + 30_000, ORIGEN[1], ORIGEN[0] + 30_060, ORIGEN[1] - 60)),  # fuera
    ])
    aoi = lim.seleccionar(["05172", "05147", "05045"])
    r = sj.cruzar(s, j, aoi, carpeta=tmp_path / "o")
    z = r.datos["zonas"]
    assert z["05172"]["pixeles_zona_en_cuadricula"] == 2 and z["05172"]["pixeles_validos"] == 2
    assert z["05172"]["cobertura_sar_valida_pct"] == 100.0
    assert z["05147"]["pixeles_zona_en_cuadricula"] == 1 and z["05147"]["sin_observaciones_validas"]
    assert z["05147"]["cobertura_sar_valida_pct"] == 0.0
    assert z["05147"]["umbrales_jrc"][0]["pct_jrc_entre_detecciones"] is None           # N/D, no 0 %
    assert z["05045"]["pixeles_zona_en_cuadricula"] == 0 and z["05045"]["cobertura_sar_valida_pct"] is None
    assert z["05045"]["cobertura_cuadricula_pct"] == 0.0
    assert any("Carepa" in a and "N/D" in a for a in r.datos["avisos"])
    assert r.datos["global"]["pixeles_validos"] == 2                 # solo dentro del AOI
    with r.csv.open(encoding="utf-8-sig") as f:
        filas = list(csv.DictReader(f))
    carepa = [f for f in filas if f["codigo"] == "05147"]
    assert len(carepa) == 4 and carepa[0]["pct_jrc_entre_detecciones"] == ""          # N/D vacío


def test_zonas_solapadas_cuentan_en_ambas(entradas, tmp_path):
    s, j = entradas
    g = _zona_wgs(ORIGEN[0], ORIGEN[1], ORIGEN[0] + 120, ORIGEN[1] - 90)
    lim = _limites(tmp_path, [("05172", "A", g), ("05147", "B", g)])
    aoi = lim.seleccionar(["05172", "05147"])
    assert any("se solapan" in a for a in aoi.avisos)
    r = sj.cruzar(s, j, aoi, carpeta=tmp_path / "o")
    assert r.datos["zonas"]["05172"]["pixeles_validos"] == r.datos["zonas"]["05147"]["pixeles_validos"] == 9
    assert r.datos["global"]["pixeles_validos"] == 9                  # el total no duplica


# --- tabulación de Chigorodó (sintética) y puerta con datos reales ----------------------

def chigorodo_sintetico(tmp_path, jrc_255_en_detecciones=0):
    """924×926 con el histograma de QGIS: 815 237 / 11 / 27 992 / 12 293 / 91 y 1 / 1 335 / 2 668 con agua."""
    sar = np.concatenate([np.zeros(815_237, "uint8"), np.full(11, 1, "uint8"), np.full(27_992, 2, "uint8"),
                          np.full(12_293, 3, "uint8"), np.full(91, 255, "uint8")])
    agua = np.zeros(sar.size, "uint8")
    p = 815_237
    agua[p:p + 1] = 10
    agua[p + 11:p + 11 + 1335] = 10
    agua[p + 11 + 27_992:p + 11 + 27_992 + 2668] = 10
    agua[:3862] = 10
    if jrc_255_en_detecciones:
        agua[p + 11 + 2000:p + 11 + 2000 + jrc_255_en_detecciones] = 255
    s = escribir(tmp_path / "coincidencia_VV_VH_20260924_20261006.tif", sar.reshape(926, 924), 255,
                 origen=(301_380, 862_620), mascara_vv_vh=True)
    j = escribir(tmp_path / "JRC_Occurrence_Chigorodo_30m.tif", agua.reshape(926, 924), None, origen=(301_380, 862_620))
    return s, j


def test_tabulacion_de_qgis_en_raster_sintetico(tmp_path):
    s, j = chigorodo_sintetico(tmp_path)
    r = sj.cruzar(s, j, carpeta=tmp_path / "o")
    assert sj.comparar_con_referencia(r.datos, sj.leer_referencia()) == []
    u1 = r.datos["global"]["umbrales_jrc"][0]
    assert u1["pixeles_sar_jrc"] == 4004 and u1["hectareas_sar_jrc"] == pytest.approx(360.36)
    assert u1["pct_jrc_entre_detecciones"] == pytest.approx(9.9365, abs=1e-4)
    assert u1["por_clase"]["VV_y_VH"]["pct_dentro_clase"] == pytest.approx(21.7034, abs=1e-4)
    assert r.datos["global"]["hectareas_detecciones"] == pytest.approx(3626.64)
    assert r.datos["control"]["pixeles_sar_sin_dato_en_aoi"] == 91


def test_jrc_sin_dato_en_detecciones_hace_fallar_la_reproduccion(tmp_path):
    """Si el JRC real tuviera 255 dentro de las detecciones, no se maquilla: la reproducción falla."""
    s, j = chigorodo_sintetico(tmp_path, jrc_255_en_detecciones=5)
    r = sj.cruzar(s, j, carpeta=tmp_path / "o")
    difs = sj.comparar_con_referencia(r.datos, sj.leer_referencia())
    assert any("sin dato JRC" in d for d in difs) and any("detecciones totales" in d for d in difs)


def test_puerta_de_habilitacion(tmp_path):
    analisis, regional = tmp_path / "analisis", tmp_path / "regional"
    analisis.mkdir()
    s, j = chigorodo_sintetico(analisis)
    ok, motivo = sj.estado_habilitacion(regional, analisis)
    assert not ok and "reproducir" in motivo
    reg = sj.reproducir_chigorodo(s, j, regional)
    assert reg["resultado"] == "APROBADA" and not list(analisis.glob("sar_jrc_*"))   # no escribe en data/analisis
    ok, motivo = sj.estado_habilitacion(regional, analisis)
    assert ok and "APROBADA" in motivo
    with rasterio.open(s, "r+") as ds:                         # la máscara cambia → se deshabilita
        ds.update_tags(OTRA="x")
    assert not sj.estado_habilitacion(regional, analisis)[0]


def test_puerta_fallida_no_habilita(tmp_path):
    analisis, regional = tmp_path / "analisis", tmp_path / "regional"
    analisis.mkdir()
    s, j = chigorodo_sintetico(analisis, jrc_255_en_detecciones=3)
    reg = sj.reproducir_chigorodo(s, j, regional)
    assert reg["resultado"] == "FALLIDA"
    ok, motivo = sj.estado_habilitacion(regional, analisis)
    assert not ok and "NO coincide" in motivo


def test_procedencia_se_hereda_de_la_mascara(entradas, tmp_path):
    s, j = entradas
    r = sj.cruzar(s, j, carpeta=tmp_path / "o")
    ficha = json.loads(r.coincidencia.with_suffix(".json").read_text())
    assert ficha["procedencia"]["estado"] == procedencia.NO_DECLARADA          # la máscara no trae ficha real
    estado = procedencia.evaluar(False, ficha, procedencia.sha256_archivo(r.coincidencia))
    assert estado.estado == procedencia.NO_DECLARADA
    with rasterio.open(s, "r+") as ds:
        ds.update_tags(VISOR_DEMO="1")
    r2 = sj.cruzar(s, j, carpeta=tmp_path / "o2")
    with rasterio.open(r2.coincidencia) as ds:
        assert ds.tags()["VISOR_DEMO"] == "1"


def test_cli_reproducir_y_puerta(tmp_path, monkeypatch, capsys):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import regional
    analisis, reg = tmp_path / "analisis", tmp_path / "regional"
    analisis.mkdir()
    monkeypatch.setattr(sj, "CARPETA_REGIONAL", reg)
    monkeypatch.setattr(sj, "CARPETA_ANALISIS", analisis)
    s, j = chigorodo_sintetico(analisis)
    assert regional.main(["cruzar", "--sar", str(s), "--jrc", str(j)]) == 3          # bloqueado sin reproducir
    assert "BLOQUEADO" in capsys.readouterr().err
    assert regional.main(["reproducir", "--sar", str(s), "--jrc", str(j)]) == 0
    assert "APROBADA" in capsys.readouterr().out
    assert regional.main(["cruzar", "--sar", str(s), "--jrc", str(j)]) == 0
    salida = capsys.readouterr().out
    assert "9.9365 %" in salida
