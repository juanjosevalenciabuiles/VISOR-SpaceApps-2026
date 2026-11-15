"""Regresión: valores truthy no equivalen a QA científico verificado."""
from utils.v10_sentinel.publicacion import publicar_comparacion


def test_publicacion_rechaza_flags_no_booleanos(tmp_path):
    for qa, fuente in (("VERIFICADA", True), (True, "VERIFICADA"), (1, True), (True, 1)):
        destino = tmp_path / "rechazado.tif"
        resultado = publicar_comparacion(
            {"estado": "APTA", "cobertura_qa_completa": True, "clases": [[2]], "pixeles_totales": 1},
            {"crs": "EPSG:4326", "transform": (1, 0, 0, 0, -1, 0)},
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z",
            "pre", "post", destino,
            qa_verificada=qa, fuente_verificada=fuente,
        )
        assert resultado["estado"] == "NO_APTA"
        assert resultado["motivo"] == "FUENTE_O_QA_NO_VERIFICADA"
        assert not destino.exists()
