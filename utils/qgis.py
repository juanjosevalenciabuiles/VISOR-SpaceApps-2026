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


_RESERVADOS_WINDOWS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                       *(f"LPT{i}" for i in range(1, 10))}


def nombre_seguro(texto: str) -> str:
    """Nombre válido en Windows, Linux y macOS (sin tildes, caracteres ni nombres
    reservados como CON o COM1, que Windows no permite ni con extensión)."""
    limpio = re.sub(r"[^A-Za-z0-9._-]+", "_", texto).strip("._")[:80].rstrip("._")
    if limpio.split(".")[0].upper() in _RESERVADOS_WINDOWS:
        limpio = f"resultado_{limpio}"
    return limpio or "resultado"


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


def estilo_qml_continuo() -> str:
    """Pseudocolor interpolado con la rampa y la opacidad del visor (±10 dB, saturación fuera del rango)."""
    from utils.diferencia_db import RAMPA, RANGO_DB, alfa
    items = "\n".join(
        f'          <item value="{x:g}" color="{c.lower()}" alpha="{round(float(alfa(x)) * 255)}" '
        f'label={quoteattr(f"{x:+g} dB")}/>' for x, c in RAMPA)
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        f'<qgis version="{VERSION_QGIS_MINIMA}" styleCategories="Symbology">\n'
        "  <pipe>\n"
        f'    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" '
        f'classificationMin="{-RANGO_DB:g}" classificationMax="{RANGO_DB:g}" nodataColor="">\n'
        "      <rasterTransparency/>\n"
        "      <rastershader>\n"
        f'        <colorrampshader colorRampType="INTERPOLATED" classificationMode="1" clip="0" '
        f'minimumValue="{-RANGO_DB:g}" maximumValue="{RANGO_DB:g}">\n'
        f"{items}\n"
        "        </colorrampshader>\n"
        "      </rastershader>\n"
        "    </rasterrenderer>\n"
        '    <resampler zoomedInResampler="" zoomedOutResampler="" maxOversampling="2"/>\n'
        "  </pipe>\n"
        "</qgis>\n"
    )


def leyenda_csv_continua() -> str:
    from utils.diferencia_db import RAMPA, alfa
    salida = io.StringIO()
    w = csv.writer(salida, lineterminator="\r\n")
    w.writerow(["delta_db", "color", "opacidad"])
    for x, c in RAMPA:
        w.writerow([f"{x:g}", c, f"{float(alfa(x)):.2f}"])
    w.writerow(["NoData", "", "0"])
    return salida.getvalue()


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


def _leeme(nombre: str, estado: procedencia.Procedencia, con_aoi: bool, con_ficha: bool,
           continuo: bool = False) -> str:
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
        ("  3. Diferencia continua en dB (posterior - anterior), sin umbral: pseudocolor fijo de -10 a +10 dB "
         "(azul disminucion, rojo aumento), NoData transparente." if continuo else
         "  3. Clases 0 y NoData (255) son transparentes. No representan zonas sin cambio garantizado ni zonas inundadas."),
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


def exportar(ruta_tif: str | Path, clases, nombre_producto: str, nodata: int | None = NODATA,
             continuo: bool = False) -> tuple[str, bytes]:
    """Devuelve (nombre_zip, contenido). Lee el GeoTIFF y su ficha sin modificarlos.
    `continuo=True`: diferencia en dB, con estilo de pseudocolor en vez de paleta."""
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
        f"{base}.qml": (estilo_qml_continuo() if continuo else estilo_qml(clases, nodata)).encode("utf-8"),
        f"{base}_leyenda.csv": (leyenda_csv_continua() if continuo else leyenda_csv(clases, nodata)).encode("utf-8-sig"),
    }
    if bytes_ficha is not None:
        archivos[f"{base}.json"] = bytes_ficha
    geojson = aoi_geojson(ficha if isinstance(ficha, dict) else None)
    if geojson is not None:
        archivos[f"{base}_aoi.geojson"] = geojson.encode("utf-8")
    archivos["LEEME_QGIS.txt"] = _leeme(base, estado, geojson is not None, bytes_ficha is not None,
                                        continuo).encode("utf-8")
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


