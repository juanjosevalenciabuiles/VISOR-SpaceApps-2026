"""Exportación de un resultado SAR para QGIS Desktop (interoperabilidad opcional).

QGIS no es una dependencia de la app: este módulo solo arma un paquete ZIP
que QGIS abre directamente, con rutas relativas y nombres válidos en Windows:

    <nombre>.tif             el GeoTIFF ORIGINAL, byte a byte (mismo SHA-256)
    <nombre>.qml             estilo categórico; QGIS lo aplica solo al abrir el .tif
    <nombre>.json            ficha de procedencia original, si existe
    <nombre>_aoi.geojson     AOI declarada en la ficha (solo si existe y es válida)
    <nombre>_leyenda.csv     valor, etiqueta, color y transparencia de cada clase
    LEEME_QGIS.txt           cómo abrirlo y qué NO hacer (remuestrear con bilineal…)
    manifiesto.json          huella SHA-256 de cada archivo del paquete y procedencia

Nunca reescribe ni reproyecta el GeoTIFF: los valores de clase y la huella
se conservan. No inventa geometrías: sin AOI declarada no hay GeoJSON.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import quoteattr

from utils import procedencia

MAX_BYTES_EXPORTACION = 200 * 1024 * 1024
VERSION_QGIS_MINIMA = "3.28"
NODATA = 255


class ErrorExportacion(Exception):
    """Mensaje legible para la interfaz."""


def nombre_seguro(texto: str) -> str:
    """Nombre válido en Windows, Linux y macOS (sin tildes ni caracteres reservados)."""
    limpio = re.sub(r"[^A-Za-z0-9._-]+", "_", texto).strip("._")
    return (limpio or "resultado")[:80]


def estilo_qml(clases, nodata: int | None = NODATA) -> str:
    """Estilo «Paleta / valores únicos». Las clases sin color quedan con alfa 0."""
    entradas = []
    for valor, etiqueta, color in clases:
        alfa = 255 if color else 0
        entradas.append(f'        <paletteEntry value="{int(valor)}" color="{(color or "#000000").lower()}" '
                        f'alpha="{alfa}" label={quoteattr(f"{valor} · {etiqueta}")}/>')
    if nodata is not None:
        entradas.append(f'        <paletteEntry value="{int(nodata)}" color="#000000" alpha="0" '
                        f'label={quoteattr(f"{nodata} · Sin dato (NoData)")}/>')
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        f'<qgis version="{VERSION_QGIS_MINIMA}" styleCategories="Symbology">\n'
        "  <pipe>\n"
        '    <rasterrenderer type="paletted" band="1" opacity="1" alphaBand="-1" nodataColor="">\n'
        "      <rasterTransparency/>\n"
        "      <colorPalette>\n" + "\n".join(entradas) + "\n"
        "      </colorPalette>\n"
        "    </rasterrenderer>\n"
        '    <resampler zoomedInResampler="" zoomedOutResampler="" maxOversampling="2"/>\n'
        "  </pipe>\n"
        "</qgis>\n"
    )


def leyenda_csv(clases, nodata: int | None = NODATA) -> str:
    salida = io.StringIO()
    w = csv.writer(salida, lineterminator="\r\n")          # CRLF: Excel en Windows lo abre bien
    w.writerow(["valor", "etiqueta", "color", "transparente"])
    for valor, etiqueta, color in clases:
        w.writerow([valor, etiqueta, color or "", "si" if not color else "no"])
    if nodata is not None:
        w.writerow([nodata, "Sin dato (NoData)", "", "si"])
    return salida.getvalue()


def aoi_geojson(ficha: dict | None) -> str | None:
    """GeoJSON de la AOI DECLARADA en la ficha ([oeste, sur, este, norte] en grados), o None."""
    aoi = (ficha or {}).get("aoi_lonlat")
    if not (isinstance(aoi, (list, tuple)) and len(aoi) == 4):
        return None
    try:
        o, s, e, n = (float(v) for v in aoi)
    except (TypeError, ValueError):
        return None
    if not (-180 <= o < e <= 180 and -90 <= s < n <= 90):
        return None
    anillo = [[o, s], [e, s], [e, n], [o, n], [o, s]]
    return json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"nombre": "AOI declarada en la ficha", "origen": "ficha.aoi_lonlat"},
                      "geometry": {"type": "Polygon", "coordinates": [anillo]}}],
    }, ensure_ascii=False, indent=2)


def _leeme(nombre: str, estado: procedencia.Procedencia, con_aoi: bool, con_ficha: bool) -> str:
    return "\r\n".join([
        "V.I.S.O.R. · Paquete para QGIS Desktop",
        "",
        f"Capa: {nombre}.tif   Procedencia: {estado.etiqueta}",
        f"  {estado.motivo}",
        "",
        "Abrir:",
        f"  1. Descomprimir la carpeta completa y arrastrar {nombre}.tif a QGIS ({VERSION_QGIS_MINIMA} o posterior).",
        f"     QGIS aplica {nombre}.qml automaticamente (si no: Propiedades > Simbologia > Estilo > Cargar estilo).",
        "  2. Propiedades > Informacion: comprobar CRS, tamano, resolucion y NoData.",
        "  3. Clases 0 y NoData (255) son transparentes. No representan zonas sin cambio garantizado ni zonas inundadas.",
        *([f"  4. {nombre}_aoi.geojson es la AOI declarada en la ficha."] if con_aoi else
          ["  4. Sin AOI: la ficha no declara una geometria valida, asi que no se genero ninguna."]),
        "",
        "No hacer:",
        "  - Reproyectar o remuestrear con bilineal o cubica: crea clases inexistentes. Usar vecino mas cercano.",
        "  - Guardar encima del .tif: cambia su SHA-256 y la ficha deja de corresponderle.",
        "",
        "Verificar integridad: comparar el SHA-256 del .tif con manifiesto.json"
        + (" y con la ficha .json." if con_ficha else "."),
        "",
        "Advertencia: indicios de cambio en la senal de radar. No confirman inundaciones ni otros fenomenos;",
        "requieren validacion independiente.",
        "",
    ])


def exportar(ruta_tif: str | Path, clases, nombre_producto: str, nodata: int | None = NODATA) -> tuple[str, bytes]:
    """Devuelve (nombre_zip, contenido). Lee el GeoTIFF y su ficha sin modificarlos."""
    ruta = Path(ruta_tif)
    if not ruta.is_file():
        raise ErrorExportacion(f"No se encontró `{ruta.name}`.")
    tamano = ruta.stat().st_size
    if tamano > MAX_BYTES_EXPORTACION:
        raise ErrorExportacion(f"`{ruta.name}` pesa {tamano / 1e6:.0f} MB; el límite de exportación es "
                               f"{MAX_BYTES_EXPORTACION / 1e6:.0f} MB. Recórtalo con un AOI.")
    bytes_tif = ruta.read_bytes()
    sha_tif = hashlib.sha256(bytes_tif).hexdigest()

    lateral = ruta.with_suffix(".json")
    bytes_ficha = lateral.read_bytes() if lateral.is_file() else None
    ficha = None
    if bytes_ficha is not None:
        try:
            ficha = json.loads(bytes_ficha.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            ficha = None
    import rasterio  # perezoso: este módulo se importa en la interfaz
    with rasterio.open(ruta) as src:
        es_demo = src.tags().get("VISOR_DEMO") == "1"
    estado = procedencia.evaluar(es_demo, ficha if isinstance(ficha, dict) else None, sha_tif)

    base = nombre_seguro(ruta.stem)
    archivos: dict[str, bytes] = {
        f"{base}.tif": bytes_tif,
        f"{base}.qml": estilo_qml(clases, nodata).encode("utf-8"),
        f"{base}_leyenda.csv": leyenda_csv(clases, nodata).encode("utf-8-sig"),
    }
    if bytes_ficha is not None:
        archivos[f"{base}.json"] = bytes_ficha
    geojson = aoi_geojson(ficha if isinstance(ficha, dict) else None)
    if geojson is not None:
        archivos[f"{base}_aoi.geojson"] = geojson.encode("utf-8")
    archivos["LEEME_QGIS.txt"] = _leeme(base, estado, geojson is not None, bytes_ficha is not None).encode("utf-8")
    manifiesto = {
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "producto": nombre_producto,
        "origen": f"data/analisis/{ruta.name}",
        "procedencia": {"estado": estado.estado, "etiqueta": estado.etiqueta, "motivo": estado.motivo},
        "geotiff_original_sha256": sha_tif,
        "archivos": {n: hashlib.sha256(b).hexdigest() for n, b in archivos.items()},
        "advertencia": "No confirma inundaciones ni otros fenómenos; requiere validación independiente.",
    }
    archivos["manifiesto.json"] = json.dumps(manifiesto, ensure_ascii=False, indent=2).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in archivos.items():
            z.writestr(f"{base}/{n}", b)
    return f"{base}_QGIS.zip", buffer.getvalue()
