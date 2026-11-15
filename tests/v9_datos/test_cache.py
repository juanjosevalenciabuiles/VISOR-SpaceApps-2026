"""Pruebas offline, datos sintéticos."""
import hashlib
import pytest
from utils.v9_datos.cache import firma_cache, guardar, recuperar


def firma(madurez="PROVISIONAL", qa="qa1"):
    return firma_cache(["A", "B"], [-76.7, 7.5, -76.6, 7.6], "v9", qa, madurez, "HH")


def test_hit_miss_integridad(tmp_path):
    key = firma()
    digest = hashlib.sha256(b"abc").hexdigest()
    assert recuperar(tmp_path, key, sha256=digest)["estado"] == "MISS"
    assert guardar(tmp_path, key, b"abc")["estado"] == "GUARDADO"
    assert recuperar(tmp_path, key, sha256=digest)["contenido"] == b"abc"
    assert recuperar(tmp_path, key, sha256="0" * 64)["estado"] == "CACHE_INVALIDA"


def test_madurez_qa_aisladas():
    assert firma() != firma("VALIDATED")
    assert firma() != firma(qa="qa2")


def test_presupuesto(tmp_path):
    key = firma()
    assert guardar(tmp_path, key, b"abcd", max_bytes=3)["estado"] == "PRESUPUESTO_EXCEDIDO"
    assert guardar(tmp_path, key, b"abcd")["estado"] == "GUARDADO"
    assert recuperar(tmp_path, key, sha256=hashlib.sha256(b"abcd").hexdigest(),
                     max_bytes=3)["estado"] == "PRESUPUESTO_EXCEDIDO"


def test_entradas_invalidas():
    with pytest.raises(ValueError):
        firma("DESCONOCIDA")
    with pytest.raises(ValueError):
        firma_cache(["A"], [float("nan"), 0, 1, 2], "v", "qa", "PROVISIONAL", "HH")
