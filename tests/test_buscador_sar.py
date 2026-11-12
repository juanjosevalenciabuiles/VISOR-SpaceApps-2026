"""Pruebas del buscador de escenas Sentinel-1 (catálogo de ASF).

Ninguna prueba usa la red: las respuestas de ASF se simulan. El archivo
tests/datos/asf_chigorodo_20260920_20261010.json es una respuesta REAL del
catálogo (solo metadatos), guardada para comprobar el caso de Chigorodó.
"""
import copy
import io
import json
import socket
import sys
import urllib.error
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from shapely import wkt as shapely_wkt
from shapely.geometry import box, mapping

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils import buscador_sar as bus  # noqa: E402
from utils.buscador_sar import ErrorBusqueda, ErrorConexion, ErrorServicio  # noqa: E402

CHIGORODO = (-76.85, 7.40, -76.40, 7.95)
ANTES_CONOCIDA = "S1C_IW_GRDH_1SDV_20260924T232218_20260924T232254_009596_013189_1338"
DESPUES_CONOCIDA = "S1C_IW_GRDH_1SDV_20261006T232218_20261006T232254_009771_013762_116E"
HOY = date(2026, 11, 12)
REAL = json.loads((RAIZ / "tests" / "datos" / "asf_chigorodo_20260920_20261010.json").read_text(encoding="utf-8"))
REGION = bus.validar_region(*CHIGORODO)


# ---------------------------------------------------------------------------
# Utilidades para simular a ASF
# ---------------------------------------------------------------------------

class Respuesta:
    def __init__(self, cuerpo):
        self.cuerpo = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()

    def read(self):
        return self.cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def servidor(cuerpo, registro=None):
    """Sustituto de urlopen que devuelve `cuerpo` y anota la petición."""
    def abrir(peticion, timeout=None):
        if registro is not None:
            registro.append((peticion, timeout))
        if isinstance(cuerpo, Exception):
            raise cuerpo
        return Respuesta(cuerpo)
    return abrir


def elemento(nombre="S1A_IW_GRDH_1SDV_20250105T230000_20250105T230025_057300_070D00_AAAA", huella=None, **props):
    """Elemento GeoJSON como los de ASF. Por defecto cubre toda la región."""
    p = nombre.split("_")
    hora = lambda t: f"{t[:4]}-{t[4:6]}-{t[6:8]}T{t[9:11]}:{t[11:13]}:{t[13:15]}Z"  # noqa: E731
    base = {"sceneName": nombre, "beamModeType": "IW", "processingLevel": "GRD_HD", "polarization": "VV+VH",
            "flightDirection": "ASCENDING", "pathNumber": 48, "bytes": 1_000_000_000}
    if len(p) == 9:                                   # nombre con la forma de Sentinel-1
        base.update({
            "fileID": f"{nombre}-GRD_HD", "platform": f"Sentinel-1{p[0][-1]}", "orbit": int(p[6]),
            "startTime": hora(p[4]), "stopTime": hora(p[5]),
            "url": f"https://datapool.asf.alaska.edu/GRD_HD/S{p[0][-1]}/{nombre}.zip",
        })
    base.update(props)
    base = {k: v for k, v in base.items() if v is not None}
    geometria = mapping(huella if huella is not None else box(-78, 6, -75, 9))
    return {"type": "Feature", "geometry": geometria, "properties": base}


def coleccion(*elementos):
    return {"type": "FeatureCollection", "features": list(elementos)}


def nombre(fecha, plataforma="S1A", orbita=57300, sufijo="AAAA", hora="230000"):
    return f"{plataforma}_IW_GRDH_1SDV_{fecha}T{hora}_{fecha}T{hora[:4]}25_{orbita:06d}_070D00_{sufijo}"


def escenas(*elementos, region=REGION):
    return bus.interpretar_respuesta(coleccion(*elementos), region).escenas


# ---------------------------------------------------------------------------
# Validación de coordenadas
# ---------------------------------------------------------------------------

def test_region_valida():
    r = bus.validar_region("-76.85", 7.40, -76.40, "7.95")
    assert r.limites == CHIGORODO and r.centro == pytest.approx((7.675, -76.625))
    assert r.poligono.area == pytest.approx(0.45 * 0.55)


