"""Pruebas sintéticas sin red para clasificación conservadora WTR."""
import pytest

from utils.v10_sentinel.wtr import comparar_wtr


def test_agua_nueva_persistente_y_ambigua():
    resultado = comparar_wtr(
        [[0, 1, 0, 9]], [[1, 1, 0, 1]],
        [[True] * 4], [[True] * 4],
        codigos={"agua": 1, "no_agua": 0}, version_verificada=True,
    )
    assert resultado["clases"] == [[2, 1, 0, 255]]
    assert resultado["pixeles_validos"] == 3


def test_qa_faltante_no_publica_mapa():
    resultado = comparar_wtr(
        [[0]], [[1]], [[True]], [[False]],
        codigos={"agua": 1, "no_agua": 0}, version_verificada=True,
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
                     version_verificada=True)
