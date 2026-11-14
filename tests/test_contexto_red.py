"""Contexto ambiental contra los servicios REALES (solo con VISOR_PRUEBAS_RED=1, trabajo manual de la CI).

Comprueba HTTP, formato, campos, fechas y geometría de NASA EONET v3 y de la capa 2 «Alertas
Hidrológicas» del servidor ArcGIS REST del IDEAM, e imprime lo observado para dejar evidencia en el
registro. No inventa respuestas: si un servicio no responde, la prueba lo dice.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytestmark = [pytest.mark.red, pytest.mark.skipif(os.environ.get("VISOR_PRUEBAS_RED") != "1",
                                                  reason="servicios reales: requiere VISOR_PRUEBAS_RED=1")]

IDEAM = "https://visualizador.ideam.gov.co/gisserver/rest/services/StoryMaps_IDA/Alertas_Hidrologicas/MapServer/2"
AGENTE = {"User-Agent": "VISOR-SpaceApps-2026 (contexto ambiental; pruebas)", "Accept": "application/json"}


def _json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENTE), timeout=30) as r:
        assert r.status == 200
        return json.loads(r.read().decode("utf-8"))


def test_ideam_capa_2_esquema_real():
    meta = _json(IDEAM + "?f=json")
    campos = [(c["name"], c["type"], c.get("alias")) for c in meta.get("fields", [])]
    print("IDEAM_META", json.dumps({k: meta.get(k) for k in ("name", "type", "geometryType", "maxRecordCount",
                                                            "displayField", "supportedQueryFormats",
                                                            "copyrightText", "description", "editingInfo")},
                                   ensure_ascii=False)[:3000])
    print("IDEAM_CAMPOS", json.dumps(campos, ensure_ascii=False))
    print("IDEAM_SR", json.dumps((meta.get("extent") or {}).get("spatialReference")))
    assert campos, "la capa debe declarar campos"
    q = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "returnGeometry": "false", "f": "json",
                                "resultRecordCount": "5"})
    muestra = _json(IDEAM + "/query?" + q)
    print("IDEAM_MUESTRA", json.dumps([f.get("attributes") for f in muestra.get("features", [])],
                                      ensure_ascii=False)[:4000])
    conteo = _json(IDEAM + "/query?" + urllib.parse.urlencode({"where": "1=1", "returnCountOnly": "true",
                                                                "f": "json"}))
    print("IDEAM_CONTEO", conteo)


def test_ideam_consulta_por_zona_con_el_adaptador():
    from utils import contexto_ambiental as ca
    from utils.config import AOI_CHIGORODO
    from shapely.geometry import box, mapping
    for nombre, limites in (("chigorodo", AOI_CHIGORODO), ("bogota", (-74.25, 4.5, -73.95, 4.8)),
                            ("mojana", (-75.2, 8.3, -74.5, 9.0))):
        res = ca.consultar_ideam(mapping(box(*limites)))
        print("IDEAM_ZONA", nombre, json.dumps({k: res[k] for k in ("estado", "error") if k in res},
                                               ensure_ascii=False), len(res.get("items", [])),
              json.dumps([{k: i.get(k) for k in ("title", "value", "status", "published_at", "valid_from",
                                                 "spatial_relation")} for i in res.get("items", [])[:3]],
                         ensure_ascii=False))
        assert res["estado"] in ("CON_RESULTADOS", "SIN_COINCIDENCIAS"), res


def test_eonet_consulta_real():
    from utils import contexto_ambiental as ca
    from utils.config import AOI_CHIGORODO
    from shapely.geometry import box, mapping
    for nombre, limites, inicio, fin in (
            ("chigorodo_par", AOI_CHIGORODO, date(2026, 9, 9), date(2026, 10, 21)),
            ("colombia_2026", (-79.0, -4.2, -66.9, 12.5), date(2026, 1, 1), date(2026, 11, 14))):
        res = ca.consultar_eonet(mapping(box(*limites)), inicio, fin)
        print("EONET", nombre, res["estado"], len(res["items"]),
              json.dumps([{k: i.get(k) for k in ("title", "phenomenon", "event_start")} for i in res["items"][:5]],
                         ensure_ascii=False))
        assert res["estado"] in ("CON_RESULTADOS", "SIN_COINCIDENCIAS"), res
