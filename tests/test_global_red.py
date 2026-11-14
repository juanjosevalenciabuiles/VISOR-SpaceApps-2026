"""Comprobaciones REALES de los servicios cartográficos y del catálogo fuera de Colombia (GLO-04…07, 09, 11).

No corren por defecto ni en la CI ordinaria: solo en el trabajo manual «red» de GitHub Actions o con

    VISOR_PRUEBAS_RED=1 python -m pytest -q -m red --ignore=tests/e2e

Respetan las políticas de uso: Nominatim a lo sumo una consulta por segundo (lo impone utils/lugares.py),
una sola tesela por proveedor y ciudad, metadatos de ASF sin credenciales ni descargas.
Un fallo aquí dice qué servicio no está disponible desde ese entorno; no se oculta con datos simulados.
"""
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import buscador_sar as bus  # noqa: E402
from utils import lugares, mapas_base  # noqa: E402

pytestmark = [
    pytest.mark.red,
    pytest.mark.skipif(os.environ.get("VISOR_PRUEBAS_RED") != "1", reason="consulta real: requiere VISOR_PRUEBAS_RED=1"),
]

CIUDADES = {   # consulta → (país esperado en la respuesta, lat, lon)
    "Chigorodó, Antioquia": ("Colombia", 7.67, -76.68),
    "Paris France": ("France", 48.86, 2.35),
    "Nairobi Kenya": ("Kenya", -1.29, 36.82),
    "Tokyo Japan": ("Japan", 35.68, 139.69),
    "Sydney Australia": ("Australia", -33.87, 151.21),
}


@pytest.fixture(autouse=True)
def nominatim_publico(monkeypatch):
    monkeypatch.delenv("VISOR_GEOCODIFICADOR_URL", raising=False)       # proveedor por defecto


@pytest.mark.parametrize("consulta", list(CIUDADES))
def test_geocodificador_real_en_cinco_continentes(consulta):
    pais, lat, lon = CIUDADES[consulta]
    encontrados, fuente, aviso = lugares.buscar(consulta)
    assert aviso is None and fuente == lugares.EN_LINEA, aviso
    primero = encontrados[0]
    assert abs(primero.latitud - lat) < 0.6 and abs(primero.longitud - lon) < 0.6, primero
    assert primero.pais, primero


def _tesela(url: str) -> tuple[int, str]:
    peticion = urllib.request.Request(url, headers={"User-Agent": lugares.AGENTE})
    with urllib.request.urlopen(peticion, timeout=20) as r:
        return r.status, r.headers.get("Content-Type", "")


@pytest.mark.parametrize("clave", mapas_base.ofrecidos())
def test_teselas_reales_de_cada_mapa_base_ofrecido(clave):
    """Una tesela por fondo ofrecido, en una ciudad de cada continente (zoom 6)."""
    mapa = mapas_base.MAPAS_BASE[clave]
    plantilla = mapas_base.url_teselas(mapa).replace("{s}", (mapa.subdominios or "a")[:1]).replace("{r}", "")
    import math
    for _, lat, lon in CIUDADES.values():
        z = 6
        x = int((lon + 180) / 360 * 2 ** z)
        y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z)
        estado, tipo = _tesela(plantilla.format(z=z, x=x, y=y))
        assert estado == 200 and tipo.startswith("image/"), (clave, lat, lon, estado, tipo)


@pytest.mark.parametrize("nombre,zona", [
    ("Nairobi", (36.70, -1.40, 36.95, -1.15)),
    ("Sídney", (151.05, -33.95, 151.30, -33.75)),
    ("Tokio", (139.60, 35.60, 139.85, 35.80)),
])
def test_catalogo_asf_real_fuera_de_colombia(nombre, zona):
    """Hay imágenes Sentinel-1 en el catálogo en otros continentes. Encontrarlas NO significa que haya
    RTC procesados ni un análisis validado allí."""
    fin = datetime.now(timezone.utc).date()
    r = bus.buscar(*zona, fin - timedelta(days=120), fin)
    assert r.escenas, f"{nombre}: ASF no devolvió escenas Sentinel-1 en 120 días"
    assert all(e.plataforma.startswith("S1") for e in r.escenas)
