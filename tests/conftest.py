"""Entorno común de las pruebas.

- Los trabajos de análisis se guardan en una carpeta temporal, nunca en data/trabajos/ del equipo.
- Las pruebas con AppTest ejecutan el trabajo en el mismo hilo (VISOR_TRABAJOS_SINCRONOS=1): es el
  mismo código de fases, registro y verificación, sin el hilo. El modo en segundo plano lo cubren
  tests/test_trabajos.py (hilos reales) y las pruebas de navegador (servidor real, sin esta variable).
- La comprobación automática de servicios externos queda desactivada (no hay red en las pruebas).
- Alcance: la app se despliega en Modo Colombia (VISOR_REGION_MODE=CO por defecto, también en
  verificar.sh). Las pruebas heredadas verifican las funciones GLOBALES, que se conservan para una
  ampliación futura, así que corren con GLOBAL; el Modo Colombia se prueba explícitamente en
  tests/test_modo_colombia.py (CO-01…CO-12), incluido el flujo completo de Chigorodó, y en
  tests/e2e/test_modo_colombia_e2e.py con un servidor en modo CO.
"""
import os
import tempfile

os.environ.setdefault("VISOR_TRABAJOS_DIR", tempfile.mkdtemp(prefix="visor_trabajos_"))
os.environ.setdefault("VISOR_TRABAJOS_SINCRONOS", "1")
os.environ.setdefault("VISOR_DIAGNOSTICO", "desactivado")
os.environ.setdefault("VISOR_REGION_MODE", "GLOBAL")
os.environ.setdefault("VISOR_SENSOR_DEFECTO", "SENTINEL")
os.environ.setdefault("VISOR_FENOMENOS_LEGACY", "1")
