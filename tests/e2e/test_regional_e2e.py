"""Paso «05 · Regional» en el navegador. Límites y JRC sintéticos; sin reproducción real, el cruce está bloqueado."""
import json

import pytest

pytestmark = pytest.mark.navegador


def _abrir_regional(p):
    p.clic("btn_sar")
    p.page.locator(".st-key-panel_sar [role=tab]").nth(4).click()
    p.esperar(1200)


def test_regional_aoi_cobertura_y_puerta(abrir):
    p = abrir()
    p.marcar_mapa()
    _abrir_regional(p)
    panel = p.texto("panel_sar")
    assert "chigorodó, carepa, apartadó y turbo" in panel.lower()          # piloto por defecto
    assert "dentro de la cuadrícula sar" in panel.lower() and "sin dato" in panel.lower()
    assert "falta reproducir con los geotiff reales" in panel.lower()
    assert p.page.locator(".st-key-reg_cruzar button").is_disabled()        # bloqueado hasta reproducir Chigorodó
    assert "no se aplican a nisar" in panel.lower()
    assert p.superposiciones() == [] and p.mapa_intacto()
    # El contorno del AOI regional se dibuja sobre el mapa.
    marco = p.page.frame_locator("iframe[title*='folium'], iframe[title*='st_folium']").first
    assert marco.locator("path[stroke='#FFD60A']").count() >= 4


def test_regional_geojson_propio(abrir, tmp_path):
    p = abrir()
    _abrir_regional(p)
    p.page.locator(".st-key-reg_origen label", has_text="GeoJSON propio").click()
    p.esperar()
    assert "sube un geojson" in p.texto("panel_sar").lower()
    archivo = tmp_path / "mi_area.geojson"
    archivo.write_text(json.dumps({"type": "Feature", "properties": {"nombre": "Finca"}, "geometry": {
        "type": "Polygon", "coordinates": [[[-76.70, 7.60], [-76.65, 7.60], [-76.65, 7.65], [-76.70, 7.65], [-76.70, 7.60]]]}}))
    p.page.locator(".st-key-reg_geojson input[type=file]").set_input_files(str(archivo))
    p.esperar(1500)
    panel = p.texto("panel_sar").lower()
    assert "aoi «mi_area»: 1 zona(s)" in panel and "finca" in panel
    # Un archivo que no es un polígono se rechaza con un mensaje, sin romper la app.
    malo = tmp_path / "linea.geojson"
    malo.write_text(json.dumps({"type": "LineString", "coordinates": [[-76.7, 7.6], [-76.6, 7.7]]}))
    p.page.locator(".st-key-reg_geojson input[type=file]").set_input_files(str(malo))
    p.esperar(1500)
    assert "no admitido" in p.texto("panel_sar").lower()
    assert p.page.locator("[data-testid=stException]").count() == 0
