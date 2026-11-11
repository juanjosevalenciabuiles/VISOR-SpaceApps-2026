"""Pruebas de compatibilidad con Replit: configuración, arranque y seguridad.

Se ejecutan fuera de Replit. Comprueban que los archivos de configuración son
coherentes y que start.sh elige bien la biblioteca Expat en un almacén Nix
simulado; NO sustituyen la verificación en el Replit real.
"""
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
START = RAIZ / "start.sh"
necesita_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="requiere bash")

PYTHON_FALSO = """#!/usr/bin/env bash
# Imita a Python en Replit: pyexpat + rasterio solo importan con una Expat >= 2.6.
if [ "${1:-}" = "-m" ]; then
    echo "$*" > "$REGISTRO"
    exit 0
fi
if [ "${1:-}" = "-" ]; then exit 1; fi            # consulta de puerto: libre
if [[ "$*" == *"print("* ]]; then echo "Expat: simulada | Rasterio: simulado"; fi
case ":${LD_LIBRARY_PATH:-}:" in
    *expat-2.8.5/lib:*|*expat-2.7.1/lib:*) exit 0 ;;
    *) echo "ImportError: libexpat.so.1: cannot open shared object file" >&2; exit 1 ;;
esac
"""


@pytest.fixture
def replit_simulado(tmp_path):
    """Almacén Nix de mentira con varias Expat, y un intérprete simulado."""
    almacen = tmp_path / "store"
    for nombre, con_lib in [("aaa-expat-2.5.0", True), ("bbb-expat-2.8.5", True),
                            ("ccc-expat-2.8.5-dev", False), ("ddd-expat-2.7.1", True),
                            ("eee-otracosa-1.0", False)]:
        (almacen / nombre / "lib").mkdir(parents=True)
        if con_lib:
            (almacen / nombre / "lib" / "libexpat.so.1").touch()
    falso = tmp_path / "python"
    falso.write_text(PYTHON_FALSO)
    falso.chmod(0o755)
    entorno = {"PATH": "/usr/bin:/bin", "VISOR_PYTHON": str(falso), "VISOR_NIX_STORE": str(almacen),
               "REGISTRO": str(tmp_path / "registro.txt")}
    return almacen, entorno, tmp_path / "registro.txt"


def ejecutar(entorno, *args):
    return subprocess.run(["bash", str(START), *args], env=entorno, capture_output=True, text=True, timeout=60)


# ---------------------------------------------------------------------------
# Archivos de configuración
# ---------------------------------------------------------------------------

def test_replit_desarrollo_y_despliegue_usan_el_mismo_arranque():
    cfg = tomllib.loads((RAIZ / ".replit").read_text())
    assert cfg["run"] == "bash start.sh"
    assert cfg["deployment"]["run"] == ["bash", "start.sh"]
    assert "python-3.12" in cfg["modules"]
    assert "expat" in cfg["nix"]["packages"]


def test_puerto_5000_coherente():
    cfg = tomllib.loads((RAIZ / ".replit").read_text())
    assert cfg["ports"] == [{"localPort": 5000, "externalPort": 80}]
    guion = START.read_text()
    assert re.search(r"^PUERTO=5000$", guion, re.M) and '--server.port "$PUERTO"' in guion
    assert "port" not in tomllib.loads((RAIZ / ".streamlit/config.toml").read_text()).get("server", {})


def test_cors_y_xsrf_siguen_activados():
    servidor = tomllib.loads((RAIZ / ".streamlit/config.toml").read_text()).get("server", {})
    assert servidor.get("enableCORS", True) is True
    assert servidor.get("enableXsrfProtection", True) is True
    guion = START.read_text()
    assert "enableCORS" not in guion and "enableXsrfProtection" not in guion


def test_dependencias_acotadas():
    lineas = [l.strip() for l in (RAIZ / "requirements.txt").read_text().splitlines()]
    paquetes = [l for l in lineas if l and not l.startswith("#")]
    assert {re.split(r"[~=<>]", p)[0] for p in paquetes} >= {
        "streamlit", "folium", "streamlit-folium", "rasterio", "numpy", "geopandas", "pytest"}
    assert all(re.search(r"(~=|==)\d", p) for p in paquetes)


