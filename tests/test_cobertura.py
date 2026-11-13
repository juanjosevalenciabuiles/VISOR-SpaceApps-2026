"""Cobertura regional con huellas SINTÉTICAS y con la respuesta real de ASF guardada (Chigorodó)."""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from shapely.geometry import box

from utils import cobertura as cob
from utils import regiones
from utils.buscador_sar import Escena

DATOS = Path(__file__).parent / "datos"


def zona(codigo, nombre, o, s, e, n):
    return regiones.Zona(codigo, nombre, box(o, s, e, n))


@pytest.fixture
def aoi():
    """Tres «municipios» sintéticos en fila de sur a norte (no son límites oficiales)."""
    zonas = (zona("A", "Sur", -77, 7.0, -76, 7.5), zona("B", "Centro", -77, 7.5, -76, 8.0),
             zona("C", "Norte", -77, 8.0, -76, 8.5))
    return regiones._aoi("Fila sintética", zonas, "geojson", "sintético", None)


def escena(dia, hora, sur, norte, orbita=48, plataforma="S1C", absoluta=None, pols=("VV", "VH"),
           direccion="ASCENDING", oeste=-77.5, este=-75.5, segundos=25):
    inicio = datetime(2026, 10, dia, 23, 22, hora, tzinfo=timezone.utc)
    return Escena(nombre=f"{plataforma}_IW_GRDH_{dia:02d}_{hora:02d}_{orbita}", plataforma=plataforma, inicio=inicio,
                  fin=inicio + timedelta(seconds=segundos), orbita_absoluta=absoluta or 1000 + dia,
                  orbita_relativa=orbita, direccion=direccion, modo="IW", nivel="GRD_HD", polarizaciones=pols,
                  huella=box(oeste, sur, este, norte), tamano_bytes=10 ** 9)


def test_dos_cuadros_de_una_pasada_forman_un_mosaico_candidato(aoi):
    escenas = [escena(1, 0, 6.8, 7.8), escena(1, 25, 7.7, 8.7), escena(13, 0, 6.8, 7.8), escena(13, 25, 7.7, 8.7)]
    c = cob.evaluar(escenas, aoi)
    assert [len(p.escenas) for p in c.pasadas] == [2, 2]
    assert all(p.cobertura == pytest.approx(1.0) for p in c.pasadas)
    par = c.mejor_par
    assert par.completo and round(par.dias) == 12 and par.polarizaciones == ("VV", "VH")
    assert par.resumen()["requiere_mosaico"] and par.estado == "Compatible (sin validar)"
    assert any("mosaico" in a for a in par.avisos) and c.avisos == []
    assert c.pasadas[0].tamano_bytes == 2 * 10 ** 9


def test_cobertura_parcial_nunca_es_completa_y_dice_que_municipio_falta(aoi):
    # Segunda fecha: solo el cuadro sur. El par cubre Sur y parte de Centro; Norte queda sin dato.
    escenas = [escena(1, 0, 6.8, 7.8), escena(1, 25, 7.7, 8.7), escena(13, 0, 6.8, 7.7)]
    c = cob.evaluar(escenas, aoi)
    par = c.mejor_par
    assert par.cobertura_comun == pytest.approx(0.7 / 1.5, abs=1e-6) and not par.completo
    assert par.cobertura_zonas == pytest.approx({"A": 1.0, "B": 0.4, "C": 0.0})
    assert any("SIN DATO" in a for a in par.avisos)
    assert any("Sin cobertura en: Norte" in a for a in par.avisos)
    assert any("Cobertura parcial: Centro 40%" in a for a in par.avisos)
    assert any("Ningún par cubre todo el AOI" in a for a in c.avisos)


