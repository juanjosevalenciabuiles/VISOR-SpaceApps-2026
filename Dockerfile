# V.I.S.O.R. — despliegue portable (Render, Railway, Docker local).
# Python 3.12, separado de la configuración Nix/Replit de start.sh.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8501

WORKDIR /app

# Bibliotecas compartidas para GDAL/Rasterio y lectura geoespacial.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libexpat1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .
RUN groupadd --gid 10001 visor && useradd --uid 10001 --gid 10001 --create-home visor \
    && mkdir -p /app/data/analisis /app/data/sar /app/data/nisar /app/data/trabajos /app/storage \
    && chown -R visor:visor /app

USER visor
EXPOSE 8501
# Streamlit publica este endpoint sin registrar secretos ni iniciar un análisis.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8501')+'/_stcore/health',timeout=3).read()" || exit 1

CMD ["python", "scripts/arranque_portable.py"]
