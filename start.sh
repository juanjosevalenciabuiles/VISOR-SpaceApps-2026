#!/usr/bin/env bash
set -e

# Biblioteca Expat compatible comprobada
EXPAT_DIR="/nix/store/b56ind0m3byv7pzby5mwsn5qsy1g6lqf-expat-2.8.5/lib"

if [ ! -f "$EXPAT_DIR/libexpat.so.1" ]; then
    echo "ERROR: No se encuentra Expat 2.8.5"
    exit 1
fi

export LD_LIBRARY_PATH="$EXPAT_DIR:${LD_LIBRARY_PATH:-}"

echo "Verificando bibliotecas..."
python -c "import pyexpat, rasterio; print('Expat:', pyexpat.EXPAT_VERSION, '| Rasterio:', rasterio.__version__)"

echo "Iniciando V.I.S.O.R..."
exec python -m streamlit run app.py \
    --server.address 0.0.0.0 \
    --server.port 5000 \
    --server.headless true