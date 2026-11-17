#!/usr/bin/env bash
# Solo produccion Replit: iniciar con paquetes ya preparados en el build.
# No muta ni descarga COG, no reinstala Streamlit y no crea .venv.
set -euo pipefail
cd "$(dirname "$0")/.."

PUERTO=5000
PYTHON=""
for candidato in python3.12 python3 python; do
    if command -v "$candidato" >/dev/null 2>&1; then
        PYTHON="$candidato"
        break
    fi
done
[[ -n "$PYTHON" ]] || { echo "[VISOR] ERROR: Python del sistema no disponible." >&2; exit 1; }
[[ -f runtime_packages/streamlit/__init__.py ]] || {
    echo "[VISOR] ERROR: runtime_packages no existe en el deployment. Verifica deploy/build.sh y el empaquetado." >&2
    exit 1
}
export PYTHONPATH="$PWD/runtime_packages"
export PYTHONNOUSERSITE=1
export PIP_USER=0

comprobar() {
    "$PYTHON" -c 'import pyexpat, rasterio, streamlit, folium, geopandas, shapely, harmony, h5py' >/dev/null 2>&1
}

# Algunas imagenes Nix exponen libexpat.so en otra ruta. Reutilizar la misma
# busqueda que start.sh, pero sin mutar Python ni descargar ninguna biblioteca.
if ! comprobar; then
    candidatas=()
    IFS=':' read -ra declaradas <<< "${REPLIT_LD_LIBRARY_PATH:-}"
    for carpeta in "${declaradas[@]}"; do candidatas+=("$carpeta"); done
    for carpeta in /nix/store/*-expat-*/lib; do candidatas+=("$carpeta"); done
    for carpeta in "${candidatas[@]}"; do
        [[ -e "$carpeta/libexpat.so.1" ]] || continue
        if LD_LIBRARY_PATH="$carpeta:${LD_LIBRARY_PATH:-}" comprobar; then
            export LD_LIBRARY_PATH="$carpeta:${LD_LIBRARY_PATH:-}"
            echo "[VISOR] Expat compatible: $carpeta"
            break
        fi
    done
fi

if ! comprobar; then
    echo "[VISOR] ERROR: bibliotecas cientificas incompletas; no se intentara pip en runtime." >&2
    "$PYTHON" -c 'import pyexpat, rasterio, streamlit, folium, geopandas, shapely, harmony, h5py' >&2
    exit 1
fi

if [[ "${1:-}" == "--verificar" ]]; then
    echo "[VISOR] Verificacion offline correcta: librerias cientificas disponibles."
    exit 0
fi
if [[ -n "${1:-}" ]]; then
    echo "[VISOR] ERROR: argumento no reconocido: $1" >&2
    exit 2
fi

ORIGENES=()
IFS=',' read -ra dominios <<< "${REPLIT_DEV_DOMAIN:-},${REPLIT_DOMAINS:-}"
for dominio in "${dominios[@]}"; do
    dominio="${dominio// /}"
    if [[ "$dominio" =~ ^[A-Za-z0-9.-]+$ ]]; then
        ORIGENES+=(--server.corsAllowedOrigins "https://$dominio")
    fi
done

if [[ -n "${CARTO_API_KEY:-}" ]]; then
    echo "[VISOR] CARTO_API_KEY disponible"
else
    echo "[VISOR] CARTO_API_KEY no definida (fondo CARTO puede mostrar marca de agua)"
fi

echo "[VISOR] Iniciando Streamlit con dependencias precompiladas, puerto $PUERTO"
exec "$PYTHON" -m streamlit run app.py \
    --server.address 0.0.0.0 \
    --server.port "$PUERTO" \
    --server.headless true \
    "${ORIGENES[@]}"
