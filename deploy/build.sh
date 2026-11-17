#!/usr/bin/env bash
# V.I.S.O.R. NASA: dependencias listas en BUILD, nunca instalar al atender a usuarios.
# Mantiene start.sh y el procesamiento SAR intactos.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[VISOR build] Verificando la version funcional y sus dependencias..."
bash start.sh --verificar

# Un PYTHONPATH apuntando a paquetes copiados no es lo mismo que un venv:
# Python no procesa .pth ni aísla completamente el entorno. Crear un entorno
# de produccion real antes de desplegar, y copiar los paquetes YA verificados.
BASE=".venv/bin/python"
[[ -x "$BASE" ]] || { echo "[VISOR build] ERROR: no existe .venv/bin/python" >&2; exit 1; }
ORIGEN="$("$BASE" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"

PY_BASE="${VISOR_PYTHON:-}"
if [[ -z "$PY_BASE" ]]; then
    for c in python3.12 python3 python; do
        if command -v "$c" >/dev/null 2>&1; then PY_BASE="$c"; break; fi
    done
fi
[[ -n "$PY_BASE" ]] || { echo "[VISOR build] ERROR: Python 3.12 no disponible." >&2; exit 1; }

if [[ -d runtime_env ]]; then
    echo "[VISOR build] Reutilizando runtime_env existente."
else
    "$PY_BASE" -m venv runtime_env || {
        echo "[VISOR build] ERROR: no se pudo crear runtime_env" >&2
        exit 1
    }
fi
DESTINO="$(runtime_env/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
[[ -d "$ORIGEN/streamlit" && -d "$DESTINO" ]] || {
    echo "[VISOR build] ERROR: carpeta site-packages no disponible" >&2; exit 1
}
# Reemplazar SOLO dependencias del runtime; no tocar data/ ni resultados SAR.
find "$DESTINO" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
cp -a "$ORIGEN"/. "$DESTINO"/

bash deploy/run.sh --verificar
echo "[VISOR build] Entorno aislado preparado: $(du -sh runtime_env | cut -f1)"

# El chequeo de importaciones por sí solo no detecta errores de configuracion
# de Streamlit. Exigir que el mismo arranque de produccion abra una ruta HTTP.
SMOKE_PORT=5193
LOG="$(mktemp)"
VISOR_DEPLOY_PORT="$SMOKE_PORT" bash deploy/run.sh >"$LOG" 2>&1 &
PID=$!
limpiar() {
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
    rm -f "$LOG"
}
trap limpiar EXIT
OK=0
for intento in $(seq 1 50); do
    if ! kill -0 "$PID" 2>/dev/null; then break; fi
    if "$PY_BASE" - "$SMOKE_PORT" <<'PY'
import sys
import urllib.request
try:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{sys.argv[1]}/_stcore/health", timeout=1
    ) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
    then
        OK=1
        break
    fi
    sleep 0.5
done
if [[ "$OK" != 1 ]]; then
    echo "[VISOR build] ERROR: el arranque HTTP de produccion fallo ANTES de publicar." >&2
    echo "[VISOR build] Ultimas lineas del error real:" >&2
    tail -n 100 "$LOG" >&2
    exit 1
fi
echo "[VISOR build] OK: Streamlit abre HTTP /_stcore/health antes de publicar."
echo "[VISOR build] No se hicieron solicitudes a Harmony ni cambios en GeoTIFF."
