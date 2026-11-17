#!/usr/bin/env bash
# Preparacion de la imagen de produccion, nunca se ejecuta al servir visitantes.
# Mantiene el entorno de desarrollo y el codigo cientifico intactos.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[VISOR build] Preparando las dependencias de Python en build..."
bash start.sh --verificar

# Replit puede omitir el .venv del runtime, por ser un directorio oculto/ignorado.
# Publicar exclusivamente los modulos instalados en un directorio visible y portable
# evita crear .venv y descargar paquetes al inicio de cada instancia Autoscale.
PY_VENV=".venv/bin/python"
[[ -x "$PY_VENV" ]] || { echo "[VISOR build] ERROR: falta .venv/bin/python" >&2; exit 1; }
SITE_PACKAGES="$("$PY_VENV" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
[[ -d "$SITE_PACKAGES/streamlit" ]] || {
    echo "[VISOR build] ERROR: Streamlit no se instalo en $SITE_PACKAGES" >&2
    exit 1
}

mkdir -p runtime_packages
# Copiar solo si es necesario: elimina versiones antiguas del paquete,
# nunca los datos NISAR ni los GeoTIFF originales.
find runtime_packages -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
cp -a "$SITE_PACKAGES"/. runtime_packages/

[[ -f runtime_packages/streamlit/__init__.py ]] || {
    echo "[VISOR build] ERROR: faltan bibliotecas empaquetadas." >&2
    exit 1
}
echo "[VISOR build] Bibliotecas disponibles: $(du -sh runtime_packages | cut -f1)"
echo "[VISOR build] Listo. El runtime no necesita instalar paquetes."
