"""Catálogo de mapas base (fondos) de V.I.S.O.R.

Cada fondo declara su proveedor, licencia y atribución obligatoria. El mapa
base es solo contexto visual: nunca modifica ni reemplaza la capa SAR.

Para agregar o cambiar un fondo basta con editar MAPAS_BASE. Antes de hacerlo,
revisar las condiciones de uso del proveedor y anotar la fecha de revisión.
"""
from __future__ import annotations

from dataclasses import dataclass

from utils.config import carto_estado, sufijo_clave_carto

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
    clase_css: str | None = None         # p. ej. el filtro que oscurece las teselas de OSM
    cobertura: str = "Mundial."          # alcance real de las teselas


_POLITICA_OSM = ("Servidor público de la Fundación OpenStreetMap: uso moderado, solo las teselas de la vista, "
                 "sin descargas masivas; para tráfico alto hay que usar otro proveedor "
                 "(operations.osmfoundation.org/policies/tiles).")


MAPAS_BASE: dict[str, MapaBase] = {
    "osm_oscuro": MapaBase(
        clave="osm_oscuro",
        nombre="Oscuro · OpenStreetMap",
        uso="Fondo oscuro Mission Control sin clave: calles, carreteras, ríos y nombres de OpenStreetMap "
            "con los colores invertidos en el navegador. Resalta las capas SAR.",
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        atribucion=_OSM,
        proveedor="OpenStreetMap",
        licencia="Datos © OpenStreetMap (ODbL). " + _POLITICA_OSM,
        max_zoom=19,
        subdominios="",
        clase_css="visor-base-oscura",
    ),
    "calles": MapaBase(
        clave="calles",
        nombre="Calles · OpenStreetMap",
        uso="Mapa de calles legible en todo el mundo: carreteras, puentes, ríos, lagos y nombres de lugares.",
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        atribucion=_OSM,
        proveedor="OpenStreetMap",
        licencia="Datos © OpenStreetMap (ODbL). " + _POLITICA_OSM,
        max_zoom=19,
        subdominios="",
    ),
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

# Sin clave de CARTO el oscuro de CARTO saldría con marca de agua: el predeterminado sin clave es el
# oscuro de OpenStreetMap. `predeterminado()` decide en cada ejecución.
MAPA_BASE_PREDETERMINADO = "carto_oscuro"
PREDETERMINADO_SIN_CLAVE = "osm_oscuro"


# Fondos que fallaron la última comprobación de servicios (utils/diagnostico): clave → motivo.
_caidos: dict[str, str] = {}


def registrar_caidos(caidos: dict[str, str]) -> None:
    """Sustituye la lista de fondos caídos por la de la última comprobación."""
    _caidos.clear()
    _caidos.update(caidos)


def disponible(mapa: MapaBase, considerar_diagnostico: bool = True) -> tuple[bool, str | None]:
    """(se puede ofrecer, motivo si no). Un fondo que respondería con marca de agua o 401/403 por falta
    de clave, o que falló la última comprobación de servicios, no se ofrece como disponible."""
    if mapa.usa_clave_carto and carto_estado() != "ok":
        return False, ("requiere CARTO_API_KEY (variable de entorno o Secret de Replit)" if carto_estado() == "ausente"
                       else "CARTO_API_KEY tiene una forma inválida")
    if considerar_diagnostico and mapa.clave in _caidos:
        return False, f"falló la última comprobación: {_caidos[mapa.clave]}"
    return True, None


def ofrecidos() -> list[str]:
    return [k for k, m in MAPAS_BASE.items() if disponible(m)[0]]


def no_ofrecidos() -> dict[str, str]:
    return {k: disponible(m)[1] for k, m in MAPAS_BASE.items() if not disponible(m)[0]}


def predeterminado() -> str:
    """El primer fondo disponible en orden de preferencia; si ninguno pasó la comprobación, el de OSM."""
    for clave in (MAPA_BASE_PREDETERMINADO, PREDETERMINADO_SIN_CLAVE, *MAPAS_BASE):
        if disponible(MAPAS_BASE[clave])[0]:
            return clave
    return PREDETERMINADO_SIN_CLAVE


def obtener(clave: str | None) -> MapaBase:
    """Fondo pedido, o el predeterminado si la clave no existe o ese fondo no está disponible."""
    mapa = MAPAS_BASE.get(clave or "")
    return mapa if mapa is not None and disponible(mapa)[0] else MAPAS_BASE[predeterminado()]


def url_teselas(mapa: MapaBase) -> str:
    """URL final de las teselas. Solo los fondos de CARTO reciben la API key, y
    solo si es válida; nunca se envía la clave de CARTO a otro proveedor."""
    return mapa.url + sufijo_clave_carto() if mapa.usa_clave_carto else mapa.url
