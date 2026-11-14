"""Cálculo temporal NISAR con recortes de GCOV SINTÉTICOS (tests/nisar_sintetico.py)."""
from __future__ import annotations

import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from tests import nisar_sintetico as sint
from utils import analisis_sar as sar
from utils import nisar_flujo as flujo
from utils import nisar_gcov as g
from utils.analisis_sar import ErrorSAR, ParametrosCambio

CHIGORODO = (-76.80, 7.55, -76.55, 7.80)
AOI_PEQUENO = (-76.70, 7.62, -76.66, 7.66)        # ~220 × 220 px a 20 m
PARCHE = (slice(700, 800), slice(700, 800), 10 ** (-6 / 10))   # −6 dB exactos antes del speckle


def recorte(tmp_path, nombre, termino="HHHH", **kw):
    h5 = sint.gcov(tmp_path / f"{nombre}.h5", **kw)
    return g.exportar_recorte(h5, CHIGORODO, "A", termino, carpeta=tmp_path / "nisar")


@pytest.fixture
def par(tmp_path):
    recorte(tmp_path, "a", fecha="2026-10-24T23:15:00", mision="NISAR", semilla=1)
    recorte(tmp_path, "b", fecha="2026-11-05T23:15:00", mision="NISAR", semilla=2, parche=PARCHE)
    inv = flujo.inventario(tmp_path / "nisar")
    assert len(inv.pares) == 1 and inv.bloqueos == []
    return inv.pares[0]


def test_cambio_temporal_con_el_motor_comun(par, tmp_path):
    r = flujo.analizar(par, None, ParametrosCambio(3.0, 3.0, 5), tmp_path / "analisis")
    assert r.mascara.name == "nisar_cambio_AHHHH_20261024_20261105_mascara.tif"
    with rasterio.open(r.diferencia) as src:
        dif = src.read(1, masked=True)
        tags = src.tags()
        transform = src.transform
    with rasterio.open(r.mascara) as src:
        masc = src.read(1, masked=True)
    # Ubicar el parche (filas/columnas del HDF5) dentro de la cuadrícula del recorte.
    x = sint.X0 + sint.PASO * 750
    y = sint.Y0 - sint.PASO * 750
    fila, col = rasterio.transform.rowcol(transform, x, y)
    centro = dif[fila - 30:fila + 30, col - 30:col + 30]
    assert float(np.ma.median(centro)) == pytest.approx(-6.0, abs=0.6)
    assert float((masc[fila - 30:fila + 30, col - 30:col + 30] == sar.DISMINUCION).mean()) > 0.95
    lejos = dif[:200, :200]
    assert abs(float(np.ma.median(lejos))) < 0.3
    assert (tags["SENSOR"], tags["BANDA"], tags["POLARIZACION"]) == ("NISAR", "L", "HH")
    assert "experimentales" in tags["UMBRALES"] and "VISOR_DEMO" not in tags
    informe = json.loads(r.informe.read_text(encoding="utf-8"))
    assert informe["sensor"] == "NISAR" and informe["entradas"]["antes"]["geometria_nisar"]["track"] == "48"
    assert any("banda L" in lim for lim in informe["limitaciones"])
    assert not any(lim.startswith("Vegetación: bajo dosel denso o cultivos altos el agua puede no oscurecer la señal en banda C")
                   for lim in informe["limitaciones"])
    assert any("EXPERIMENTALES" in a for a in informe["avisos"])


def test_sin_umbrales_explicitos_no_se_analiza(par, tmp_path):
    with pytest.raises(ErrorSAR, match="umbrales"):
        sar.analizar_par(par.antes.ruta, par.despues.ruta, tmp_path / "x")
    with pytest.raises(ErrorSAR, match="umbrales"):
        flujo.analizar(par, None, None, tmp_path / "x")


def test_entradas_sinteticas_propagan_demo(tmp_path):
    recorte(tmp_path, "a", fecha="2026-10-24T23:15:00", semilla=1)        # missionId sintético
    recorte(tmp_path, "b", fecha="2026-11-05T23:15:00", semilla=2)
    par = flujo.inventario(tmp_path / "nisar").pares[0]
    r = flujo.analizar(par, AOI_PEQUENO, ParametrosCambio(3.0, 3.0, 1), tmp_path / "analisis")
    for ruta in (r.diferencia, r.mascara):
        with rasterio.open(ruta) as src:
            assert src.tags()["VISOR_DEMO"] == "1"


@pytest.mark.parametrize("cambio, motivo", [
    ({"track": 49}, "TRACK distinto"),
    ({"frame": 13}, "FRAME distinto"),
    ({"direccion": "Descending"}, "DIRECCION distinto"),
    ({"crid": "P05023"}, "CRID distinto"),
])
def test_recortes_incompatibles_no_forman_par(tmp_path, cambio, motivo):
    recorte(tmp_path, "a", fecha="2026-10-24T23:15:00", semilla=1)
    recorte(tmp_path, "b", fecha="2026-11-05T23:15:00", semilla=2, **cambio)
    inv = flujo.inventario(tmp_path / "nisar")
    assert inv.pares == [] and motivo in inv.bloqueos[0]
    assert any("escena única" in a for a in inv.avisos)
    a, b = inv.recortes
    with pytest.raises(ErrorSAR, match="no son comparables"):
        sar.analizar_par(a.ruta, b.ruta, tmp_path / "x", parametros=ParametrosCambio())


