#!/usr/bin/env bash
# Arranque único de V.I.S.O.R.: lo usan el botón Run, el despliegue de Replit
# y cualquier ejecución local. Prepara todo solo; no hay que instalar nada a mano.
#
#   bash start.sh              prepara el entorno e inicia la app (puerto 5000)
#   bash start.sh --verificar  prepara y comprueba el entorno, sin iniciar la app
#   bash start.sh --pruebas    prepara el entorno y ejecuta pytest
#
# Qué hace, en orden:
#   1. Elige el Python del sistema y comprueba que pyexpat funciona.
#   2. Crea o reutiliza el entorno virtual .venv (nunca instala en el Python de Nix).
#   3. Instala dependencias solo si .venv es nuevo o cambió requirements.txt.
#   4. Busca una Expat con la que pyexpat + rasterio importan de verdad.
#   5. Inicia Streamlit.
set -euo pipefail
cd "$(dirname "$0")"

PUERTO=5000
VENV="${VISOR_VENV:-.venv}"
ALMACEN_NIX="${VISOR_NIX_STORE:-/nix/store}"
ARCHIVO_PID="$VENV/.visor.pid"
# Ruta comprobada el 11-nov-2026. Solo es el último recurso si la búsqueda falla.
# Se construye desde ALMACEN_NIX (en Replit, /nix/store: la misma carpeta de siempre)
# para que una simulación con otro almacén no vea la Expat real del sistema.
EXPAT_RESPALDO="$ALMACEN_NIX/b56ind0m3byv7pzby5mwsn5qsy1g6lqf-expat-2.8.5/lib"

