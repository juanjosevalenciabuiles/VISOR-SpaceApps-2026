"""Catálogo de mapas base (fondos) de V.I.S.O.R.

Cada fondo declara su proveedor, licencia y atribución obligatoria. El mapa
base es solo contexto visual: nunca modifica ni reemplaza la capa SAR.

Para agregar o cambiar un fondo basta con editar MAPAS_BASE. Antes de hacerlo,
revisar las condiciones de uso del proveedor y anotar la fecha de revisión.
"""
from __future__ import annotations

from dataclasses import dataclass

from utils.config import sufijo_clave_carto

_OSM = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
_CARTO = f'{_OSM} &copy; <a href="https://carto.com/attributions">CARTO</a>'
_URL_CARTO = "https://{{s}}.basemaps.cartocdn.com/{estilo}/{{z}}/{{x}}/{{y}}{{r}}.png"


@dataclass(frozen=True)
class MapaBase:
    clave: str
    nombre: str
    uso: str                    # para qué sirve este fondo en V.I.S.O.R.
    url: str                    # plantilla de teselas, SIN credenciales
    atribucion: str             # HTML que exige el proveedor (va dentro del mapa)
    proveedor: str
    licencia: str               # condiciones de uso, en texto plano (para créditos)
    max_zoom: int               # zoom máximo que ofrece la interfaz
    max_zoom_nativo: int | None = None   # si el proveedor llega menos lejos, se amplía la imagen
    subdominios: str = "abc"
    usa_clave_carto: bool = False


MAPAS_BASE: dict[str, MapaBase] = {
    "carto_oscuro": MapaBase(
        clave="carto_oscuro",
        nombre="Oscuro · Dark Matter",
        uso="Fondo predeterminado: resalta las capas SAR en colores neón.",
        url=_URL_CARTO.format(estilo="dark_all"),
        atribucion=_CARTO,
        proveedor="CARTO",
        licencia="Teselas © CARTO, datos © OpenStreetMap (ODbL). Requiere API key de CARTO.",
        max_zoom=20,
        subdominios="abcd",
        usa_clave_carto=True,
    ),
    "carto_voyager": MapaBase(
        clave="carto_voyager",
        nombre="Carreteras · Voyager",
        uso="Destaca vías, ciudades y localidades para ubicar infraestructura cercana.",
        url=_URL_CARTO.format(estilo="rastertiles/voyager"),
        atribucion=_CARTO,
        proveedor="CARTO",
        licencia="Teselas © CARTO, datos © OpenStreetMap (ODbL). Requiere API key de CARTO.",
        max_zoom=20,
        subdominios="abcd",
        usa_clave_carto=True,
    ),
    "carto_positron": MapaBase(
        clave="carto_positron",
        nombre="Claro · Positron",
        uso="Fondo claro y minimalista para comparar capas con menor contraste.",
        url=_URL_CARTO.format(estilo="light_all"),
        atribucion=_CARTO,
        proveedor="CARTO",
        licencia="Teselas © CARTO, datos © OpenStreetMap (ODbL). Requiere API key de CARTO.",
        max_zoom=20,
        subdominios="abcd",
        usa_clave_carto=True,
    ),
    "topografico": MapaBase(
        clave="topografico",
        nombre="Relieve · OpenTopoMap",
        uso="Relieve sombreado y curvas de nivel para contextualizar laderas.",
        url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        atribucion=(
            f'Datos: {_OSM}, <a href="https://www.earthdata.nasa.gov/data/instruments/srtm">SRTM</a> '
            '| Estilo: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> '
            '(<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)'
        ),
        proveedor="OpenTopoMap",
        licencia=(
            "Teselas CC-BY-SA 3.0; datos OpenStreetMap (ODbL) y SRTM. Servidor de voluntarios: "
            "uso moderado y sin descargas masivas; para proyectos grandes hay que contactarlos."
        ),
        max_zoom=17,
    ),
    "satelital": MapaBase(
        clave="satelital",
        nombre="Satélite 2016 · Sentinel-2",
        uso="Mosaico óptico sin nubes para ver bosque, agua y zonas urbanas. Imagen de 2016: "
            "es contexto, no muestra el estado actual del terreno.",
        url="https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg",
        atribucion=(
            '<a href="https://s2maps.eu">Sentinel-2 cloudless - https://s2maps.eu</a> by '
            '<a href="https://eox.at">EOX IT Services GmbH</a> '
            "(Contains modified Copernicus Sentinel data 2016 &amp; 2017)"
        ),
        proveedor="EOX IT Services (datos Copernicus Sentinel-2)",
        licencia="CC BY 4.0 (edición 2016). Las ediciones 2018 en adelante son solo para uso no comercial.",
        max_zoom=17,
        max_zoom_nativo=13,
    ),
}

MAPA_BASE_PREDETERMINADO = "carto_oscuro"


def obtener(clave: str | None) -> MapaBase:
    """Fondo pedido, o el predeterminado si la clave no existe."""
    return MAPAS_BASE.get(clave or "", MAPAS_BASE[MAPA_BASE_PREDETERMINADO])


def url_teselas(mapa: MapaBase) -> str:
    """URL final de las teselas. Solo los fondos de CARTO reciben la API key, y
    solo si es válida; nunca se envía la clave de CARTO a otro proveedor."""
    return mapa.url + sufijo_clave_carto() if mapa.usa_clave_carto else mapa.url
