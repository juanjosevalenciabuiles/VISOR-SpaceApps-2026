"""Pruebas sintéticas sin red para clasificación conservadora WTR."""
import pytest
import numpy as np

from utils.v10_sentinel.wtr import comparar_wtr

GEO = {"crs": "EPSG:32618", "transform": (30.0, 0.0, 500000.0, 0.0, -30.0, 900000.0)}



def test_agua_nueva_persistente_y_ambigua():
    resultado = comparar_wtr(
        [[0, 1, 0, 9]], [[1, 1, 0, 1]],
        [[True] * 4], [[True] * 4],
        codigos={"agua": 1, "no_agua": 0}, version_verificada=True, georef_anterior=GEO, georef_posterior=GEO,
    )
    assert resultado["estado"] == "NO_APTA"
    assert resultado["clases"] is None
    assert resultado["cobertura_qa_completa"] is False
    assert resultado["pixeles_validos"] == 3


def test_qa_faltante_no_publica_mapa():
    resultado = comparar_wtr(
        [[0]], [[1]], [[True]], [[False]],
        codigos={"agua": 1, "no_agua": 0}, version_verificada=True, georef_anterior=GEO, georef_posterior=GEO,
    )
    assert resultado["estado"] == "NO_APTA"
    assert resultado["clases"] is None


def test_sin_codebook_verificado_rechaza():
    with pytest.raises(ValueError, match="no está verificada"):
        comparar_wtr([[0]], [[1]], [[True]], [[True]],
                     codigos={"agua": 1, "no_agua": 0})


def test_codigo_ambiguo_no_se_declara_agua():
    with pytest.raises(ValueError, match="inequívocos"):
        comparar_wtr([[0]], [[1]], [[True]], [[True]],
                     codigos={"agua": 1, "no_agua": 0, "sombra": 9},
                     version_verificada=True, georef_anterior=GEO, georef_posterior=GEO)


def test_cobertura_completa_permite_salida_exploratoria():
    resultado = comparar_wtr(
        [[0, 1, 0]], [[1, 1, 0]],
        [[True] * 3], [[True] * 3],
        codigos={"agua": 1, "no_agua": 0}, version_verificada=True, georef_anterior=GEO, georef_posterior=GEO,
    )
    assert resultado["estado"] == "APTA"
    assert resultado["cobertura_qa_completa"] is True
    assert resultado["clases"] == [[2, 1, 0]]


def test_codigo_desconocido_en_post_impide_publicacion_parcial():
    resultado = comparar_wtr(
        [[0, 0]], [[1, 9]], [[True, True]], [[True, True]],
        codigos={"agua": 1, "no_agua": 0}, version_verificada=True, georef_anterior=GEO, georef_posterior=GEO,
    )
    assert resultado["estado"] == "NO_APTA"
    assert resultado["clases"] is None
    assert resultado["pixeles_validos"] == 1


def test_mascaras_numpy_booleanas_de_rasterio():
    """La QA booleana de un COG no debe descartarse por identidad Python."""
    resultado = comparar_wtr(
        np.array([[0, 1]], dtype=np.uint8),
        np.array([[1, 1]], dtype=np.uint8),
        np.array([[True, True]], dtype=np.bool_),
        np.array([[True, True]], dtype=np.bool_),
        mascara_aoi=np.array([[True, False]], dtype=np.bool_),
        codigos={"agua": 1, "no_agua": 0},
        version_verificada=True,
        georef_anterior=GEO,
        georef_posterior=GEO,
    )
    assert resultado["estado"] == "APTA"
    assert resultado["clases"] == [[2, 255]]
    assert resultado["pixeles_totales"] == 1


def test_qa_numerica_no_autoriza_publicacion():
    resultado = comparar_wtr(
        [[0]], [[1]], [[1]], [[1]],
        codigos={"agua": 1, "no_agua": 0},
        version_verificada=True,
        georef_anterior=GEO, georef_posterior=GEO,
    )
    assert resultado["estado"] == "NO_APTA"
    assert resultado["clases"] is None
