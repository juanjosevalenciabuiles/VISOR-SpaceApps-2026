"""Paso «05 · Regional» en Mission Control (AppTest). Límites, máscara y JRC SINTÉTICOS."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import rasterio

from tests.test_regiones import SINTETICOS, rect
from tests.test_sar_jrc import chigorodo_sintetico
from utils import qgis, regiones, resultados, sar_jrc

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Máscara y JRC con el histograma de QGIS (ubicaciones inventadas) sobre «Chigorodó» y «Carepa»
    sintéticos; «Apartadó» y «Turbo» quedan fuera de la cuadrícula."""
    d = {n: tmp_path / n for n in ("analisis", "jrc", "limites", "aoi", "regional")}
    for c in d.values():
        c.mkdir()
    s, j = chigorodo_sintetico(d["analisis"])
    j = Path(shutil.move(j, d["jrc"] / j.name))
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"MPIO_CDPMP": c, "MPIO_CNMBR": n}, "geometry": rect(*b)}
        for c, (n, b) in SINTETICOS.items()]}
    (d["limites"] / "MGN_sintetico.geojson").write_text(json.dumps(fc), encoding="utf-8")
    monkeypatch.setattr(regiones, "CARPETA_LIMITES", d["limites"])
    monkeypatch.setattr(regiones, "CARPETA_AOI", d["aoi"])
    monkeypatch.setattr(sar_jrc, "CARPETA_JRC", d["jrc"])
    monkeypatch.setattr(sar_jrc, "CARPETA_ANALISIS", d["analisis"])
    monkeypatch.setattr(sar_jrc, "CARPETA_REGIONAL", d["regional"])
    monkeypatch.setattr(resultados, "CARPETA_ANALISIS", d["analisis"])
    monkeypatch.chdir(RAIZ)
    return d, s, j


def app():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=240).run()
    at.button(key="btn_sar").click().run()
    assert not at.exception, at.exception
    return at


def texto(at) -> str:
    return " ".join(m.value for m in at.markdown)


def test_sin_reproduccion_el_cruce_esta_bloqueado(entorno):
    at = app()
    assert at.multiselect(key="reg_municipios").value == list(regiones.PILOTO)
    assert at.button(key="reg_cruzar").disabled
    t = texto(at)
    assert "Falta reproducir con los GeoTIFF reales" in t
    assert "Piloto: Chigorodó, Carepa, Apartadó y Turbo" in t and "no implica que haya escenas" in t


def test_cobertura_parcial_visible_antes_de_analizar(entorno):
    t = texto(app())
    assert "<td>Turbo</td><td>0%</td>" in t and re.search(r"<td>Apartadó</td><td>[0-2]%</td>", t)
    assert "<td>Chigorodó</td><td>100%</td>" in t and re.search(r"<b>AOI</b></td><td><b>2\d%</b>", t)
    assert "SIN DATO, no «sin cambio»" in t and "<b>100%</b>" not in t


def test_cruce_por_municipio_con_nd_y_capas_exportables(entorno):
    d, s, j = entorno
    huellas = {p: sar_jrc.procedencia.sha256_archivo(p) for p in (s, j)}
    assert sar_jrc.reproducir_chigorodo(s, j)["resultado"] == "APROBADA"
    at = app()
    assert "Reproducción de Chigorodó APROBADA" in texto(at) and not at.button(key="reg_cruzar").disabled
    at.button(key="reg_cruzar").click().run()
    assert not at.exception, at.exception
    t = texto(at)
    assert "Sobre JRC ≥ 1 %" in t and "N/D" in t and "No confirma inundaciones" in t
    fila_turbo = t.split("<td>Turbo</td>")[-1].split("</tr>")[0]
    assert fila_turbo.count("N/D") >= 5 and "0.0 %" not in fila_turbo          # sin datos ≠ 0 %
    informe = json.loads(next(d["analisis"].glob("sar_jrc_*_informe.json")).read_text(encoding="utf-8"))
    assert informe["zonas"]["05837"]["sin_observaciones_validas"] and informe["zonas"]["05837"]["cobertura_cuadricula_pct"] == 0
    u1 = informe["global"]["umbrales_jrc"][0]
    assert 0 < u1["pixeles_sar_jrc"] <= 4004 and u1["denominador_detecciones"] == informe["global"]["detecciones"]
    assert f"{u1['pixeles_sar_jrc']:,} / {u1['denominador_detecciones']:,}" in t   # total con su denominador
    assert informe["aoi"]["sha256_fuente"] and informe["aoi"]["origen"] == "limites_oficiales"
    assert {p: sar_jrc.procedencia.sha256_archivo(p) for p in (s, j)} == huellas   # entradas intactas
    # Umbral ≥ 50 %: la tabla cambia con su propio denominador.
    at.button_group(key="reg_umbral").select(50).run()
    assert "Sobre JRC ≥ 50 %" in texto(at)
    # Las dos capas nuevas se reconocen, se dibujan y se exportan para QGIS.
    nuevos = [r for r in resultados.cargar_resultados() if r.ruta.name.startswith("sar_jrc_")]
    assert {r.perfil.clave for r in nuevos} == {sar_jrc.TIPO_COINCIDENCIA, sar_jrc.TIPO_POLARIZACIONES}
    for r in nuevos:
        assert r.dibujable, r.error
        _, paquete = qgis.exportar(r.ruta, r.perfil.clases, r.nombre)
        assert qgis.verificar_paquete(paquete, r.ruta, r.perfil.clases) == []
        with rasterio.open(r.ruta) as src:
            assert src.nodata == 255
    # Repetir reutiliza el resultado: no duplica archivos.
    at.button(key="reg_cruzar").click().run()
    assert "reutilizado" in texto(at) and len(list(d["analisis"].glob("sar_jrc_*_informe.json"))) == 1


def test_seleccion_de_un_solo_municipio_y_guardado_sin_sobrescribir(entorno):
    d, _, _ = entorno
    at = app()
    at.multiselect(key="reg_municipios").set_value(["05172"]).run()
    assert "AOI «Chigorodó»: 1 zona(s)" in texto(at)
    at.button(key="reg_guardar").click().run()
    at.button(key="reg_guardar").click().run()
    assert sorted(p.name for p in d["aoi"].glob("*.geojson")) == ["aoi_Chigorodo.geojson", "aoi_Chigorodo_r2.geojson"]
    at.multiselect(key="reg_municipios").set_value([]).run()
    assert "Elige al menos un municipio" in texto(at) and not any(b.key == "reg_cruzar" for b in at.button)


def test_sin_limites_oficiales_no_se_inventan_poligonos(entorno):
    d, _, _ = entorno
    (d["limites"] / "MGN_sintetico.geojson").unlink()
    at = app()
    assert "No se usan polígonos inventados" in texto(at)
    assert not any(b.key == "reg_cruzar" for b in at.button) and not at.exception


def test_sentinel1_sigue_igual(entorno):
    at = app()
    assert any(b.key == "sar_buscar" for b in at.button) and not at.exception
