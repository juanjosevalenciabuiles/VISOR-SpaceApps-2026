"""El verificador integral: veredicto, auditoría de datos y garantía de solo lectura."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))

from test_resultados import exploratorio, reproducible  # noqa: E402
from utils import verificacion as v  # noqa: E402


def test_veredicto():
    inf = v.Informe()
    inf.agregar("A", "x", "a", "c", v.CRITICO, v.APROBADA)
    assert inf.veredicto == v.APTO
    inf.agregar("B", "x", "b", "c", v.INFORMATIVO, v.OMITIDA)
    assert inf.veredicto == v.APTO
    inf.agregar("C", "x", "c", "c", v.IMPORTANTE, v.ADVERTENCIA)
    assert inf.veredicto == v.APTO_ADVERTENCIAS
    inf.agregar("D", "x", "d", "c", v.IMPORTANTE, v.FALLIDA)
    assert inf.veredicto == v.NO_APTO
    otro = v.Informe()
    otro.agregar("E", "x", "e", "c", v.CRITICO, v.OMITIDA)
    assert otro.veredicto == v.APTO_ADVERTENCIAS, "lo crítico sin comprobar no puede dar APTO"
    md = inf.a_markdown()
    assert "**Veredicto: NO APTO**" in md and "Requiere atención" in md and "Criterios del veredicto" in md
    assert json.loads(inf.a_json())["veredicto"] == v.NO_APTO


def test_huellas_detectan_cualquier_cambio(tmp_path):
    (tmp_path / "a.tif").write_bytes(b"1")
    antes = v.huellas(tmp_path)
    assert v.diferencias_huellas(antes, v.huellas(tmp_path)) == []
    (tmp_path / "a.tif").write_bytes(b"2")
    (tmp_path / "b.tif").write_bytes(b"3")
    cambios = v.diferencias_huellas(antes, v.huellas(tmp_path))
    assert "modificado: a.tif" in cambios and "nuevo: b.tif" in cambios


def referencia_sintetica(carpeta: Path) -> dict:
    """Referencia con los conteos de los rásteres sintéticos (40×40) de las pruebas."""
    return {
        "cuadricula": {"crs": "EPSG:32618", "ancho": 40, "alto": 40, "nodata": 255, "pixeles_sin_dato": 40},
        "productos": {
            "coincidencia_VV_VH_Chigorodo.tif": {"procedencia": "no_declarada",
                                                 "clases": {"0": 960, "1": 200, "2": 200, "3": 200}},
            "coincidencia_VV_VH_20260924_20261006.tif": {"procedencia": "real_sin_validar",
                                                         "clases": {"0": 960, "1": 200, "2": 200, "3": 200},
                                                         "umbrales_db": {"VV": 7.5, "VH": 3.0}},
        },
        "comparacion": {"a": "coincidencia_VV_VH_20260924_20261006.tif", "b": "coincidencia_VV_VH_Chigorodo.tif",
                        "equivalentes": False, "pixeles_distintos": 80},
    }


def datos_sinteticos(carpeta: Path) -> Path:
    analisis = carpeta / "analisis"
    analisis.mkdir(parents=True)
    expl = exploratorio(analisis / "coincidencia_VV_VH_Chigorodo.tif")
    reproducible(analisis)
    shutil.rmtree(analisis / "entradas")
    # Como en Chigorodó: el exploratorio difiere del reproducible en una zona (aquí 80 píxeles).
    with rasterio.open(expl, "r+") as dst:
        d = dst.read(1)
        d[20:22] = np.where(d[20:22] == 0, 1, d[20:22])
        dst.write(d, 1)
    return analisis


def estados(inf):
    return {c.id: c.estado for c in inf.comprobaciones}


def test_auditoria_de_datos_con_referencia(tmp_path):
    analisis = datos_sinteticos(tmp_path)
    ref = referencia_sintetica(tmp_path)
    ref["productos"]["coincidencia_VV_VH_Chigorodo.tif"]["clases"] = {"0": 880, "1": 280, "2": 200, "3": 200}
    inf = v.Informe()
    v.auditar_resultados(inf, analisis, ref)
    e = estados(inf)
    assert all(e[k] == v.APROBADA for k in e if k.endswith(("a", "b", "d", "f", "g", "h", "i"))), e
    assert e["DAT-CMP"] == v.APROBADA, "la diferencia documentada se mantiene: no se exige equivalencia"
    assert inf.veredicto == v.APTO

    # Si la diferencia cambia (p. ej. alguien regeneró un archivo), se advierte; no se «corrige».
    ref["comparacion"]["pixeles_distintos"] = 15860
    inf = v.Informe()
    v.auditar_resultados(inf, analisis, ref)
    assert estados(inf)["DAT-CMP"] == v.ADVERTENCIA and inf.veredicto == v.APTO_ADVERTENCIAS


def test_ficha_que_no_corresponde_es_fallo_critico(tmp_path):
    analisis = datos_sinteticos(tmp_path)
    with rasterio.open(analisis / "coincidencia_VV_VH_20260924_20261006.tif", "r+") as dst:
        d = dst.read(1)
        d[0, 0] = 3
        dst.write(d, 1)
    inf = v.Informe()
    v.auditar_resultados(inf, analisis, None)
    fallo = [c for c in inf.comprobaciones if c.estado == v.FALLIDA]
    assert any("SHA-256" in c.descripcion for c in fallo) and inf.veredicto == v.NO_APTO


def test_verificador_completo_no_modifica_datos(tmp_path):
    datos = tmp_path / "data"
    datos.mkdir()
    for p in (RAIZ / "data").glob("*.tif"):
        shutil.copy2(p, datos / p.name)
    if (RAIZ / "data" / "contexto").is_dir():
        shutil.copytree(RAIZ / "data" / "contexto", datos / "contexto")
    datos_sinteticos(datos)
    antes = v.huellas(datos)
    salida = tmp_path / "informes"
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "verificar_visor.py"), "--sin-pytest",
                        "--sin-navegador", "--salida", str(salida)], cwd=RAIZ, capture_output=True, text=True,
                       timeout=900, env={**os.environ, "VISOR_DATA_DIR": str(datos)})
    assert "VEREDICTO:" in r.stdout, r.stdout + r.stderr
    assert v.huellas(datos) == antes
    informe = json.loads(next(salida.glob("*.json")).read_text(encoding="utf-8"))
    e = {c["id"]: c["estado"] for c in informe["comprobaciones"]}
    assert e["DAT-RO"] == v.APROBADA and e["APP-01"] == v.APROBADA and e["E2E-01"] == v.OMITIDA
    # Los sintéticos no coinciden con la referencia real de Chigorodó: advertencia, nunca un «arreglo».
    assert v.ADVERTENCIA in {c["estado"] for c in informe["comprobaciones"] if c["id"].endswith("g")}
    assert informe["veredicto"] in (v.APTO_ADVERTENCIAS, v.NO_APTO)
    assert (salida / next(salida.glob("*.md")).name).read_text(encoding="utf-8").startswith("# Informe")
