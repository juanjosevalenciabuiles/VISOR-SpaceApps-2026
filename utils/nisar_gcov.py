"""Lector de NISAR L2 GCOV (HDF5) y recorte del área de interés a GeoTIFF.

Adaptado del prototipo «VISOR_NISAR_inicio_2026-11-13» y contrastado con:
- nisar-docs.asf.alaska.edu/gcov/: rejillas en `/science/LSAR/GCOV/grids/
  frequencyA|B/`; términos diagonales reales (HHHH, HVHV, VVVV, VHVH, RHRH,
  RVRV) y cruzados complejos; valores gamma0 en potencia; RTC ya aplicada
  (por eso NUNCA se pasa un GCOV por HyP3 RTC).
- ISCE3 (procesador oficial): `xCoordinates`/`yCoordinates` son centros de
  píxel, `projection` lleva `epsg_code`, relleno de los rásteres flotantes =
  NaN y la máscara usa 255 = fuera de la cuadrícula de radar, 0 = muestra no
  válida, 1…N = subfranja válida (`GeocodeCov.cpp`, `GcovWriter.py`).

Nada aquí convierte a dB ni calcula cambios: se copia la ventana del AOI en
potencia lineal, sin tocar el HDF5 de origen, a un GeoTIFF que el motor SAR
ya sabe leer. Los términos cruzados (complejos) se rechazan siempre.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from utils.config import DATA_DIR

BASE = "/science/LSAR/GCOV/grids"
IDENTIFICACION = "/science/LSAR/identification"
FRECUENCIAS = ("A", "B")
DIAGONALES = ("HHHH", "HVHV", "VVVV", "VHVH", "RHRH", "RVRV")
CRUZADOS = ("HHHV", "HHVH", "HHVV", "HVVH", "HVVV", "VHVV", "RHRV")
POLARIZACION_DE = {t: t[:2] for t in DIAGONALES}      # HHHH → HH (nunca VV/VH si no lo es)
NODATA = -9999.0
MAX_PIXELES = 16_000_000
MADUREZ_VALIDAS = ("VALIDATED", "PROVISIONAL", "BETA")
CARPETA_NISAR = DATA_DIR / "nisar"
# Regla de la máscara (ISCE3 GeocodeCov.cpp): 255 fuera del radar, 0 muestra no válida.
MASCARA_NO_VALIDA = (0, 255)


class ErrorGCOV(Exception):
    """Problema con un producto GCOV, explicado para el usuario."""


@dataclass(frozen=True)
class Cuadricula:
    epsg: int
    x0: float          # centro del primer píxel
    y0: float
    dx: float
    dy: float          # negativo: filas hacia el sur
    ancho: int
    alto: int

    @property
    def limites(self) -> tuple[float, float, float, float]:
        """(oeste, sur, este, norte) de los bordes de píxel, en el CRS del producto."""
        oeste, norte = self.x0 - self.dx / 2, self.y0 - self.dy / 2
        return oeste, norte + self.dy * self.alto, oeste + self.dx * self.ancho, norte


@dataclass
class CapaGCOV:
    frecuencia: str
    termino: str
    polarizacion: str
    cuadricula: Cuadricula
    tipo: str
    con_mascara: bool


@dataclass
class ProductoGCOV:
    archivo: str
    mision: str | None
    tipo_producto: str | None
    granule: str | None
    track: int | None
    frame: int | None
    direccion: str | None
    inicio: str | None
    fin: str | None
    version_producto: str | None
    crid: str | None
    capas: list[CapaGCOV]
    terminos_cruzados: list[str]
    huella_wkt: str | None
    rtc_aplicada: bool | None
    avisos: list[str] = field(default_factory=list)

    @property
    def es_nisar(self) -> bool:
        return (self.mision or "").upper() == "NISAR"

    def capa(self, frecuencia: str, termino: str) -> CapaGCOV:
        for c in self.capas:
            if c.frecuencia == frecuencia and c.termino == termino:
                return c
        disponibles = ", ".join(f"{c.frecuencia}:{c.termino}" for c in self.capas) or "ninguna"
        raise ErrorGCOV(f"El producto no tiene la capa {frecuencia}:{termino}. Disponibles: {disponibles}.")

    def resumen(self) -> dict:
        d = asdict(self)
        d["es_nisar"] = self.es_nisar
        return d


def _texto(valor) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, np.ndarray):
        valor = valor.item() if valor.shape == () else valor.tolist()
    if isinstance(valor, (bytes, np.bytes_)):
        valor = valor.decode("utf-8", "replace")
    if isinstance(valor, np.generic):
        valor = valor.item()
    texto = str(valor).strip()
    return texto or None


def _entero(valor) -> int | None:
    t = _texto(valor)
    try:
        return int(float(t)) if t is not None else None
    except ValueError:
        return None


def _abrir(ruta: Path):
    try:
        import h5py
    except ImportError as e:  # pragma: no cover - dependencia declarada
        raise ErrorGCOV("Falta la biblioteca h5py (requirements.txt).") from e
    if not ruta.is_file():
        raise ErrorGCOV(f"No se encontró `{ruta.name}`.")
    try:
        return h5py.File(ruta, "r")
    except OSError as e:
        raise ErrorGCOV(f"`{ruta.name}` no es un HDF5 legible o está dañado.") from e


def _dataset(h5, ruta: str):
    try:
        obj = h5.get(ruta)
    except (KeyError, OSError):
        return None
    import h5py
    return obj if isinstance(obj, h5py.Dataset) else None


def _cuadricula(h5, frecuencia: str, forma: tuple[int, int]) -> Cuadricula:
    g = f"{BASE}/frequency{frecuencia}"
    x, y, proy = _dataset(h5, f"{g}/xCoordinates"), _dataset(h5, f"{g}/yCoordinates"), _dataset(h5, f"{g}/projection")
    if x is None or y is None or proy is None:
        raise ErrorGCOV(f"Frecuencia {frecuencia}: faltan xCoordinates, yCoordinates o projection.")
    if x.ndim != 1 or y.ndim != 1 or (len(y), len(x)) != forma:
        raise ErrorGCOV(f"Frecuencia {frecuencia}: las coordenadas no coinciden con la forma del ráster {forma}.")
    if len(x) < 2 or len(y) < 2:
        raise ErrorGCOV(f"Frecuencia {frecuencia}: la cuadrícula tiene menos de 2×2 píxeles.")
    xs, ys = np.asarray(x[...], dtype="float64"), np.asarray(y[...], dtype="float64")
    dx, dy = float(xs[1] - xs[0]), float(ys[1] - ys[0])
    if not (math.isfinite(dx) and math.isfinite(dy) and dx > 0 and dy < 0):
        raise ErrorGCOV(f"Frecuencia {frecuencia}: orientación no admitida (se espera x creciente e y decreciente).")
    # Regularidad relativa al paso (la tolerancia absoluta fallaría en grados).
    for nombre, v, paso in (("x", xs, dx), ("y", ys, dy)):
        if np.max(np.abs(np.diff(v) - paso)) > 1e-6 * abs(paso) + 1e-9:
            raise ErrorGCOV(f"Frecuencia {frecuencia}: la cuadrícula {nombre} no es regular; no se exporta.")
    epsg = _entero(proy.attrs.get("epsg_code")) or _entero(proy[()])
    if epsg is None or not 1024 <= epsg <= 999_999:
        raise ErrorGCOV(f"Frecuencia {frecuencia}: código EPSG ausente o no válido.")
    return Cuadricula(epsg, float(xs[0]), float(ys[0]), dx, dy, len(xs), len(ys))


def inspeccionar(ruta: str | Path) -> ProductoGCOV:
    """Metadatos y capas diagonales, sin leer las matrices completas."""
    ruta = Path(ruta)
    with _abrir(ruta) as h5:
        if BASE not in h5:
            raise ErrorGCOV(f"`{ruta.name}` no es un NISAR L2 GCOV (no tiene {BASE}).")
        ident = {k: _texto(h5[f"{IDENTIFICACION}/{k}"][()]) for k in (
            "missionId", "productType", "trackNumber", "frameNumber", "orbitPassDirection",
            "zeroDopplerStartTime", "zeroDopplerEndTime", "productVersion", "compositeReleaseId",
            "granuleId", "boundingPolygon") if f"{IDENTIFICACION}/{k}" in h5}
        avisos, capas, cruzados = [], [], []
        rtc = None
        for f in FRECUENCIAS:
            g = f"{BASE}/frequency{f}"
            if g not in h5:
                continue
            bandera = _dataset(h5, f"{g}/radiometricTerrainCorrectionFlag")
            if bandera is not None:
                rtc = bool(bandera[()]) if rtc is None else rtc and bool(bandera[()])
            for t in CRUZADOS:
                if _dataset(h5, f"{g}/{t}") is not None:
                    cruzados.append(f"{f}:{t}")
            for t in DIAGONALES:
                d = _dataset(h5, f"{g}/{t}")
                if d is None:
                    continue
                if d.ndim != 2 or d.dtype.kind != "f":
                    avisos.append(f"{f}:{t} no es una matriz real 2D ({d.dtype}); se ignora.")
                    continue
                try:
                    cuad = _cuadricula(h5, f, d.shape)
                except ErrorGCOV as e:
                    avisos.append(str(e))
                    continue
                masc = _dataset(h5, f"{g}/mask")
                capas.append(CapaGCOV(f, t, POLARIZACION_DE[t], cuad, str(d.dtype),
                                      masc is not None and masc.shape == d.shape))
    if not capas:
        raise ErrorGCOV(f"`{ruta.name}` no tiene ninguna capa diagonal GCOV utilizable.")
    if (ident.get("productType") or "GCOV").upper() != "GCOV":
        raise ErrorGCOV(f"`{ruta.name}` declara productType={ident.get('productType')}, no GCOV.")
    if (ident.get("missionId") or "").upper() != "NISAR":
        avisos.append(f"missionId={ident.get('missionId') or 'ausente'}: no es un producto de la misión NISAR; "
                      "solo sirve como estructura de prueba (se marcará DEMO).")
    if rtc is False:
        avisos.append("radiometricTerrainCorrectionFlag=False: el producto declara que no tiene RTC.")
    direccion = (ident.get("orbitPassDirection") or "").upper()
    if direccion not in ("ASCENDING", "DESCENDING"):
        if direccion:
            avisos.append(f"orbitPassDirection='{ident.get('orbitPassDirection')}' no es ascending/descending.")
        direccion = None
    granule = ident.get("granuleId") or (ruta.stem if ruta.stem.startswith("NISAR_L2_") else None)
    crid = ident.get("compositeReleaseId")
    if crid is None and granule:
        m = re.search(r"_([A-Z]\d{5})_[A-Z]_[A-Z]_[A-Z]_\d{3}$", granule)
        crid = m.group(1) if m else None
    return ProductoGCOV(
        archivo=ruta.name, mision=ident.get("missionId"), tipo_producto=ident.get("productType"),
        granule=granule, track=_entero(ident.get("trackNumber")), frame=_entero(ident.get("frameNumber")),
        direccion=direccion, inicio=ident.get("zeroDopplerStartTime"), fin=ident.get("zeroDopplerEndTime"),
        version_producto=ident.get("productVersion"), crid=crid, capas=capas, terminos_cruzados=cruzados,
        huella_wkt=ident.get("boundingPolygon"), rtc_aplicada=rtc, avisos=avisos,
    )


@dataclass
class Ventana:
    datos: np.ma.MaskedArray         # gamma0 en potencia lineal; máscara = no válido
    transform: object                # rasterio Affine
    epsg: int
    fila: int
    columna: int
    cobertura_aoi: float             # fracción del AOI dentro de la cuadrícula
    avisos: list[str]

    @property
    def pixeles_validos(self) -> int:
        return int(self.datos.count())


def leer_ventana(ruta: str | Path, frecuencia: str, termino: str,
                 bbox_lonlat: tuple[float, float, float, float], max_pixeles: int = MAX_PIXELES) -> Ventana:
    """Lee SOLO la ventana del AOI. Inválido: NaN, ≤ 0, infinito o máscara 0/255."""
    from rasterio.crs import CRS
    from rasterio.transform import Affine
    from rasterio.warp import transform_bounds

    ruta = Path(ruta)
    if termino in CRUZADOS:
        raise ErrorGCOV(f"{termino} es un término cruzado (complejo): no es potencia y no se exporta.")
    if termino not in DIAGONALES:
        raise ErrorGCOV(f"Término '{termino}' no reconocido. Diagonales: {', '.join(DIAGONALES)}.")
    if frecuencia not in FRECUENCIAS:
        raise ErrorGCOV("La frecuencia debe ser A o B.")
    oeste, sur, este, norte = bbox_lonlat
    if not (-180 <= oeste < este <= 180 and -90 <= sur < norte <= 90):
        raise ErrorGCOV("Recuadro lon/lat no válido (oeste < este, sur < norte).")
    producto = inspeccionar(ruta)
    capa = producto.capa(frecuencia, termino)
    c = capa.cuadricula
    izq, abajo, der, arriba = transform_bounds("EPSG:4326", CRS.from_epsg(c.epsg), oeste, sur, este, norte,
                                               densify_pts=21)
    o, s, e, n = c.limites
    interseccion = max(0.0, min(der, e) - max(izq, o)) * max(0.0, min(arriba, n) - max(abajo, s))
    area_aoi = (der - izq) * (arriba - abajo)
    cobertura = interseccion / area_aoi if area_aoi > 0 else 0.0
    if cobertura <= 0:
        raise ErrorGCOV("El área de interés queda fuera de la cobertura de este producto.")
    c0 = max(0, math.floor((izq - o) / c.dx))
    c1 = min(c.ancho, math.ceil((der - o) / c.dx))
    r0 = max(0, math.floor((n - arriba) / -c.dy))
    r1 = min(c.alto, math.ceil((n - abajo) / -c.dy))
    if r0 >= r1 or c0 >= c1:
        raise ErrorGCOV("El área de interés queda fuera de la cobertura de este producto.")
    if (r1 - r0) * (c1 - c0) > max_pixeles:
        raise ErrorGCOV(f"El área pedida tiene {(r1 - r0) * (c1 - c0):,} píxeles (máximo {max_pixeles:,}); redúcela.")
    avisos = list(producto.avisos)
    g = f"{BASE}/frequency{frecuencia}"
    with _abrir(ruta) as h5:
        datos = np.asarray(h5[f"{g}/{termino}"][r0:r1, c0:c1], dtype="float32")
        validos = np.isfinite(datos) & (datos > 0)
        if capa.con_mascara:
            m = np.asarray(h5[f"{g}/mask"][r0:r1, c0:c1])
            validos &= ~np.isin(m, MASCARA_NO_VALIDA)
        else:
            avisos.append(f"{frecuencia}:{termino}: el producto no trae máscara; solo se descartan NaN y valores ≤ 0.")
    if not validos.any():
        raise ErrorGCOV("La ventana del área de interés no tiene ningún píxel válido.")
    if cobertura < 0.999:
        avisos.append(f"El producto cubre el {cobertura:.0%} del área de interés.")
    transform = Affine(c.dx, 0.0, o + c0 * c.dx, 0.0, c.dy, n + r0 * c.dy)
    return Ventana(np.ma.MaskedArray(datos, mask=~validos), transform, c.epsg, r0, c0, cobertura, avisos)


def _fecha_iso(texto: str | None) -> str:
    """'2026-10-24T23:15:00.000000' → '2026-10-24T23:15:00' (formato que lee el motor)."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2}))?", texto or "")
    return "" if not m else (f"{m[1]}T{m[2]}" if m[2] else m[1])