@pytest.mark.parametrize("limites, mensaje", [
    ((-76.40, 7.40, -76.85, 7.95), "oeste debe ser menor"),
    ((-76.85, 7.95, -76.40, 7.40), "sur debe ser menor"),
    ((-76.85, 7.40, -76.85, 7.95), "oeste debe ser menor"),
    ((-190, 7.40, -76.40, 7.95), "longitudes"),
    ((-76.85, 7.40, 181, 7.95), "longitudes"),
    ((-76.85, -91, -76.40, 7.95), "latitudes"),
    ((-76.85, 7.40, -76.40, 95), "latitudes"),
    (("abc", 7.40, -76.40, 7.95), "debe ser un número"),
    ((None, 7.40, -76.40, 7.95), "debe ser un número"),
    ((float("nan"), 7.40, -76.40, 7.95), "finito"),
    ((float("inf"), 7.40, -76.40, 7.95), "finito"),
    ((-76.85, 7.40, -76.8499, 7.95), "demasiado pequeña"),
    ((-80, 2, -70, 12), "demasiado amplia"),
    ((-76.85, 7.40, -70.0, 7.95), "demasiado amplia"),
])
def test_region_invalida(limites, mensaje):
    with pytest.raises(ErrorBusqueda, match=mensaje):
        bus.validar_region(*limites)


def test_region_desde_punto():
    r = bus.region_desde_punto(7.67, -76.68, 20)
    assert r.centro == pytest.approx((7.67, -76.68), abs=1e-6)
    assert (r.norte - r.sur) * 110.574 == pytest.approx(40, rel=1e-3)            # 20 km a cada lado
    assert (r.este - r.oeste) > (r.norte - r.sur)                               # los grados de longitud son más cortos
    assert bus.region_desde_punto(60, 10, 20).este - bus.region_desde_punto(60, 10, 20).oeste == pytest.approx(
        2 * 20 / (111.320 * 0.5), rel=1e-3)
    for malo in ((95, 0, 10), (0, 200, 10), (7, -76, 0), (7, -76, -5), ("x", -76, 10)):
        with pytest.raises(ErrorBusqueda):
            bus.region_desde_punto(*malo)
    with pytest.raises(ErrorBusqueda, match="demasiado amplia"):
        bus.region_desde_punto(7, -76, 400)


# ---------------------------------------------------------------------------
# Validación de fechas
# ---------------------------------------------------------------------------

def test_fechas_validas():
    assert bus.validar_fechas("2026-09-20", "2026-10-10", HOY) == (date(2026, 9, 20), date(2026, 10, 10))
    assert bus.validar_fechas(date(2026, 9, 20), datetime(2026, 10, 10, 15, 0), HOY) == (date(2026, 9, 20), date(2026, 10, 10))
    assert bus.validar_fechas("2026-11-12", "2026-11-12", HOY) == (HOY, HOY)       # un solo día
    assert bus.validar_fechas("2026-11-01", "2026-12-31", HOY)[1] == date(2026, 12, 31)   # el final puede ser futuro


@pytest.mark.parametrize("inicio, fin, mensaje", [
    ("2026-10-10", "2026-09-20", "posterior a la fecha final"),
    ("2026-12-01", "2026-12-20", "futuro"),
    ("2010-01-01", "2010-06-01", "no tiene datos anteriores"),
    ("2024-01-01", "2026-01-01", "demasiado largo"),
    ("20/09/2026", "2026-10-10", "no es una fecha válida"),
    ("2026-02-30", "2026-03-10", "no es una fecha válida"),
    ("", "2026-10-10", "no es una fecha válida"),
])
def test_fechas_invalidas(inicio, fin, mensaje):
    with pytest.raises(ErrorBusqueda, match=mensaje):
        bus.validar_fechas(inicio, fin, HOY)


# ---------------------------------------------------------------------------
# Geometría de búsqueda
# ---------------------------------------------------------------------------

def test_geometria_de_busqueda():
    texto = bus.wkt_region(REGION)
    assert texto == "POLYGON((-76.85 7.4,-76.4 7.4,-76.4 7.95,-76.85 7.95,-76.85 7.4))"
    poligono = shapely_wkt.loads(texto)
    assert poligono.is_valid and poligono.exterior.is_ccw and poligono.equals(REGION.poligono)
    assert bus.bbox_region(REGION) == "-76.85,7.4,-76.4,7.95"                   # oeste, sur, este, norte
    assert bus.bbox_region(bus.validar_region(-0.5, -0.25, 0.123456789, 0.5)) == "-0.5,-0.25,0.123457,0.5"


def test_parametros_de_la_consulta():
    p = bus.construir_consulta(REGION, date(2026, 9, 20), date(2026, 10, 10))
    assert p == {
        "platform": "Sentinel-1", "processingLevel": "GRD_HD", "beamMode": "IW",
        "bbox": "-76.85,7.4,-76.4,7.95",
        "start": "2026-09-20T00:00:00Z", "end": "2026-10-10T23:59:59Z",      # incluye completo el último día
        "output": "geojson", "maxResults": "250",
    }
    url = bus.url_consulta(p)
    assert url.startswith("https://api.daac.asf.alaska.edu/services/search/param?")
    assert dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)) == p


