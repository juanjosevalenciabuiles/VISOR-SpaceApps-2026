"""Configuración central de V.I.S.O.R.

Todo lo que cambia entre fenómenos (archivo, colores, textos) vive aquí.
Para agregar o ajustar un caso de uso solo se edita este archivo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "data"
ASSETS_DIR = RAIZ / "assets"

# Rectángulo APROXIMADO que contiene a Antioquia (oeste, sur, este, norte) en
# EPSG:4326. Es solo una referencia para centrar y validar capas; NO es el
# límite oficial del departamento.
ANTIOQUIA_BBOX = (-77.20, 5.40, -73.80, 8.90)
MAPA_CENTRO = (7.0, -75.5)  # (lat, lon)
MAPA_ZOOM = 8

# Mapa base CartoDB Dark Matter (`cartodbdark_matter`). Desde 2026 CARTO exige
# una API key gratuita para sus teselas ráster; sin ella se ven con la marca de
# agua "API KEY REQUIRED". Se pide en https://carto.com/basemaps/apikey/ y se
# guarda como secreto/variable de entorno CARTO_API_KEY (nunca en el código).
MAPA_ATRIBUCION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
    'contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
)


def carto_api_key() -> str:
    return os.environ.get("CARTO_API_KEY", "").strip()


def url_mapa_base() -> str:
    url = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
    clave = carto_api_key()
    return f"{url}?key={clave}" if clave else url


# Lado máximo (px) con el que se lee un ráster. Protege la memoria y mantiene
# fluida la demo aunque alguien deje un GeoTIFF grande en /data.
MAX_LADO_PX = 1024


@dataclass(frozen=True)
class Fenomeno:
    clave: str
    nombre: str
    icono: str
    archivo: str                 # nombre del GeoTIFF dentro de /data
    colores: tuple[str, ...]     # rampa de menor a mayor indicio
    descripcion: str
    producto: str                # tipo de producto SAR esperado
    fuente: str                  # fuente esperada de los datos reales
    leyenda_min: str
    leyenda_max: str
    advertencias: tuple[str, ...]
    invertir: bool = False       # True si valores BAJOS indican mayor indicio
    vmin: float | None = None    # rango fijo de visualización (None = percentiles)
    vmax: float | None = None

    @property
    def ruta(self) -> Path:
        return DATA_DIR / self.archivo

    @property
    def color(self) -> str:
        """Color de acento (el más intenso de la rampa)."""
        return self.colores[-1]


FENOMENOS: dict[str, Fenomeno] = {
    "inundacion": Fenomeno(
        clave="inundacion",
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
        fuente="Sentinel-1 (ESA/Copernicus), procesado con ASF HyP3",
        leyenda_min="Menor indicio",
        leyenda_max="Mayor indicio de agua",
        advertencias=(
            "Superficies lisas (pistas, vías, suelo desnudo) y la sombra de radar "
            "en montaña pueden confundirse con agua.",
            "La vegetación inundada puede no verse oscura en banda C.",
        ),
    ),
    "deslizamiento": Fenomeno(
        clave="deslizamiento",
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
        fuente="Sentinel-1 (ESA/Copernicus), procesado con ASF HyP3",
        leyenda_min="Menor indicio",
        leyenda_max="Mayor indicio de cambio",
        advertencias=(
            "En topografía andina hay sombra y layover: zonas donde el radar no "
            "observa bien la ladera.",
            "La vegetación densa reduce la coherencia y puede ocultar o simular "
            "movimiento; la atmósfera también afecta la fase.",
        ),
    ),
    "deforestacion": Fenomeno(
        clave="deforestacion",
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
        fuente="Sentinel-1 (ESA/Copernicus), procesado con ASF HyP3",
        leyenda_min="Menor indicio",
        leyenda_max="Mayor indicio de cambio",
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
