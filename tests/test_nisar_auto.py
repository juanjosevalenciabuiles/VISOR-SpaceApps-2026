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



def test_harmony_presupuesto_1gib_por_par_y_saldo_entre_fechas(monkeypatch, tmp_path):
    """No descarga nada real: ambas fechas comparten UN presupuesto total."""
    from utils import nisar_harmony as harmony

    plan = auto.planear(resultado(), max_gb=5)
    fake_caps = {"madurez": "VALIDATED"}
    monkeypatch.setattr(auto.shutil, "disk_usage", lambda _: NS(free=3 * 1024**3))
    monkeypatch.setattr(harmony, "especificar", lambda c, aoi, caps, **kw: NS(
        granule=c.granule, bbox=aoi, solo_cambio=kw.get("solo_cambio")
    ))
    llamadas = []

    def obtener(spec, carpeta, **kwargs):
        llamadas.append((spec, kwargs["limite_bytes"]))
        return {"bytes_totales": 450 * 1024**2, "carpeta_relativa": spec.granule,
                "archivos": [{"archivo": "HHHH.tif"}]}

    monkeypatch.setattr(harmony, "obtener", obtener)
    plan.id_par_seleccionado = "id_de_prueba"
    salida = auto.preparar_harmony(
        plan, carpeta=tmp_path, max_mb=1024, caps=fake_caps, cliente=object()
    )
    assert len(llamadas) == 2
    assert llamadas[0][1] == 1024 * 1024**2
    assert llamadas[1][1] == (1024 - 450) * 1024**2
    assert all(c[0].solo_cambio is True for c in llamadas)
    assert salida["bytes_totales"] == 900 * 1024**2
    assert len(salida["escenas"]) == 2


def test_harmony_limite_1gib_no_permite_sobrepasar_ni_descargar_sin_espacio(
    monkeypatch, tmp_path,
):
    """1 GiB es techo, no permiso para agotar el disco ni abrir red."""
    plan = auto.planear(resultado(), max_gb=5)
    llamadas = []
    monkeypatch.setattr(auto.shutil, "disk_usage", lambda _: NS(free=1300 * 1024**2))
    from utils import nisar_harmony as harmony
    monkeypatch.setattr(harmony, "especificar",
                        lambda *a, **kw: llamadas.append("spec"))
    monkeypatch.setattr(harmony, "obtener",
                        lambda *a, **kw: llamadas.append("descarga"))
    with pytest.raises(auto.ErrorAutoNISAR, match="Espacio insuficiente"):
        auto.preparar_harmony(
            plan, carpeta=tmp_path, max_mb=1024,
            caps={"madurez": "VALIDATED"}, cliente=object(),
        )
    with pytest.raises(auto.ErrorAutoNISAR, match="64 y 1024"):
        auto.preparar_harmony(
            plan, carpeta=tmp_path, max_mb=1025,
            caps={"madurez": "VALIDATED"}, cliente=object(),
        )
    assert not llamadas, "el control de recursos ocurre antes de crear solicitudes"