def test_sin_credenciales_ni_rutas_absolutas_en_el_codigo():
    rutas = [p for p in RAIZ.rglob("*") if p.is_file() and p.suffix in {".py", ".toml", ".sh", ".md", ".yml"}
             and not {".git", "tests", ".pythonlibs", ".venv"} & set(p.relative_to(RAIZ).parts)]
    rutas.append(RAIZ / ".replit")
    for ruta in rutas:
        texto = ruta.read_text(encoding="utf-8")
        assert not re.search(r"[?&]key=[A-Za-z0-9]{8,}", texto), f"posible clave en {ruta.name}"
        if ruta.suffix == ".py":
            assert "/home/" not in texto and "/nix/store" not in texto, ruta.name
    # La única ruta fija de Nix es el respaldo explícito de start.sh.
    assert len(re.findall(r"/nix/store/[a-z0-9]{32}-", START.read_text())) == 1
    ignorados = (RAIZ / ".gitignore").read_text()
    assert ".env" in ignorados and ".streamlit/secrets.toml" in ignorados


# ---------------------------------------------------------------------------
# start.sh
# ---------------------------------------------------------------------------

@necesita_bash
def test_start_sh_sintaxis_y_un_solo_proceso():
    assert subprocess.run(["bash", "-n", str(START)]).returncode == 0
    guion = START.read_text()
    assert re.search(r'^exec "\$PY" -m streamlit run app\.py', guion, re.M)   # reemplaza al shell
    assert guion.count("streamlit run app.py \\") == 1
    assert "liberar_puerto" in guion and "pkill" in guion


@necesita_bash
def test_start_sh_verifica_el_entorno_real():
    r = subprocess.run(["bash", str(START), "--verificar"], capture_output=True, text=True, timeout=120,
                       env={"PATH": "/usr/bin:/bin", "VISOR_PYTHON": sys.executable,
                            "VISOR_NIX_STORE": "/no/existe"})
    assert r.returncode == 0, r.stderr
    assert "Rasterio:" in r.stdout and "Verificación correcta" in r.stdout


@necesita_bash
def test_start_sh_elige_la_expat_mas_nueva_que_funciona(replit_simulado):
    almacen, entorno, _ = replit_simulado
    r = ejecutar(entorno, "--verificar")
    assert r.returncode == 0, r.stderr
    assert f"Expat: usando {almacen}/bbb-expat-2.8.5/lib" in r.stdout    # no la 2.5.0 ni la -dev


@necesita_bash
def test_start_sh_prefiere_lo_que_declara_replit(replit_simulado):
    almacen, entorno, _ = replit_simulado
    entorno["REPLIT_LD_LIBRARY_PATH"] = f"/no/existe:{almacen}/ddd-expat-2.7.1/lib"
    r = ejecutar(entorno, "--verificar")
    assert r.returncode == 0 and f"Expat: usando {almacen}/ddd-expat-2.7.1/lib" in r.stdout


@necesita_bash
def test_start_sh_descarta_expat_incompatible_y_falla_con_mensaje_claro(replit_simulado):
    almacen, entorno, registro = replit_simulado
    shutil.rmtree(almacen / "bbb-expat-2.8.5")
    shutil.rmtree(almacen / "ddd-expat-2.7.1")                           # solo queda la 2.5.0
    r = ejecutar(entorno)
    assert r.returncode == 1 and not registro.exists()                   # Streamlit no arranca
    assert "no se pudo importar pyexpat + rasterio" in r.stderr and "libexpat.so.1" in r.stderr


@necesita_bash
def test_start_sh_arranca_streamlit_y_autoriza_solo_dominios_de_replit(replit_simulado):
    _, entorno, registro = replit_simulado
    entorno.update(REPLIT_DEV_DOMAIN="abc-00.riker.replit.dev",
                   REPLIT_DOMAINS='visor.replit.app, malo.com"];x, otro.example.org',
                   CARTO_API_KEY="CLAVESECRETA123")
    r = ejecutar(entorno)
    assert r.returncode == 0, r.stderr
    args = registro.read_text().split()
    assert args[:4] == ["-m", "streamlit", "run", "app.py"]
    assert "--server.port 5000" in " ".join(args) and "--server.address 0.0.0.0" in " ".join(args)
    origenes = [args[i + 1] for i, a in enumerate(args) if a == "--server.corsAllowedOrigins"]
    assert origenes == [
        "https://abc-00.riker.replit.dev", "https://visor.replit.app", "https://otro.example.org"]
    assert "CLAVESECRETA123" not in r.stdout + r.stderr                  # la clave nunca se imprime
    assert "CARTO_API_KEY: disponible" in r.stdout


@necesita_bash
def test_start_sh_fuera_de_replit_no_toca_cors(replit_simulado):
    _, entorno, registro = replit_simulado
    assert ejecutar(entorno).returncode == 0
    assert "corsAllowedOrigins" not in registro.read_text()
