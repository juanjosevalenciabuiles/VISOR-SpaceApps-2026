"""Contrato de la publicación en Replit (Autoscale).

Regresión del 17-nov-2026: excluir .pythonlibs/ dejaba roto el Python de .venv
dentro del contenedor (pyvenv.cfg: home = .pythonlibs/bin), start.sh intentaba
instalar desde PyPI sin red y el despliegue nunca abría el puerto 5000.
"""
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
IGNORAR = RAIZ / ".replitignore"


def _patrones() -> list[str]:
    return [linea.strip() for linea in IGNORAR.read_text(encoding="utf-8").splitlines()
            if linea.strip() and not linea.strip().startswith("#")]


def test_el_entorno_python_del_arranque_se_publica():
    for patron in _patrones():
        base = patron.lstrip("/").rstrip("/*")
        assert base not in (".pythonlibs", ".venv"), (
            f"'{patron}' rompe el Python de .venv en producción")


def test_se_excluye_lo_pesado_que_no_sirve_a_la_app():
    patrones = _patrones()
    for requerido in (".git/", "runtime_env/", "runtime_packages/", "data/nisar/harmony/**"):
        assert requerido in patrones


def test_resultados_sar_y_par_de_demostracion_se_publican():
    patrones = _patrones()
    assert not any(p.startswith("data/analisis") for p in patrones)
    # El modo jurado descubre los pares en data/trabajos/ y sus manifiestos en el catálogo.
    assert not any(p.startswith(("data/trabajos", "data/nisar/catalogo")) for p in patrones)
    assert not any(p.rstrip("/*") == "data" for p in patrones)
    for cache in ("375d3135cd519661", "3875345486d3a7c7"):
        assert f"!data/nisar/harmony/{cache}/**" in patrones


def test_publicacion_usa_el_arranque_que_funciono():
    cfg = tomllib.loads((RAIZ / ".replit").read_text(encoding="utf-8"))
    dep = cfg["deployment"]
    assert dep["deploymentTarget"] == "autoscale"
    assert dep["build"] == ["bash", "start.sh", "--verificar"]
    assert dep["run"] == ["bash", "start.sh"]
    assert cfg["ports"] == [{"localPort": 5000, "externalPort": 80}]
    assert not (RAIZ / "deploy" / "run.sh").exists()