fallo() { echo "ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------- Python base
PY_BASE="${VISOR_PYTHON:-}"
if [ -z "$PY_BASE" ]; then
    for candidato in python3.12 python3 python; do
        if command -v "$candidato" >/dev/null 2>&1; then PY_BASE="$candidato"; break; fi
    done
fi
[ -n "$PY_BASE" ] || fallo "no se encontró Python. En Replit, revisa que .replit tenga el módulo python-3.12."

VPY="$VENV/bin/python"
# El entorno virtual se ejecuta aislado de las variables de paquetes de Replit
# (PYTHONPATH, instalación en modo usuario), para que solo vea lo de .venv.
AISLADO=(env -u PYTHONPATH -u PYTHONHOME -u PIP_TARGET PIP_USER=0 PYTHONNOUSERSITE=1)
vpy() { "${AISLADO[@]}" "$VPY" "$@"; }

# -------------------------------------------------------------------- Expat
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

# asegurar_importa "<módulos>" <comando python…>
# Si los módulos no importan, prueba cada Expat candidata hasta que lo hagan.
asegurar_importa() {
    local modulos="$1"; shift
    if "$@" -c "import $modulos" >/dev/null 2>&1; then return 0; fi
    local carpeta
    while IFS= read -r carpeta; do
        [ -e "$carpeta/libexpat.so.1" ] || continue
        if LD_LIBRARY_PATH="$carpeta:${LD_LIBRARY_PATH:-}" "$@" -c "import $modulos" >/dev/null 2>&1; then
            export LD_LIBRARY_PATH="$carpeta:${LD_LIBRARY_PATH:-}"
            echo "  Expat: usando $carpeta"
            return 0
        fi
    done < <(candidatas_expat)
    return 1
}

# --------------------------------------------------------- Entorno virtual
huella_requisitos() {
    { sha256sum requirements.txt 2>/dev/null || cksum requirements.txt; } | cut -d' ' -f1
}

crear_venv() {
    echo "  Creando el entorno virtual $VENV…"
    rm -rf "$VENV"
    if ! "$PY_BASE" -m venv "$VENV" >/dev/null 2>&1; then
        rm -rf "$VENV"
        if ! { command -v uv >/dev/null 2>&1 && uv venv --quiet --python "$PY_BASE" "$VENV"; }; then
            fallo "no se pudo crear $VENV con '$PY_BASE -m venv' ni con uv."
        fi
    fi
}

INSTALADO_AHORA=0
instalar_dependencias() {
    echo "  Instalando dependencias en $VENV (puede tardar unos minutos)…"
    if vpy -m pip --version >/dev/null 2>&1; then
        vpy -m pip install --quiet --disable-pip-version-check -r requirements.txt \
            || fallo "falló la instalación de dependencias (revisa requirements.txt y la conexión)."
    elif command -v uv >/dev/null 2>&1; then
        uv pip install --quiet --python "$VPY" -r requirements.txt \
            || fallo "falló la instalación de dependencias (revisa requirements.txt y la conexión)."
    else
        fallo "el entorno $VENV no tiene pip y no hay uv disponible."
    fi
    huella_requisitos > "$VENV/.requisitos"   # solo se anota si la instalación terminó bien
    INSTALADO_AHORA=1
}

preparar_venv() {
    # Un .venv roto (por ejemplo, tras reconstruirse el entorno Nix) se rehace.
    if [ ! -x "$VPY" ] || ! vpy -c "" >/dev/null 2>&1; then crear_venv; fi
    if [ "$(cat "$VENV/.requisitos" 2>/dev/null || true)" != "$(huella_requisitos)" ]; then
        instalar_dependencias
    else
        echo "  Dependencias al día (requirements.txt no cambió)."
    fi
}

preparar_entorno() {
    echo "Preparando el entorno…"
    asegurar_importa "pyexpat" "$PY_BASE" \
        || fallo "el Python del sistema ($PY_BASE) no puede importar pyexpat con ninguna Expat disponible."
    preparar_venv
    if ! asegurar_importa "pyexpat, rasterio, streamlit" vpy; then
        # Marca al día pero paquetes ausentes o dañados: se rehace .venv una sola vez.
        if [ "$INSTALADO_AHORA" = 0 ]; then
            echo "  El entorno parece incompleto; se rehace desde cero."
            crear_venv
            instalar_dependencias
        fi
        if ! asegurar_importa "pyexpat, rasterio, streamlit" vpy; then
            echo "ERROR: no se pudo importar pyexpat + rasterio + streamlit." >&2
            echo "  - En Replit: confirma que 'expat' esté en [nix] packages de .replit y recarga el entorno." >&2
            echo "  - Para empezar de cero: borra la carpeta $VENV y vuelve a ejecutar." >&2
            echo "  - Detalle:" >&2
            vpy -c "import pyexpat, rasterio, streamlit" 2>&1 | tail -n 2 >&2 || true
            exit 1
        fi
    fi
    vpy -c "import sys, pyexpat, rasterio, streamlit; print('  Python', sys.version.split()[0], '| Expat:', pyexpat.EXPAT_VERSION, '| Rasterio:', rasterio.__version__, '| Streamlit:', streamlit.__version__)"
}

# ------------------------------------------------------------------- Puerto
puerto_ocupado() {
    vpy - "$PUERTO" <<'PYEOF'
import socket, sys
with socket.socket() as s:
    s.settimeout(0.5)
    sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PYEOF
}

# Solo se cierra una instancia anterior de ESTA app (la que anotó su PID al
# arrancar desde esta misma carpeta). Nunca se toca un proceso ajeno.
liberar_puerto() {
    puerto_ocupado || return 0
    local pid
    pid="$(cat "$ARCHIVO_PID" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null \
        && [ "$(readlink "/proc/$pid/cwd" 2>/dev/null)" = "$PWD" ] \
        && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "streamlit run app.py"; then
        echo "Cerrando la instancia anterior de V.I.S.O.R. (PID $pid)…"
        kill "$pid" 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
            puerto_ocupado || return 0
            sleep 0.5
        done
    fi
    fallo "el puerto $PUERTO está ocupado por otro proceso. No se cerró nada: deténlo y vuelve a intentar."
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

# ---------------------------------------------------------------- Ejecución
MODO="${1:-}"
case "$MODO" in
    ""|--verificar|--pruebas) ;;
    *) fallo "opción desconocida: $MODO  (usa --verificar o --pruebas)";;
esac

preparar_entorno

if [ "$MODO" = "--verificar" ]; then
    echo "Verificación correcta."
    exit 0
fi
if [ "$MODO" = "--pruebas" ]; then
    exec "${AISLADO[@]}" "$VPY" -m pytest -q
fi

liberar_puerto
autorizar_dominios_replit

# La clave de CARTO se lee del entorno dentro de la app; aquí solo se informa
# si existe, sin mostrarla.
if [ -n "${CARTO_API_KEY:-}" ]; then echo "CARTO_API_KEY: disponible"; else echo "CARTO_API_KEY: no definida (los mapas CARTO saldrán con marca de agua)"; fi

echo "Iniciando V.I.S.O.R. en el puerto $PUERTO…"
echo "$$" > "$ARCHIVO_PID"   # exec conserva este PID: identifica a esta instancia
exec "${AISLADO[@]}" "$VPY" -m streamlit run app.py \
    --server.address 0.0.0.0 \
    --server.port "$PUERTO" \
    --server.headless true \
    ${ORIGENES[@]+"${ORIGENES[@]}"}
