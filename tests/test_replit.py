"""Pruebas de compatibilidad con Replit: configuración, arranque automático,
entorno virtual y actualización desde GitHub.

Se ejecutan fuera de Replit, con un Python simulado y un almacén Nix de
mentira. Comprueban la lógica de start.sh y actualizar.sh; NO sustituyen la
verificación en el Replit real.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
START = RAIZ / "start.sh"
ACTUALIZAR = RAIZ / "actualizar.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="requiere bash")

PYTHON_FALSO = r"""#!/usr/bin/env bash
# Imita a Python en Replit. Anota cada llamada y obedece estas variables:
#   FALLA_PIP=1       la instalación de dependencias falla
#   PUERTO_OCUPADO=0  el puerto 5000 aparece ocupado
# rasterio solo "importa" si LD_LIBRARY_PATH trae una Expat >= 2.6.
echo "$*" >> "$REGISTRO"
case "${1:-}" in
    -m)
        case "${2:-}" in
            venv) mkdir -p "$3/bin" && cp "$0" "$3/bin/python"; exit 0 ;;
            pip) if [ "${3:-}" = "--version" ]; then exit 0; fi; exit "${FALLA_PIP:-0}" ;;
            *) exit 0 ;;
        esac ;;
    -) exit "${PUERTO_OCUPADO:-1}" ;;
    -c)
        if [[ "$2" == *"print("* ]]; then echo "  Python simulado"; exit 0; fi
        if [[ "$2" == *rasterio* ]]; then
            case ":${LD_LIBRARY_PATH:-}:" in
                *expat-2.8.5/lib:*|*expat-2.7.1/lib:*) exit 0 ;;
                *) echo "ImportError: libexpat.so.1: cannot open shared object file" >&2; exit 1 ;;
            esac
        fi
        exit 0 ;;
