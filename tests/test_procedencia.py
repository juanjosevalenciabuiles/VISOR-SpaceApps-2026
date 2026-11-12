"""Estados de procedencia: REAL SIN VALIDAR y VALIDADO nunca se asignan por defecto."""
import copy
import json

import numpy as np
import rasterio
from rasterio.transform import from_origin

from utils import procedencia as p
from utils.geotiff import leer_geotiff


def ficha_completa(sha: str, estado: str = p.REAL_SIN_VALIDAR) -> dict:
    return {
        "esquema": p.ESQUEMA_FICHA,
        "procedencia": {
            "estado": estado,
            "sensor": "Sentinel-1C · SAR banda C",
            "fechas": ["2026-09-24", "2026-10-06"],
            "polarizaciones": ["VV", "VH"],
            "metodo": "Diferencia de retrodispersión con umbral",
            "entradas": [{"archivo": "a.tif", "sha256": "0" * 64}],
            "generado_por": {"funcion": "utils.combinacion_sar.combinar_vv_vh"},
            "archivo": {"nombre": "x.tif", "sha256": sha},
        },
    }


def tif(ruta, tags=None):
    datos = np.array([[0, 1], [2, 3]], dtype="uint8")
    with rasterio.open(ruta, "w", driver="GTiff", height=2, width=2, count=1, dtype="uint8",
                       crs="EPSG:32618", transform=from_origin(250000, 850000, 30, 30), nodata=255) as dst:
        dst.write(datos, 1)
        if tags:
            dst.update_tags(**tags)
    return ruta


def test_sin_ficha_es_no_declarada_y_nunca_real():
    e = p.evaluar(False, None)
    assert e.estado == p.NO_DECLARADA and not e.es_real
    assert e.etiqueta == "PROCEDENCIA NO DECLARADA"


def test_demo_manda_aunque_la_ficha_diga_otra_cosa():
    assert p.evaluar(True, ficha_completa("a" * 64)).estado == p.DEMO
    assert p.evaluar(False, {"procedencia": {"estado": "demo"}}).estado == p.DEMO


def test_ficha_completa_y_huella_correcta_es_real_sin_validar():
    e = p.evaluar(False, ficha_completa("ab" * 32), "AB" * 32)
    assert e.estado == p.REAL_SIN_VALIDAR and e.etiqueta == "REAL SIN VALIDAR"


def test_cada_campo_de_trazabilidad_es_obligatorio():
    for campo in p.CAMPOS_TRAZABILIDAD:
        f = ficha_completa("ab" * 32)
        f["procedencia"][campo] = [] if campo in ("fechas", "polarizaciones", "entradas") else ""
        e = p.evaluar(False, f, "ab" * 32)
        assert e.estado == p.NO_DECLARADA and campo in e.faltantes, campo


def test_estado_desconocido_o_ausente_no_es_real():
    for estado in (None, "", "real", "confirmado", "inundacion"):
        f = ficha_completa("ab" * 32)
        f["procedencia"]["estado"] = estado
        assert p.evaluar(False, f, "ab" * 32).estado == p.NO_DECLARADA
    assert p.evaluar(False, {"fuente": "Sentinel-1"}).estado == p.NO_DECLARADA   # sin bloque


def test_huella_ausente_o_distinta_rechaza_la_ficha():
    f = ficha_completa("ab" * 32)
    assert p.evaluar(False, f, "cd" * 32).estado == p.NO_DECLARADA
    assert "no corresponde" in p.evaluar(False, f, "cd" * 32).motivo
    assert p.evaluar(False, f, None).estado == p.NO_DECLARADA
    del f["procedencia"]["archivo"]["sha256"]
    assert p.evaluar(False, f, "ab" * 32).estado == p.NO_DECLARADA


def test_validado_exige_evidencia_documentada():
    f = ficha_completa("ab" * 32, p.VALIDADO)
    e = p.evaluar(False, f, "ab" * 32)
    assert e.estado == p.REAL_SIN_VALIDAR and "validacion.referencia" in e.faltantes
    f["procedencia"]["validacion"] = {"responsable": "Equipo", "fecha": "2026-11-20",
                                      "metodo": "Comparación con imagen óptica", "referencia": "informe.pdf"}
    assert p.evaluar(False, f, "ab" * 32).estado == p.VALIDADO


def test_el_cargador_evalua_la_procedencia(tmp_path):
    sin_ficha = leer_geotiff(tif(tmp_path / "a.tif"), categorico=True)
    assert sin_ficha.procedencia.estado == p.NO_DECLARADA and sin_ficha.ficha is None

    demo = leer_geotiff(tif(tmp_path / "d.tif", {"VISOR_DEMO": "1"}), categorico=True)
    assert demo.procedencia.estado == p.DEMO

    ruta = tif(tmp_path / "r.tif")
    ficha = ficha_completa(p.sha256_archivo(ruta))
    ruta.with_suffix(".json").write_text(json.dumps(ficha), encoding="utf-8")
    real = leer_geotiff(ruta, categorico=True)
    assert real.procedencia.estado == p.REAL_SIN_VALIDAR and real.ficha["procedencia"]["sensor"]

    # Si el GeoTIFF cambia después de escribir la ficha, la ficha deja de valer.
    with rasterio.open(ruta, "r+") as dst:
        dst.write(np.array([[1, 1], [1, 1]], dtype="uint8"), 1)
    assert leer_geotiff(ruta, categorico=True).procedencia.estado == p.NO_DECLARADA


def test_una_ficha_ajena_no_sirve_para_otro_archivo(tmp_path):
    a, b = tif(tmp_path / "a.tif"), tif(tmp_path / "b.tif", {"OTRO": "1"})
    ficha = ficha_completa(p.sha256_archivo(a))
    b.with_suffix(".json").write_text(json.dumps(copy.deepcopy(ficha)), encoding="utf-8")
    assert leer_geotiff(b, categorico=True).procedencia.estado == p.NO_DECLARADA
