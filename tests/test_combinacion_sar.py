"""Combinación VV/VH reproducible (Fase B3).

Los rásteres de estas pruebas son sintéticos: comprueban la regla de
combinación, la ficha de procedencia y la equivalencia con el script
exploratorio. La última prueba usa el GeoTIFF real de Chigorodó solo si está
presente en data/analisis/ (no se sube a GitHub).
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils import procedencia  # noqa: E402
from utils.analisis_sar import ErrorSAR, ParametrosCambio, analizar_par  # noqa: E402
from utils.combinacion_sar import (  # noqa: E402
    AMBAS, SIN_DISMINUCION, SOLO_VH, SOLO_VV, clasificar, combinar_vv_vh, comparar_geotiff,
    describir_clases,
)
from utils.geotiff import leer_geotiff  # noqa: E402

X0, Y0, RES, LADO = 300_000.0, 860_000.0, 30.0, 60
EXPLORATORIO = RAIZ / "data" / "analisis" / "coincidencia_VV_VH_Chigorodo.tif"


def referencia_exploratoria(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Copia literal de la regla del script exploratorio (handoff del 12-nov-2026)."""
    validos = (a != 255) & (b != 255)
    resultado = np.zeros(a.shape, dtype=np.uint8)
    resultado[~validos] = 255
    resultado[validos & (a == 1) & (b != 1)] = 1
    resultado[validos & (a != 1) & (b == 1)] = 2
    resultado[validos & (a == 1) & (b == 1)] = 3
    return resultado


def escribir_exploratorio(vv_path: Path, vh_path: Path, salida: Path) -> Path:
    """Reproduce el script exploratorio completo (mismo perfil y etiquetas)."""
    with rasterio.open(vv_path) as vv, rasterio.open(vh_path) as vh:
        resultado = referencia_exploratoria(vv.read(1), vh.read(1))
        perfil = vv.profile.copy()
        perfil.update(driver="GTiff", count=1, dtype="uint8", nodata=255, compress="deflate")
        with rasterio.open(salida, "w", **perfil) as dst:
            dst.write(resultado, 1)
            dst.update_tags(descripcion="Coincidencia de cambios SAR VV y VH", clase_0="Sin disminucion conjunta",
                            clase_1="Disminucion solo VV", clase_2="Disminucion solo VH",
                            clase_3="Disminucion VV y VH", clase_255="Sin dato",
                            advertencia="No confirma inundaciones")
    return salida


def rtc(ruta: Path, datos: np.ndarray) -> Path:
    with rasterio.open(ruta, "w", driver="GTiff", height=LADO, width=LADO, count=1, dtype="float32",
                       crs="EPSG:32618", transform=from_origin(X0, Y0, RES, RES), nodata=0.0) as dst:
        dst.write(datos.astype("float32"), 1)
    return ruta


def mascaras_del_motor(tmp_path: Path) -> tuple[Path, Path]:
    """Corre el motor real sobre RTC sintéticos con nombres de HyP3 (VV y VH).

    Filas 0–9: baja solo VV · 10–19: baja en ambas · 20–29: baja solo VH ·
    40–44: AUMENTO en VH (debe quedar en clase 0) · fila 59: sin dato en VV.
    """
    entrada = tmp_path / "sar"
    entrada.mkdir()
    base = np.full((LADO, LADO), 0.1, dtype="float32")             # −10 dB
    vv_antes, vv_despues, vh_antes, vh_despues = base.copy(), base.copy(), base.copy(), base.copy()
    vv_despues[0:20] = 0.01                                          # −20 dB → −10 dB de cambio
    vh_despues[10:30] = 0.01
    vh_despues[40:45] = 1.0                                          # +10 dB
    vv_antes[59] = 0.0                                               # NoData
    rutas = {}
    for pol, antes, despues in (("VV", vv_antes, vv_despues), ("VH", vh_antes, vh_despues)):
        a = rtc(entrada / f"S1C_IW_20260924T231502_DVP_RTC30_G_gpuned_1A2B_{pol}.tif", antes)
        d = rtc(entrada / f"S1C_IW_20261006T231503_DVP_RTC30_G_gpuned_3C4D_{pol}.tif", despues)
        rutas[pol] = analizar_par(a, d, tmp_path / "analisis", parametros=ParametrosCambio(ventana_speckle=1)).mascara
    return rutas["VV"], rutas["VH"]


def test_regla_identica_al_script_exploratorio_para_todas_las_combinaciones():
    valores = np.array([0, 1, 2, 3, 255], dtype="uint8")
    a, b = np.meshgrid(valores, valores)
    assert np.array_equal(clasificar(a, b), referencia_exploratoria(a, b))
    rng = np.random.default_rng(7)
    a, b = rng.choice(valores, (200, 200)), rng.choice(valores, (200, 200))
    assert np.array_equal(clasificar(a, b), referencia_exploratoria(a, b))