def test_la_consulta_es_de_solo_lectura_y_sin_credenciales():
    registro = []
    bus.consultar_asf(bus.construir_consulta(REGION, date(2026, 9, 20), date(2026, 10, 10)),
                      abrir=servidor(coleccion(), registro))
    peticion, espera = registro[0]
    assert peticion.get_method() == "GET" and peticion.data is None and espera == bus.TIEMPO_ESPERA_S
    cabeceras = {k.lower() for k in peticion.headers}
    assert "authorization" not in cabeceras and "cookie" not in cabeceras
    assert "hyp3" not in peticion.full_url.lower() and "datapool" not in peticion.full_url.lower()
    codigo = (RAIZ / "utils" / "buscador_sar.py").read_text(encoding="utf-8")
    for prohibido in ("hyp3-api", "urlretrieve", "EARTHDATA", "password", "token", "netrc"):
        assert prohibido not in codigo


# ---------------------------------------------------------------------------
# Filtrado de productos
# ---------------------------------------------------------------------------

def test_filtra_productos_incompatibles():
    r = bus.interpretar_respuesta(coleccion(
        elemento(nombre("20250105")),
        elemento(nombre("20250106", sufijo="META"), processingLevel="METADATA_GRD_HD"),
        elemento(nombre("20250107").replace("GRDH", "SLCS"), processingLevel="SLC"),
        elemento(nombre("20250108").replace("GRDH", "GRDM"), processingLevel="GRD_MD"),
        elemento(nombre("20250109").replace("_IW_", "_EW_"), beamModeType="EW"),
        elemento("ALPSRP074606580", platform="ALOS", processingLevel="GRD_HD", beamModeType="IW",
                 startTime="2007-01-01T00:00:00Z", stopTime="2007-01-01T00:00:10Z", orbit=7460),
        elemento(nombre("20250110"), flightDirection=None),
        elemento(nombre("20250111"), polarization="", sceneName="S1A_RARO", fileID=None, startTime="2025-01-11T23:00:00Z"),
        elemento(nombre("20250112"), huella=box(10, 40, 11, 41)),                 # en otro continente
        {"type": "Feature", "geometry": None, "properties": {"sceneName": nombre("20250113"), "processingLevel": "GRD_HD",
                                                             "beamModeType": "IW", "flightDirection": "ASCENDING",
                                                             "pathNumber": 48, "polarization": "VV"}},
        {"type": "Feature", "geometry": None, "properties": {}},
        "esto no es un elemento",
    ), REGION)
    assert [e.nombre for e in r.escenas] == [nombre("20250105")]
    assert r.recibidos == 12 and sum(r.descartes.values()) == 11
    assert r.descartes["solo metadatos"] == 1
    assert r.descartes["producto SLC, no GRD de alta resolución"] == 1
    assert r.descartes["producto GRD_MD, no GRD de alta resolución"] == 1
    assert r.descartes["modo EW, no IW"] == 1
    assert r.descartes["no es Sentinel-1"] == 1
    assert r.descartes["sin dirección de vuelo"] == 1
    assert r.descartes["no cubre la región"] == 1
    assert r.descartes["sin huella geográfica"] == 1
    assert r.descartes["sin nombre de escena"] == 1 and r.descartes["elemento ilegible"] == 1


def test_metadatos_de_una_escena():
    e = escenas(elemento(nombre("20250105", "S1A", 57300), pathNumber=48, frameNumber=1205,
                         polarization="VV+VH", flightDirection="DESCENDING"))[0]
    assert (e.plataforma, e.modo, e.nivel) == ("S1A", "IW", "GRD_HD")
    assert e.inicio == datetime(2025, 1, 5, 23, 0, 0, tzinfo=timezone.utc) and e.fin > e.inicio
    assert (e.orbita_absoluta, e.orbita_relativa, e.cuadro) == (57300, 48, 1205)
    assert e.direccion == "DESCENDING" and e.direccion_es == "Descendente"
    assert e.polarizaciones == ("VV", "VH") and e.cobertura == pytest.approx(1.0)
    assert e.url.startswith("https://datapool.asf.alaska.edu/") and e.tamano_bytes == 1_000_000_000
    assert e.enlace_vertex == f"https://search.asf.alaska.edu/#/?searchType=List%20Search&searchList={e.nombre}"
    m = e.metadatos()
    assert m["nombre"] == e.nombre and m["polarizaciones"] == ["VV", "VH"] and m["inicio_utc"].endswith("+00:00")
    assert shapely_wkt.loads(m["huella_wkt"]).equals(e.huella)
    json.dumps(m)                                                             # se puede serializar


