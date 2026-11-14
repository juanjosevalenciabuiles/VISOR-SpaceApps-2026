"""Prepara las capas de contexto MUNDIALES (ríos, lagos y carreteras) de data/contexto/mundo/.

Fuente: Natural Earth 1:10m, dominio público (https://www.naturalearthdata.com,
https://github.com/nvkelso/natural-earth-vector). Los archivos ya están en el repositorio;
solo hace falta ejecutar esto para regenerarlos o actualizarlos.

Uso (con una copia local de natural-earth-vector; basta con la carpeta geojson/):

    git clone --depth 1 --filter=blob:none --sparse https://github.com/nvkelso/natural-earth-vector.git ne
    cd ne && git sparse-checkout set --no-cone /geojson/ne_10m_rivers_lake_centerlines.geojson \\
        /geojson/ne_10m_lakes.geojson /geojson/ne_10m_roads.geojson /VERSION && cd ..
    python scripts/preparar_contexto.py ne

Simplifica las geometrías (≈300–450 m, suficiente para la escala general de Natural Earth), conserva solo
nombre/tipo/importancia, redondea a 4 decimales (~11 m) y comprime con gzip. Imprime el SHA-256 de cada
archivo para registrarlo.
"""
import gzip
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

import geopandas as gpd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils.capas_contexto import CONTEXTO_DIR  # noqa: E402

CAPAS = {
    # salida: (archivo de Natural Earth, columnas que se conservan, tolerancia de simplificación en grados)
    "rios.geojson.gz": ("ne_10m_rivers_lake_centerlines.geojson", ["name", "featurecla", "scalerank"], 0.003),
    "lagos.geojson.gz": ("ne_10m_lakes.geojson", ["name", "featurecla", "scalerank"], 0.003),
    "carreteras.geojson.gz": ("ne_10m_roads.geojson", ["type", "scalerank"], 0.004),
}


def preparar(origen: Path, destino: Path = CONTEXTO_DIR / "mundo") -> None:
    destino.mkdir(parents=True, exist_ok=True)
    version = (origen / "VERSION").read_text().strip() if (origen / "VERSION").exists() else "desconocida"
    print(f"Natural Earth versión {version}")
    for salida, (archivo, columnas, tolerancia) in CAPAS.items():
        gdf = gpd.read_file(origen / "geojson" / archivo)
        gdf = gdf[[c for c in columnas if c in gdf.columns] + ["geometry"]]
        poligonos = gdf.geom_type.str.contains("Polygon").any()
        gdf["geometry"] = gdf.geometry.simplify(tolerancia, preserve_topology=bool(poligonos))
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
        with tempfile.TemporaryDirectory() as tmp:
            plano = Path(tmp) / "capa.geojson"
            gdf.to_file(plano, driver="GeoJSON", COORDINATE_PRECISION=4)
            with open(plano, "rb") as a, gzip.open(destino / salida, "wb", compresslevel=9) as b:
                shutil.copyfileobj(a, b)
        huella = hashlib.sha256((destino / salida).read_bytes()).hexdigest()
        print(f"{salida}: {len(gdf)} elementos · {(destino / salida).stat().st_size / 1e6:.2f} MB · {huella}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    preparar(Path(sys.argv[1]))
