"""Catálogo NISAR GCOV sin red.

Las respuestas UMM-G son SINTÉTICAS: se construyen con las rutas de campos que
usa `asf_search` (NISARProduct) y con nombres de granule de la forma real
publicada en el NISAR Cookbook de ASF. No son respuestas reales del CMR.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from datetime import date

import pytest

from utils import nisar_catalogo as cat
from utils.buscador_sar import ErrorConexion, ErrorServicio

CHIGORODO = (-76.80, 7.55, -76.55, 7.80)
HOY = date(2026, 11, 13)
# Nombre real del NISAR Cookbook (PROVISIONAL, otro lugar): sirve para la convención.
REAL_COOKBOOK = "NISAR_L2_PR_GCOV_021_172_A_008_2005_DHDH_A_20260602T024621_20260602T024656_P05023_N_F_J_001"


def granule(fecha="20261024T231500", track=48, frame=12, direccion="A", modo="2005", pol="DHDH",
            crid="P05036", contador=1, ciclo=30):
    fin = fecha[:-2] + "50"
    return (f"NISAR_L2_PR_GCOV_{ciclo:03d}_{track:03d}_{direccion}_{frame:03d}_{modo}_{pol}_A_"
            f"{fecha}_{fin}_{crid}_N_F_J_{contador:03d}")


def item(nombre, huella=(-77.2, 7.2, -76.2, 8.2), atributos=None, crid=None, qa=True, tamano=2_400_000_000):
    o, s, e, n = huella
    puntos = [{"Longitude": x, "Latitude": y} for x, y in ((o, s), (e, s), (e, n), (o, n), (o, s))]
    partes = nombre.split("_")
    attrs = {"TRACK_NUMBER": partes[5], "FRAME_NUMBER": partes[7],
             "ASCENDING_DESCENDING": "ASCENDING" if partes[6] == "A" else "DESCENDING",
             "PRODUCT_TYPE": "GCOV", "FULL_FRAME": "FULL", **(atributos or {})}
    url = f"https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GCOV_V1/{nombre}/{nombre}.h5"
    urls = [{"Type": "GET DATA", "URL": url}]
    archivos = [{"Name": f"{nombre}.h5", "SizeInBytes": tamano, "Format": "HDF5"}]
    if qa:
        urls.insert(0, {"Type": "GET DATA", "URL": url.replace(".h5", "_QA_STATS.h5")})
        archivos.append({"Name": f"{nombre}_QA_STATS.h5", "SizeInBytes": 1000, "Format": "HDF5"})
    return {"meta": {"concept-id": "G0-ASF"}, "umm": {
        "GranuleUR": nombre,
        "DataGranule": {"Identifiers": [{"IdentifierType": "ProducerGranuleId", "Identifier": nombre},
                                        {"IdentifierType": "CRID", "Identifier": crid or partes[13]}],
                        "ArchiveAndDistributionInformation": archivos},
        "AdditionalAttributes": [{"Name": k, "Values": [v]} for k, v in attrs.items()],
        "SpatialExtent": {"HorizontalSpatialDomain": {"Geometry": {"GPolygons": [{"Boundary": {"Points": puntos}}]}}},
        "RelatedUrls": urls,
    }}


class Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def servidor(cuerpo, registro=None):
    def abrir(peticion, timeout=None):
        if registro is not None:
            registro.append(peticion)
        if isinstance(cuerpo, Exception):
            raise cuerpo
        return Respuesta(json.dumps(cuerpo).encode() if isinstance(cuerpo, dict) else cuerpo)
    return abrir


def region():
    return cat.validar_region(*CHIGORODO)


# --- convención de nombres ---------------------------------------------------

def test_nombre_real_del_cookbook():
    n = cat.leer_nombre(REAL_COOKBOOK)
    assert (n.track, n.frame, n.direccion, n.ciclo) == (172, 8, "ASCENDING", 21)
    assert (n.modo_a, n.modo_b, n.pol_a, n.pol_b) == ("20", "05", ("HH", "HV"), ("HH", "HV"))
    assert (n.crid, n.contador, n.configuracion) == ("P05023", 1, "PR")
    assert n.inicio.isoformat() == "2026-06-02T02:46:21+00:00"


@pytest.mark.parametrize("nombre", ["S1C_IW_GRDH_1SDV_20261006T232218_20261006T232243_004567_00ABCD_116E",
                                    "NISAR_L1_PR_RSLC_004_122_D_067_4005_DHDH_A_20251106T160541_20251106T160622_X05009_N_F_J_001",
                                    REAL_COOKBOOK.replace("DHDH", "XXDH"), ""])
def test_otros_productos_no_se_interpretan_como_gcov(nombre):
    assert cat.leer_nombre(nombre) is None


# --- consulta ------------------------------------------------------------------

@pytest.mark.parametrize("madurez, coleccion", [("VALIDATED", "NISAR_L2_GCOV_V1"),
                                                ("provisional", "NISAR_L2_GCOV_PROVISIONAL_V1"),
                                                ("BETA", "NISAR_L2_GCOV_BETA_V1")])
def test_consulta_por_madurez_sin_credenciales(madurez, coleccion):
    p = dict(cat.construir_consulta(region(), date(2026, 10, 21), HOY, madurez))
    assert p["short_name"] == coleccion and p["provider"] == "ASF"
    assert p["bounding_box"] == "-76.800000,7.550000,-76.550000,7.800000"
    url = cat.url_consulta(cat.construir_consulta(region(), date(2026, 10, 21), HOY))
    assert url.startswith("https://cmr.earthdata.nasa.gov/search/granules.umm_json?")
    assert not any(k in url.lower() for k in ("token", "password", "authorization"))


def test_madurez_desconocida():
    with pytest.raises(ErrorServicio, match="Madurez"):
        cat.construir_consulta(region(), date(2026, 10, 21), HOY, "FINAL")


@pytest.mark.parametrize("fallo, error", [
    (urllib.error.URLError("sin red"), ErrorConexion),
    (TimeoutError(), ErrorConexion),
    (urllib.error.HTTPError("u", 503, "x", {}, None), ErrorConexion),
    (urllib.error.HTTPError("u", 400, "x", {}, None), ErrorServicio),
    (b"<html>no json</html>", ErrorServicio),
    ({"errors": ["parametro invalido"]}, ErrorServicio),
    ({"hits": 0}, ErrorServicio),
])
def test_errores_de_red_y_formato_son_legibles(fallo, error):
    with pytest.raises(error):
        cat.buscar(*CHIGORODO, "2026-10-21", "2026-11-13", abrir=servidor(fallo), hoy=HOY)


def test_busqueda_vacia(tmp_path):
    r = cat.buscar(*CHIGORODO, "2026-10-21", "2026-11-13", abrir=servidor({"items": []}), hoy=HOY)
    assert r.candidatos == [] and r.pares == []
    assert any("no devolvió escenas" in a for a in r.avisos)


def test_peticion_es_get_sin_cabecera_de_autenticacion():
    registro = []
    cat.buscar(*CHIGORODO, "2026-10-21", "2026-11-13", abrir=servidor({"items": []}, registro), hoy=HOY)
    pet = registro[0]
    assert pet.get_method() == "GET" and "Authorization" not in pet.headers
    consulta = urllib.parse.parse_qs(urllib.parse.urlsplit(pet.full_url).query)
    assert consulta["short_name"] == ["NISAR_L2_GCOV_V1"]


# --- interpretación --------------------------------------------------------------

def test_versiones_duplicadas_se_reducen_a_la_mas_reciente():
    a = granule(contador=1)
    b = granule(contador=2)
    c = granule(crid="P05023", contador=3)
    candidatos, descartes = cat.interpretar({"items": [item(a), item(b), item(c)]}, region())
    assert len(candidatos) == 1 and descartes == []
    elegido = candidatos[0]
    assert (elegido.nombre.crid, elegido.nombre.contador) == ("P05036", 2)
    assert set(elegido.otras_versiones) == {a, c}


def test_qa_stats_no_es_el_producto_y_se_toma_su_tamano_real():
    c = cat.interpretar({"items": [item(granule(), tamano=2_400_000_000)]}, region())[0][0]
    assert c.url_h5.endswith(".h5") and "QA_STATS" not in c.url_h5
    assert c.tamano_bytes == 2_400_000_000


@pytest.mark.parametrize("cambio, motivo", [
    ({"atributos": {"TRACK_NUMBER": "99"}}, "TRACK_NUMBER"),
    ({"atributos": {"ASCENDING_DESCENDING": "DESCENDING"}}, "dirección"),
    ({"crid": "P05023"}, "CRID"),
    ({"atributos": {"PRODUCT_TYPE": "GSLC"}}, "GSLC"),
    ({"huella": (-60, 10, -59, 11)}, "no toca"),
])
def test_metadatos_inconsistentes_o_fuera_del_area_se_descartan(cambio, motivo):
    candidatos, descartes = cat.interpretar({"items": [item(granule(), **cambio)]}, region())
    assert candidatos == [] and motivo in descartes[0]


def test_nombre_no_gcov_se_descarta():
    _, descartes = cat.interpretar({"items": [item(REAL_COOKBOOK.replace("GCOV", "GSLC"))]}, region())
    assert "convención" in descartes[0]


# --- pares ---------------------------------------------------------------------------

def test_par_compatible_es_candidato_no_validado():
    items = [item(granule("20261024T231500", ciclo=30)), item(granule("20261105T231500", ciclo=31))]
    r = cat.buscar(*CHIGORODO, "2026-10-21", "2026-11-13", abrir=servidor({"items": items}), hoy=HOY)
    assert len(r.pares) == 1 and r.bloqueos == []
    par = r.pares[0]
    assert par.estado == "CANDIDATO NO VALIDADO" and round(par.dias) == 12
    assert par.polarizaciones_A == ("HH", "HV")
    assert any("inspeccionar" in a for a in par.avisos)


@pytest.mark.parametrize("otro, motivo", [
    ({"track": 49}, "track distinto"),
    ({"frame": 13}, "frame distinto"),
    ({"direccion": "D"}, "dirección distinta"),
    ({"modo": "4005"}, "modo de ancho de banda"),
    ({"pol": "SHNA"}, "polarizaciones distintas"),
    ({"crid": "P05023"}, "CRID distinto"),
    ({"fecha": "20261024T235900"}, "mismo día"),
])
def test_incompatibilidades_bloquean_el_par(otro, motivo):
    base = {"fecha": "20261105T231500"} | otro
    items = [item(granule("20261024T231500")), item(granule(**base))]
    r = cat.buscar(*CHIGORODO, "2026-10-21", "2026-11-13", abrir=servidor({"items": items}), hoy=HOY)
    assert r.pares == [] and motivo in r.bloqueos[0]
    assert any("escena única" in a for a in r.avisos)


def test_huellas_que_no_se_superponen_en_la_region_bloquean():
    items = [item(granule("20261024T231500"), huella=(-76.80, 7.55, -76.70, 7.80)),
             item(granule("20261105T231500"), huella=(-76.65, 7.55, -76.55, 7.80))]
    r = cat.buscar(*CHIGORODO, "2026-10-21", "2026-11-13", abrir=servidor({"items": items}), hoy=HOY)
    assert r.pares == [] and "no comparten área" in r.bloqueos[0]


def test_validated_antes_de_su_inicio_avisa():
    r = cat.buscar(*CHIGORODO, "2026-10-01", "2026-11-13", abrir=servidor({"items": []}), hoy=HOY)
    assert any("21-oct-2026" in a for a in r.avisos)


def test_registro_es_json_y_no_afirma_validacion():
    items = [item(granule("20261024T231500")), item(granule("20261105T231500"))]
    r = cat.buscar(*CHIGORODO, "2026-10-21", "2026-11-13", abrir=servidor({"items": items}), hoy=HOY)
    reg = json.loads(json.dumps(cat.registro_json(r)))
    assert reg["pares"][0]["estado"] == "CANDIDATO NO VALIDADO"
    assert reg["candidatos"][0]["sensor"] == "NISAR" and reg["candidatos"][0]["banda"] == "L"
    assert "no se descargó nada" in reg["nota"]


# --- nombres REALES del catálogo (CMR, 13-nov-2026, GitHub Actions) ---------------

REALES_CHIGORODO = [
    "NISAR_L2_PR_GCOV_033_148_A_005_2005_DHDH_M_20261022T104722_20261022T104757_P05036_N_F_J_001",
    "NISAR_L2_PR_GCOV_033_148_A_005_4005_DHDH_A_20261022T104744_20261022T104757_P05036_N_P_J_001",
    "NISAR_L2_PR_GCOV_034_011_D_085_4005_DHDH_A_20261024T232837_20261024T232912_P05036_N_F_J_001",
    "NISAR_L2_PR_GCOV_034_047_A_005_4005_DHDH_A_20261027T103903_20261027T103938_P05036_N_F_J_001",
    "NISAR_L2_PR_GCOV_034_047_A_006_4005_DHDH_A_20261027T103937_20261027T104011_P05036_N_F_J_001",
    "NISAR_L2_PR_GCOV_034_112_D_084_2005_SHSH_M_20261031T233623_20261031T233658_P05036_N_F_J_001",
    "NISAR_L2_PR_GCOV_034_112_D_084_4005_DHDH_A_20261031T233632_20261031T233658_P05036_N_P_J_001",
    "NISAR_L2_PR_GCOV_034_112_D_085_2005_SHSH_M_20261031T233657_20261031T233731_P05036_N_F_J_001",
    "NISAR_L2_PR_GCOV_034_112_D_085_4005_DHDH_A_20261031T233657_20261031T233713_P05036_N_P_J_001",
    "NISAR_L2_PR_GCOV_034_148_A_005_2005_DHDH_M_20261103T104722_20261103T104757_P05036_N_F_J_001",
    "NISAR_L2_PR_GCOV_034_148_A_005_4005_DHDH_A_20261103T104745_20261103T104757_P05036_N_P_J_001",
]


def test_nombres_reales_de_chigorodo_se_interpretan():
    nombres = [cat.leer_nombre(n) for n in REALES_CHIGORODO]
    assert all(n is not None and n.crid == "P05036" for n in nombres)
    primero = nombres[0]
    assert (primero.track, primero.frame, primero.direccion, primero.fuente_datos, primero.cobertura) == \
        (148, 5, "ASCENDING", "M", "F")
    assert nombres[5].pol_a == ("HH",) and nombres[1].cobertura == "P"
    assert {n.fuente_datos for n in nombres} == {"A", "M"}


def test_pares_de_los_nombres_reales_solo_track_148():
    """Con las huellas del catálogo (aquí simuladas iguales), los únicos pares posibles son los
    de track 148 / frame 5: mismo modo y misma fuente de datos, 12 días. Lo demás se bloquea."""
    candidatos, _ = cat.interpretar({"items": [item(n) for n in REALES_CHIGORODO]}, region())
    pares, _ = cat.emparejar(candidatos, region())
    claves = {(p.antes.nombre.track, p.antes.nombre.modo_a, p.antes.nombre.fuente_datos, round(p.dias)) for p in pares}
    assert claves == {(148, "20", "M", 12), (148, "40", "A", 12)}
    mixto = next(p for p in pares if p.antes.nombre.fuente_datos == "M")
    assert any("modos de adquisición mixtos" in a for a in mixto.avisos)
    parcial = next(p for p in pares if p.antes.nombre.fuente_datos == "A")
    assert any("cobertura parcial" in a for a in parcial.avisos)


def test_modo_unico_y_mixto_no_se_emparejan():
    a = item(granule("20261024T231500"))
    b = item(granule("20261105T231500").replace("_DHDH_A_", "_DHDH_M_"))
    r = cat.buscar(*CHIGORODO, "2026-10-21", "2026-11-13", abrir=servidor({"items": [a, b]}), hoy=HOY)
    assert r.pares == [] and "modos mixtos" in r.bloqueos[0]


# --- registro REAL guardado (tests/datos/, obtenido en GitHub Actions) ---------------

def _registro_real():
    from pathlib import Path
    ruta = Path(__file__).parent / "datos" / "nisar_catalogo_chigorodo_20261113.json"
    return ruta, json.loads(ruta.read_text(encoding="utf-8"))


def test_registro_real_coincide_con_lo_documentado():
    _, reg = _registro_real()
    assert reg["consulta"]["coleccion"] == "NISAR_L2_GCOV_V1" and reg["consulta"]["madurez"] == "VALIDATED"
    assert reg["total_catalogo"] == 11 and reg["descartes"] == []
    assert sorted(c["granule"] for c in reg["candidatos"]) == sorted(REALES_CHIGORODO)
    assert {c["crid"] for c in reg["candidatos"]} == {"P05036"}
    assert {(p["antes"][21:24], round(p["dias"])) for p in reg["pares"]} == {("148", 12)}
    assert all(p["estado"] == "CANDIDATO NO VALIDADO" and p["cobertura_comun"] < 0.45 for p in reg["pares"])
    mejor = max(reg["candidatos"], key=lambda c: c["cobertura_aoi"])
    assert (mejor["track"], mejor["frame"], round(mejor["cobertura_aoi"], 2)) == (112, 85, 0.94)


def test_los_enlaces_reales_pasan_las_comprobaciones_de_descarga_sin_red(tmp_path):
    """URL https en el servidor de ASF y tamaño conocido; sin confirmar el tamaño, nada se pide."""
    from utils import nisar_descarga
    _, reg = _registro_real()
    for c in reg["candidatos"]:
        gb = c["tamano_bytes"] / 1e9
        url, tamano, destino = nisar_descarga.comprobar(c, tmp_path, gb + 0.01, libre_bytes=10 ** 12)
        assert url.startswith("https://nisar.asf.earthdatacloud.nasa.gov/") and tamano == c["tamano_bytes"]
        assert destino.name == f"{c['granule']}.h5"
        with pytest.raises(nisar_descarga.ErrorDescarga, match="confírmalo"):
            nisar_descarga.comprobar(c, tmp_path, None, libre_bytes=10 ** 12)
    assert 1.1 < min(c["tamano_bytes"] for c in reg["candidatos"]) / 1e9 < 1.3