def test_datos_que_faltan_se_deducen_del_nombre_cuando_es_posible():
    e = escenas(elemento(nombre("20250105", "S1A", 57300), pathNumber=None, startTime=None, stopTime=None,
                         polarization=None, beamModeType=None, processingLevel=None, platform=None, url="ftp://x"))[0]
    assert e.inicio == datetime(2025, 1, 5, 23, 0, 0, tzinfo=timezone.utc)
    assert e.polarizaciones == ("VV", "VH") and e.modo == "IW" and e.nivel == "GRD_HD" and e.plataforma == "S1A"
    assert e.orbita_relativa == (57300 - 73) % 175 + 1                        # fórmula publicada para S1A
    assert e.url is None and "search.asf.alaska.edu" in bus.filas_escenas([e])[0]["ASF"]
    # Sin órbita relativa y sin fórmula para ese satélite: no se inventa.
    r = bus.interpretar_respuesta(coleccion(elemento(nombre("20260105", "S1C", 9596), pathNumber=None)), REGION)
    assert not r.escenas and r.descartes == {"sin órbita": 1}


@pytest.mark.parametrize("texto, esperado", [
    ("VV+VH", ("VV", "VH")), ("HH+HV", ("HH", "HV")), ("VV", ("VV",)), ("vv, vh", ("VV", "VH")), ("VV/VH", ("VV", "VH")),
])
def test_polarizaciones(texto, esperado):
    assert escenas(elemento(nombre("20250105"), polarization=texto))[0].polarizaciones == esperado


# ---------------------------------------------------------------------------
# Superposición espacial
# ---------------------------------------------------------------------------

def test_cobertura_de_la_region():
    oeste, sur, este, norte = CHIGORODO
    mitad_oeste = box(-78, 6, (oeste + este) / 2, 9)
    cuarto = box(-78, 6, (oeste + este) / 2, (sur + norte) / 2)
    es = escenas(elemento(nombre("20250105")), elemento(nombre("20250117", orbita=57475), huella=mitad_oeste),
                 elemento(nombre("20250129", orbita=57650), huella=cuarto))
    assert [round(e.cobertura, 3) for e in es] == [1.0, 0.5, 0.25]
    assert bus.cobertura_comun(es[0], es[1], REGION) == pytest.approx(0.5)
    assert bus.cobertura_comun(es[1], es[2], REGION) == pytest.approx(0.25)
    mitad_este = escenas(elemento(nombre("20250210", orbita=57825), huella=box((oeste + este) / 2, 6, -75, 9)))[0]
    assert bus.cobertura_comun(es[1], mitad_este, REGION) == pytest.approx(0.0)   # cada una cubre media región distinta


def test_la_cobertura_minima_filtra_pares():
    oeste, sur, este, norte = CHIGORODO
    parcial = box(-78, 6, oeste + 0.3 * (este - oeste), 9)                      # 30 % de la región
    es = escenas(elemento(nombre("20250105")), elemento(nombre("20250117", orbita=57475), huella=parcial))
    assert bus.emparejar(es, REGION) == []                                     # por defecto exige 50 %
    par = bus.emparejar(es, REGION, min_cobertura=0.25)[0]
    assert par.cobertura_comun == pytest.approx(0.3) and any("no cubre toda la región" in a for a in par.avisos)


def test_huella_invalida_se_repara_o_se_descarta():
    lazo = {"type": "Polygon", "coordinates": [[[-78, 6], [-75, 9], [-75, 6], [-78, 9], [-78, 6]]]}   # se cruza
    roto = elemento(nombre("20250105"))
    roto["geometry"] = lazo
    assert 0 < escenas(roto)[0].cobertura <= 1
    punto = elemento(nombre("20250106"))
    punto["geometry"] = {"type": "Point", "coordinates": [-76.6, 7.6]}
    assert bus.interpretar_respuesta(coleccion(punto), REGION).descartes == {"sin huella geográfica": 1}


# ---------------------------------------------------------------------------
# Duplicados
# ---------------------------------------------------------------------------

def test_duplicados_exactos():
    r = bus.interpretar_respuesta(coleccion(*[elemento(nombre("20250105"))] * 3, elemento(nombre("20250117", orbita=57475))), REGION)
    assert len(r.escenas) == 2 and r.duplicados == 2 and r.versiones == 0 and r.recibidos == 4


