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


# ---------------------------------------------------------------------------
# Ningún error puede quedar oculto
# ---------------------------------------------------------------------------

def test_una_excepcion_inesperada_es_fallo_critico():
    inf = v.Informe()

    def rota():
        raise KeyError("campo_que_no_existe")
    assert inf.protegido("X-01", "x", "etapa rota", rota) is None
    c = inf.comprobaciones[-1]
    assert (c.estado, c.nivel) == (v.FALLIDA, v.CRITICO) and "KeyError" in c.detalle
    assert inf.veredicto == v.NO_APTO
    assert inf.protegido("X-02", "x", "etapa sana", lambda: 7) == 7 and len(inf.comprobaciones) == 1


def test_un_archivo_que_rompe_la_auditoria_no_oculta_los_demas(tmp_path, monkeypatch):
    from utils import resultados
    analisis = datos_sinteticos(tmp_path)
    original = resultados.leer_resultado

    def falla_con_uno(ruta, *a, **k):
        if ruta.name == "coincidencia_VV_VH_Chigorodo.tif":
            raise RuntimeError("fallo simulado")
        return original(ruta, *a, **k)
    monkeypatch.setattr(resultados, "leer_resultado", falla_con_uno)
    inf = v.Informe()
    v.auditar_resultados(inf, analisis, None)
    e = estados(inf)
    fallidas = [c for c in inf.comprobaciones if c.estado == v.FALLIDA]
    assert any("RuntimeError" in c.detalle and "Chigorodo" in c.descripcion for c in fallidas)
    assert any(k.endswith("e") and e[k] == v.APROBADA for k in e), "el otro archivo se auditó igual"
    assert inf.veredicto == v.NO_APTO


def test_geotiff_danado_en_resultados_es_no_apto(tmp_path):
    analisis = datos_sinteticos(tmp_path)
    (analisis / "cambio_VV_20260924_20261006_mascara.tif").write_bytes(b"II*\x00no es un raster")
    inf = v.Informe()
    v.auditar_resultados(inf, analisis, None)
    assert inf.veredicto == v.NO_APTO
    assert any(c.estado == v.FALLIDA and "cambio_VV" in c.descripcion for c in inf.comprobaciones)


def test_cero_pruebas_recogidas_es_fallo_no_omision():
    sys.path.insert(0, str(RAIZ / "scripts"))
    import verificar_visor
    inf = v.Informe()
    verificar_visor.pytest_(inf, "PYT-T", "batería vacía", "marca_que_no_existe_en_ninguna_prueba", v.CRITICO, 300)
    c = inf.comprobaciones[-1]
    assert c.estado == v.FALLIDA and inf.veredicto == v.NO_APTO


# ---------------------------------------------------------------------------
# NISAR
# ---------------------------------------------------------------------------

def _recorte_nisar(tmp_path):
    from tests import nisar_sintetico as sint
    from utils import nisar_gcov
    h5 = sint.gcov(tmp_path / "a.h5", n=1500)
    return nisar_gcov.exportar_recorte(h5, (-76.70, 7.62, -76.66, 7.66), carpeta=tmp_path / "nisar")


def test_nisar_sin_recortes_se_omite(tmp_path):
    inf = v.Informe()
    v.auditar_nisar(inf, tmp_path / "nisar")
    assert estados(inf) == {"NIS-00": v.OMITIDA} and inf.veredicto != v.NO_APTO


def test_nisar_recorte_correcto_aprueba(tmp_path):
    _recorte_nisar(tmp_path)
    inf = v.Informe()
    v.auditar_nisar(inf, tmp_path / "nisar")
    assert set(estados(inf).values()) == {v.APROBADA} and len(inf.comprobaciones) == 4


def test_nisar_recorte_alterado_es_no_apto(tmp_path):
    import rasterio
    ruta = _recorte_nisar(tmp_path)
    with rasterio.open(ruta, "r+") as dst:
        dst.update_tags(POLARIZACION="VV")                 # HH rotulado como VV y archivo modificado
    inf = v.Informe()
    v.auditar_nisar(inf, tmp_path / "nisar")
    e = estados(inf)
    assert e["NIS-01a"] == v.FALLIDA and e["NIS-01c"] == v.FALLIDA and inf.veredicto == v.NO_APTO


def test_ficha_descriptiva_del_motor_no_es_fallo(tmp_path):
    """Las máscaras del motor llevan un JSON descriptivo (fuente, fecha, producto, unidades) sin
    bloque `procedencia`: el verificador las trata como NO DECLARADAS, no como ficha que no coincide.
    Así ocurre con los productos reales de Chigorodó (12-nov-2026)."""
    from test_analisis_sar import ANTES, DESPUES, campo, crear_rtc

    from utils.analisis_sar import ParametrosCambio, analizar_par

    despues = campo()
    despues[10:20, 10:20] = 0.005                      # −23 dB: disminución marcada
    a = crear_rtc(tmp_path / ANTES, campo())
    d = crear_rtc(tmp_path / DESPUES, despues)
    analisis = tmp_path / "analisis"
    analizar_par(a, d, analisis, parametros=ParametrosCambio(ventana_speckle=1))
    lateral = next(analisis.glob("*_mascara.json"))
    assert "procedencia" not in json.loads(lateral.read_text(encoding="utf-8"))

    inf = v.Informe()
    v.auditar_resultados(inf, analisis, None)
    e = {c.id: c for c in inf.comprobaciones}
    fichas = [c for k, c in e.items() if k.startswith("DAT-") and k.endswith("e")]
    assert fichas and all(c.estado == v.APROBADA for c in fichas), [(c.id, c.detalle) for c in fichas]
    assert inf.veredicto != v.NO_APTO, [(c.id, c.estado) for c in inf.comprobaciones]