def test_orbitas_distintas_no_se_combinan(aoi):
    # Órbita 48 cubre el oeste; órbita 121 cubre el este. Juntas cubrirían todo, pero no se mezclan.
    escenas = [escena(1, 0, 6.8, 8.7, orbita=48, este=-76.5), escena(13, 0, 6.8, 8.7, orbita=48, este=-76.5),
               escena(3, 0, 6.8, 8.7, orbita=121, oeste=-76.5), escena(15, 0, 6.8, 8.7, orbita=121, oeste=-76.5)]
    c = cob.evaluar(escenas, aoi)
    assert len(c.pares) == 2 and all(p.cobertura_comun == pytest.approx(0.5) for p in c.pares)
    assert {p.antes.orbita_relativa for p in c.pares} == {48, 121}
    assert all(p.antes.orbita_relativa == p.despues.orbita_relativa for p in c.pares)
    assert c.orbitas == pytest.approx({(48, "ASCENDING"): 0.5, (121, "ASCENDING"): 0.5})
    assert any("varias órbitas relativas" in a for a in c.avisos)


@pytest.mark.parametrize("cambio", [{"direccion": "DESCENDING"}, {"orbita": 49}, {"pols": ("HH",)}])
def test_geometria_o_polarizacion_incompatibles_no_forman_par(aoi, cambio):
    c = cob.evaluar([escena(1, 0, 6.8, 8.7), escena(13, 0, 6.8, 8.7, **cambio)], aoi)
    assert c.pares == [] and any("sin par comparable" in a for a in c.avisos)


def test_cuadros_no_contiguos_no_se_unen(aoi):
    a = escena(1, 0, 6.8, 7.8)
    b = escena(1, 25, 7.7, 8.7)
    lejano = Escena(**{**b.__dict__, "inicio": b.inicio + timedelta(minutes=10), "fin": b.fin + timedelta(minutes=10),
                       "nombre": "lejano"})
    assert [len(p.escenas) for p in cob.agrupar_pasadas([a, lejano], aoi)] == [1, 1]
    assert [len(p.escenas) for p in cob.agrupar_pasadas([a, b], aoi)] == [2]


def test_sin_escenas_sobre_el_aoi(aoi):
    c = cob.evaluar([escena(1, 0, 20, 21)], aoi)
    assert c.pasadas == [] and c.escenas[0][1] == 0 and "Ninguna escena" in c.avisos[0]


def test_la_cobertura_se_mide_sobre_el_poligono_no_sobre_su_recuadro():
    # AOI en «L»: la escena cubre todo el recuadro vacío de la L, pero poco polígono.
    ele = regiones._aoi("L", (zona("V", "Vertical", 0, 0, 1, 10), zona("H", "Horizontal", 1, 0, 10, 1)),
                        "geojson", "sintético", None)
    e = escena(1, 0, 2, 10, oeste=2, este=10)
    assert cob.fraccion(e.huella, box(*ele.limites)) == pytest.approx(0.64)
    assert cob.fraccion(e.huella, ele.geometria) == 0.0


def test_respuesta_real_de_asf_sobre_un_aoi_de_chigorodo():
    """Catálogo REAL guardado (ASF, 20-sep a 10-oct-2026); el AOI es un recuadro, no un límite oficial."""
    aoi = regiones.aoi_recuadro(-76.80, 7.55, -76.55, 7.80, "Recuadro Chigorodó")
    cuerpo = (DATOS / "asf_chigorodo_20260920_20261010.json").read_bytes()

    class Respuesta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    resultado, c = cob.buscar(aoi, "2026-09-20", "2026-10-10", abrir=lambda *a, **k: Respuesta(cuerpo),
                              hoy=date(2026, 11, 13))
    assert resultado.escenas and c.pasadas
    par = next(p for p in c.pares if f"{p.antes.inicio:%Y%m%d}" == "20260924" and f"{p.despues.inicio:%Y%m%d}" == "20261006")
    assert (par.antes.plataforma, par.antes.orbita_relativa, par.antes.direccion) == ("S1C", 48, "ASCENDING")
    assert par.completo and set(par.polarizaciones) == {"VV", "VH"}
    assert c.resumen()["nota"].startswith("Solo metadatos")
