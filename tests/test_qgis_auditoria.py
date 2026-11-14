"""Interoperabilidad con QGIS y auditoría de GeoTIFF (rásteres sintéticos aislados)."""
import io
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))

from test_resultados import exploratorio, reproducible  # noqa: E402
from utils import procedencia, qgis  # noqa: E402
from utils.auditoria import auditar, transiciones  # noqa: E402
from utils.combinacion_sar import CLASES_COINCIDENCIA  # noqa: E402


def abrir_zip(datos: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_exportar_conserva_el_geotiff_byte_a_byte(tmp_path):
    ruta = reproducible(tmp_path)
    antes = procedencia.sha256_archivo(ruta)
    nombre, datos = qgis.exportar(ruta, CLASES_COINCIDENCIA, "Coincidencia VV/VH")
    assert procedencia.sha256_archivo(ruta) == antes                # la fuente no se tocó
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == sorted([ruta.name, ruta.with_suffix(".json").name])

    base = ruta.stem
    archivos = abrir_zip(datos)
    assert nombre == f"{base}_QGIS.zip"
    assert set(archivos) == {f"{base}/{n}" for n in (f"{base}.tif", f"{base}.qml", f"{base}.json",
                                                     f"{base}_leyenda.csv", "LEEME_QGIS.txt", "manifiesto.json")}
    tif = archivos[f"{base}/{base}.tif"]
    assert tif == ruta.read_bytes()
    manifiesto = json.loads(archivos[f"{base}/manifiesto.json"])
    assert manifiesto["geotiff_original_sha256"] == antes
    assert manifiesto["procedencia"]["estado"] == procedencia.REAL_SIN_VALIDAR
    import hashlib
    for n, sha in manifiesto["archivos"].items():
        assert hashlib.sha256(archivos[f"{base}/{n}"]).hexdigest() == sha

    # El GeoTIFF exportado conserva CRS, tamaño, NoData y clases.
    salida = tmp_path / "abierto.tif"
    salida.write_bytes(tif)
    with rasterio.open(salida) as src:
        assert src.crs.to_epsg() == 32618 and (src.width, src.height) == (40, 40) and src.nodata == 255
        assert set(np.unique(src.read(1)).tolist()) == {0, 1, 2, 3, 255}
    # La ficha va tal cual y sigue correspondiendo al GeoTIFF exportado.
    ficha = json.loads(archivos[f"{base}/{base}.json"])
    assert ficha["procedencia"]["archivo"]["sha256"] == antes


def test_estilo_qml_categorico_con_transparencias():
    raiz = ET.fromstring(qgis.estilo_qml(CLASES_COINCIDENCIA).split("\n", 1)[1])
    render = raiz.find("pipe/rasterrenderer")
    assert render.get("type") == "paletted" and render.get("band") == "1"
    entradas = {int(e.get("value")): e for e in render.iter("paletteEntry")}
    assert sorted(entradas) == [0, 1, 2, 3, 255]
    assert (entradas[1].get("color"), entradas[2].get("color"), entradas[3].get("color")) == ("#00f0ff", "#ff9f0a", "#7d7aff")
    assert all(entradas[v].get("alpha") == "255" for v in (1, 2, 3))
    assert entradas[0].get("alpha") == "0" and entradas[255].get("alpha") == "0"
    assert "solo en VV" in entradas[1].get("label") and "NoData" in entradas[255].get("label")


def test_aoi_solo_si_esta_declarada():
    assert qgis.aoi_geojson(None) is None
    assert qgis.aoi_geojson({"aoi_lonlat": None}) is None
    assert qgis.aoi_geojson({"aoi_lonlat": [-76.5, 7.5, -76.8, 7.8]}) is None      # oeste > este
    assert qgis.aoi_geojson({"aoi_lonlat": [-76.8, 7.55, "x", 7.8]}) is None
    g = json.loads(qgis.aoi_geojson({"aoi_lonlat": [-76.80, 7.55, -76.55, 7.80]}))
    anillo = g["features"][0]["geometry"]["coordinates"][0]
    assert anillo[0] == anillo[-1] == [-76.8, 7.55] and len(anillo) == 5


def test_geojson_de_aoi_lo_lee_gdal(tmp_path):
    import geopandas as gpd
    ruta = tmp_path / "aoi.geojson"
    ruta.write_text(qgis.aoi_geojson({"aoi_lonlat": [-76.80, 7.55, -76.55, 7.80]}), encoding="utf-8")
    g = gpd.read_file(ruta)
    assert g.crs.to_epsg() == 4326 and g.geometry.iloc[0].is_valid
    assert tuple(round(v, 2) for v in g.total_bounds) == (-76.8, 7.55, -76.55, 7.8)


def test_exploratorio_sin_ficha_se_exporta_sin_ficha_ni_aoi(tmp_path):
    ruta = exploratorio(tmp_path / "coincidencia VV-VH (Chigorodó).tif")
    nombre, datos = qgis.exportar(ruta, CLASES_COINCIDENCIA, "Coincidencia VV/VH")
    assert nombre == "coincidencia_VV-VH_Chigorod_QGIS.zip" or nombre.endswith("_QGIS.zip")
    assert all(ord(c) < 128 and c not in '<>:"\\|?*' for c in nombre)
    archivos = abrir_zip(datos)
    assert not any(n.endswith(".json") and "manifiesto" not in n for n in archivos)
    assert not any(n.endswith(".geojson") for n in archivos)
    leeme = next(v for n, v in archivos.items() if n.endswith("LEEME_QGIS.txt")).decode()
    assert "PROCEDENCIA NO DECLARADA" in leeme and "vecino mas cercano" in leeme and "No confirman" in leeme


def test_limite_de_tamano(tmp_path, monkeypatch):
    ruta = exploratorio(tmp_path / "e.tif")
    monkeypatch.setattr(qgis, "MAX_BYTES_EXPORTACION", 10)
    with pytest.raises(qgis.ErrorExportacion, match="límite"):
        qgis.exportar(ruta, CLASES_COINCIDENCIA, "x")


# ---------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------

def test_transiciones():
    a = np.array([[0, 1], [3, 255]], dtype="uint8")
    b = np.array([[0, 3], [3, 255]], dtype="uint8")
    assert transiciones(a, b, a == 255) == {"0->0": 1, "1->3": 1, "3->3": 1}


def test_auditoria_coteja_la_huella_con_la_ficha(tmp_path):
    ruta = reproducible(tmp_path)
    i = auditar(ruta)
    assert i["ficha"]["sha256_coincide"] and i["ficha"]["estado_efectivo"] == procedencia.REAL_SIN_VALIDAR
    assert i["archivo"]["crs"] == "EPSG:32618" and i["archivo"]["nodata"] == 255
    assert i["clases"]["pixeles_sin_dato"] == 40
    with rasterio.open(ruta, "r+") as dst:                          # el archivo cambia después de la ficha
        d = dst.read(1)
        d[0, 0] = 3
        dst.write(d, 1)
    i = auditar(ruta)
    assert not i["ficha"]["sha256_coincide"] and i["ficha"]["estado_efectivo"] == procedencia.NO_DECLARADA


def test_auditoria_compara_versiones_sin_forzar_equivalencia(tmp_path):
    """Dos versiones con umbral VV distinto: se informa la diferencia, no se corrige."""
    real = reproducible(tmp_path / "r")
    otra = tmp_path / "exploratorio.tif"
    with rasterio.open(real) as src:
        datos, perfil = src.read(1), src.profile
    datos2 = datos.copy()
    datos2[20:22] = np.where(datos2[20:22] == 0, 1, datos2[20:22])  # VV más permisiva: aparecen clases 1
    with rasterio.open(otra, "w", **perfil) as dst:
        dst.write(datos2, 1)
    i = auditar(real, comparar=otra)
    c = i["comparacion"]
    assert c["misma_cuadricula"] and not c["equivalentes"] and c["pixeles_distintos"] == 80
    assert c["transiciones"]["0->1"] == 80
    assert procedencia.sha256_archivo(otra) == c["sha256"]          # se lee, no se modifica


def test_auditoria_reconstruye_desde_las_mascaras(tmp_path):
    ruta = reproducible(tmp_path)
    vv = tmp_path / "entradas" / "cambio_VV_20260924_20261006_mascara.tif"
    vh = tmp_path / "entradas" / "cambio_VH_20260924_20261006_mascara.tif"
    i = auditar(ruta, vv=vv, vh=vh)
    assert i["reconstruccion"]["reproduce_el_producto"] and i["reconstruccion"]["pixeles_distintos"] == 0
    assert '"umbral_disminucion_db": 7.5' in i["reconstruccion"]["parametros_vv"]
    with pytest.raises(Exception, match="dos máscaras"):
        auditar(ruta, vv=vv)


def test_lineas_de_comandos(tmp_path):
    ruta = reproducible(tmp_path)
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "auditar_geotiff.py"), str(ruta),
                        "--salida", str(tmp_path / "informe.json")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp_path / "informe.json").read_text(encoding="utf-8"))["ficha"]["sha256_coincide"]
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "auditar_geotiff.py"), str(ruta),
                        "--salida", str(ruta)], capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and procedencia.sha256_archivo(ruta) == auditar(ruta)["archivo"]["sha256"]
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "exportar_qgis.py"), str(ruta),
                        "--carpeta", str(tmp_path / "exp")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "exp" / f"{ruta.stem}_QGIS.zip").exists()


