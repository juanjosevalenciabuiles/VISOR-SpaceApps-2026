"""Construye el límite nacional de Colombia que usa el Modo Colombia (utils/alcance_geografico.py).

Fuente: Marco Geoestadístico Nacional 2025 del DANE, en la simplificación publicada por
https://github.com/ytolosa/mapas-colombia (datos CC BY 4.0). Se usa la variante `real`
(San Andrés y Providencia en su posición real, sin recuadro) al nivel `municipal`, que la
propia fuente indica para cálculos y cruces con otras capas.

Salidas en data/contexto/colombia/:
- colombia_mgn2025_municipal.geojson.gz  unión de los 33 departamentos: VALIDACIÓN de zonas.
- colombia_dibujo.geojson.gz             la misma unión simplificada (~300 m, coordenadas a 4 decimales):
                                         SOLO dibujo (contorno y velo). Conserva los 69 polígonos (todas las
                                         islas); el nivel `nacional` de la fuente pierde los cayos pequeños.
- FUENTE.json                            versión, commit, licencia, atribución y SHA-256.

Uso:
    git clone --depth 1 https://github.com/ytolosa/mapas-colombia /tmp/mapas-colombia
    python scripts/preparar_limite_colombia.py /tmp/mapas-colombia

No modifica la geometría más allá de unir los departamentos (unary_union) y corregir validez
(buffer(0)); no añade islas de otras fuentes ni infiere límites marítimos.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "contexto" / "colombia"
VALIDACION = "colombia_mgn2025_municipal.geojson.gz"
DIBUJO = "colombia_dibujo.geojson.gz"
TOLERANCIA_DIBUJO = 0.003   # grados (~300 m): invisible a escala nacional, aligera la página


def redondear(geometria, decimales: int = 4):
    from shapely import set_precision
    return set_precision(geometria, 10 ** -decimales)


def unir(ruta: Path):
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return unary_union([shape(f["geometry"]) for f in datos["features"]]).buffer(0), len(datos["features"])


def escribir(geometria, destino: Path, nivel: str) -> str:
    coleccion = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"nombre": "Colombia", "fuente": "MGN 2025 DANE", "nivel": nivel},
        "geometry": mapping(geometria)}]}
    texto = json.dumps(coleccion, separators=(",", ":")).encode("utf-8")
    destino.write_bytes(gzip.compress(texto, compresslevel=9, mtime=0))
    return hashlib.sha256(destino.read_bytes()).hexdigest()


def main(origen: Path) -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "-C", str(origen), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    ficha = {
        "nombre": "Límite nacional de Colombia (territorio continental e insular)",
        "fuente": "Marco Geoestadístico Nacional 2025, DANE (www.dane.gov.co)",
        "derivado": "https://github.com/ytolosa/mapas-colombia",
        "commit_derivado": commit,
        "licencia": "CC BY 4.0 (datos derivados); cita obligatoria al DANE",
        "atribucion": "Límite: Marco Geoestadístico Nacional 2025, DANE (www.dane.gov.co). "
                      "Simplificación: github.com/ytolosa/mapas-colombia, CC BY 4.0.",
        "crs": "EPSG:4326",
        "variante": "real (San Andrés y Providencia en su posición real)",
        "procesado": "unión de departamentos (shapely.unary_union) + buffer(0); sin añadir ni mover geometrías",
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "advertencias": [
            "Límite de una fuente estadística (DANE), no una definición jurídica de fronteras.",
            "Solo territorio terrestre e insular representado en la fuente: no incluye mar territorial, "
            "zona económica exclusiva ni límites marítimos.",
            "La simplificación usada no contiene la isla Gorgona ni la isla de Malpelo; zonas allí se rechazan "
            "hasta incorporar una geometría oficial que las incluya.",
        ],
        "archivos": {},
    }
    geometria, departamentos = unir(origen / "output" / "geojson" / "col_departamentos_real_municipal.geojson")
    dibujo = redondear(geometria.simplify(TOLERANCIA_DIBUJO, preserve_topology=True))
    for nombre, geo, uso in ((VALIDACION, geometria, "validación de zonas (nivel municipal de la fuente)"),
                             (DIBUJO, dibujo, f"solo dibujo (simplificada {TOLERANCIA_DIBUJO}°, 4 decimales)")):
        partes = list(getattr(geo, "geoms", [geo]))
        ficha["archivos"][nombre] = {
            "uso": uso, "departamentos": departamentos, "poligonos": len(partes),
            "vertices": sum(len(p.exterior.coords) + sum(len(i.coords) for i in p.interiors) for p in partes),
            "limites": [round(v, 6) for v in geo.bounds],
            "sha256": escribir(geo, DESTINO / nombre, uso.split(" ")[0])}
    (DESTINO / "FUENTE.json").write_text(json.dumps(ficha, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(ficha["archivos"], indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/mapas-colombia"))
