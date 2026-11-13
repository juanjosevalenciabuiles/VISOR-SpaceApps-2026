"""Mosaico de RTC de una pasada con rásteres SINTÉTICOS (nombres con la convención HyP3)."""
from __future__ import annotations

import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from utils import mosaico
from utils.analisis_sar import ErrorSAR, ParametrosCambio, analizar_par, describir_escena
from utils.procedencia import sha256_archivo

X0, Y0, RES = 300_000.0, 900_000.0, 30.0


def rtc(carpeta, hora, fila0, alto=200, ancho=300, pol="VV", plataforma="S1C", dia="20261006", valor=0.1,
        x0=X0, res=RES, crs="EPSG:32618", ident="1A2B", escala="p", hueco=True):
    """Cuadro cuyo borde norte está `fila0` píxeles al sur del origen común."""
    ruta = carpeta / f"{plataforma}_IW_{dia}T{hora}_DVP_RTC30_G_g{escala}uned_{ident}_{pol}.tif"
    datos = np.full((alto, ancho), valor, dtype="float32")
    if hueco:
        datos[:, :10] = 0.0                       # sin dato de HyP3 en un borde
    with rasterio.open(ruta, "w", driver="GTiff", height=alto, width=ancho, count=1, dtype="float32", crs=crs,
                       transform=from_origin(x0, Y0 - fila0 * res, res, res), nodata=0.0) as dst:
        dst.write(datos, 1)
    return ruta


def test_une_dos_cuadros_consecutivos_sin_tocar_las_entradas(tmp_path):
    a = rtc(tmp_path, "232218", 0, valor=0.10)
    b = rtc(tmp_path, "232243", 150, valor=0.10, ident="3C4D")       # 50 filas de solape
    huellas = sha256_archivo(a), sha256_archivo(b)
    m = mosaico.unir([b, a], tmp_path / "mosaicos", bloque=128)       # el orden de entrada no importa
    assert (sha256_archivo(a), sha256_archivo(b)) == huellas
    with rasterio.open(m.ruta) as src:
        datos = src.read(1, masked=True)
        assert (src.height, src.width, src.crs.to_epsg(), src.nodata) == (350, 300, 32618, 0.0)
        assert src.transform == from_origin(X0, Y0, RES, RES)
        etiquetas = src.tags()
    assert datos.mask[:, :10].all() and not datos.mask[:, 10:].any()
    assert float(datos.compressed().min()) == pytest.approx(0.1)
    assert m.ficha["solape"] == {"pixeles": 50 * 290, "diferencia_media_abs_db": 0.0}
    assert m.ficha["pixeles_sin_dato"] == 350 * 10 and m.ficha["sha256"] == sha256_archivo(m.ruta)
    assert (etiquetas["POLARIZACION"], etiquetas["ESCALA"], etiquetas["FECHA_ADQUISICION"]) == ("VV", "power", "2026-10-06T23:22:18")
    e = describir_escena(m.ruta)                                     # el motor lo lee sin nombre HyP3
    assert (e.polarizacion, e.escala, f"{e.fecha:%Y-%m-%d}") == ("VV", "power", "2026-10-06")


def test_cache_por_huellas_y_no_sobrescribe(tmp_path):
    a, b = rtc(tmp_path, "232218", 0), rtc(tmp_path, "232243", 150, ident="3C4D")
    primero = mosaico.unir([a, b], tmp_path / "m")
    segundo = mosaico.unir([a, b], tmp_path / "m")
    assert segundo.desde_cache and segundo.ruta == primero.ruta
    tercero = mosaico.unir([a, b], tmp_path / "m", usar_cache=False)
    assert tercero.ruta.name.endswith("_r2.tif") and sha256_archivo(primero.ruta) == primero.ficha["sha256"]
    with rasterio.open(a, "r+") as dst:                               # cambia una entrada → otra clave
        dst.update_tags(X="1")
    assert not mosaico.unir([a, b], tmp_path / "m").desde_cache


def test_en_el_solape_gana_el_primero_y_se_mide_la_diferencia(tmp_path):
    a = rtc(tmp_path, "232218", 0, valor=0.10)
    b = rtc(tmp_path, "232243", 150, valor=0.20, ident="3C4D")       # 3,01 dB más brillante
    m = mosaico.unir([a, b], tmp_path / "m")
    with rasterio.open(m.ruta) as src:
        datos = src.read(1)
    assert datos[160, 100] == pytest.approx(0.10) and datos[300, 100] == pytest.approx(0.20)
    assert m.ficha["solape"]["diferencia_media_abs_db"] == pytest.approx(3.01, abs=0.01)
    assert any("difieren" in av for av in m.ficha["avisos"])


@pytest.mark.parametrize("cambio, mensaje", [
    ({"hora": "233500"}, "no son cuadros consecutivos"),
    ({"dia": "20261018"}, "no son cuadros consecutivos"),
    ({"pol": "VH"}, "distinta polarización"),
    ({"plataforma": "S1A"}, "distinta satélite"),
    ({"escala": "d"}, "distinta escala"),
    ({"crs": "EPSG:32617"}, "otro CRS"),
    ({"res": 10.0}, "tamaño de píxel o alineación"),
    ({"x0": X0 + 7.0}, "tamaño de píxel o alineación"),
    ({"hora": "232218"}, "misma hora"),
])
def test_solo_se_unen_cuadros_de_la_misma_pasada(tmp_path, cambio, mensaje):
    a = rtc(tmp_path, "232218", 0)
    b = rtc(tmp_path, **({"hora": "232243", "fila0": 150, "ident": "3C4D"} | cambio))
    with pytest.raises(ErrorSAR, match=mensaje):
        mosaico.unir([a, b], tmp_path / "m")
    assert not (tmp_path / "m").exists() or not list((tmp_path / "m").glob("*"))


def test_un_solo_cuadro_no_es_un_mosaico(tmp_path):
    with pytest.raises(ErrorSAR, match="al menos dos"):
        mosaico.unir([rtc(tmp_path, "232218", 0)], tmp_path / "m")


def test_el_motor_analiza_un_par_de_mosaicos(tmp_path):
    """Dos fechas, dos cuadros cada una; en la segunda, el cuadro sur pierde 6 dB."""
    antes = mosaico.unir([rtc(tmp_path, "232218", 0, dia="20260924", ident="AAAA"),
                          rtc(tmp_path, "232243", 150, dia="20260924", ident="BBBB")], tmp_path / "m")
    despues = mosaico.unir([rtc(tmp_path, "232218", 0, ident="CCCC"),
                            rtc(tmp_path, "232243", 200, ident="DDDD", valor=0.1 * 10 ** -0.6)], tmp_path / "m")
    r = analizar_par(antes.ruta, despues.ruta, tmp_path / "out", parametros=ParametrosCambio(3.0, 3.0, 1))
    with rasterio.open(r.diferencia) as src:
        dif = src.read(1, masked=True)
    assert dif.shape == (350, 300)                                    # cuadrícula de la imagen anterior
    assert float(dif[100, 100]) == pytest.approx(0.0, abs=1e-4) and float(dif[300, 100]) == pytest.approx(-6.0, abs=1e-3)
    informe = json.loads(r.informe.read_text(encoding="utf-8"))
    assert informe["entradas"]["antes"]["archivo"].startswith("mosaico_S1C_20260924")
