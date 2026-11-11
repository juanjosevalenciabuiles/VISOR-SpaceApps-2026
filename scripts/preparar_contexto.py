"""Descarga y recorta las capas de contexto (hidrografía y vías) para Antioquia.

Fuente: Natural Earth 1:10m, versión fijada (dominio público).
https://www.naturalearthdata.com  ·  https://github.com/nvkelso/natural-earth-vector

Escribe GeoJSON ligeros en data/contexto/. Solo hace falta ejecutarlo si se
quieren regenerar los archivos; los resultados ya están en el repositorio.

Uso:  python scripts/preparar_contexto.py
"""
import sys
import tempfile
import urllib.request
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils.capas_contexto import CONTEXTO_DIR  # noqa: E402
from utils.config import ANTIOQUIA_BBOX  # noqa: E402

VERSION = "v5.1.2"
BASE = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{VERSION}/geojson"
CAPAS = {
    # salida: (archivo de Natural Earth, columnas que se conservan)
    "hidrografia.geojson": ("ne_10m_rivers_lake_centerlines.geojson", ["name", "featurecla", "scalerank"]),
    "vias.geojson": ("ne_10m_roads.geojson", ["name", "type", "scalerank"]),
}


def preparar(salida: str, origen: str, columnas: list[str], carpeta: Path) -> None:
    local = carpeta / origen
    print(f"  descargando {origen} …")
    urllib.request.urlretrieve(f"{BASE}/{origen}", local)  # noqa: S310 - URL fija y versionada
    gdf = gpd.read_file(local)
    recorte = gpd.clip(gdf[columnas + ["geometry"]], box(*ANTIOQUIA_BBOX))
    recorte = recorte[~recorte.geometry.is_empty].reset_index(drop=True)
    if recorte.empty:
        raise SystemExit(f"{origen}: no hay elementos dentro del área de referencia.")
    CONTEXTO_DIR.mkdir(parents=True, exist_ok=True)
    destino = CONTEXTO_DIR / salida
    destino.write_text(recorte.to_json(drop_id=True, to_wgs84=True), encoding="utf-8")
    print(f"  data/contexto/{salida}: {len(recorte)} elementos, {destino.stat().st_size / 1024:.0f} kB")


if __name__ == "__main__":
    print(f"Natural Earth {VERSION} → recorte al área de referencia {ANTIOQUIA_BBOX}")
    with tempfile.TemporaryDirectory() as tmp:
        for salida, (origen, columnas) in CAPAS.items():
            preparar(salida, origen, columnas, Path(tmp))
