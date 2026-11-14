"""Entorno común de las pruebas.

- Los trabajos de análisis se guardan en una carpeta temporal, nunca en data/trabajos/ del equipo.
- Las pruebas con AppTest ejecutan el trabajo en el mismo hilo (VISOR_TRABAJOS_SINCRONOS=1): es el
  mismo código de fases, registro y verificación, sin el hilo. El modo en segundo plano lo cubren
  tests/test_trabajos.py (hilos reales) y las pruebas de navegador (servidor real, sin esta variable).
- La comprobación automática de servicios externos queda desactivada (no hay red en las pruebas).
"""
import os
import tempfile

os.environ.setdefault("VISOR_TRABAJOS_DIR", tempfile.mkdtemp(prefix="visor_trabajos_"))
os.environ.setdefault("VISOR_TRABAJOS_SINCRONOS", "1")
os.environ.setdefault("VISOR_DIAGNOSTICO", "desactivado")