def test_terminos_distintos_no_se_comparan(tmp_path):
    recorte(tmp_path, "a", fecha="2026-10-24T23:15:00", termino="HHHH")
    recorte(tmp_path, "b", fecha="2026-11-05T23:15:00", termino="HVHV")
    inv = flujo.inventario(tmp_path / "nisar")
    assert inv.pares == [] and "TERMINO distinto" in inv.bloqueos[0]


def test_nunca_se_mezcla_banda_l_con_sentinel1(par, tmp_path):
    s1 = tmp_path / "S1C_IW_20261105T232218_DVP_RTC30_G_gpuned_1A2B_VV.tif"
    with rasterio.open(par.antes.ruta) as src:
        perfil = src.profile
        datos = src.read(1)
    perfil.update(nodata=0.0)
    with rasterio.open(s1, "w", **perfil) as dst:
        dst.write(np.where(datos > 0, datos, 0).astype("float32"), 1)
    with pytest.raises(ErrorSAR, match="sensores o bandas distintos"):
        sar.analizar_par(par.antes.ruta, s1, tmp_path / "x", parametros=ParametrosCambio(), polarizacion="VV")
    with pytest.raises(ErrorSAR):     # ni siquiera forzando la polarización
        sar.analizar_par(s1, par.despues.ruta, tmp_path / "x", parametros=ParametrosCambio(), polarizacion="HH")


def test_un_geotiff_con_nombre_s1_y_etiqueta_nisar_se_rechaza(par, tmp_path):
    falso = tmp_path / "S1C_IW_20261105T232218_DVP_RTC30_G_gpuned_1A2B_VV.tif"
    falso.write_bytes(par.antes.ruta.read_bytes())
    with pytest.raises(ErrorSAR, match="declara SENSOR=NISAR"):
        sar.describir_escena(falso)


def test_escena_unica_en_db_sin_umbral(par, tmp_path):
    ruta = flujo.escena_unica(par.antes, tmp_path / "analisis")
    assert ruta.name == "nisar_gamma0_AHHHH_20261024_T48_F12_db.tif"
    with rasterio.open(ruta) as src:
        db = src.read(1, masked=True)
        tags = src.tags()
    assert float(np.ma.median(db)) == pytest.approx(-7.0, abs=0.5)        # HH sintético a −7 dB
    assert (tags["TIPO_PRODUCTO"], tags["UNIDADES"], tags["SENSOR"]) == ("retrodispersion_db", "dB", "NISAR")
    informe = json.loads((tmp_path / "analisis" / "nisar_gamma0_AHHHH_20261024_T48_F12_analisis.json").read_text())
    assert "no un cambio" in " ".join(informe["metodo"]) and informe["huella_sha256"]
    otra = flujo.escena_unica(par.antes, tmp_path / "analisis")
    assert otra.name.endswith("_r2_db.tif")


def test_potencia_no_positiva_es_invalida(tmp_path):
    ruta = tmp_path / "nisar" / "nisar_gcov_20261024_T048_F012_A_A_HHHH.tif"
    ruta.parent.mkdir()
    datos = np.array([[0.1, 0.0], [-0.2, 0.05]], dtype="float32")
    with rasterio.open(ruta, "w", driver="GTiff", height=2, width=2, count=1, dtype="float32", crs="EPSG:32618",
                       transform=from_origin(0, 0, 20, 20), nodata=-9999.0) as dst:
        dst.write(datos, 1)
        dst.update_tags(SENSOR="NISAR", BANDA="L", POLARIZACION="HH", ESCALA="power", FECHA_ADQUISICION="2026-10-24",
                        TRACK="48", FRAME="12", DIRECCION="ASCENDING", FRECUENCIA="A", TERMINO="HHHH", CRID="P05036")
    salida = flujo.escena_unica(flujo.recortes_locales(ruta.parent)[0][0], tmp_path / "a")
    with rasterio.open(salida) as src:
        db = src.read(1, masked=True)
    assert db.mask.tolist() == [[False, True], [True, False]]
    assert db[0, 0] == pytest.approx(-10.0, abs=1e-4)


def test_inventario_ignora_lo_que_no_es_nisar(tmp_path):
    carpeta = tmp_path / "nisar"
    carpeta.mkdir()
    (carpeta / "nisar_gcov_roto.tif").write_bytes(b"II*\x00")
    with rasterio.open(carpeta / "nisar_gcov_sin_etiqueta.tif", "w", driver="GTiff", height=2, width=2, count=1,
                       dtype="float32", crs="EPSG:32618", transform=from_origin(0, 0, 20, 20)) as dst:
        dst.write(np.ones((2, 2), "float32"), 1)
        dst.update_tags(POLARIZACION="HH")
    inv = flujo.inventario(carpeta)
    assert inv.recortes == [] and len(inv.avisos) == 2
