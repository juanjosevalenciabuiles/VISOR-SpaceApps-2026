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
