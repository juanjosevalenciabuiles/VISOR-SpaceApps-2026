"""Descarga controlada de NISAR: todo con servidor simulado. No se contacta a ASF."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from utils import nisar_descarga as d

GRANULE = "NISAR_L2_PR_GCOV_030_048_A_012_2005_DHDH_A_20261024T231500_20261024T231550_P05036_N_F_J_001"
URL = f"https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GCOV_V1/{GRANULE}/{GRANULE}.h5"
CUERPO = b"\x89HDF\r\n\x1a\n" + b"x" * 5000


@pytest.fixture
def registro(tmp_path):
    p = tmp_path / "busqueda.json"
    p.write_text(json.dumps({"candidatos": [{"granule": GRANULE, "url_h5": URL, "tamano_bytes": len(CUERPO)}]}))
    return p


class Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def servidor(cuerpo=CUERPO, registro=None):
    def abrir(peticion, timeout=None):
        if registro is not None:
            registro.append(peticion)
        if isinstance(cuerpo, Exception):
            raise cuerpo
        return Respuesta(cuerpo)
    return abrir


def test_sin_confirmar_el_tamano_solo_informa(registro, tmp_path, monkeypatch):
    monkeypatch.setenv(d.VARIABLE_TOKEN, "secreto")
    pedidos = []
    with pytest.raises(d.ErrorDescarga, match="confírmalo con --confirmo-gb"):
        d.descargar(registro, GRANULE, tmp_path / "crudos", None, abrir=servidor(registro=pedidos))
    with pytest.raises(d.ErrorDescarga, match="confírmalo"):
        d.descargar(registro, GRANULE, tmp_path / "crudos", 0.000001, abrir=servidor(registro=pedidos))
    assert pedidos == [] and not list((tmp_path / "crudos").glob("*")) if (tmp_path / "crudos").exists() else True


def test_sin_token_no_hay_peticion(registro, tmp_path, monkeypatch):
    monkeypatch.delenv(d.VARIABLE_TOKEN, raising=False)
    pedidos = []
    with pytest.raises(d.ErrorDescarga, match="EARTHDATA_TOKEN"):
        d.descargar(registro, GRANULE, tmp_path / "crudos", 1.0, abrir=servidor(registro=pedidos))
    assert pedidos == []


def test_descarga_confirmada_y_token_solo_en_la_cabecera(registro, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(d.VARIABLE_TOKEN, "secreto-123")
    pedidos = []
    destino = d.descargar(registro, GRANULE, tmp_path / "crudos", 1.0, abrir=servidor(registro=pedidos))
    assert destino.read_bytes() == CUERPO and destino.name == f"{GRANULE}.h5"
    assert pedidos[0].get_header("Authorization") == "Bearer secreto-123" and pedidos[0].full_url == URL
    assert not list(destino.parent.glob("*.part"))
    salida = capsys.readouterr()
    assert "secreto-123" not in salida.out + salida.err
    with pytest.raises(d.ErrorDescarga, match="no se sobrescribe"):
        d.descargar(registro, GRANULE, tmp_path / "crudos", 1.0, abrir=servidor())


@pytest.mark.parametrize("cuerpo, mensaje", [
    (CUERPO[:100], "incompleta"),
    (CUERPO + b"de mas", "más datos"),
    (urllib.error.HTTPError(URL, 401, "x", {}, None), "credencial rechazada"),
    (urllib.error.URLError("sin red"), "No se pudo completar"),
])
def test_fallos_no_dejan_archivos(registro, tmp_path, monkeypatch, cuerpo, mensaje):
    monkeypatch.setenv(d.VARIABLE_TOKEN, "secreto")
    with pytest.raises(d.ErrorDescarga, match=mensaje) as e:
        d.descargar(registro, GRANULE, tmp_path / "crudos", 1.0, abrir=servidor(cuerpo))
    assert "secreto" not in str(e.value)
    assert list((tmp_path / "crudos").glob("*")) == []


def test_sin_espacio_en_disco(registro, tmp_path, monkeypatch):
    monkeypatch.setenv(d.VARIABLE_TOKEN, "secreto")
    with pytest.raises(d.ErrorDescarga, match="Espacio insuficiente"):
        d.descargar(registro, GRANULE, tmp_path / "crudos", 1.0, abrir=servidor(), libre_bytes=len(CUERPO))


@pytest.mark.parametrize("cambio, mensaje", [
    ({"url_h5": "https://ejemplo.com/x.h5"}, "servidor de ASF"),
    ({"url_h5": "http://nisar.asf.earthdatacloud.nasa.gov/x.h5"}, "enlace https"),
    ({"tamano_bytes": None}, "no informa el tamaño"),
    ({"granule": "OTRO"}, "no está en el registro"),
])
def test_registro_incompleto_o_ajeno(tmp_path, monkeypatch, cambio, mensaje):
    monkeypatch.setenv(d.VARIABLE_TOKEN, "secreto")
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"candidatos": [{"granule": GRANULE, "url_h5": URL, "tamano_bytes": 10} | cambio]}))
    with pytest.raises(d.ErrorDescarga, match=mensaje):
        d.descargar(p, GRANULE, tmp_path / "crudos", 1.0, abrir=servidor())


def test_la_credencial_no_se_reenvia_a_otro_servidor():
    manejador = d._SinReenviarCredencial()
    pet = urllib.request.Request(URL, headers={"Authorization": "Bearer secreto"})
    otra = manejador.redirect_request(pet, None, 302, "Found", {}, "https://bucket.s3.amazonaws.com/x.h5?firma=1")
    misma = manejador.redirect_request(pet, None, 302, "Found", {}, URL + "?v=2")
    assert otra.get_header("Authorization") is None and misma.get_header("Authorization") == "Bearer secreto"
