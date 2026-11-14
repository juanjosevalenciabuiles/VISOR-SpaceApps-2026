"""El plan de NISAR debe priorizar la cobertura del sitio de interés."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from shapely.geometry import box

from utils.nisar_auto import ErrorAutoNISAR, planear

AOI = (-76.8, 7.55, -76.55, 7.8)
PUNTO = (-76.6774845, 7.6645455)


def _candidato(nombre, huella):
    return NS(granule=nombre, huella=huella, tamano_bytes=800_000_000,
              url_h5=f"https://nisar.asf.earthdatacloud.nasa.gov/{nombre}.h5",
              nombre=NS(pol_a=("HH", "HV")))


def _par(a, b, cobertura):
    return NS(antes=a, despues=b, cobertura_comun=cobertura,
              polarizaciones_A=("HH", "HV"))


def _resultado():
    # Mejor pareja por % AOI: solo flanco occidental, sin cabecera.
    oeste = box(-76.8, 7.55, -76.742, 7.80)
    centro = box(-76.76, 7.60, -76.59, 7.73)
    a, b = _candidato("OCT_OESTE", oeste), _candidato("NOV_OESTE", oeste)
    c, d = _candidato("OCT_CENTRO", centro), _candidato("NOV_CENTRO", centro)
    return NS(
        region=NS(limites=AOI),
        candidatos=[a, b, c, d],
        pares=[_par(a, b, .81), _par(c, d, .31)],
    )


def test_sin_ancla_prefiere_cobertura_total_mayor():
    p = planear(_resultado(), cobertura_minima=.20)
    assert p.granules == ("OCT_OESTE", "NOV_OESTE")
    assert p.resumen()["punto_prioritario"] is None


def test_con_ancla_prefiere_par_sobre_cabecera_aunque_area_aoI_menor():
    p = planear(_resultado(), cobertura_minima=.20, punto_prioritario=PUNTO,
                aceptar_escena_unica=False)
    assert p.granules == ("OCT_CENTRO", "NOV_CENTRO")
    assert p.resumen()["punto_prioritario"] == list(PUNTO)
    assert p.resumen()["cobertura_punto"] == "SOLO_HUELLAS_CMR_NO_QA"
    assert "NO verifica la cobertura QA" in " ".join(p.avisos)


def test_bloquea_par_sin_dos_huellas_sobre_el_punto():
    r = _resultado()
    r.pares = r.pares[:1]
    with pytest.raises(ErrorAutoNISAR, match="No existe un par NISAR candidato"):
        planear(r, cobertura_minima=.20, punto_prioritario=PUNTO,
                aceptar_escena_unica=False)


def test_bloquea_punto_fuera_del_area():
    with pytest.raises(ErrorAutoNISAR, match="fuera del AOI"):
        planear(_resultado(), cobertura_minima=.20,
                punto_prioritario=(-76.4, 7.6645),
                aceptar_escena_unica=False)


def test_ambas_huellas_obligatorias():
    r = _resultado()
    r.pares[1].despues.huella = None
    with pytest.raises(ErrorAutoNISAR, match="No existe un par"):
        planear(r, cobertura_minima=.20, punto_prioritario=PUNTO,
                aceptar_escena_unica=False)
