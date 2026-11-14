#!/usr/bin/env bash
# Verificación integral de V.I.S.O.R. (solo lectura sobre data/). Uso:
#   bash verificar.sh                 todo lo posible en este entorno
#   bash verificar.sh --navegador     exige las pruebas de navegador (requirements-dev.txt)
#   bash verificar.sh --red           añade una consulta REAL a ASF
#   bash verificar.sh --sin-pytest    solo entorno, Git, app y datos (más rápido)
# Deja el informe en informes/ y termina con código 1 si el veredicto es NO APTO.
set -u
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
exec "$PY" scripts/verificar_visor.py "$@"