def test_versiones_de_una_misma_adquisicion():
    r = bus.interpretar_respuesta(coleccion(
        elemento(nombre("20250105", sufijo="F000")), elemento(nombre("20250105", sufijo="116E")),
        elemento(nombre("20250105", sufijo="0001")), elemento(nombre("20250117", orbita=57475)),
    ), REGION)
    assert len(r.escenas) == 2 and r.versiones == 2 and r.duplicados == 0
    primera = r.escenas[0]
    assert primera.nombre.endswith("_0001")                                   # elección estable: orden alfabético
    assert [n[-4:] for n in primera.otras_versiones] == ["116E", "F000"]
    assert r.escenas[1].otras_versiones == ()
    par = bus.emparejar(r.escenas, REGION)
    assert len(par) == 1                                                      # no se multiplican los pares
    assert any("otra versión" in a and "F000" in a for a in par[0].avisos)
    assert par[0].para_motor()["antes"]["otras_versiones"] == list(primera.otras_versiones)


def test_dos_tomas_distintas_del_mismo_dia_no_son_duplicados():
    r = bus.interpretar_respuesta(coleccion(
        elemento(nombre("20250105", hora="230000")), elemento(nombre("20250105", hora="230025", sufijo="BBBB")),
    ), REGION)
    assert len(r.escenas) == 2 and r.versiones == 0
    assert bus.emparejar(r.escenas, REGION) == []                             # misma pasada: no es un par temporal


# ---------------------------------------------------------------------------
# Compatibilidad de órbitas y polarizaciones
# ---------------------------------------------------------------------------

def test_compatibilidad_de_orbitas():
    a, misma, otra_orbita, otra_direccion = escenas(
        elemento(nombre("20250105")),
        elemento(nombre("20250117", orbita=57475)),
        elemento(nombre("20250118", orbita=57490), pathNumber=142),
        elemento(nombre("20250119", orbita=57505), flightDirection="DESCENDING"),
    )
    assert bus.geometria_compatible(a, misma)
    assert not bus.geometria_compatible(a, otra_orbita) and not bus.geometria_compatible(a, otra_direccion)
    pares = bus.emparejar([a, misma, otra_orbita, otra_direccion], REGION)
    assert [(p.antes.nombre, p.despues.nombre) for p in pares] == [(a.nombre, misma.nombre)]


def test_compatibilidad_de_polarizaciones():
    doble, solo_vv, hh = escenas(
        elemento(nombre("20250105")),
        elemento(nombre("20250117", orbita=57475).replace("1SDV", "1SSV"), polarization="VV"),
        elemento(nombre("20250129", orbita=57650).replace("1SDV", "1SDH"), polarization="HH+HV"),
    )
    assert bus.polarizaciones_comunes(doble, solo_vv) == ("VV",)
    assert bus.polarizaciones_comunes(doble, hh) == () and bus.polarizaciones_comunes(solo_vv, hh) == ()
    pares = bus.emparejar([doble, solo_vv, hh], REGION)
    assert len(pares) == 1 and pares[0].polarizaciones_comunes == ("VV",)


# ---------------------------------------------------------------------------
# Selección de pares
# ---------------------------------------------------------------------------

def test_prioriza_mismo_satelite_y_cercania_temporal():
    es = escenas(
        elemento(nombre("20250105", "S1A", 57300)),
        elemento(nombre("20250111", "S1C", 500), sufijo="CCCC"),                 # 6 días, otro satélite
        elemento(nombre("20250117", "S1A", 57475)),                              # 12 días, mismo satélite
        elemento(nombre("20250411", "S1A", 58700)),                              # 96 días, mismo satélite
    )
    pares = bus.emparejar(es, REGION)
    assert len(pares) == 6
    mejor = pares[0]
    assert (mejor.antes.inicio.day, mejor.despues.inicio.day) == (5, 17) and mejor.misma_plataforma
    assert mejor.recomendado and mejor.estado == "Recomendado (sin validar)" and round(mejor.dias) == 12
    assert [p.recomendado for p in pares].count(True) == 1
    assert all(p.estado == "Compatible (sin validar)" for p in pares[1:])
    assert pares == sorted(pares, key=lambda p: -p.puntuacion)
    mixto = next(p for p in pares if not p.misma_plataforma)
    assert mixto.puntuacion < mejor.puntuacion and any("Satélites distintos" in a for a in mixto.avisos)
    largo = next(p for p in pares if round(p.dias) == 96)
    assert largo.puntuacion < mejor.puntuacion and any("96 días" in a for a in largo.avisos)
    assert all(p.antes.inicio < p.despues.inicio for p in pares)              # siempre antes → después