def verificar_paquete(datos_zip: bytes, ruta_tif_original: str | Path, clases, nodata: int | None = NODATA,
                      continuo: bool = False) -> list[str]:
    """Comprueba un paquete exportado. Devuelve la lista de problemas (vacía = correcto).

    - estructura: una sola carpeta, nombres ASCII sin caracteres reservados de Windows;
    - el .tif es idéntico al original (SHA-256) y la ficha .json, si existe, también;
    - el manifiesto declara la huella correcta de cada archivo y del GeoTIFF original;
    - el .qml es un estilo de paleta con exactamente las clases, colores y transparencias del perfil;
    - el GeoJSON, si existe, es un polígono válido en grados.
    """
    import xml.etree.ElementTree as ET

    problemas: list[str] = []
    original = Path(ruta_tif_original)
    sha_original = hashlib.sha256(original.read_bytes()).hexdigest()
    try:
        with zipfile.ZipFile(io.BytesIO(datos_zip)) as z:
            contenido = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    except zipfile.BadZipFile:
        return ["El paquete no es un ZIP válido."]
    carpetas = {n.split("/", 1)[0] for n in contenido}
    if len(carpetas) != 1 or any(n.count("/") != 1 for n in contenido):
        problemas.append(f"Estructura inesperada: {sorted(contenido)}")
    for n in contenido:
        if any(ord(c) > 127 or c in '<>:"\\|?*' for c in n):
            problemas.append(f"Nombre no portable a Windows: {n}")
    planos = {n.split("/", 1)[-1]: b for n, b in contenido.items()}
    base = nombre_seguro(original.stem)

    tif = planos.get(f"{base}.tif")
    if tif is None:
        problemas.append("Falta el GeoTIFF.")
    elif hashlib.sha256(tif).hexdigest() != sha_original:
        problemas.append("El GeoTIFF del paquete no es idéntico al original (SHA-256 distinto).")
    lateral = original.with_suffix(".json")
    if lateral.is_file() and planos.get(f"{base}.json") != lateral.read_bytes():
        problemas.append("La ficha .json del paquete no es idéntica a la original.")
    if not lateral.is_file() and f"{base}.json" in planos:
        problemas.append("El paquete trae una ficha .json que no existe junto al original.")

    try:
        manifiesto = json.loads(planos["manifiesto.json"])
        if manifiesto.get("geotiff_original_sha256") != sha_original:
            problemas.append("El manifiesto declara otra huella para el GeoTIFF original.")
        declarados = manifiesto.get("archivos", {})
        for n, b in planos.items():
            if n == "manifiesto.json":
                continue
            if declarados.get(n) != hashlib.sha256(b).hexdigest():
                problemas.append(f"Huella del manifiesto incorrecta o ausente: {n}")
        if set(declarados) - set(planos):
            problemas.append(f"El manifiesto lista archivos inexistentes: {sorted(set(declarados) - set(planos))}")
    except (KeyError, ValueError):
        problemas.append("Falta el manifiesto o no es JSON válido.")

    try:
        raiz = ET.fromstring(planos[f"{base}.qml"].decode("utf-8").split("\n", 1)[1])
        render = raiz.find("pipe/rasterrenderer")
        if continuo:
            esperado_qml = ET.fromstring(estilo_qml_continuo().split("\n", 1)[1]).find("pipe/rasterrenderer")
            items = [(e.get("value"), e.get("color"), e.get("alpha")) for e in render.iter("item")] if render is not None else []
            esperados = [(e.get("value"), e.get("color"), e.get("alpha")) for e in esperado_qml.iter("item")]
            if render is None or render.get("type") != "singlebandpseudocolor" or items != esperados:
                problemas.append("El .qml no es el pseudocolor ±10 dB del visor.")
        elif render is None or render.get("type") != "paletted" or render.get("band") != "1":
            problemas.append("El .qml no es un estilo de paleta sobre la banda 1.")
        else:
            entradas = {int(e.get("value")): (e.get("color"), e.get("alpha")) for e in render.iter("paletteEntry")}
            esperadas = {int(v): ((c or "#000000").lower(), "255" if c else "0") for v, _, c in clases}
            if nodata is not None:
                esperadas[int(nodata)] = ("#000000", "0")
            if entradas != esperadas:
                problemas.append(f"Paleta del .qml distinta del perfil: {entradas} ≠ {esperadas}")
    except (KeyError, IndexError, ET.ParseError, ValueError):
        problemas.append("Falta el .qml o no es XML válido.")

    for n, b in planos.items():
        if n.endswith(".geojson"):
            try:
                g = json.loads(b)
                anillo = g["features"][0]["geometry"]["coordinates"][0]
                if anillo[0] != anillo[-1] or not all(-180 <= x <= 180 and -90 <= y <= 90 for x, y in anillo):
                    problemas.append(f"{n}: polígono no cerrado o fuera de rango.")
            except (ValueError, KeyError, IndexError, TypeError):
                problemas.append(f"{n}: GeoJSON inválido.")
    for requerido in ("LEEME_QGIS.txt", f"{base}_leyenda.csv"):  # leyenda continua o por clases
        if requerido not in planos:
            problemas.append(f"Falta {requerido}.")
    return problemas
