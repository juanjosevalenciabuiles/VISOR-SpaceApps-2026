"""NISAR primero, sin descargas inesperadas ni resultados de inundación inventados."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from utils import nisar_auto as auto


def candidato(name, size, coverage=0.94, pol=("HH", "HV")):
    return NS(granule=name, tamano_bytes=size, cobertura=coverage,
              url_h5=f"https://nisar.asf.earthdatacloud.nasa.gov/{name}.h5",
              nombre=NS(pol_a=pol))


def resultado():
    a = candidato("NISAR_A", 1_640_000_000, coverage=.42)
    b = candidato("NISAR_B", 1_640_000_000, coverage=.41)
    c = candidato("NISAR_UNICA", 1_230_000_000, coverage=.94)
    par = NS(antes=a, despues=b, cobertura_comun=.41, polarizaciones_A=("HH", "HV"))
    return NS(region=NS(limites=(-76.8, 7.55, -76.55, 7.8)), pares=[par], candidatos=[a, b, c])


def test_plan_prefiere_par_pero_no_oculta_cobertura_incompleta():
    p = auto.planear(resultado(), max_gb=5)
    assert p.tipo == "PAR"
    assert p.granules == ("NISAR_A", "NISAR_B")
    assert p.termino == "HHHH"  # banda L, nunca VV ficticio
    assert p.tamano_bytes == 3_280_000_000
    assert p.cobertura == .41
    assert "NO declarar inundación" in " ".join(p.avisos)


def test_cuando_no_cabe_par_solo_entrega_una_fecha_no_inundacion():
    p = auto.planear(resultado(), max_gb=2)
    assert p.tipo == "ESCENA_UNICA"
    assert p.granules == ("NISAR_UNICA",)
    assert "NO permite identificar" in " ".join(p.avisos)


def test_sin_candidatos_bloquea_sin_sintetizar():
    r = resultado()
    r.pares = []
    r.candidatos = []
    with pytest.raises(auto.ErrorAutoNISAR, match="No se encontró"):
        auto.planear(r)


def test_presupuesto_invalido_bloqueado():
    with pytest.raises(auto.ErrorAutoNISAR):
        auto.planear(resultado(), max_gb=0)


def test_preparar_sin_token_no_usa_red(monkeypatch, tmp_path):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    p = auto.planear(resultado())
    with pytest.raises(auto.ErrorAutoNISAR, match="Secrets"):
        auto.preparar(p, tmp_path / "registro.json", tmp_path / "crudos", tmp_path / "recortes")
    assert not list(tmp_path.glob("**/*.h5"))


def test_preparar_con_producto_simulado_no_lo_publica_como_nisar(monkeypatch, tmp_path):
    p = auto.planear(resultado(), max_gb=2)
    monkeypatch.setenv("EARTHDATA_TOKEN", "PRUEBA_NO_REAL")
    monkeypatch.setattr(auto.shutil, "disk_usage",
                        lambda *_: NS(free=20_000_000_000))
    llamadas = []
    def guardar_h5(_registro, granule, carpeta, _confirmo, avance=None):
        llamadas.append(granule)
        ruta = Path(carpeta) / (granule + ".h5")
        ruta.write_bytes(b"\x89HDF\r\n\x1a\n" + b"x" * 10)
        return ruta
    monkeypatch.setattr(auto.desc, "descargar", guardar_h5)
    monkeypatch.setattr(auto.gcov, "inspeccionar", lambda _: NS(es_nisar=False))
    registro = tmp_path / "registro.json"
    registro.write_text(json.dumps({"candidatos": []}))
    with pytest.raises(auto.ErrorAutoNISAR, match="no declara la misión NISAR"):
        auto.preparar(p, registro, tmp_path / "crudos", tmp_path / "recortes")
    assert llamadas == ["NISAR_UNICA"]
    assert not list((tmp_path / "recortes").glob("*.tif")) if (tmp_path / "recortes").exists() else True