def test_ningun_par_queda_validado():
    es = escenas(elemento(nombre("20250105")), elemento(nombre("20250117", orbita=57475)))
    par = bus.emparejar(es, REGION)[0]
    assert par.recomendado and par.validado is False
    motor = par.para_motor()
    assert motor["validado_cientificamente"] is False and "no validado" in motor["advertencia"]
    assert "sin validar" in bus.filas_pares([par])[0]["Estado"]
    assert "no validado" in bus.ADVERTENCIA_PAR


def test_fecha_de_interes():
    es = escenas(
        elemento(nombre("20250105")), elemento(nombre("20250117", orbita=57475)),
        elemento(nombre("20250129", orbita=57650)), elemento(nombre("20250210", orbita=57825)),
    )
    sin_evento = bus.emparejar(es, REGION)[0]
    assert (sin_evento.antes.inicio.day, sin_evento.despues.inicio.day) == (5, 17)
    con_evento = bus.emparejar(es, REGION, fecha_evento="2025-01-30")[0]
    assert (con_evento.antes.inicio.date(), con_evento.despues.inicio.date()) == (date(2025, 1, 29), date(2025, 2, 10))
    assert any("Encierra la fecha de interés" in m for m in con_evento.motivos)
    fuera = [p for p in bus.emparejar(es, REGION, fecha_evento="2025-01-30") if p.despues.inicio.date() < date(2025, 1, 30)]
    assert fuera and all(any("No encierra" in a for a in p.avisos) for p in fuera)
    with pytest.raises(ErrorBusqueda, match="fecha válida"):
        bus.emparejar(es, REGION, fecha_evento="mañana")


def test_sin_pares_posibles():
    assert bus.emparejar([], REGION) == []
    assert bus.emparejar(escenas(elemento(nombre("20250105"))), REGION) == []
    assert bus.filas_pares([]) == [] and bus.filas_escenas([]) == []


def test_salida_para_el_motor_de_analisis():
    es = escenas(elemento(nombre("20250105")), elemento(nombre("20250117", orbita=57475)))
    motor = bus.emparejar(es, REGION)[0].para_motor()
    assert set(motor) >= {"antes", "despues", "polarizaciones_comunes", "orbita_relativa", "direccion",
                          "dias_entre_escenas", "cobertura_comun_region", "estado"}
    assert motor["antes"]["nombre"] == nombre("20250105") and motor["despues"]["nombre"] == nombre("20250117", orbita=57475)
    assert motor["polarizaciones_comunes"] == ["VV", "VH"] and motor["dias_entre_escenas"] == 12.0
    assert json.loads(json.dumps(motor)) == motor                             # serializable tal cual


def test_tablas_de_presentacion():
    es = escenas(elemento(nombre("20250105")), elemento(nombre("20250117", "S1C", 600)))
    fila = bus.filas_escenas(es)[0]
    assert fila == {"Fecha (UTC)": "2025-01-05 23:00", "Satélite": "S1A", "Órbita rel.": 48, "Dirección": "Ascendente",
                    "Modo": "IW", "Polarizaciones": "VV+VH", "Cubre la región": 100, "Escena": nombre("20250105"),
                    "Otras versiones": 0, "ASF": es[0].enlace_vertex}
    par = bus.filas_pares(bus.emparejar(es, REGION))[0]
    assert par["Antes"] == "2025-01-05" and par["Después"] == "2025-01-17" and par["Días"] == 12
    assert par["Satélites"] == "S1A / S1C" and par["Cobertura común"] == 100
    assert par["ASF"].startswith("https://search.asf.alaska.edu/") and nombre("20250105") in par["ASF"]


# ---------------------------------------------------------------------------
# Resultados vacíos y errores de conexión
# ---------------------------------------------------------------------------

def buscar(abrir, **kw):
    args = dict(inicio="2026-09-20", fin="2026-10-10", hoy=HOY)
    args.update(kw)
    return bus.buscar(*CHIGORODO, abrir=abrir, **args)


def test_resultado_vacio():
    r = buscar(servidor(coleccion()))
    assert r.escenas == [] and r.pares == [] and r.recomendado is None
    assert r.recibidos == 0 and not r.truncado and r.descartes == {}


def test_respuesta_truncada():
    r = buscar(servidor(coleccion(elemento(nombre("20260924", "S1C", 9596)), elemento(nombre("20261006", "S1C", 9771)))),
               max_resultados=2)
    assert r.truncado and "maxResults=2" in r.url
    assert not buscar(servidor(coleccion(elemento(nombre("20260924", "S1C", 9596))))).truncado


