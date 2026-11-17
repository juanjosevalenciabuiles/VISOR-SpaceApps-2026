#!/usr/bin/env bash
# Solo produccion Replit: iniciar con paquetes ya preparados en el build.
# No muta ni descarga COG, no reinstala Streamlit y no crea .venv.
set -euo pipefail
cd "$(dirname "$0")/.."

PUERTO="${VISOR_DEPLOY_PORT:-5000}"
[[ "$PUERTO" =~ ^[0-9]+$ ]] || {
    echo "[VISOR] ERROR: puerto invalido" >&2
    exit 1
}
# Utilizar un entorno virtual REAL, como start.sh en el Preview funcional.
# Nunca instalar, actualizar ni crear paquetes al iniciar Autoscale.
PYTHON="runtime_env/bin/python"
[[ -x "$PYTHON" ]] || {
    echo "[VISOR] ERROR: runtime_env no esta disponible. Ejecuta deploy/build.sh durante la construccion." >&2
    exit 1
}
AISLADO=(env -u PYTHONPATH -u PYTHONHOME -u PIP_TARGET PIP_USER=0 PYTHONNOUSERSITE=1)

comprobar() {
    "${AISLADO[@]}" "$PYTHON" -c 'import pyexpat, rasterio, streamlit, folium, geopandas, shapely, harmony, h5py' >/dev/null 2>&1
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
    "${AISLADO[@]}" "$PYTHON" -c 'import pyexpat, rasterio, streamlit, folium, geopandas, shapely, harmony, h5py' >&2
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
exec "${AISLADO[@]}" "$PYTHON" -m streamlit run app.py \
    --server.address 0.0.0.0 \
    --server.port "$PUERTO" \
    --server.headless true \
    "${ORIGENES[@]}"
