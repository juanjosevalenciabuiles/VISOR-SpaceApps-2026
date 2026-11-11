#!/usr/bin/env bash
# Arranque único de V.I.S.O.R.: lo usan el botón Run, el despliegue de Replit
# y cualquier ejecución local.
#
#   bash start.sh              verifica bibliotecas e inicia Streamlit
#   bash start.sh --verificar  solo verifica bibliotecas y termina
#
# Problema que resuelve: en Replit (Nix) Rasterio necesita libexpat.so.1 y el
# cargador dinámico no siempre la encuentra. En lugar de fijar una ruta de
# /nix/store (cambia al reconstruir el entorno), se buscan las Expat instaladas
# y se usa la primera con la que `pyexpat` y `rasterio` importan de verdad.
set -euo pipefail
cd "$(dirname "$0")"

PUERTO=5000
PY="${VISOR_PYTHON:-python}"
ALMACEN_NIX="${VISOR_NIX_STORE:-/nix/store}"
# Ruta comprobada el 11-nov-2026. Solo es el último recurso si la búsqueda falla.
EXPAT_RESPALDO="/nix/store/b56ind0m3byv7pzby5mwsn5qsy1g6lqf-expat-2.8.5/lib"

importa_bien() { "$PY" -c "import pyexpat, rasterio" >/dev/null 2>&1; }

# Carpetas que contienen libexpat.so.1, de la más a la menos preferida.
candidatas_expat() {
    local carpeta
    # 1) Lo que Replit declara para los paquetes Nix del proyecto.
    IFS=':' read -ra declaradas <<< "${REPLIT_LD_LIBRARY_PATH:-}"
    for carpeta in "${declaradas[@]}"; do
        if [ -n "$carpeta" ] && [ -e "$carpeta/libexpat.so.1" ]; then echo "$carpeta"; fi
    done
    # 2) Cualquier Expat del almacén Nix, de la versión más nueva a la más antigua.
    for carpeta in "$ALMACEN_NIX"/*-expat-*/lib; do
        if [ -e "$carpeta/libexpat.so.1" ]; then echo "$carpeta"; fi
    done | sed -E 's#(.*-expat-([0-9][0-9.]*)[^/]*/lib)$#\2 \1#' | sort -k1,1 -V -r | cut -d' ' -f2-
    # 3) Ruta fija anterior.
    echo "$EXPAT_RESPALDO"
}

preparar_bibliotecas() {
    if importa_bien; then return 0; fi
    local carpeta
    while IFS= read -r carpeta; do
        [ -e "$carpeta/libexpat.so.1" ] || continue
        if LD_LIBRARY_PATH="$carpeta:${LD_LIBRARY_PATH:-}" importa_bien; then
            export LD_LIBRARY_PATH="$carpeta:${LD_LIBRARY_PATH:-}"
            echo "Expat: usando $carpeta"
            return 0
        fi
    done < <(candidatas_expat)
    echo "ERROR: no se pudo importar pyexpat + rasterio con ninguna Expat disponible." >&2
    echo "  - ¿Están instaladas las dependencias?  pip install -r requirements.txt" >&2
    echo "  - En Replit: confirma que 'expat' esté en [nix] packages de .replit y recarga el entorno." >&2
    echo "  - Detalle del error:" >&2
    "$PY" -c "import pyexpat, rasterio" 2>&1 | tail -n 2 >&2 || true
    return 1
}

puerto_ocupado() {
    "$PY" - "$PUERTO" <<'PYEOF'
import socket, sys
with socket.socket() as s:
    s.settimeout(0.5)
    sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PYEOF
}

# Evita dos Streamlit a la vez: si el puerto está tomado por una instancia
# anterior de esta app, se cierra; si lo tiene otro programa, se detiene aquí.
liberar_puerto() {
    puerto_ocupado || return 0
    if pgrep -f "streamlit run app.py" >/dev/null 2>&1; then
        echo "Cerrando una instancia anterior de V.I.S.O.R. en el puerto $PUERTO…"
        pkill -f "streamlit run app.py" || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            puerto_ocupado || return 0
            sleep 0.5
        done
    fi
    echo "ERROR: el puerto $PUERTO está ocupado por otro proceso. Deténlo y vuelve a intentar." >&2
    return 1
}

# CORS y XSRF de Streamlit quedan activados. Si Replit publica la app bajo su
# propio dominio, se autoriza SOLO ese dominio en lugar de desactivar la protección.
ORIGENES=()
autorizar_dominios_replit() {
    local dominio
    IFS=',' read -ra dominios <<< "${REPLIT_DEV_DOMAIN:-},${REPLIT_DOMAINS:-}"
    for dominio in "${dominios[@]}"; do
        dominio="${dominio// /}"
        if [[ "$dominio" =~ ^[A-Za-z0-9.-]+$ ]]; then
            ORIGENES+=(--server.corsAllowedOrigins "https://$dominio")
        fi
    done
}

echo "Verificando bibliotecas…"
preparar_bibliotecas
"$PY" -c "import pyexpat, rasterio; print('Expat:', pyexpat.EXPAT_VERSION, '| Rasterio:', rasterio.__version__)"

if [ "${1:-}" = "--verificar" ]; then
    echo "Verificación correcta."
    exit 0
fi

liberar_puerto
autorizar_dominios_replit

# La clave de CARTO se lee del entorno dentro de la app; aquí solo se informa
# si existe, sin mostrarla.
if [ -n "${CARTO_API_KEY:-}" ]; then echo "CARTO_API_KEY: disponible"; else echo "CARTO_API_KEY: no definida (los mapas CARTO saldrán con marca de agua)"; fi

echo "Iniciando V.I.S.O.R. en el puerto $PUERTO…"
exec "$PY" -m streamlit run app.py \
    --server.address 0.0.0.0 \
    --server.port "$PUERTO" \
    --server.headless true \
    ${ORIGENES[@]+"${ORIGENES[@]}"}