def test_no_se_consulta_si_la_entrada_es_invalida():
    registro = []
    abrir = servidor(coleccion(), registro)
    for kw in (dict(inicio="2026-10-10", fin="2026-09-20"), dict(inicio="2020-01-01"),
               dict(fecha_evento="2027-01-01"), dict(fecha_evento="no")):
        with pytest.raises(ErrorBusqueda):
            buscar(abrir, **kw)
    with pytest.raises(ErrorBusqueda, match="demasiado amplia"):
        bus.buscar(-80, 0, -70, 10, "2026-09-20", "2026-10-10", abrir=abrir, hoy=HOY)
    assert registro == []                                                     # ninguna petición salió


@pytest.mark.parametrize("fallo, mensaje", [
    (urllib.error.URLError("Name or service not known"), "No se pudo conectar"),
    (ConnectionResetError("reset"), "No se pudo conectar"),
    (TimeoutError("timed out"), "tardó demasiado"),
    (socket.timeout("timed out"), "tardó demasiado"),
    (urllib.error.URLError(TimeoutError("timed out")), "tardó demasiado"),
    (urllib.error.HTTPError("u", 503, "Service Unavailable", {}, io.BytesIO(b"")), "no está disponible"),
    (urllib.error.HTTPError("u", 500, "Error", {}, io.BytesIO(b"<html>")), "no está disponible"),
])
def test_errores_de_conexion(fallo, mensaje):
    with pytest.raises(ErrorConexion, match=mensaje):
        buscar(servidor(fallo))


def test_errores_del_servicio():
    rechazo = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(
        json.dumps({"error": {"type": "VALIDATION_ERROR", "report": "Cannot parse bbox"}}).encode()))
    with pytest.raises(ErrorServicio, match="HTTP 400.*Cannot parse bbox") as info:
        buscar(servidor(rechazo))
    assert not isinstance(info.value, ErrorConexion)
    with pytest.raises(ErrorServicio, match="no es JSON"):
        buscar(servidor(b"<html>Mantenimiento</html>"))
    with pytest.raises(ErrorServicio, match="informó un error.*demasiado"):
        buscar(servidor({"error": {"type": "X", "report": "demasiado"}}))
    with pytest.raises(ErrorServicio, match="formato esperado"):
        buscar(servidor({"results": []}))
    with pytest.raises(ErrorServicio, match="formato esperado"):
        buscar(servidor([1, 2, 3]))
    assert issubclass(ErrorConexion, ErrorBusqueda) and issubclass(ErrorServicio, ErrorBusqueda)


# ---------------------------------------------------------------------------
# Caso obligatorio: Chigorodó, con la respuesta real de ASF
# ---------------------------------------------------------------------------

def test_chigorodo_respuesta_real_de_asf():
    registro = []
    r = buscar(servidor(REAL, registro))
    assert "bbox=-76.85%2C7.4%2C-76.4%2C7.95" in registro[0][0].full_url

    assert r.recibidos == 13 and len(r.escenas) == 10 and r.versiones == 3 and r.duplicados == 0
    assert r.descartes == {} and not r.truncado
    nombres = {e.nombre for e in r.escenas} | {v for e in r.escenas for v in e.otras_versiones}
    assert ANTES_CONOCIDA in nombres and DESPUES_CONOCIDA in nombres and len(nombres) == 13

    anterior = next(e for e in r.escenas if e.nombre == ANTES_CONOCIDA)
    assert (anterior.plataforma, anterior.orbita_relativa, anterior.direccion) == ("S1C", 48, "ASCENDING")
    assert anterior.polarizaciones == ("VV", "VH") and anterior.modo == "IW" and anterior.cobertura == pytest.approx(1.0)
    assert anterior.inicio == datetime(2026, 9, 24, 23, 22, 18, tzinfo=timezone.utc)
    assert {(e.plataforma, e.orbita_relativa) for e in r.escenas} == {("S1C", 48), ("S1D", 48), ("S1C", 142), ("S1D", 142), ("S1C", 40)}
    assert all(e.cobertura < 0.5 for e in r.escenas if e.orbita_relativa == 40)   # la órbita 40 apenas toca la región

    par = r.recomendado
    assert (par.antes.nombre, par.despues.nombre) == (ANTES_CONOCIDA, DESPUES_CONOCIDA)
    assert par.recomendado and not par.validado and par.misma_plataforma
    assert round(par.dias) == 12 and par.polarizaciones_comunes == ("VV", "VH")
    assert par.cobertura_comun == pytest.approx(1.0) and par.puntuacion == max(p.puntuacion for p in r.pares)
    assert par.despues.otras_versiones == (DESPUES_CONOCIDA[:-4] + "F000",)
    assert any("otra versión" in a for a in par.avisos)

    assert len(r.pares) == 6
    assert {p.antes.orbita_relativa for p in r.pares} == {48, 142}             # la 40 no alcanza la cobertura mínima
    assert all(bus.geometria_compatible(p.antes, p.despues) for p in r.pares)


