"""Imprime las capturas de una carpeta en el registro del trabajo de CI (JPEG reducido, base64).

Sirve para recuperar la evidencia desde entornos que pueden leer los registros de GitHub Actions
pero no descargar artefactos. Una línea por imagen: «CAPTURA <nombre> <base64>».
"""
import base64
import io
import sys
from pathlib import Path

from PIL import Image

carpeta = Path(sys.argv[1] if len(sys.argv) > 1 else "informes/capturas_reales")
for ruta in sorted(carpeta.glob("*.png")):
    imagen = Image.open(ruta).convert("RGB")
    imagen.thumbnail((1280, 1280))
    buf = io.BytesIO()
    imagen.save(buf, "JPEG", quality=72)
    print(f"CAPTURA {ruta.stem} {base64.b64encode(buf.getvalue()).decode()}")
