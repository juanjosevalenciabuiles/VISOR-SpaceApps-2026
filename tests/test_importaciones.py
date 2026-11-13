"""Cada módulo se importa solo, en un proceso limpio y en cualquier orden.

Protege contra importaciones circulares y nombres faltantes como el
`ImportError: cannot import name 'insignia'` visto una vez en Replit
(causa probable: recarga en caliente de Streamlit durante `git pull`, con
módulos viejos y nuevos mezclados en memoria).
"""
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
MODULOS = sorted(
    f"{p.parent.name}.{p.stem}"
    for carpeta in ("components", "utils")
    for p in (RAIZ / carpeta).glob("*.py")
    if p.stem != "__init__"
)


@pytest.mark.parametrize("modulo", MODULOS)
def test_modulo_se_importa_solo(modulo):
    r = subprocess.run([sys.executable, "-c", f"import {modulo}"], cwd=RAIZ,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]


def test_app_completa_arranca_en_proceso_limpio():
    codigo = ("from streamlit.testing.v1 import AppTest\n"
              "at = AppTest.from_file('app.py', default_timeout=120).run()\n"
              "assert not at.exception, at.exception\n")
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]


def test_dependencias_externas_declaradas():
    """Todo paquete externo que importa la app está en requirements.txt (o en requirements-dev.txt
    si solo lo usan las pruebas). Evita que Replit falle por una dependencia que aquí llegó de rebote."""
    import ast
    distribucion = {"streamlit_folium": "streamlit-folium"}
    solo_desarrollo = {"playwright"}
    pedidos = {ln.split("~=")[0].split(">=")[0].split("<")[0].strip().lower()
               for ln in (RAIZ / "requirements.txt").read_text().splitlines() if ln.strip() and not ln.startswith("#")}
    dev = (RAIZ / "requirements-dev.txt").read_text().lower()
    usados = set()
    for carpeta in ("components", "utils", "pages", "scripts"):
        for p in (RAIZ / carpeta).glob("*.py"):
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Import):
                    usados |= {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                    usados.add(n.module.split(".")[0])
    externos = {m for m in usados if m not in sys.stdlib_module_names and m not in ("utils", "components")}
    faltan = [m for m in externos if distribucion.get(m, m).lower() not in pedidos
              and not (m in solo_desarrollo and m in dev)]
    assert not faltan, f"importados pero no declarados en requirements.txt: {faltan}"
