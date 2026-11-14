"""NASA Harmony NISAR GCOV: solicitudes mínimas, descargas acotadas y rechazo seguro.

Ninguna prueba contacta NASA ni descarga imágenes reales.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from utils import nisar_harmony as h

AOI = (-76.8, 7.55, -76.55, 7.8)
GRANULE = "NISAR_L2_PR_GCOV_033_148_A_005_2005_DHDH_M_20261022T104722_20261022T104757_P05036_N_F_J_001"
CAPAS = ("HHHH", "HVHV", "mask", "numberOfLooks")
VARIABLES = ["/science/LSAR/GCOV/grids/frequencyA/" + c for c in CAPAS]


class Respuesta(io.BytesIO):
    def __init__(self, contenido, url):
        super().__init__(contenido)
        self.url = url
        self.headers = {"Content-Length": str(len(contenido))}

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def caps():
    return {"coleccion": "C3622241360-ASF", "variables": set(VARIABLES)}


def candidato(pols=("HH", "HV")):
    return NS(granule=GRANULE, nombre=NS(pol_a=pols))


def test_capacidades_publicas_mock_sin_secreto():
    payload = {"conceptId": "C3622241360-ASF", "shortName": "NISAR_L2_GCOV_V1",
               "variables": [{"name": v} for v in VARIABLES]}
    pedidos = []
    def abrir(req, timeout):
        pedidos.append(req)
        return Respuesta(json.dumps(payload).encode(), req.full_url)
    resultado = h.capacidades(abrir)
    assert resultado["coleccion"] == "C3622241360-ASF"
    assert set(VARIABLES) == resultado["variables"]
    assert len(pedidos) == 1
    assert pedidos[0].get_header("Authorization") is None


def test_solo_polarizaciones_presentes_y_mascara():
    s = h.especificar(candidato(), AOI, caps())
    assert s.capas == CAPAS
    assert s.variables == tuple(VARIABLES)
    assert s.bbox == AOI
    assert s.coleccion == "C3622241360-ASF"
    with pytest.raises(h.ErrorHarmony, match="variables necesarias"):
        h.especificar(candidato(), AOI, {"coleccion": s.coleccion,
                                          "variables": {VARIABLES[0], VARIABLES[1]}})
    with pytest.raises(h.ErrorHarmony, match="polarización copolar"):
        h.especificar(candidato(pols=("HV",)), AOI, caps())


def test_no_resample_ni_crs_en_solicitud():
    pytest.importorskip("harmony")
    spec = h.especificar(candidato(), AOI, caps())
    req = h.construir_solicitud(spec)
    assert list(req.variables) == list(VARIABLES)
    assert req.crs is None and req.width is None and req.height is None
    assert req.spatial.w == AOI[0]
    assert req.max_results == 1
    assert req.format == "image/tiff"


def test_no_urls_ajenas_o_http_ni_capa_b():
    h._url_datos("https://harmony.earthdata.nasa.gov/results/nisar_HHHH.tif")
    h._url_datos("https://harmony-test.s3.us-west-2.amazonaws.com/a.tif?firma=abc")
    for url in ("http://harmony.earthdata.nasa.gov/a.tif",
                "https://example.com/a.tif",
                "https://127.0.0.1/a.tif",
                "https://user:password@harmony.earthdata.nasa.gov/a.tif"):
        with pytest.raises(h.ErrorHarmony):
            h._url_datos(url)
    assert h._etiqueta("https://harmony.earthdata.nasa.gov/x_frequencyA_HHHH.tif", CAPAS) == "HHHH"
    with pytest.raises(h.ErrorHarmony):
        h._etiqueta("https://harmony.earthdata.nasa.gov/x_frequencyB_HHHH.tif", CAPAS)
    with pytest.raises(h.ErrorHarmony):
        h._etiqueta("https://harmony.earthdata.nasa.gov/no_identificable.tif", CAPAS)


def tiff(dtype="float32", cambio_x=0):
    memoria = MemoryFile()
    datos = np.ones((32, 32), dtype=dtype)
    with memoria.open(driver="GTiff", width=32, height=32, count=1,
                      dtype=dtype, crs="EPSG:32618",
                      transform=from_origin(310000 + cambio_x, 850000, 20, 20)) as dst:
        dst.write(datos, 1)
    return memoria.read()


def test_descarga_limitada_sin_token_ni_part(monkeypatch, tmp_path):
    url = "https://harmony.earthdata.nasa.gov/frequencyA_HHHH.tif?signature=PRIVATE"
    data = tiff()
    assert len(data) > 1024
    seen = []
    def abrir(req, timeout):
        seen.append(req)
        return Respuesta(data, url)
    p = tmp_path / "HHHH.tif"
    size, sha = h._descargar_cota(url, p, len(data) + 1, abrir=abrir)
    assert size == len(data) and len(sha) == 64
    assert p.read_bytes() == data and not list(tmp_path.glob("*.part"))
    assert seen[0].get_header("Authorization") is None
    with pytest.raises(h.ErrorHarmony):
        h._descargar_cota(url, tmp_path / "otro.tif", len(data) - 1, abrir=abrir)
    assert not list(tmp_path.glob("*.part"))


class ClienteFake:
    def __init__(self):
        self.cancelado = False
        self.solicitudes = []

    def submit(self, req):
        self.solicitudes.append(req)
        return "job_1234567890123"

    def status(self, job):
        return {"status": "successful", "progress": 100}

    def result_urls(self, job):
        return [f"https://harmony.earthdata.nasa.gov/NISAR_frequencyA_{c}.tif"
                for c in CAPAS]

    def cancel(self, job):
        self.cancelado = True


def test_obtener_solo_4_geotiff_validos_con_trazabilidad(monkeypatch, tmp_path):
    data = {c: tiff(dtype="uint8" if c == "mask" else "float32") for c in CAPAS}
    monkeypatch.setattr(h.shutil, "disk_usage", lambda _: NS(free=2 * 1024**3))
    c = ClienteFake()
    def abrir(req, timeout):
        capa = h._etiqueta(req.full_url, CAPAS)
        return Respuesta(data[capa], req.full_url)
    spec = h.especificar(candidato(), AOI, caps())
    meta = h.obtener(spec, tmp_path, cliente=c, abrir=abrir, dormir=lambda _: None, limite_bytes=8 * 1024**2)
    assert meta["estado"] == "INSUMOS_GCOV_SIN_CLASIFICAR"
    assert meta["bytes_totales"] == sum(map(len, data.values()))
    assert set(a["capa"] for a in meta["archivos"]) == set(CAPAS)
    assert all(len(a["sha256"]) == 64 for a in meta["archivos"])
    final = tmp_path / meta["carpeta_relativa"]
    assert (final / "manifest.json").exists()
    assert not list(tmp_path.glob(".preparando-*"))
    assert h.obtener(spec, tmp_path, cliente=c, abrir=abrir, limite_bytes=8 * 1024**2) == meta
    assert len(c.solicitudes) == 1
    assert c.solicitudes[0].crs is None  # mantener resolución nativa


def test_no_publicar_si_capas_no_coinciden(monkeypatch, tmp_path):
    monkeypatch.setattr(h.shutil, "disk_usage", lambda _: NS(free=2 * 1024**3))
    c = ClienteFake()
    c.result_urls = lambda _: ["https://harmony.earthdata.nasa.gov/NISAR_frequencyA_HHHH.tif"]
    with pytest.raises(h.ErrorHarmony, match="Faltan capas"):
        h.obtener(h.especificar(candidato(), AOI, caps()), tmp_path, cliente=c,
                  dormir=lambda _: None)
    assert c.cancelado
    assert not list(tmp_path.glob(".preparando-*"))


def test_cap_8_mb_es_pequeno_para_hdf5_pero_suficiente_cog(monkeypatch, tmp_path):
    monkeypatch.setattr(h.shutil, "disk_usage", lambda _: NS(free=2 * 1024**3))
    spec = h.especificar(candidato(), AOI, caps())
    c = ClienteFake()
    c.status = lambda _: {"status": "failed"}
    with pytest.raises(h.ErrorHarmony):
        h.obtener(spec, tmp_path, cliente=c, dormir=lambda _: None, limite_bytes=8 * 1024**2)
    assert not any(p.suffix == ".h5" for p in tmp_path.rglob("*"))
