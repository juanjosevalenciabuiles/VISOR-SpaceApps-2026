"""Seguridad: los textos que vienen de archivos (etiquetas del GeoTIFF, fichas JSON) nunca se
interpretan como HTML. Un metadato con <img onerror=…> debe aparecer escapado, no ejecutable."""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

ATAQUE = '<img src=x onerror="alert(1)">'


def _contaminado(ruta: Path, tags: dict, ficha: dict | None):
    datos = np.zeros((20, 20), "uint8")
    datos[:5] = 3
    with rasterio.open(ruta, "w", driver="GTiff", height=20, width=20, count=1, dtype="uint8",
                       crs="EPSG:32618", transform=from_origin(301_398, 862_610, 30, 30), nodata=255) as dst:
        dst.write(datos, 1)
        dst.update_tags(**tags)
    if ficha is not None:
        ruta.with_suffix(".json").write_text(json.dumps(ficha), encoding="utf-8")


def test_metadatos_maliciosos_se_muestran_escapados(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from utils import resultados

    datos = tmp_path / "data"
    datos.mkdir()
    for p in (RAIZ / "data").glob("*.tif"):
        shutil.copy2(p, datos / p.name)
    # Fenómeno: JSON lateral malicioso junto a la capa de inundaciones.
    (datos / "inundacion.json").write_text(json.dumps(
        {"fuente": ATAQUE, "fecha": ATAQUE, "producto": ATAQUE, "unidades": ATAQUE}), encoding="utf-8")
    analisis = datos / "analisis"
    analisis.mkdir()
    etiquetas = {"clase_1": "Disminucion solo VV " + ATAQUE, "clase_2": "Disminucion solo VH",
                 "clase_3": "Disminucion VV y VH", "descripcion": ATAQUE, "advertencia": ATAQUE,
                 "FECHA": ATAQUE, "POLARIZACION": ATAQUE, "PRODUCTO": ATAQUE}
    _contaminado(analisis / "malicioso.tif", etiquetas,
                 {"producto": ATAQUE, "fuente": ATAQUE, "limitaciones": [ATAQUE],
                  "procedencia": {"estado": "real_sin_validar", "sensor": ATAQUE, "fechas": [ATAQUE, ATAQUE],
                                  "polarizaciones": [ATAQUE], "metodo": ATAQUE, "entradas": [{"archivo": ATAQUE}],
                                  "generado_por": {"funcion": ATAQUE}, "archivo": {"sha256": "0" * 64}}})
    monkeypatch.setenv("VISOR_DATA_DIR", str(datos))
    monkeypatch.setattr(resultados, "CARPETA_ANALISIS", analisis)
    import utils.config as config
    monkeypatch.setattr(config, "DATA_DIR", datos)
    for f in config.FENOMENOS.values():
        monkeypatch.setattr(type(f), "ruta", property(lambda self, d=datos: d / self.archivo), raising=False)
    monkeypatch.chdir(RAIZ)

    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120).run()
    at.toggle(key="capa_sar").set_value(True).run()              # la DEMO (con su JSON malicioso), a propósito
    at.button(key="hist_ver_malicioso").click().run()
    at.button(key="btn_ayuda").click().run()
    assert not at.exception
    html = " ".join(str(m.value) for m in at.markdown) + " ".join(str(c.value) for c in at.caption)
    assert html.count("&lt;img") >= 8, "el texto malicioso debía llegar (fenómeno, resultado, ficha), escapado"
    assert ATAQUE not in html and "<img src=x" not in html
