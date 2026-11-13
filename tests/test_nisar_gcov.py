"""Lector GCOV con HDF5 sintéticos (tests/nisar_sintetico.py) y, si está
disponible, el GCOV de prueba de ISCE3 (VISOR_GCOV_ISCE3=ruta). Ninguno es
un producto real de la misión NISAR."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.warp import transform_bounds

from tests import nisar_sintetico as sint
from utils import nisar_gcov as g
from utils.analisis_sar import describir_escena

CHIGORODO = (-76.80, 7.55, -76.55, 7.80)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def h5(tmp_path):
    return sint.gcov(tmp_path / "NISAR_L2_PR_GCOV_030_048_A_012_2005_DHDH_A_20261024T231500_20261024T231550_P05036_N_F_J_001.h5",
                     mision="NISAR")


def test_inspeccion_solo_diagonales_y_metadatos(h5):
    p = g.inspeccionar(h5)
    assert [(c.frecuencia, c.termino, c.polarizacion) for c in p.capas] == [("A", "HHHH", "HH"), ("A", "HVHV", "HV")]
    assert p.terminos_cruzados == ["A:HHHV"]
    assert (p.track, p.frame, p.direccion, p.crid, p.es_nisar) == (48, 12, "ASCENDING", "P05036", True)
    assert p.capas[0].cuadricula.epsg == 32618 and p.capas[0].con_mascara
    assert p.rtc_aplicada is True


def test_terminos_cruzados_nunca_se_exportan(h5, tmp_path):
    with pytest.raises(g.ErrorGCOV, match="cruzado"):
        g.leer_ventana(h5, "A", "HHHV", CHIGORODO)


def test_ventana_solo_lee_el_aoi_y_respeta_mascara_y_relleno(h5):
    c = g.inspeccionar(h5).capas[0].cuadricula
    # AOI pequeño en la esquina NO, que incluye bordes NaN, máscara 255 y 0.
    o, s, e, n = transform_bounds("EPSG:32618", "EPSG:4326", c.x0 - 10, c.y0 - 10 - 40 * 20, c.x0 - 10 + 40 * 20, c.y0 + 10)
    v = g.leer_ventana(h5, "A", "HHHH", (o, s, e, n))
    assert v.datos.shape[0] <= 45 and v.datos.shape[1] <= 45        # no lee la escena entera
    assert v.datos.mask[:5, :].all()                                 # NaN
    assert v.datos.mask[:, :3].all()                                 # máscara 255
    assert v.datos.mask[10:12, 10:12].all()                          # máscara 0
    assert (v.datos.compressed() > 0).all()
    assert v.transform.c == pytest.approx(c.x0 - 10) and v.transform.f == pytest.approx(c.y0 + 10)


def test_recorte_georreferenciado_y_origen_intacto(h5, tmp_path):
    antes = _sha(h5)
    salida = g.exportar_recorte(h5, CHIGORODO, "A", "HVHV", carpeta=tmp_path / "nisar", madurez="VALIDATED",
                                sha_origen=True)
    assert _sha(h5) == antes
    assert salida.name == "nisar_gcov_20261024_T048_F012_A_A_HVHV.tif"
    with rasterio.open(salida) as src:
        assert src.crs.to_epsg() == 32618 and src.nodata == g.NODATA and src.dtypes[0] == "float32"
        t = src.tags()
        datos = src.read(1, masked=True)
    assert (t["SENSOR"], t["BANDA"], t["POLARIZACION"], t["ESCALA"], t["MADUREZ"]) == ("NISAR", "L", "HV", "power", "VALIDATED")
    assert "VISOR_DEMO" not in t
    # La mediana de gamma0 en potencia se conserva (no se convirtió a dB).
    assert 10 * np.log10(np.ma.median(datos)) == pytest.approx(-14, abs=0.5)
    ficha = json.loads(salida.with_suffix(".json").read_text(encoding="utf-8"))
    assert ficha["sha256"] == _sha(salida) and ficha["origen"]["sha256"] == antes
    assert ficha["estado"] == "REAL_SIN_VALIDAR" and "no valida" in ficha["advertencia"]
    # El motor SAR lo lee como potencia HV con su fecha, sin confundirlo con VV/VH.
    e = describir_escena(salida)
    assert (e.polarizacion, e.escala, f"{e.fecha:%Y-%m-%d}") == ("HV", "power", "2026-10-24")


def test_no_sobrescribe(h5, tmp_path):
    a = g.exportar_recorte(h5, CHIGORODO, carpeta=tmp_path)
    huella = _sha(a)
    b = g.exportar_recorte(h5, CHIGORODO, carpeta=tmp_path)
    assert b.name.endswith("_r2.tif") and _sha(a) == huella


def test_sin_sha_de_origen_lo_declara(h5, tmp_path):
    ficha = json.loads(g.exportar_recorte(h5, CHIGORODO, carpeta=tmp_path).with_suffix(".json").read_text())
    assert ficha["origen"]["sha256"] is None and "NO VERIFICADA" in ficha["origen"]["integridad"]
    assert ficha["madurez_producto"] == "NO_COMPROBADA"


def test_producto_no_nisar_queda_como_demo(tmp_path):
    h5 = sint.gcov(tmp_path / "x.h5")                     # missionId NISAR_SINTETICO
    p = g.inspeccionar(h5)
    assert not p.es_nisar and any("DEMO" in a for a in p.avisos)
    salida = g.exportar_recorte(h5, CHIGORODO, carpeta=tmp_path)
    with rasterio.open(salida) as src:
        assert src.tags()["VISOR_DEMO"] == "1"
    assert json.loads(salida.with_suffix(".json").read_text())["estado"] == "DEMO"


@pytest.mark.parametrize("cambios, mensaje", [
    ({"x0": 900_000.0}, "fuera de la cobertura"),
    ({"terminos": ()}, "ninguna capa diagonal"),
])
def test_escenas_sin_cobertura_o_sin_capas(tmp_path, cambios, mensaje):
    h5 = sint.gcov(tmp_path / "x.h5", **cambios)
    with pytest.raises(g.ErrorGCOV, match=mensaje):
        g.exportar_recorte(h5, CHIGORODO, carpeta=tmp_path)


def test_cuadricula_irregular_se_rechaza(tmp_path):
    import h5py
    h5 = sint.gcov(tmp_path / "x.h5", n=300)
    with h5py.File(h5, "r+") as f:
        x = f["/science/LSAR/GCOV/grids/frequencyA/xCoordinates"]
        datos = x[...]
        datos[150:] += 3.0                                # salto de 3 m a mitad de fila
        x[...] = datos
    with pytest.raises(g.ErrorGCOV, match="ninguna capa diagonal"):
        g.inspeccionar(h5)


def test_area_demasiado_grande(h5, tmp_path):
    with pytest.raises(g.ErrorGCOV, match="píxeles"):
        g.exportar_recorte(h5, CHIGORODO, carpeta=tmp_path, max_pixeles=10_000)


@pytest.mark.parametrize("contenido", [b"", b"\x89HDF\r\n\x1a\n roto", b"no es hdf5"])
def test_archivo_danado(tmp_path, contenido):
    p = tmp_path / "danado.h5"
    p.write_bytes(contenido)
    with pytest.raises(g.ErrorGCOV, match="no es un HDF5 legible"):
        g.inspeccionar(p)


def test_hdf5_que_no_es_gcov(tmp_path):
    import h5py
    p = tmp_path / "otro.h5"
    with h5py.File(p, "w") as f:
        f.create_group("/science/LSAR/GSLC/grids/frequencyA")
    with pytest.raises(g.ErrorGCOV, match="no es un NISAR L2 GCOV"):
        g.inspeccionar(p)


def test_madurez_desconocida(h5, tmp_path):
    with pytest.raises(g.ErrorGCOV, match="Madurez"):
        g.exportar_recorte(h5, CHIGORODO, carpeta=tmp_path, madurez="FINAL")


ISCE3 = os.environ.get("VISOR_GCOV_ISCE3")


@pytest.mark.skipif(not ISCE3 or not Path(ISCE3).is_file(),
                    reason="VISOR_GCOV_ISCE3 no apunta al GCOV de prueba de ISCE3 (isce3/tests/data/nisar_129_gcov_crop.h5)")
def test_gcov_de_referencia_de_isce3(tmp_path):
    """Estructura escrita por el procesador oficial (datos UAVSAR, versión 0.1, EPSG:4326)."""
    p = g.inspeccionar(ISCE3)
    assert not p.es_nisar and p.mision == "UAVSAR"
    terminos = {(c.frecuencia, c.termino) for c in p.capas}
    assert {("A", "HHHH"), ("B", "HHHH"), ("B", "HVHV"), ("B", "VVVV")} <= terminos
    c = p.capa("A", "HHHH").cuadricula
    o, s, e, n = c.limites
    centro = ((o + e) / 2, (s + n) / 2)
    bbox = (centro[0] - 0.01, centro[1] - 0.01, centro[0] + 0.01, centro[1] + 0.01)
    salida = g.exportar_recorte(ISCE3, bbox, "A", "HHHH", carpeta=tmp_path)
    with rasterio.open(salida) as src:
        assert src.crs.to_epsg() == 4326 and src.tags()["VISOR_DEMO"] == "1"
        assert src.read(1, masked=True).count() > 0


def test_cli_inspeccionar_y_recortar(h5, tmp_path, capsys):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import nisar
    assert nisar.main(["inspeccionar", str(h5)]) == 0
    assert '"termino": "HHHH"' in capsys.readouterr().out
    assert nisar.main(["recortar", str(h5), "--termino", "HVHV", "--carpeta", str(tmp_path)]) == 0
    assert (tmp_path / "nisar_gcov_20261024_T048_F012_A_A_HVHV.tif").is_file()


def test_cli_rechaza_terminos_cruzados(h5, tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import nisar
    with pytest.raises(SystemExit):                      # argparse: HHHV no es una opción
        nisar.main(["recortar", str(h5), "--termino", "HHHV", "--carpeta", str(tmp_path)])