def test_combinacion_desde_el_motor_con_ficha_completa(tmp_path):
    vv, vh = mascaras_del_motor(tmp_path)
    r = combinar_vv_vh(vv, vh, zona="Prueba sintética")
    assert r.geotiff.name == "coincidencia_VV_VH_20260924_20261006.tif" and r.ficha_ruta.exists()

    with rasterio.open(r.geotiff) as src:
        clases, tags = src.read(1), src.tags()
        assert src.crs.to_epsg() == 32618 and src.nodata == 255 and src.dtypes[0] == "uint8"
    assert (clases[0:10, :] == SOLO_VV).all() and (clases[10:20, :] == AMBAS).all()
    assert (clases[20:30, :] == SOLO_VH).all()
    assert (clases[40:45, :] == SIN_DISMINUCION).all()               # el aumento no es disminución
    assert (clases[59] == 255).all()
    assert tags["TIPO_PRODUCTO"] == "coincidencia_vv_vh" and tags["POLARIZACION"] == "VV+VH"

    f = json.loads(r.ficha_ruta.read_text(encoding="utf-8"))
    b = f["procedencia"]
    assert b["estado"] == procedencia.REAL_SIN_VALIDAR and "faltantes" not in b
    assert b["sensor"].startswith("Sentinel-1C") and "banda C" in b["sensor"] and "NISAR" not in b["sensor"]
    assert b["fechas"] == ["2026-09-24", "2026-10-06"] and b["polarizaciones"] == ["VV", "VH"]
    assert "≤ −3 dB" in b["metodo"]
    assert [e["sha256"] for e in b["entradas"]] == [procedencia.sha256_archivo(vv), procedencia.sha256_archivo(vh)]
    assert b["entradas"][0]["rtc_antes"].startswith("S1C_IW_20260924") and b["entradas"][1]["polarizacion"] == "VH"
    assert b["archivo"]["sha256"] == procedencia.sha256_archivo(r.geotiff)
    assert b["validacion"] is None and f["zona_declarada"] == "Prueba sintética"

    e = f["estadisticas"]
    assert e["pixeles_totales"] == LADO * LADO and e["pixeles_sin_dato"] == LADO
    assert e["clases"]["1"]["pixeles"] == 10 * LADO and e["clases"]["3"]["pixeles"] == 10 * LADO
    assert e["clases"]["3"]["area_ha"] == pytest.approx(10 * LADO * 0.09, abs=0.01)
    assert sum(c["pixeles"] for c in e["clases"].values()) == e["pixeles_validos"]
    assert any("No confirma" in x or "no confirma" in x for x in [f["advertencia"], *f["limitaciones"]])
    assert any("clase 0" in x for x in f["limitaciones"])

    capa = leer_geotiff(r.geotiff, categorico=True)
    assert capa.procedencia.estado == procedencia.REAL_SIN_VALIDAR


def test_equivalencia_con_el_script_exploratorio(tmp_path):
    vv, vh = mascaras_del_motor(tmp_path)
    r = combinar_vv_vh(vv, vh)
    exploratorio = escribir_exploratorio(vv, vh, tmp_path / "coincidencia_VV_VH_Chigorodo.tif")
    c = comparar_geotiff(r.geotiff, exploratorio)
    assert c["equivalentes"] and c["pixeles_distintos"] == 0
    assert c["a"]["clases"] == c["b"]["clases"]

    # Un solo píxel distinto rompe la equivalencia.
    with rasterio.open(exploratorio, "r+") as dst:
        datos = dst.read(1)
        datos[30, 30] = 3
        dst.write(datos, 1)
    c = comparar_geotiff(r.geotiff, exploratorio)
    assert not c["equivalentes"] and c["pixeles_distintos"] == 1

    # El archivo exploratorio, sin ficha, nunca pasa por real.
    assert leer_geotiff(exploratorio, categorico=True).procedencia.estado == procedencia.NO_DECLARADA


def test_mascaras_sin_marcas_del_motor_no_se_declaran_reales(tmp_path):
    vv, vh = mascaras_del_motor(tmp_path)
    limpias = []
    for ruta, pol in ((vv, "VV"), (vh, "VH")):
        with rasterio.open(ruta) as src:
            datos, perfil = src.read(1), src.profile
        destino = tmp_path / f"sin_tags_{pol}_mascara.tif"
        with rasterio.open(destino, "w", **perfil) as dst:
            dst.write(datos, 1)
        limpias.append(destino)
    r = combinar_vv_vh(*limpias, carpeta_salida=tmp_path / "otra")
    assert r.estado == procedencia.NO_DECLARADA
    assert {"sensor", "fechas", "polarizaciones"} <= set(r.ficha["procedencia"]["faltantes"])
    assert leer_geotiff(r.geotiff, categorico=True).procedencia.estado == procedencia.NO_DECLARADA


