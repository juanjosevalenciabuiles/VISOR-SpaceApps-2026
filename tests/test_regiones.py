"""AOI regionales. Los polígonos son SINTÉTICOS (rectángulos con campos del MGN de DANE);
solo los códigos DIVIPOLA y nombres de Urabá son reales."""
from __future__ import annotations

import json

import pytest

from utils import regiones as rg

# Rectángulos sintéticos, aproximadamente donde están los municipios (no son límites oficiales).
SINTETICOS = {
    "05837": ("TURBO", (-76.90, 7.90, -76.50, 8.40)),
    "05045": ("APARTADÓ", (-76.75, 7.80, -76.55, 7.90)),
    "05147": ("CAREPA", (-76.75, 7.70, -76.55, 7.80)),
    "05172": ("CHIGORODÓ", (-76.80, 7.55, -76.55, 7.70)),
    "05480": ("MUTATÁ", (-76.60, 7.10, -76.30, 7.55)),
}


def rect(o, s, e, n):
    return {"type": "Polygon", "coordinates": [[[o, s], [e, s], [e, n], [o, n], [o, s]]]}


@pytest.fixture
def mgn(tmp_path):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"DPTO_CCDGO": "05", "MPIO_CDPMP": c, "MPIO_CNMBR": n}, "geometry": rect(*b)}
        for c, (n, b) in SINTETICOS.items()]}
    ruta = tmp_path / "MGN_sintetico.geojson"
    ruta.write_text(json.dumps(fc), encoding="utf-8")
    return ruta


def test_catalogo_de_uraba_y_piloto():
    assert len(rg.URABA) == 11 and set(rg.PILOTO) <= set(rg.URABA)
    assert [rg.URABA[c] for c in rg.PILOTO] == ["Chigorodó", "Carepa", "Apartadó", "Turbo"]


def test_union_del_piloto(mgn):
    lim = rg.cargar_limites(mgn)
    assert lim.zonas["05172"].nombre == "Chigorodó"           # mayúsculas del MGN → nombre legible
    aoi = lim.seleccionar(list(rg.PILOTO), "Piloto Urabá")
    assert aoi.codigos == rg.PILOTO and aoi.origen == "limites_oficiales"
    assert aoi.sha256_fuente and aoi.fuente == "MGN_sintetico.geojson"
    o, s, e, n = aoi.limites
    assert (o, s, e, n) == (-76.9, 7.55, -76.5, 8.4)
    suma = sum(rg.area_geodesica_km2(z.geometria) for z in aoi.zonas)
    assert aoi.area_km2 == pytest.approx(suma, rel=1e-4)          # sin solapes: unión ≈ suma (aristas geodésicas)
    assert not any("solapan" in a for a in aoi.avisos)


def test_municipio_ausente(mgn):
    with pytest.raises(rg.ErrorAOI, match="Necoclí"):
        rg.cargar_limites(mgn).seleccionar(["05172", "05490"])


def test_guardar_no_sobrescribe(mgn, tmp_path):
    aoi = rg.cargar_limites(mgn).seleccionar(["05172"])
    a, b = aoi.guardar(tmp_path / "aoi"), aoi.guardar(tmp_path / "aoi")
    assert a.name == "aoi_Chigorodo.geojson" and b.name == "aoi_Chigorodo_r2.geojson"
    datos = json.loads(a.read_text())
    assert datos["visor_aoi"]["sha256_fuente"] == aoi.sha256_fuente
    assert rg.aoi_desde_geojson(a).zonas[0].codigo == "05172"     # se vuelve a cargar


def test_geojson_libre_y_multiparte(tmp_path):
    geo = {"type": "MultiPolygon", "coordinates": [rect(-76.8, 7.5, -76.7, 7.6)["coordinates"],
                                                    rect(-76.6, 7.5, -76.5, 7.6)["coordinates"]]}
    aoi = rg.aoi_desde_geojson(json.dumps(geo), "Dos parches")
    assert len(aoi.zonas) == 1 and any("2 partes" in a for a in aoi.avisos)


@pytest.mark.parametrize("contenido, mensaje", [
    ("no es json", "no es un JSON"),
    (json.dumps({"type": "Point", "coordinates": [0, 0]}), "no admitido"),
    (json.dumps({"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}),
     "solo se admiten polígonos"),
    (json.dumps({"type": "FeatureCollection", "features": []}), "no contiene polígonos"),
    (json.dumps(rect(300000, 860000, 300100, 860100)), "WGS84"),
    (json.dumps({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:32618"}},
                 "features": [{"type": "Feature", "properties": {}, "geometry": rect(-76.8, 7.5, -76.7, 7.6)}]}),
     "EPSG:32618"),
])
def test_geojson_invalido(contenido, mensaje):
    with pytest.raises(rg.ErrorAOI, match=mensaje):
        rg.aoi_desde_geojson(contenido)


def test_poligono_invalido_se_repara():
    corbata = {"type": "Polygon", "coordinates": [[[-76.8, 7.5], [-76.7, 7.6], [-76.7, 7.5], [-76.8, 7.6], [-76.8, 7.5]]]}
    aoi = rg.aoi_desde_geojson(json.dumps(corbata))
    assert aoi.geometria.is_valid and aoi.area_km2 > 0


def test_limites_sin_codigo(tmp_path):
    p = tmp_path / "x.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"nombre": "X"}, "geometry": rect(-76.8, 7.5, -76.7, 7.6)}]}))
    with pytest.raises(rg.ErrorAOI, match="DIVIPOLA"):
        rg.cargar_limites(p)


def test_recuadro_avisa_que_no_es_limite():
    aoi = rg.aoi_recuadro(-76.80, 7.55, -76.55, 7.80, "Chigorodó (recuadro)")
    assert aoi.origen == "recuadro" and any("no es un límite administrativo" in a for a in aoi.avisos)


def test_municipio_en_varias_features_se_une(tmp_path):
    p = tmp_path / "partido.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"MPIO_CDPMP": "5837", "MPIO_CNMBR": "TURBO"}, "geometry": rect(-76.9, 7.9, -76.8, 8.0)},
        {"type": "Feature", "properties": {"MPIO_CDPMP": "05837", "MPIO_CNMBR": "TURBO"}, "geometry": rect(-76.7, 7.9, -76.6, 8.0)}]}))
    lim = rg.cargar_limites(p)
    assert list(lim.zonas) == ["05837"] and lim.zonas["05837"].geometria.geom_type == "MultiPolygon"
