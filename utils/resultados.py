"""Resultados de análisis SAR en data/analisis/ como capas opcionales.

Cada GeoTIFF de la carpeta se reconoce por su perfil de producto (qué
significan sus clases y cómo se colorean). Los perfiles se identifican por lo
que el archivo declara de sí mismo —ficha JSON o etiquetas internas—, nunca
por el nombre del archivo.

    coincidencia_vv_vh   combinación VV/VH (utils/combinacion_sar.py o el
                         GeoTIFF exploratorio de Chigorodó)
    mascara_cambios      máscara de una polarización del motor SAR

Los demás GeoTIFF (por ejemplo, la diferencia continua en dB) se listan como
no reconocidos y no se dibujan. La visualización solo cambia colores: los
valores del archivo no se tocan y las estadísticas se calculan sobre el
archivo original a resolución completa.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import rasterio
import streamlit as st
from rasterio.errors import RasterioError

from utils.analisis_sar import CLASES_MASCARA, LIMITACIONES, ErrorSAR
from utils.combinacion_sar import (
    CLASES_COINCIDENCIA,
    LIMITACIONES_COMBINACION,
    NOTA_CLASE_0,
    TIPO_PRODUCTO,
    describir_clases,
)
from utils.config import DATA_DIR
from utils.diferencia_db import RANGO_DB, describir_continuo
from utils.geotiff import (  # noqa: F401 (_firma se reexporta)
    Capa,
    ErrorCapa,
    _firma,
    _metadatos,
    leer_geotiff,
)
from utils.sar_jrc import (
    CLASES_RASTER_COINCIDENCIA,
    CLASES_RASTER_POLARIZACIONES,
    TIPO_COINCIDENCIA,
    TIPO_POLARIZACIONES,
)
from utils.sar_jrc import LIMITACIONES as LIMITACIONES_JRC

CARPETA_ANALISIS = DATA_DIR / "analisis"
# Protección de memoria: un resultado más grande no se carga en el visor.
MAX_BYTES_RESULTADO = 200 * 1024 * 1024


@dataclass(frozen=True)
class PerfilResultado:
    clave: str
    nombre: str
    descripcion: str
    clases: tuple[tuple[int, str, str | None], ...]
    nota: str
    limitaciones: tuple[str, ...]
    continuo: bool = False          # True: valores continuos (dB) con rampa, sin clases
    unidades: str = "clase"


PERFILES: dict[str, PerfilResultado] = {
    "diferencia_db": PerfilResultado(
        clave="diferencia_db",
        nombre="Diferencia de retrodispersión (dB)",
        descripcion=(
            "Diferencia continua posterior − anterior en dB de una polarización, sin umbral: es el dato del "
            "que el motor saca la máscara de cambios. Azul = disminución, naranja-rojo = aumento."
        ),
        clases=(),
        nota=(f"Rampa fija de ±{RANGO_DB:g} dB (fuera de ese rango el color se satura, el valor no cambia). "
              "La opacidad crece con |Δ|; ningún píxel válido se oculta. No se aplica ningún umbral."),
        limitaciones=(
            "Una disminución de retrodispersión no confirma agua ni inundación: también la producen humedad, "
            "cosechas, labores agrícolas o viento sobre el agua.",
            "El speckle residual produce variaciones de ±1–2 dB sin cambio real en la superficie.",
            *LIMITACIONES,
        ),
        continuo=True,
        unidades="dB",
    ),
    TIPO_PRODUCTO: PerfilResultado(
        clave=TIPO_PRODUCTO,
        nombre="Coincidencia VV/VH",
        descripcion=(
            "Dónde la retrodispersión de radar disminuyó de forma significativa entre dos fechas, "
            "según la polarización: solo en VV, solo en VH o en ambas. Una disminución en las dos "
            "polarizaciones es un indicio más consistente, no una inundación confirmada."
        ),
        clases=CLASES_COINCIDENCIA,
        nota=NOTA_CLASE_0,
        limitaciones=(*LIMITACIONES_COMBINACION, *LIMITACIONES),
    ),
    "mascara_cambios": PerfilResultado(
        clave="mascara_cambios",
        nombre="Cambios de retrodispersión",
        descripcion=(
            "Máscara de cambios significativos de retrodispersión de una polarización entre dos "
            "fechas, producida por el motor SAR de V.I.S.O.R."
        ),
        clases=CLASES_MASCARA,
        nota="La clase «sin cambio significativo» es transparente.",
        limitaciones=LIMITACIONES,
    ),
    TIPO_COINCIDENCIA: PerfilResultado(
        clave=TIPO_COINCIDENCIA,
        nombre="Detecciones SAR × agua histórica (JRC)",
        descripcion=(
            "Detecciones de la máscara VV/VH de Sentinel-1 separadas según caigan o no sobre agua histórica "
            "(JRC Global Surface Water Occurrence ≥ 1 %, 1984–2024). Es una asociación geográfica con el "
            "pasado: no confirma inundaciones ni valida la detección."
        ),
        clases=CLASES_RASTER_COINCIDENCIA,
        nota=("Transparente = área válida sin detección SAR. Sin dato (SAR, JRC o fuera del AOI) no se dibuja "
              "y no significa «sin cambio»."),
        limitaciones=LIMITACIONES_JRC,
    ),
    TIPO_POLARIZACIONES: PerfilResultado(
        clave=TIPO_POLARIZACIONES,
        nombre="Detecciones SAR por polarización × agua histórica (JRC)",
        descripcion=(
            "Cada detección de Sentinel-1 (solo VV, solo VH o ambas) según caiga sobre agua histórica JRC "
            "(≥ 1 %) o no. Asociación con el pasado, no una inundación confirmada."
        ),
        clases=CLASES_RASTER_POLARIZACIONES,
        nota=("Clases 1–3: sin agua histórica; 11–13: sobre agua histórica. Las clases VV/VH son de Sentinel-1 "
              "(banda C); no se aplican a otros sensores."),
        limitaciones=LIMITACIONES_JRC,
    ),
}


def _normal(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


def identificar_perfil(etiquetas: dict[str, str], ficha: dict | None = None) -> str | None:
    """Perfil declarado por el propio archivo, o None si no se reconoce."""
    declarado = (ficha or {}).get("tipo_producto") or etiquetas.get("TIPO_PRODUCTO")
    if declarado:
        return declarado if declarado in PERFILES else None
    # GeoTIFF exploratorio: lo identifican sus etiquetas de clase.
    c1, c2, c3 = (_normal(etiquetas.get(f"CLASE_{i}", "")) for i in (1, 2, 3))
    if "solo vv" in c1 and "solo vh" in c2 and "vv y vh" in c3:
        return TIPO_PRODUCTO
    if etiquetas.get("VISOR_ANALISIS") == "1" and etiquetas.get("UNIDADES", "").lower() == "clase":
        return "mascara_cambios"
    # Diferencia continua del motor (no las retrodispersiones de cada fecha, que también están en dB).
    if (etiquetas.get("VISOR_ANALISIS") == "1" and etiquetas.get("UNIDADES", "").lower() == "db"
            and _normal(etiquetas.get("PRODUCTO", "")).startswith("cambio de retrodispersion")):
        return "diferencia_db"
    return None


@dataclass
class ResultadoSAR:
    id: str                              # clave estable para los controles
    ruta: Path
    perfil: PerfilResultado | None
    capa: Capa | None = None
    estadisticas: dict | None = None
    error: str | None = None

    @property
    def archivo(self) -> str:
        return f"data/analisis/{self.ruta.name}"

    @property
    def nombre(self) -> str:
        return self.perfil.nombre if self.perfil else self.ruta.stem

    @property
    def ficha(self) -> dict | None:
        return self.capa.ficha if self.capa else None

    @property
    def dibujable(self) -> bool:
        return self.perfil is not None and self.capa is not None


def id_resultado(ruta: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "_", ruta.stem.lower()).strip("_")


def listar(carpeta: Path | None = None) -> list[Path]:
    carpeta = CARPETA_ANALISIS if carpeta is None else Path(carpeta)
    if not carpeta.is_dir():
        return []
    return sorted(p for p in carpeta.iterdir() if p.is_file() and p.suffix.lower() in (".tif", ".tiff"))


def declaracion(ruta: Path) -> tuple[dict[str, str] | None, dict | None]:
    """Etiquetas (en mayúsculas) y ficha JSON lateral, sin leer píxeles. (None, None) si no abre."""
    try:
        with rasterio.open(ruta) as src:
            etiquetas, _, ficha = _metadatos(src, ruta)
    except (RasterioError, OSError, ValueError):
        return None, None
    return etiquetas, ficha


def leer_resultado(ruta: str | Path) -> ResultadoSAR:
    """Carga un resultado sin Streamlit (se prueba con pytest)."""
    ruta = Path(ruta)
    res = ResultadoSAR(id_resultado(ruta), ruta, None)
    if ruta.stat().st_size > MAX_BYTES_RESULTADO:
        res.error = "Archivo demasiado grande para el visor; recórtalo con un AOI."
        return res
    # El perfil se decide por lo que declara el archivo (etiquetas + ficha), sin leer el ráster;
    # así el ráster se lee una sola vez, con el remuestreo que corresponde al perfil.
    etiquetas, ficha = declaracion(ruta)
    clave = identificar_perfil(etiquetas, ficha) if etiquetas is not None else None
    if etiquetas is not None and clave is None:
        res.error = "Perfil de producto no reconocido: no se dibuja."
        return res
    perfil = PERFILES.get(clave)
    continuo = bool(perfil and perfil.continuo)
    try:
        capa = leer_geotiff(ruta, categorico=not continuo)       # bilineal solo para la imagen continua
    except ErrorCapa as e:
        res.error = str(e)
        return res
    res.perfil = perfil
    if continuo:
        try:
            res.capa = capa
            res.estadisticas = describir_continuo(ruta)          # siempre del archivo original
        except ValueError as e:
            res.perfil, res.capa, res.error = None, None, str(e)
        return res
    res.capa = capa
    try:
        res.estadisticas = describir_clases(ruta, res.perfil.clases)
    except ErrorSAR as e:
        res.error = str(e)
    return res


@st.cache_data(show_spinner=False, max_entries=24)
def _cargar_con_cache(ruta: str, firma: tuple) -> ResultadoSAR:
    return leer_resultado(ruta)


def cargar_resultados(carpeta: Path | None = None) -> list[ResultadoSAR]:
    """Todos los resultados de la carpeta; relee un archivo solo si cambió él o su ficha."""
    return [_cargar_con_cache(str(r), _firma(r)) for r in listar(carpeta)]