def test_el_codigo_no_depende_de_las_escenas_conocidas():
    codigo = (RAIZ / "utils" / "buscador_sar.py").read_text(encoding="utf-8")
    pagina = (RAIZ / "pages" / "2_Buscador_SAR.py").read_text(encoding="utf-8")
    for texto in (codigo, pagina):
        assert "013189" not in texto and "013762" not in texto and "20260924" not in texto
    otra = copy.deepcopy(REAL)                                                 # sin las escenas conocidas, sigue funcionando
    otra["features"] = [f for f in otra["features"] if f["properties"]["pathNumber"] != 48]
    r = buscar(servidor(otra))
    assert r.recomendado.antes.orbita_relativa == 142 and round(r.recomendado.dias) == 12


# ---------------------------------------------------------------------------
# Página de Streamlit
# ---------------------------------------------------------------------------

def abrir_pagina(monkeypatch, cuerpo, registro=None):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(bus.urllib.request, "urlopen", servidor(cuerpo, registro))
    monkeypatch.chdir(RAIZ)
    return AppTest.from_file(str(RAIZ / "pages" / "2_Buscador_SAR.py"), default_timeout=120).run()


def fijar_periodo(at, inicio=date(2026, 9, 20), fin=date(2026, 10, 10)):
    at.date_input(key="bus_inicio").set_value(inicio)
    at.date_input(key="bus_fin").set_value(fin)
    return at


def test_pagina_busca_y_muestra_el_par(monkeypatch):
    registro = []
    at = abrir_pagina(monkeypatch, REAL, registro)
    assert not at.exception and registro == []                               # abrir la página no consulta nada
    assert at.number_input(key="bus_oeste").value == -76.85 and at.number_input(key="bus_norte").value == 7.95
    assert any("no es un par validado" in m.value for m in at.markdown)

    fijar_periodo(at).button[0].click().run()
    assert not at.exception and len(at.error) == 0 and len(registro) == 1
    assert [m.value for m in at.metric] == ["10", "6", "13"]
    assert at.selectbox(key="bus_par").options[0].startswith("2026-09-24 → 2026-10-06 · órbita 48 ascendente · Recomendado")
    textos = " ".join(m.value for m in at.markdown)
    assert ANTES_CONOCIDA in textos and DESPUES_CONOCIDA in textos
    assert "no validado" in textos and "Mismo satélite (S1C)" in textos
    assert "bbox=-76.85" in at.code[0].value

    at.selectbox(key="bus_par").select_index(1).run()                         # comparar otro par
    assert not at.exception and at.selectbox(key="bus_par").index == 1
    assert "Par recomendado, no validado" in " ".join(m.value for m in at.markdown)


def test_pagina_punto_y_radio(monkeypatch):
    registro = []
    at = abrir_pagina(monkeypatch, REAL, registro)
    at.radio(key="bus_modo").set_value("Punto y radio").run()
    fijar_periodo(at).button[0].click().run()
    assert not at.exception and len(at.error) == 0
    consulta = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(registro[0][0].full_url).query))
    oeste, sur, este, norte = (float(v) for v in consulta["bbox"].split(","))
    assert oeste < -76.68 < este and sur < 7.67 < norte and norte - sur == pytest.approx(40 / 110.574, rel=1e-3)


def test_pagina_sin_resultados_y_sin_pares(monkeypatch):
    at = abrir_pagina(monkeypatch, coleccion())
    fijar_periodo(at).button[0].click().run()
    assert not at.exception and "No hay escenas" in at.info[0].value

    una = coleccion(elemento(nombre("20260924", "S1C", 9596)))
    at = abrir_pagina(monkeypatch, una)
    fijar_periodo(at).button[0].click().run()
    assert not at.exception and "Ningún par cumple" in at.info[0].value and at.metric[0].value == "1"


def test_pagina_muestra_errores_sin_caerse(monkeypatch):
    at = abrir_pagina(monkeypatch, urllib.error.URLError("sin red"))
    fijar_periodo(at).button[0].click().run()
    assert not at.exception and "No se pudo conectar" in at.error[0].value and len(at.metric) == 0

    registro = []
    at = abrir_pagina(monkeypatch, REAL, registro)
    fijar_periodo(at, inicio=date(2026, 10, 10), fin=date(2026, 9, 20)).button[0].click().run()
    assert not at.exception and "posterior a la fecha final" in at.error[0].value

    at.number_input(key="bus_oeste").set_value(-60.0)                         # oeste > este
    fijar_periodo(at).button[0].click().run()
    assert not at.exception and "oeste debe ser menor" in at.error[0].value
    assert registro == []                                                     # nada inválido llegó a ASF