def _nombre_salida(p: ProductoGCOV, frecuencia: str, termino: str) -> str:
    fecha = (p.inicio or "")[:10].replace("-", "") or "sinfecha"
    track = f"T{p.track:03d}" if p.track is not None else "Tna"
    frame = f"F{p.frame:03d}" if p.frame is not None else "Fna"
    direccion = (p.direccion or "x")[0]
    return f"nisar_gcov_{fecha}_{track}_{frame}_{direccion}_{frecuencia}_{termino}"


def exportar_recorte(ruta_h5: str | Path, bbox_lonlat: tuple[float, float, float, float],
                     frecuencia: str = "A", termino: str = "HHHH", carpeta: str | Path | None = None,
                     madurez: str | None = None, sha_origen: bool = False,
                     max_pixeles: int = MAX_PIXELES) -> Path:
    """Escribe `nisar_gcov_…tif` (gamma0 en potencia, float32, NoData −9999) y su
    ficha `.json` en `data/nisar/`. Nunca sobrescribe: usa `_r2`, `_r3`…"""
    import rasterio
    from rasterio.crs import CRS

    from utils.analisis_sar import prefijo_libre
    from utils.procedencia import sha256_archivo

    ruta_h5 = Path(ruta_h5)
    if madurez is not None and madurez.upper() not in MADUREZ_VALIDAS:
        raise ErrorGCOV(f"Madurez '{madurez}' no reconocida. Opciones: {', '.join(MADUREZ_VALIDAS)}.")
    producto = inspeccionar(ruta_h5)
    v = leer_ventana(ruta_h5, frecuencia, termino, bbox_lonlat, max_pixeles)
    carpeta = Path(carpeta) if carpeta is not None else CARPETA_NISAR
    carpeta.mkdir(parents=True, exist_ok=True)
    base = prefijo_libre(carpeta, _nombre_salida(producto, frecuencia, termino))
    destino = carpeta / f"{base}.tif"
    madurez_txt = madurez.upper() if madurez else "NO_COMPROBADA"
    etiquetas = {
        "VISOR_NISAR": "1", "SENSOR": "NISAR", "BANDA": "L", "FRECUENCIA": frecuencia, "TERMINO": termino,
        "POLARIZACION": POLARIZACION_DE[termino], "ESCALA": "power", "RADIOMETRIA": "gamma0",
        "UNIDADES": "gamma0 potencia lineal", "FECHA_ADQUISICION": _fecha_iso(producto.inicio),
        "TRACK": "" if producto.track is None else str(producto.track),
        "FRAME": "" if producto.frame is None else str(producto.frame),
        "DIRECCION": producto.direccion or "", "CRID": producto.crid or "", "GRANULE": producto.granule or "",
        "MADUREZ": madurez_txt, "MISION": producto.mision or "", "ORIGEN": ruta_h5.name,
    }
    if not producto.es_nisar:
        etiquetas["VISOR_DEMO"] = "1"
    if destino.exists() or destino.with_suffix(".json").exists():   # prefijo_libre ya lo evita; doble seguro
        raise ErrorGCOV(f"`{destino.name}` ya existe; no se sobrescribe.")
    with rasterio.open(destino, "w", driver="GTiff", height=v.datos.shape[0], width=v.datos.shape[1], count=1,
                       dtype="float32", crs=CRS.from_epsg(v.epsg), transform=v.transform, nodata=NODATA,
                       compress="deflate", tiled=v.datos.shape[0] >= 256 and v.datos.shape[1] >= 256) as dst:
        dst.write(v.datos.filled(NODATA).astype("float32"), 1)
        dst.update_tags(**etiquetas)
    ficha = {
        "tipo": "recorte_nisar_gcov", "sensor": "NISAR", "banda": "L",
        "origen": {"archivo": ruta_h5.name, "granule": producto.granule, "mision": producto.mision,
                   "sha256": sha256_archivo(ruta_h5) if sha_origen else None,
                   "integridad": "SHA-256 calculado" if sha_origen else "NO VERIFICADA (sin SHA-256 del HDF5)"},
        "producto": {k: getattr(producto, k) for k in ("track", "frame", "direccion", "inicio", "fin",
                                                        "version_producto", "crid", "rtc_aplicada")},
        "madurez_producto": madurez_txt,
        "capa": {"frecuencia": frecuencia, "termino": termino, "polarizacion": POLARIZACION_DE[termino],
                 "unidades": "gamma0 en potencia lineal (sin convertir a dB)", "epsg": v.epsg,
                 "resolucion": [abs(v.transform.a), abs(v.transform.e)]},
        "aoi_lonlat": list(bbox_lonlat), "cobertura_aoi": round(v.cobertura_aoi, 4),
        "ventana": {"fila": v.fila, "columna": v.columna, "alto": v.datos.shape[0], "ancho": v.datos.shape[1]},
        "pixeles_validos": v.pixeles_validos, "nodata": NODATA,
        "regla_mascara": "NaN, ≤0 o máscara 0/255 → NoData (ISCE3 GeocodeCov.cpp)",
        "sha256": sha256_archivo(destino),
        "estado": "DEMO" if not producto.es_nisar else "REAL_SIN_VALIDAR",
        "advertencia": ("Recorte de un producto GCOV sin interpretar. Que el producto sea VALIDATED no valida "
                        "ningún mapa derivado."),
        "avisos": v.avisos,
        "creado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with (carpeta / f"{base}.json").open("x", encoding="utf-8") as f:
        json.dump(ficha, f, indent=2, ensure_ascii=False)
    return destino
