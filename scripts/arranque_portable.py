"""Arranque portable para Docker, sin Nix ni dependencias de Replit.

Con VISOR_DATA_DIR en un volumen, copia únicamente los recursos públicos
empaquetados si faltan, sin sobrescribir productos SAR reales ni fichas.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def puerto_valido(cadena: str) -> int:
    """Puerto TCP entre 1 y 65535. Nunca ejecutar shell con entrada externa."""
    try:
        puerto = int(cadena)
    except (ValueError, TypeError) as exc:
        raise ValueError("PORT debe ser un número entero") from exc
    if not 1 <= puerto <= 65535:
        raise ValueError("PORT debe estar entre 1 y 65535")
    return puerto


def preparar_datos(origen: Path, destino: Path) -> int:
    """Sembrar recursos ligeros sin sobrescribir los del volumen.

    Se usa para data/contexto, data/ia_lab y capas DEMO que están en Git.
    Nunca descarga imágenes ni genera resultados SAR.
    """
    origen = origen.resolve()
    destino = destino.resolve()
    if origen == destino:
        return 0
    if origen in destino.parents or destino in origen.parents:
        raise ValueError("VISOR_DATA_DIR debe ser una carpeta externa a data/")
    destino.mkdir(parents=True, exist_ok=True)
    copiados = 0
    for archivo in origen.rglob("*"):
        if not archivo.is_file() or archivo.is_symlink():
            continue
        relativa = archivo.relative_to(origen)
        salida = destino / relativa
        salida.parent.mkdir(parents=True, exist_ok=True)
        # La versión del usuario manda: no reemplazar GeoTIFF/JSON ya presentes.
        if salida.exists() or salida.is_symlink():
            continue
        shutil.copy2(archivo, salida)
        copiados += 1
    for nombre in ("analisis", "sar", "nisar", "trabajos", "crudos"):
        (destino / nombre).mkdir(parents=True, exist_ok=True)
    return copiados


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    os.chdir(raiz)
    datos_repo = raiz / "data"
    if os.environ.get("VISOR_DATA_DIR"):
        destino = Path(os.environ["VISOR_DATA_DIR"]).expanduser()
        try:
            cuantos = preparar_datos(datos_repo, destino)
        except (OSError, ValueError) as exc:
            sys.exit(f"Error al preparar volumen de datos: {exc}")
        print(f"V.I.S.O.R.: {cuantos} recursos públicos sembrados, sin sobrescribir archivos.")
    else:
        # Sin disco externo, los trabajos en /app/data son efímeros.
        for nombre in ("analisis", "sar", "nisar", "trabajos", "crudos"):
            (datos_repo / nombre).mkdir(parents=True, exist_ok=True)
    try:
        puerto = puerto_valido(os.environ.get("PORT", "8501"))
    except ValueError as exc:
        sys.exit(str(exc))

    # Un único proceso Streamlit para un estado de trabajos coherente.
    os.execv(
        sys.executable,
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.address=0.0.0.0",
            f"--server.port={puerto}",
            "--server.headless=true",
        ],
    )


if __name__ == "__main__":
    main()