def test_errores_de_entrada(tmp_path):
    vv, vh = mascaras_del_motor(tmp_path)
    with pytest.raises(ErrorSAR, match="máscara VH"):
        combinar_vv_vh(vh, vv)                                       # polarizaciones invertidas
    with pytest.raises(ErrorSAR, match="mismo archivo"):
        combinar_vv_vh(vv, vv.with_name(vv.name))
    with pytest.raises(ErrorSAR, match="sobrescribir"):
        combinar_vv_vh(vv, vh, prefijo=vv.stem)

    with rasterio.open(vh) as src:
        datos, perfil, tags = src.read(1), src.profile, src.tags()
    perfil["transform"] = from_origin(X0 + 30, Y0, RES, RES)
    movida = tmp_path / "movida_VH_mascara.tif"
    with rasterio.open(movida, "w", **perfil) as dst:
        dst.write(datos, 1)
        dst.update_tags(**tags)
    with pytest.raises(ErrorSAR, match="incompatibles"):
        combinar_vv_vh(vv, movida)

    otra_fecha = tmp_path / "otra_fecha_VH_mascara.tif"
    perfil["transform"] = from_origin(X0, Y0, RES, RES)
    with rasterio.open(otra_fecha, "w", **perfil) as dst:
        dst.write(datos, 1)
        dst.update_tags(**{**tags, "FECHA": "2026-10-06 / 2026-10-18"})
    with pytest.raises(ErrorSAR, match="mismo par de fechas"):
        combinar_vv_vh(vv, otra_fecha)


def test_describir_reproduce_las_cifras_de_chigorodo(tmp_path):
    """Ráster sintético con los mismos conteos verificados del archivo de Chigorodó."""
    alto, ancho = 926, 924
    plano = np.zeros(alto * ancho, dtype="uint8")
    inicio = 0
    for valor, n in ((255, 91), (1, 729), (2, 12_852), (3, 27_433)):
        plano[inicio:inicio + n] = valor
        inicio += n
    ruta = tmp_path / "conteos.tif"
    with rasterio.open(ruta, "w", driver="GTiff", height=alto, width=ancho, count=1, dtype="uint8",
                       crs="EPSG:32618", transform=from_origin(X0, Y0, RES, RES), nodata=255) as dst:
        dst.write(plano.reshape(alto, ancho), 1)
    d = describir_clases(ruta)
    assert d["pixeles_validos"] == 855_533 and d["pixeles_sin_dato"] == 91
    assert [d["clases"][k]["pixeles"] for k in "0123"] == [814_519, 729, 12_852, 27_433]
    assert d["clases"]["3"]["porcentaje_de_validos"] == pytest.approx(3.207, abs=0.001)
    assert d["clases"]["3"]["area_ha"] == pytest.approx(2468.97, abs=0.01)


def test_linea_de_comandos_genera_y_compara(tmp_path):
    vv, vh = mascaras_del_motor(tmp_path)
    exploratorio = escribir_exploratorio(vv, vh, tmp_path / "exploratorio.tif")
    salida = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "combinar_vv_vh.py"), "--vv", str(vv), "--vh", str(vh),
         "--salida", str(tmp_path / "cli"), "--comparar", str(exploratorio)],
        capture_output=True, text=True, timeout=120,
    )
    assert salida.returncode == 0, salida.stderr
    assert "EQUIVALENTES" in salida.stdout and "real_sin_validar" in salida.stdout
    assert "No confirma" in salida.stdout or "no confirma" in salida.stdout
    describir = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "combinar_vv_vh.py"), "--describir", str(exploratorio)],
        capture_output=True, text=True, timeout=120,
    )
    assert describir.returncode == 0 and "Clase 3" in describir.stdout


@pytest.mark.skipif(not EXPLORATORIO.exists(), reason="el GeoTIFF exploratorio de Chigorodó no está en data/analisis/")
def test_archivo_exploratorio_de_chigorodo_si_esta_presente():
    d = describir_clases(EXPLORATORIO)
    assert d["crs"] == "EPSG:32618" and d["dimensiones"] == [924, 926]
    assert d["pixeles_validos"] == 855_533 and d["pixeles_sin_dato"] == 91
    assert [d["clases"][k]["pixeles"] for k in "0123"] == [814_519, 729, 12_852, 27_433]
    assert leer_geotiff(EXPLORATORIO, categorico=True).procedencia.estado == procedencia.NO_DECLARADA
