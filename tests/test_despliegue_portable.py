"""Regresiones estructurales del despliegue Docker, sin red ni secretos."""
from pathlib import Path

import pytest

from scripts.arranque_portable import preparar_datos, puerto_valido

RAIZ = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("valor", ["0", "-1", "65536", "abc", "", "8501.5"])
def test_rechaza_puertos_invalidos(valor):
    with pytest.raises(ValueError):
        puerto_valido(valor)


@pytest.mark.parametrize("valor", ["8501", "10000", "5000", "65535"])
def test_admite_puertos_proveedor(valor):
    assert puerto_valido(valor) == int(valor)


def test_volumen_copia_recursos_publicos_sin_pisar_real(tmp_path):
    origen = tmp_path / "empaquetados"
    destino = tmp_path / "persistentes"
    (origen / "contexto").mkdir(parents=True)
    (origen / "contexto" / "municipios.geojson").write_text("PUBLICO", encoding="utf-8")
    (origen / "inundacion.tif").write_bytes(b"DEMO")
    (destino / "contexto").mkdir(parents=True)
    (destino / "contexto" / "municipios.geojson").write_text("PERSONAL", encoding="utf-8")
    (destino / "analisis").mkdir()
    (destino / "analisis" / "real.tif").write_bytes(b"REAL")
    assert preparar_datos(origen, destino) == 1
    assert (destino / "contexto" / "municipios.geojson").read_text() == "PERSONAL"
    assert (destino / "analisis" / "real.tif").read_bytes() == b"REAL"
    assert (destino / "inundacion.tif").read_bytes() == b"DEMO"
    assert preparar_datos(origen, destino) == 0


def test_arranque_no_usa_shell_ni_incluye_secretos():
    script = (RAIZ / "scripts" / "arranque_portable.py").read_text()
    docker = (RAIZ / "Dockerfile").read_text()
    ignorados = (RAIZ / ".dockerignore").read_text()
    assert "os.execv(" in script
    assert "shell=True" not in script
    assert "USER visor" in docker
    assert "scripts/arranque_portable.py" in docker
    assert "_stcore/health" in docker
    for excluido in (".env", ".streamlit/secrets.toml", "data/sar/",
                     "data/analisis/", "data/nisar/", "data/trabajos/"):
        assert excluido in ignorados


def test_documentacion_advierte_ausencia_datos_reales():
    texto = (RAIZ / "docs" / "DESPLIEGUE_PORTABLE.md").read_text(encoding="utf-8")
    assert "NO se incluyen" in texto
    assert "no traslada automáticamente" in texto
    assert "no inundaciones verificadas" in texto