def test_cuadricula_distinta_no_se_compara(tmp_path):
    a = exploratorio(tmp_path / "a.tif")
    b = tmp_path / "b.tif"
    with rasterio.open(b, "w", driver="GTiff", height=40, width=40, count=1, dtype="uint8",
                       crs="EPSG:32618", transform=from_origin(0, 0, 30, 30), nodata=255) as dst:
        dst.write(np.zeros((40, 40), "uint8"), 1)
    assert auditar(a, comparar=b)["comparacion"]["misma_cuadricula"] is False


def test_verificar_paquete_detecta_manipulaciones(tmp_path):
    ruta = reproducible(tmp_path)
    _, datos = qgis.exportar(ruta, CLASES_COINCIDENCIA, "Coincidencia VV/VH")
    assert qgis.verificar_paquete(datos, ruta, CLASES_COINCIDENCIA) == []

    def rehacer(cambio):
        archivos = abrir_zip(datos)
        cambio(archivos)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n, b in archivos.items():
                z.writestr(n, b)
        return qgis.verificar_paquete(buf.getvalue(), ruta, CLASES_COINCIDENCIA)

    base = f"{ruta.stem}/{ruta.stem}"
    tif_cambiado = rehacer(lambda a: a.__setitem__(f"{base}.tif", a[f"{base}.tif"][:-1] + bytes([a[f"{base}.tif"][-1] ^ 1])))
    assert any("no es idéntico" in p for p in tif_cambiado) and any("manifiesto" in p for p in tif_cambiado)
    qml = rehacer(lambda a: a.__setitem__(f"{base}.qml", a[f"{base}.qml"].replace(b'alpha="0"', b'alpha="255"', 1)))
    assert any("Paleta" in p or "manifiesto" in p for p in qml)
    assert any("Falta el .qml" in p for p in rehacer(lambda a: a.pop(f"{base}.qml")))
    assert qgis.verificar_paquete(b"no es zip", ruta, CLASES_COINCIDENCIA) == ["El paquete no es un ZIP válido."]


@pytest.mark.parametrize("entrada, esperado", [
    ("coincidencia VV/VH · Chigorodó", "coincidencia_VV_VH_Chigorod"),
    ("CON", "resultado_CON"), ("com1.tif", "resultado_com1.tif"), ("nul", "resultado_nul"),
    ("...", "resultado"), ("a" * 79 + ".b", "a" * 79),
])
def test_nombres_validos_en_windows(entrada, esperado):
    nombre = qgis.nombre_seguro(entrada)
    assert nombre == esperado
    assert len(nombre) <= 80 and not nombre.endswith((".", " "))
    assert re.fullmatch(r"[A-Za-z0-9._-]+", nombre)
