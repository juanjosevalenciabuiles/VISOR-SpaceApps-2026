"""Fase C: catálogo ASF → RTC locales → motor → resultados (sin red ni HyP3).

El catálogo es la respuesta real de ASF guardada en tests/datos/ (solo
metadatos). Los RTC son SINTÉTICOS, con nombres de HyP3 que derivan de las
escenas del par recomendado de Chigorodó.
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils import buscador_sar as bus  # noqa: E402
from utils import flujo_sar as flujo  # noqa: E402
from utils import procedencia  # noqa: E402
from utils.analisis_sar import ErrorSAR  # noqa: E402
from utils.config import AOI_CHIGORODO  # noqa: E402

REAL = json.loads((RAIZ / "tests" / "datos" / "asf_chigorodo_20260920_20261010.json").read_text(encoding="utf-8"))


def buscar_sin_red():
    """`buscar` completo, con la red sustituida por la respuesta guardada."""
    class Respuesta:
        def __init__(self, cuerpo):
            self.cuerpo = cuerpo

        def read(self):
            return self.cuerpo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return bus.buscar(-76.85, 7.40, -76.40, 7.95, "2026-09-20", "2026-10-10",
                      abrir=lambda *a, **k: Respuesta(json.dumps(REAL).encode()), hoy=date(2026, 11, 12))


def rtc(carpeta: Path, inicio: str, pol: str, baja: tuple[int, int] | None = None, ident="1A2B") -> Path:
    """RTC sintético (potencia, 300 m) que cubre el AOI de Chigorodó."""
    o, s, e, n = transform_bounds("EPSG:4326", "EPSG:32618", *AOI_CHIGORODO)
    lado = int((max(e - o, n - s) + 6000) // 300)
    datos = np.full((lado, lado), 0.1, dtype="float32")
    if baja:
        datos[baja[0]:baja[1]] = 0.01                               # −10 dB
    ruta = carpeta / f"S1C_IW_{inicio}_DVP_RTC30_G_gpuned_{ident}_{pol}.tif"
    with rasterio.open(ruta, "w", driver="GTiff", height=lado, width=lado, count=1, dtype="float32",
                       crs="EPSG:32618", transform=from_origin(o - 3000, n + 3000, 300, 300), nodata=0.0) as dst:
        dst.write(datos, 1)
    return ruta


@pytest.fixture
def par():
    r = buscar_sin_red()
    p = r.recomendado
    assert p.antes.inicio.strftime("%Y%m%dT%H%M%S") == "20260924T232218"
    assert p.despues.inicio.strftime("%Y%m%dT%H%M%S") == "20261006T232218"
    return p


def test_sin_rtc_se_informa_y_no_se_analiza(tmp_path, par):
    rtcs, avisos = flujo.rtc_locales(tmp_path / "no_existe")
    assert rtcs == [] and "No existe" in avisos[0]
    disp = flujo.disponibilidad(par, [])
    assert [d.polarizacion for d in disp] == ["VV", "VH"] and not any(d.completa for d in disp)
    with pytest.raises(ErrorSAR, match="faltan productos"):
        flujo.analizar_disponibles(par, disp, AOI_CHIGORODO, {"VV": 3, "VH": 3}, carpeta_salida=tmp_path)


def test_asociacion_exacta_por_dia_y_nunca_entre_satelites(tmp_path, par):
    sar = tmp_path / "sar"
    sar.mkdir()
    rtc(sar, "20260924T232218", "VV")
    rtc(sar, "20261006T232218", "VV")
    rtc(sar, "20260924T231000", "VH")                                 # mismo día, otra hora
    (sar / "otro_nombre.tif").write_bytes((sar / "S1C_IW_20260924T232218_DVP_RTC30_G_gpuned_1A2B_VV.tif").read_bytes())
    s1a = rtc(sar, "20261006T232218", "VH", ident="9999")
    s1a.rename(sar / s1a.name.replace("S1C_", "S1A_"))               # otro satélite: no vale
    rtcs, avisos = flujo.rtc_locales(sar)
    assert any(a.startswith("otro_nombre.tif") for a in avisos)          # se informa, no se asocia
    assert all(r.ruta.name != "otro_nombre.tif" for r in rtcs)
    vv, vh = flujo.disponibilidad(par, rtcs)
    assert vv.completa and (vv.tipo_antes, vv.tipo_despues) == (flujo.EXACTA, flujo.EXACTA)
    assert vh.tipo_antes == flujo.MISMO_DIA and vh.despues is None and not vh.completa


def test_flujo_completo_genera_resultados_sin_sobrescribir(tmp_path, par):
    sar, salida = tmp_path / "sar", tmp_path / "analisis"
    sar.mkdir()
    for pol, baja in (("VV", (10, 20)), ("VH", (15, 30))):
        rtc(sar, "20260924T232218", pol)
        rtc(sar, "20261006T232218", pol, baja=baja, ident="3C4D")
    # Un producto previo con el mismo nombre (como el del equipo en Replit) debe quedar intacto.
    salida.mkdir()
    previo = salida / "coincidencia_VV_VH_20260924_20261006.tif"
    previo.write_bytes(b"producto del equipo")
    huella = procedencia.sha256_archivo(previo)

    rtcs, _ = flujo.rtc_locales(sar)
    disp = flujo.disponibilidad(par, rtcs)
    inf = flujo.analizar_disponibles(par, disp, AOI_CHIGORODO, {"VV": 7.5, "VH": 3.0}, ventana_speckle=1,
                                     carpeta_salida=salida, zona="Prueba sintética")
    assert procedencia.sha256_archivo(previo) == huella
    assert inf.combinado.name == "coincidencia_VV_VH_20260924_20261006_r2.tif"
    assert set(inf.analisis) == {"VV", "VH"}

    ficha = json.loads(inf.combinado.with_suffix(".json").read_text(encoding="utf-8"))
    assert ficha["procedencia"]["estado"] == procedencia.REAL_SIN_VALIDAR
    assert ficha["parametros"]["VV"]["umbral_disminucion_db"] == 7.5
    assert ficha["parametros"]["VH"]["umbral_disminucion_db"] == 3.0
    registro = json.loads(inf.registro.read_text(encoding="utf-8"))
    assert registro["par_catalogo_asf"]["antes"]["nombre"].startswith("S1C_IW_GRDH_1SDV_20260924T232218")
    assert registro["par_catalogo_asf"]["validado_cientificamente"] is False
    assert registro["rtc"][0]["asociacion_antes"] == flujo.EXACTA
    assert registro["parametros"]["VV"]["umbral_disminucion_db"] == 7.5
    assert inf.combinado.name in registro["salidas"]

    # Una segunda ejecución tampoco sobrescribe: crea _r3.
    inf2 = flujo.analizar_disponibles(par, disp, AOI_CHIGORODO, {"VV": 3.0, "VH": 3.0}, ventana_speckle=1,
                                      carpeta_salida=salida)
    assert inf2.combinado.name.endswith("_r3.tif") and inf2.analisis["VV"].name.startswith("cambio_VV_20260924_20261006_r2")


def test_prefijo_libre(tmp_path):
    assert flujo.prefijo_libre(tmp_path, "a") == "a"
    (tmp_path / "a_mascara.tif").write_text("x")
    assert flujo.prefijo_libre(tmp_path, "a") == "a_r2"
    (tmp_path / "a_r2.json").write_text("x")
    assert flujo.prefijo_libre(tmp_path, "a") == "a_r3"
