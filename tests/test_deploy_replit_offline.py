"""Contrato de publicacion Replit: build instala, runtime solo sirve app.

Esta prueba NO descarga paquetes ni accede a NASA, Harmony o GeoTIFF.
"""
from pathlib import Path
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_build_y_run_prod_separados_de_start_dev():
    config = tomllib.loads((ROOT / ".replit").read_text(encoding="utf-8"))
    assert config["run"] == "bash start.sh"
    assert config["deployment"]["build"] == ["bash", "deploy/build.sh"]
    assert config["deployment"]["run"] == ["bash", "deploy/run.sh"]
    assert config["ports"] == [{"localPort": 5000, "externalPort": 80}]


def test_sintaxis_scripts_de_deployment():
    for path in ("deploy/build.sh", "deploy/run.sh"):
        subprocess.run(["bash", "-n", str(ROOT / path)], check=True)


def test_run_no_instala_paquetes_ni_modifica_datos():
    build = (ROOT / "deploy/build.sh").read_text(encoding="utf-8")
    run = (ROOT / "deploy/run.sh").read_text(encoding="utf-8")
    ignore = (ROOT / ".replitignore").read_text(encoding="utf-8")
    assert "bash start.sh --verificar" in build
    assert "runtime_packages" in build
    assert "runtime_packages" in run
    assert "PYTHONPATH=" in run
    assert "python" in run
    assert "--server.port" in run and "0.0.0.0" in run
    assert "pip install" not in run
    assert "start.sh --verificar" not in run
    assert "rm -rf" not in run
    assert "data/nisar/harmony/**" in ignore
    assert ".git/" in ignore and ".venv/" in ignore
    assert "runtime_packages/" not in [
        line.strip() for line in ignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "data/analisis/" not in [
        line.strip() for line in ignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