esac
exit 0
"""


class Simulacion:
    """Copia mínima del proyecto + Python simulado + almacén Nix de mentira."""

    def __init__(self, tmp: Path):
        self.proyecto = tmp / "proyecto"
        self.proyecto.mkdir()
        shutil.copy(START, self.proyecto / "start.sh")
        shutil.copy(RAIZ / "requirements.txt", self.proyecto / "requirements.txt")
        self.venv = self.proyecto / ".venv"
        self.almacen = tmp / "store"
        for nombre, con_lib in [("aaa-expat-2.5.0", True), ("bbb-expat-2.8.5", True),
                                ("ccc-expat-2.8.5-dev", False), ("ddd-expat-2.7.1", True),
                                ("eee-otracosa-1.0", False)]:
            (self.almacen / nombre / "lib").mkdir(parents=True)
            if con_lib:
                (self.almacen / nombre / "lib" / "libexpat.so.1").touch()
        self.python = tmp / "python"
        self.python.write_text(PYTHON_FALSO)
        self.python.chmod(0o755)
        self.registro = tmp / "registro.txt"
        self.entorno = {"PATH": "/usr/bin:/bin", "VISOR_PYTHON": str(self.python),
                        "VISOR_NIX_STORE": str(self.almacen), "REGISTRO": str(self.registro)}

    def ejecutar(self, *args, **extra):
        return subprocess.run(["bash", str(self.proyecto / "start.sh"), *args],
                              env={**self.entorno, **extra}, capture_output=True, text=True, timeout=60)

    def llamadas(self, texto: str) -> int:
        if not self.registro.exists():
            return 0
        return sum(texto in linea for linea in self.registro.read_text().splitlines())


@pytest.fixture
def sim(tmp_path):
    return Simulacion(tmp_path)


# ---------------------------------------------------------------------------
# Archivos de configuración
# ---------------------------------------------------------------------------

def test_replit_desarrollo_y_despliegue_usan_el_mismo_arranque():
    cfg = tomllib.loads((RAIZ / ".replit").read_text())
    assert cfg["run"] == "bash start.sh"
    assert cfg["deployment"]["run"] == ["bash", "start.sh"]
    assert cfg["deployment"]["build"] == ["bash", "start.sh", "--verificar"]
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
    excluidas = {".git", "tests", ".pythonlibs", ".venv"}
    rutas = [p for p in RAIZ.rglob("*") if p.is_file() and p.suffix in {".py", ".toml", ".sh", ".md", ".yml"}
             and not excluidas & set(p.relative_to(RAIZ).parts)]
    rutas.append(RAIZ / ".replit")
    for ruta in rutas:
        texto = ruta.read_text(encoding="utf-8")
        assert not re.search(r"[?&]key=[A-Za-z0-9]{8,}", texto), f"posible clave en {ruta.name}"
        if ruta.suffix == ".py":
            assert "/home/" not in texto and "/nix/store" not in texto, ruta.name
    # La única ruta fija de Nix es el respaldo explícito de start.sh.
    assert len(re.findall(r"/nix/store/[a-z0-9]{32}-", START.read_text())) == 1
    ignorados = (RAIZ / ".gitignore").read_text().splitlines()
    assert {".venv/", ".env", ".streamlit/secrets.toml", ".visor_anterior"} <= set(ignorados)


def test_los_guiones_no_usan_atajos_peligrosos():
    for guion in (START, ACTUALIZAR):
        assert subprocess.run(["bash", "-n", str(guion)]).returncode == 0
        codigo = "\n".join(l for l in guion.read_text().splitlines() if not l.lstrip().startswith("#"))
        for prohibido in ("--break-system-packages", "pkill", "killall", "reset --hard",
                          "clean -f", "checkout -f", "--force", "git push"):
            assert prohibido not in codigo, f"{guion.name}: {prohibido}"
    codigo = START.read_text()
    assert re.search(r'^exec "\$\{AISLADO\[@\]\}" "\$VPY" -m streamlit run app\.py', codigo, re.M)  # un solo proceso
    assert "git " not in codigo                                    # arrancar nunca actualiza el código


# ---------------------------------------------------------------------------
# start.sh · entorno virtual
# ---------------------------------------------------------------------------

def test_primera_vez_crea_venv_e_instala_dentro_de_el(sim):
    r = sim.ejecutar("--verificar")
    assert r.returncode == 0, r.stderr
    assert "Verificación correcta" in r.stdout
    assert (sim.venv / "bin" / "python").exists()
    assert sim.llamadas(f"-m venv {'.venv'}") == 1
    assert sim.llamadas("-m pip install") == 1 and sim.llamadas("-r requirements.txt") == 1
    assert sim.llamadas("-m streamlit") == 0                       # --verificar no arranca la app
    huella = hashlib.sha256((sim.proyecto / "requirements.txt").read_bytes()).hexdigest()
    assert (sim.venv / ".requisitos").read_text().strip() == huella


def test_segundo_arranque_no_reinstala(sim):
    assert sim.ejecutar("--verificar").returncode == 0
    r = sim.ejecutar("--verificar")
    assert r.returncode == 0 and "Dependencias al día" in r.stdout
    assert sim.llamadas("-m venv") == 1 and sim.llamadas("-m pip install") == 1


def test_cambio_en_requirements_reinstala_sin_rehacer_el_venv(sim):
    assert sim.ejecutar("--verificar").returncode == 0
    with (sim.proyecto / "requirements.txt").open("a") as f:
        f.write("otro-paquete~=1.0\n")
    r = sim.ejecutar("--verificar")
    assert r.returncode == 0 and "Instalando dependencias" in r.stdout
    assert sim.llamadas("-m venv") == 1 and sim.llamadas("-m pip install") == 2
    assert sim.ejecutar("--verificar").returncode == 0
    assert sim.llamadas("-m pip install") == 2                     # y vuelve a quedar al día


def test_instalacion_fallida_no_se_da_por_buena(sim):
    r = sim.ejecutar(FALLA_PIP="1")
    assert r.returncode == 1 and "falló la instalación" in r.stderr
    assert not (sim.venv / ".requisitos").exists() and sim.llamadas("-m streamlit") == 0
    assert sim.ejecutar("--verificar").returncode == 0             # al corregirse, reintenta sola
    assert sim.llamadas("-m pip install") == 2


def test_venv_roto_se_rehace(sim):
    assert sim.ejecutar("--verificar").returncode == 0
    (sim.venv / "bin" / "python").unlink()                         # p. ej. tras reconstruir Nix
    r = sim.ejecutar("--verificar")
    assert r.returncode == 0 and "Creando el entorno virtual" in r.stdout
    assert sim.llamadas("-m venv") == 2 and sim.llamadas("-m pip install") == 2


def test_el_venv_se_aisla_de_las_variables_de_paquetes_de_replit(sim):
    falso = sim.python.read_text().replace(
        'echo "$*" >> "$REGISTRO"',
        'echo "$* [PIP_USER=${PIP_USER:-} PYTHONPATH=${PYTHONPATH:-}]" >> "$REGISTRO"')
    sim.python.write_text(falso)
    assert sim.ejecutar(PIP_USER="1", PYTHONPATH="/home/runner/.pythonlibs").returncode == 0
    lineas = sim.registro.read_text().splitlines()
    for clave in ("-m pip install", "-m streamlit run"):
        linea = next(l for l in lineas if clave in l)
        assert "[PIP_USER=0 PYTHONPATH=]" in linea, linea


def test_verificacion_con_el_interprete_real(tmp_path):
    """pyexpat + rasterio + streamlit importan de verdad en el entorno actual."""
    proyecto = tmp_path / "proyecto"
    (proyecto / ".venv" / "bin").mkdir(parents=True)
    shutil.copy(START, proyecto / "start.sh")
    shutil.copy(RAIZ / "requirements.txt", proyecto / "requirements.txt")
    os.symlink(sys.executable, proyecto / ".venv" / "bin" / "python")
    huella = hashlib.sha256((proyecto / "requirements.txt").read_bytes()).hexdigest()
    (proyecto / ".venv" / ".requisitos").write_text(huella + "\n")
    r = subprocess.run(["bash", str(proyecto / "start.sh"), "--verificar"], capture_output=True, text=True,
                       timeout=120, env={"PATH": "/usr/bin:/bin", "VISOR_PYTHON": sys.executable,
                                         "VISOR_NIX_STORE": "/no/existe"})
    assert r.returncode == 0, r.stderr
    assert "Rasterio:" in r.stdout and "Dependencias al día" in r.stdout


# ---------------------------------------------------------------------------
# start.sh · Expat
# ---------------------------------------------------------------------------

def test_elige_la_expat_mas_nueva_que_funciona(sim):
    r = sim.ejecutar("--verificar")
    assert r.returncode == 0, r.stderr
    assert f"Expat: usando {sim.almacen}/bbb-expat-2.8.5/lib" in r.stdout    # no la 2.5.0 ni la -dev


def test_prefiere_lo_que_declara_replit(sim):
    r = sim.ejecutar("--verificar", REPLIT_LD_LIBRARY_PATH=f"/no/existe:{sim.almacen}/ddd-expat-2.7.1/lib")
    assert r.returncode == 0 and f"Expat: usando {sim.almacen}/ddd-expat-2.7.1/lib" in r.stdout


def test_descarta_expat_incompatible_y_falla_con_mensaje_claro(sim):
    shutil.rmtree(sim.almacen / "bbb-expat-2.8.5")
    shutil.rmtree(sim.almacen / "ddd-expat-2.7.1")                           # solo queda la 2.5.0
    r = sim.ejecutar()
    assert r.returncode == 1 and sim.llamadas("-m streamlit") == 0
    assert "no se pudo importar pyexpat + rasterio" in r.stderr and "libexpat.so.1" in r.stderr
    assert not (sim.venv / ".visor.pid").exists()


# ---------------------------------------------------------------------------
# start.sh · arranque
# ---------------------------------------------------------------------------

def test_arranca_streamlit_y_autoriza_solo_dominios_de_replit(sim):
    r = sim.ejecutar(REPLIT_DEV_DOMAIN="abc-00.riker.replit.dev",
                     REPLIT_DOMAINS='visor.replit.app, malo.com"];x, otro.example.org',
                     CARTO_API_KEY="CLAVESECRETA123")
    assert r.returncode == 0, r.stderr
    args = next(l for l in sim.registro.read_text().splitlines() if l.startswith("-m streamlit")).split()
    assert args[:4] == ["-m", "streamlit", "run", "app.py"]
    assert "--server.port 5000" in " ".join(args) and "--server.address 0.0.0.0" in " ".join(args)
    origenes = [args[i + 1] for i, a in enumerate(args) if a == "--server.corsAllowedOrigins"]
    assert origenes == [
        "https://abc-00.riker.replit.dev", "https://visor.replit.app", "https://otro.example.org"]
    assert "CLAVESECRETA123" not in r.stdout + r.stderr                      # la clave nunca se imprime
    assert "CARTO_API_KEY: disponible" in r.stdout
    assert (sim.venv / ".visor.pid").read_text().strip().isdigit()


def test_fuera_de_replit_no_toca_cors(sim):
    assert sim.ejecutar().returncode == 0
    assert sim.llamadas("-m streamlit run app.py") == 1 and sim.llamadas("corsAllowedOrigins") == 0


def test_puerto_ocupado_por_un_proceso_ajeno_no_se_toca(sim):
    ajeno = subprocess.Popen(["sleep", "30"])
    try:
        sim.venv.mkdir()
        (sim.venv / ".visor.pid").write_text(f"{ajeno.pid}\n")               # PID que no es nuestra app
        (sim.venv / "bin").mkdir()
        shutil.copy(sim.python, sim.venv / "bin" / "python")
        r = sim.ejecutar(PUERTO_OCUPADO="0")
        assert r.returncode == 1 and "No se cerró nada" in r.stderr
        assert sim.llamadas("-m streamlit") == 0
        assert ajeno.poll() is None                                          # sigue vivo
    finally:
        ajeno.kill()


def test_opcion_desconocida(sim):
    r = sim.ejecutar("--borrar-todo")
    assert r.returncode == 1 and "opción desconocida" in r.stderr and not sim.venv.exists()


# ---------------------------------------------------------------------------
# actualizar.sh
# ---------------------------------------------------------------------------

def git(carpeta, *args):
    r = subprocess.run(["git", "-c", "user.name=Prueba", "-c", "user.email=p@example.com",
                        "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
                       cwd=carpeta, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class Repos:
    """Un 'GitHub' local (remoto), la copia de otra persona y el 'Replit'."""

    def __init__(self, tmp: Path):
        self.remoto, self.colega, self.replit = tmp / "github.git", tmp / "colega", tmp / "replit"
        git(tmp, "init", "--bare", str(self.remoto))
        git(tmp, "clone", str(self.remoto), str(self.colega))
        shutil.copy(ACTUALIZAR, self.colega / "actualizar.sh")
        (self.colega / "start.sh").write_text(
            '#!/usr/bin/env bash\n# admite --verificar\n[ -f FALLA ] && { echo "verificación falló"; exit 1; }\n'
            'echo "verificado: $(cat app.txt)"\n')
        (self.colega / "app.txt").write_text("v1\n")
        self.publicar("v1", "main", nueva=True)
        git(tmp, "clone", str(self.remoto), str(self.replit))

    def publicar(self, mensaje, rama, nueva=False, **archivos):
        if not nueva and git(self.colega, "branch", "--list", rama) == "":
            git(self.colega, "checkout", "-b", rama)
        elif not nueva:
            git(self.colega, "checkout", rama)
        for nombre, contenido in archivos.items():
            (self.colega / nombre.replace("__", ".")).write_text(contenido)
        git(self.colega, "add", "-A")
        git(self.colega, "commit", "-m", mensaje, "--allow-empty")
        git(self.colega, "push", "origin", f"HEAD:{rama}")

    def actualizar(self, *args):
        return subprocess.run(["bash", "actualizar.sh", *args], cwd=self.replit, capture_output=True, text=True,
                              timeout=60, env={"PATH": os.environ["PATH"], "HOME": str(self.replit.parent),
                                               "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "Prueba",
                                               "GIT_AUTHOR_EMAIL": "p@example.com", "GIT_COMMITTER_NAME": "Prueba",
                                               "GIT_COMMITTER_EMAIL": "p@example.com"})

    def version(self):
        return (self.replit / "app.txt").read_text().strip()

    def rama(self):
        return git(self.replit, "rev-parse", "--abbrev-ref", "HEAD")


@pytest.fixture
def repos(tmp_path):
    return Repos(tmp_path)


def test_actualizar_trae_los_commits_nuevos_y_prepara_dependencias(repos):
    repos.publicar("v2", "main", app__txt="v2\n")
    r = repos.actualizar()
    assert r.returncode == 0, r.stderr
    assert repos.version() == "v2" and "verificado: v2" in r.stdout and "Pulsa Run" in r.stdout
    r = repos.actualizar()
    assert r.returncode == 0 and "Ya estabas al día" in r.stdout


def test_actualizar_se_detiene_si_hay_cambios_locales(repos):
    repos.publicar("v2", "main", app__txt="v2\n")
    (repos.replit / "app.txt").write_text("mi trabajo sin guardar\n")
    r = repos.actualizar()
    assert r.returncode == 2 and "No se actualizó nada" in r.stdout
    assert repos.version() == "mi trabajo sin guardar"                       # intacto


def test_actualizar_guardar_aparta_los_cambios_sin_perderlos(repos):
    repos.publicar("v2", "main", otro__txt="nuevo\n")
    (repos.replit / "app.txt").write_text("mi trabajo sin guardar\n")
    r = repos.actualizar("--guardar")
    assert r.returncode == 0, r.stderr
    assert (repos.replit / "otro.txt").exists() and repos.version() == "v1"
    assert "visor-antes-de-actualizar" in git(repos.replit, "stash", "list")
    git(repos.replit, "stash", "pop")
    assert repos.version() == "mi trabajo sin guardar"                       # recuperable


def test_archivos_sin_registrar_no_bloquean_ni_se_borran(repos):
    (repos.replit / "notas_locales.txt").write_text("apuntes\n")
    repos.publicar("v2", "main", app__txt="v2\n")
    assert repos.actualizar().returncode == 0
    assert repos.version() == "v2" and (repos.replit / "notas_locales.txt").read_text() == "apuntes\n"


def test_cambiar_a_rama_de_pruebas_y_volver(repos):
    repos.publicar("v1.1", "feature/visor-v1.1", app__txt="v1.1\n")
    r = repos.actualizar("feature/visor-v1.1")
    assert r.returncode == 0, r.stderr
    assert repos.rama() == "feature/visor-v1.1" and repos.version() == "v1.1"

    r = repos.actualizar("--volver")
    assert r.returncode == 0, r.stderr
    assert repos.rama() == "main" and repos.version() == "v1" and "verificado: v1" in r.stdout

    assert repos.actualizar("feature/visor-v1.1").returncode == 0            # y de nuevo a pruebas
    assert repos.actualizar("main").returncode == 0                          # versión estable por nombre
    assert repos.rama() == "main" and repos.version() == "v1"


def test_volver_tras_avanzar_la_misma_rama(repos):
    anterior = git(repos.replit, "rev-parse", "HEAD")
    repos.publicar("v2", "main", app__txt="v2\n")
    assert repos.actualizar().returncode == 0 and repos.version() == "v2"
    r = repos.actualizar("--volver")
    assert r.returncode == 0, r.stderr
    assert git(repos.replit, "rev-parse", "HEAD") == anterior and repos.version() == "v1"
    assert git(repos.replit, "rev-parse", "main") != anterior                # la rama no se reescribió


def test_si_la_version_nueva_no_verifica_avisa_como_regresar(repos):
    repos.publicar("v2 rota", "main", app__txt="v2\n", FALLA="x\n")
    r = repos.actualizar()
    assert r.returncode == 1 and "bash actualizar.sh --volver" in r.stderr
    assert repos.actualizar("--volver").returncode == 0 and repos.version() == "v1"


def test_no_fusiona_ni_reescribe_si_hay_commits_locales(repos):
    (repos.replit / "app.txt").write_text("commit local\n")
    git(repos.replit, "commit", "-am", "trabajo local")
    local = git(repos.replit, "rev-parse", "HEAD")
    repos.publicar("v2", "main", otro__txt="x\n")
    r = repos.actualizar()
    assert r.returncode == 3 and "commits propios" in r.stderr
    assert git(repos.replit, "rev-parse", "HEAD") == local and repos.version() == "commit local"


def test_rama_inexistente_y_opcion_desconocida(repos):
    antes = git(repos.replit, "rev-parse", "HEAD")
    r = repos.actualizar("no-existe")
    assert r.returncode == 1 and "no se pudo descargar" in r.stderr
    assert repos.actualizar("--forzar").returncode == 1
    assert repos.actualizar("--volver").returncode in (0, 1)
    assert git(repos.replit, "rev-parse", "HEAD") == antes and repos.rama() == "main"
