"""Configuración central de V.I.S.O.R.

Todo lo que cambia entre fenómenos (archivo, colores, textos) vive aquí.
Para agregar o ajustar un caso de uso solo se edita este archivo.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "data"
ASSETS_DIR = RAIZ / "assets"

# Rectángulo APROXIMADO que contiene a Antioquia (oeste, sur, este, norte) en
# EPSG:4326. Es solo una referencia para centrar y validar capas; NO es el
# límite oficial del departamento.
ANTIOQUIA_BBOX = (-77.20, 5.40, -73.80, 8.90)
MAPA_CENTRO = (7.0, -75.5)  # (lat, lon)
MAPA_ZOOM = 8

# Área de interés del primer análisis real (Chigorodó, Urabá antioqueño):
# el AOI con que se generaron las máscaras VV/VH (oeste, sur, este, norte).
# Es el destino predeterminado de «Ir a…».
AOI_CHIGORODO = (-76.80, 7.55, -76.55, 7.80)
CHIGORODO_CENTRO = ((AOI_CHIGORODO[1] + AOI_CHIGORODO[3]) / 2, (AOI_CHIGORODO[0] + AOI_CHIGORODO[2]) / 2)
CHIGORODO_ZOOM = 11

# --- Clave de CARTO -------------------------------------------------------
# Los mapas base de CARTO exigen una API key gratuita; sin ella las teselas
# llegan con la marca de agua "API KEY REQUIRED". La clave vive SOLO en la
# variable de entorno CARTO_API_KEY (en Replit: Secrets). Nunca en el código,
# en el repositorio ni en los registros. El catálogo de fondos está en
# utils/mapas_base.py.
_LARGO_MAX_CLAVE = 512


def carto_estado() -> str:
    """'ok', 'ausente' o 'invalida'. Nunca devuelve ni registra la clave.

    Solo se comprueba la forma (ASCII imprimible, sin espacios ni saltos de
    línea, largo razonable). Si CARTO la rechaza, se nota por la marca de agua.
    """
    clave = os.environ.get("CARTO_API_KEY", "").strip()
    if not clave:
        return "ausente"
    forma_valida = (
        len(clave) <= _LARGO_MAX_CLAVE
        and clave.isascii()
        and clave.isprintable()
        and not any(c.isspace() for c in clave)
    )
    return "ok" if forma_valida else "invalida"


def carto_api_key() -> str:
    """Clave de CARTO, o cadena vacía si falta o su forma no es válida."""
    return os.environ.get("CARTO_API_KEY", "").strip() if carto_estado() == "ok" else ""


def sufijo_clave_carto() -> str:
    """'?key=…' codificado para URL, o cadena vacía si no hay clave utilizable."""
    clave = carto_api_key()
    return f"?key={quote(clave, safe='')}" if clave else ""


# Lado máximo (px) con el que se lee un ráster. Protege la memoria y mantiene
# fluida la demo aunque alguien deje un GeoTIFF grande en /data.
MAX_LADO_PX = 1024


@dataclass(frozen=True)
class Fenomeno:
    """Perfil de visualización de un fenómeno. Cada uno se configura por separado.

    Importante: un valor alto NO significa por sí mismo "más riesgo". Qué
    extremo de la escala es el relevante depende del producto, y se declara
    aquí con `invertir`, `leyenda_min` y `leyenda_max`.
    """
    clave: str
    nombre: str
    icono: str
    archivo: str                      # nombre del GeoTIFF dentro de /data
    descripcion: str
    producto: str                     # tipo de producto SAR esperado
    advertencias: tuple[str, ...]

    # --- Valores ---
    tipo_valores: str = "continuo"    # "continuo" (bilinear) o "categorico" (nearest)
    unidades: str = "sin unidades"

    # --- Continuo: rampa y normalización ---
    colores: tuple[str, ...] = ("#1C1C1E", "#FFFFFF")   # de extremo tenue a intenso
    vmin: float | None = None         # rango fijo; None = percentiles de los datos
    vmax: float | None = None
    percentiles: tuple[float, float] = (2, 98)
    invertir: bool = False            # True: el extremo intenso va en los valores BAJOS
    leyenda_min: str = "Valores bajos"   # qué significan los valores bajos / altos
    leyenda_max: str = "Valores altos"

    # --- Categórico: (valor, etiqueta, color). color=None deja la clase transparente ---
    clases: tuple[tuple[float, str, str | None], ...] = ()

    # --- Transparencia de datos VÁLIDOS (NoData siempre es transparente) ---
    transparencia: str = "gradual"    # "gradual" (de alfa_min a 1) o "nodata" (todo opaco)
    alfa_min: float = 0.25            # opacidad mínima de un dato válido en modo gradual

    # --- Tema de la interfaz (Mission Control Earth Explorer) ---
    # Tiñe paneles, bordes y controles. NO cambia los colores de los datos
    # (`colores`, `clases`): esos describen valores, no estética.
    tema: str = "#4FDCF4"

    def __post_init__(self) -> None:
        if self.tipo_valores not in ("continuo", "categorico"):
            raise ValueError(f"{self.clave}: tipo_valores inválido")
        if self.transparencia not in ("gradual", "nodata"):
            raise ValueError(f"{self.clave}: transparencia inválida")
        if self.categorico and not self.clases:
            raise ValueError(f"{self.clave}: un producto categórico necesita `clases`")
        if self.vmin is not None and self.vmax is not None and self.vmax <= self.vmin:
            raise ValueError(f"{self.clave}: vmax debe ser mayor que vmin")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", self.tema):
            raise ValueError(f"{self.clave}: tema debe ser un color #RRGGBB")

    @property
    def categorico(self) -> bool:
        return self.tipo_valores == "categorico"

    @property
    def ruta(self) -> Path:
        return DATA_DIR / self.archivo

    @property
    def color(self) -> str:
        """Color más intenso de la rampa de datos (contorno de cobertura)."""
        return self.colores[-1]

    @property
    def tema_rgb(self) -> tuple[int, int, int]:
        """Componentes RGB exactos del color de tema, para las variables CSS."""
        return tuple(int(self.tema[i:i + 2], 16) for i in (1, 3, 5))


# PERFILES ACTUALES: pensados para los GeoTIFF sintéticos (índice 0–1 sin
# significado físico). Al integrar cada producto real de HyP3 hay que revisar
# en su perfil: unidades, vmin/vmax, invertir, transparencia y textos de leyenda.
# Fuente y fecha NO se configuran aquí: solo se muestran si vienen en los
# metadatos del archivo (etiquetas del GeoTIFF o su .json lateral).
FENOMENOS: dict[str, Fenomeno] = {
    "inundacion": Fenomeno(
        clave="inundacion",
        tema="#4FDCF4",
        nombre="Inundaciones",
        icono="🌊",
        archivo="inundacion.tif",
        colores=("#0B3C5D", "#0096FF", "#00F0FF"),
        descripcion=(
            "Posibles zonas inundadas a partir de cambios en la retrodispersión "
            "SAR. El agua en calma actúa como reflector especular y devuelve muy "
            "poca señal al radar, por lo que una caída fuerte entre dos fechas "
            "puede indicar terreno cubierto por agua."
        ),
        producto="Cambio de retrodispersión (amplitud SAR, RTC)",
        tipo_valores="continuo",
        unidades="índice relativo, sin unidades",
        vmin=None,
        vmax=None,
        invertir=False,
        transparencia="gradual",
        alfa_min=0.25,
        leyenda_min="Señal más débil",
        leyenda_max="Señal más intensa",
        advertencias=(
            "Superficies lisas (pistas, vías, suelo desnudo) y la sombra de radar "
            "en montaña pueden confundirse con agua.",
            "La vegetación inundada puede no verse oscura en banda C.",
        ),
    ),
    "deslizamiento": Fenomeno(
        clave="deslizamiento",
        tema="#F4A463",
        nombre="Deslizamientos",
        icono="⛰️",
        archivo="deslizamiento.tif",
        colores=("#5A1A00", "#FF6A00", "#FF2D55"),
        descripcion=(
            "Indicios de desplazamiento o cambio del terreno a partir de productos "
            "SAR/InSAR (fase interferométrica o diferencia de amplitud entre "
            "fechas). Señala laderas donde la superficie pudo haberse movido."
        ),
        producto="Desplazamiento InSAR / diferencia de amplitud",
        tipo_valores="continuo",
        unidades="índice relativo, sin unidades",
        vmin=None,
        vmax=None,
        invertir=False,
        transparencia="gradual",
        alfa_min=0.25,
        leyenda_min="Señal más débil",
        leyenda_max="Señal más intensa",
        advertencias=(
            "En topografía andina hay sombra y layover: zonas donde el radar no "
            "observa bien la ladera.",
            "La vegetación densa reduce la coherencia y puede ocultar o simular "
            "movimiento; la atmósfera también afecta la fase.",
        ),
    ),
    "deforestacion": Fenomeno(
        clave="deforestacion",
        tema="#64DFA7",
        nombre="Deforestación",
        icono="🌳",
        archivo="deforestacion.tif",
        colores=("#0B3D1E", "#39FF14", "#F5FF00"),
        descripcion=(
            "Posibles alteraciones de la cobertura vegetal a partir de cambios "
            "observables en datos SAR (por ejemplo, coherencia InSAR o "
            "retrodispersión entre fechas)."
        ),
        producto="Cambio de coherencia InSAR / retrodispersión",
        tipo_valores="continuo",
        unidades="índice relativo, sin unidades",
        vmin=None,
        vmax=None,
        invertir=False,
        transparencia="gradual",
        alfa_min=0.25,
        leyenda_min="Señal más débil",
        leyenda_max="Señal más intensa",
        advertencias=(
            "Cosechas, cambios de humedad del suelo y lluvias recientes también "
            "modifican la señal sin que haya tala.",
            "En bosque tropical la coherencia en banda C suele ser baja de por sí.",
        ),
    ),
}

ADVERTENCIA_GENERAL = (
    "V.I.S.O.R. muestra indicios, no detecciones confirmadas. Toda interpretación "
    "requiere validación con otras fuentes y trabajo de campo."
)
