"""Ficha científica y leyenda de los resultados SAR activos (data/analisis/).

Regla de honestidad: cada dato se muestra solo si lo declara la ficha de
procedencia o el propio GeoTIFF, y se dice de dónde sale. Lo que no está
declarado se muestra como «No declarado», nunca se rellena. Las
estadísticas se calculan aquí, a resolución completa, desde el archivo.
"""
from __future__ import annotations

from html import escape

import streamlit as st

from components.panel_info import insignia
from utils.combinacion_sar import umbrales_por_polarizacion
from utils import qgis
from utils.resultados import ResultadoSAR, _firma

NO_DECLARADO = "No declarado en el archivo"
AVISO = ("Indicio de cambio en la señal de radar. No es una inundación confirmada ni ningún otro "
         "fenómeno: requiere validación independiente.")


def _fila(etiqueta: str, valor: str, origen: str | None = None) -> str:
    nota = f'<em class="mc-origen">{escape(origen)}</em>' if origen else ""
    return (f'<div class="visor-fila"><span>{escape(etiqueta)}</span>'
            f"<strong>{escape(valor)}{nota}</strong></div>")


def _num(n: float | int, decimales: int = 0) -> str:
    texto = f"{n:,.{decimales}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def datos_declarados(res: ResultadoSAR) -> dict[str, tuple[str, str | None]]:
    """(valor, origen) de cada dato descriptivo. Primero la ficha válida, después
    las etiquetas internas del GeoTIFF; si no hay nada, NO_DECLARADO."""
    capa = res.capa
    tags = capa.metadatos if capa else {}
    real = capa is not None and capa.procedencia is not None and capa.procedencia.es_real
    bloque = (res.ficha or {}).get("procedencia") if real else None
    bloque = bloque if isinstance(bloque, dict) else {}
    de_ficha = "según la ficha de procedencia"
    de_tags = "según las etiquetas del GeoTIFF"

    def elegir(desde_ficha, desde_tags, defecto: str = NO_DECLARADO):
        if desde_ficha:
            return desde_ficha, de_ficha
        if desde_tags:
            return desde_tags, de_tags
        return defecto, None

    clases = " ".join(tags.get(f"CLASE_{i}", "") for i in (1, 2, 3)).upper()
    pols_tags = tags.get("POLARIZACION") or ("VV y VH" if "VV" in clases and "VH" in clases else "")
    # Un umbral por polarización: el producto reproducible usa VV −7,5 dB y VH −3 dB.
    umbrales = umbrales_por_polarizacion(res.ficha) if real else {}
    umbral = (" · ".join(f"{pol} −{u:g} dB".replace(".", ",") for pol, u in umbrales.items())
              + " (disminución)") if umbrales else None
    return {
        "producto": elegir((res.ficha or {}).get("producto") if real else None,
                           tags.get("PRODUCTO") or tags.get("DESCRIPCION")),
        "sensor": elegir(bloque.get("sensor"), None),
        "fechas": elegir(" → ".join(bloque.get("fechas") or []), tags.get("FECHA")),
        "polarizaciones": elegir(" y ".join(bloque.get("polarizaciones") or []), pols_tags),
        "metodo": elegir(bloque.get("metodo"), None),
        "umbral": elegir(umbral, None),
    }


def ficha_html(res: ResultadoSAR) -> str:
    """Bloque completo para el panel de información."""
    if not res.dibujable:
        return ""
    capa, perfil, e = res.capa, res.perfil, res.estadisticas or {}
    d = datos_declarados(res)
    estado = capa.procedencia
    detalle = escape(estado.motivo) + (" Falta: " + escape(", ".join(estado.faltantes)) + "."
                                       if estado.faltantes else "")
    alto, ancho = capa.forma_original
    partes = [
        f'<div class="mc-res-titulo">{escape(perfil.nombre)}</div>',
        f'<div class="mc-res-archivo"><code>{escape(res.archivo)}</code></div>',
        f'<div class="visor-procedencia">{insignia(estado)}'
        f'<p class="visor-nota-procedencia">{detalle}</p></div>',
        f'<div class="visor-aviso visor-aviso-general">{escape(AVISO)}</div>',
        f'<p class="visor-texto">{escape(perfil.descripcion)}</p>',
        '<div class="visor-seccion">Datos de origen</div>',
        _fila("Producto", *d["producto"]),
        _fila("Sensor", *d["sensor"]),
        _fila("Fechas", *d["fechas"]),
        _fila("Polarizaciones", *d["polarizaciones"]),
        _fila("Umbral", *d["umbral"]),
        _fila("CRS", capa.crs_original),
        _fila("Dimensiones", f"{ancho} × {alto} px"),
        '<div class="visor-seccion">Método</div>',
        f'<p class="visor-texto">{escape(d["metodo"][0])}</p>',
    ]
    if e:
        area = e.get("area_pixel_ha")
        filas = []
        for valor, etiqueta, color in perfil.clases:
            c = e["clases"].get(str(valor), {})
            muestra = (f'<i style="background:{color}"></i>' if color
                       else '<i class="mc-transparente" title="transparente"></i>')
            ha = f"{_num(c['area_ha'], 2)} ha" if c.get("area_ha") is not None else "—"
            filas.append(
                f"<tr><td>{muestra}{valor}</td><td>{escape(etiqueta)}</td>"
                f"<td>{_num(c.get('pixeles', 0))}</td><td>{_num(c.get('porcentaje_de_validos', 0), 2)} %</td>"
                f"<td>{ha}</td></tr>"
            )
        partes += [
            '<div class="visor-seccion">Estadísticas</div>',
            '<table class="mc-tabla"><thead><tr><th>Clase</th><th></th><th>Píxeles</th><th>% válidos</th>'
            f'<th>Área</th></tr></thead><tbody>{"".join(filas)}</tbody></table>',
            f'<div class="visor-leyenda-nota">Válidos: {_num(e["pixeles_validos"])} px · sin dato (NoData): '
            f'{_num(e["pixeles_sin_dato"])} px'
            + (f" · píxel de {_num(area, 4)} ha" if area else "")
            + ". Calculado a resolución completa desde el archivo.</div>",
        ]
        if e.get("pixeles_otros_valores"):
            partes.append(f'<div class="visor-aviso">{_num(e["pixeles_otros_valores"])} píxeles tienen valores '
                          "fuera de las clases del perfil; se pintan en gris.</div>")
    limitaciones = (res.ficha or {}).get("limitaciones") if estado.es_real else None
    lista = limitaciones if isinstance(limitaciones, list) and limitaciones else list(perfil.limitaciones)
    partes.append(
        f'<details class="mc-detalles"><summary>Limitaciones ({len(lista)})</summary><ul class="visor-lista">'
        + "".join(f"<li>{escape(str(x))}</li>" for x in lista) + "</ul></details>"
    )
    partes.append(_detalle_procedencia(res))
    for aviso in capa.avisos:
        partes.append(f'<div class="visor-aviso">{escape(aviso)}</div>')
    return f'<div class="mc-res">{"".join(partes)}</div>'


def _detalle_procedencia(res: ResultadoSAR) -> str:
    estado = res.capa.procedencia
    filas = [_fila("Ficha", f"{res.ruta.with_suffix('.json').name}" if res.ficha is not None else "No existe")]
    bloque = (res.ficha or {}).get("procedencia")
    if estado.es_real and isinstance(bloque, dict):
        gen = bloque.get("generado_por") or {}
        filas += [
            _fila("Generado por", f"{gen.get('funcion', '?')} · motor {gen.get('version_motor', '?')}"),
            _fila("Fecha de generación", str(bloque.get("generado_utc", NO_DECLARADO))),
            _fila("SHA-256", str((bloque.get("archivo") or {}).get("sha256", ""))[:16] + "…"),
        ]
        for entrada in bloque.get("entradas") or []:
            if isinstance(entrada, dict):
                filas.append(_fila(f"Entrada {entrada.get('polarizacion') or ''}".strip(),
                                   str(entrada.get("archivo", "?"))))
    else:
        filas.append(_fila("Generación", "No documentada: el archivo no trae una ficha válida"))
        tags = res.capa.metadatos
        for clave in ("DESCRIPCION", "ADVERTENCIA"):
            if tags.get(clave):
                filas.append(_fila(clave.capitalize(), tags[clave], "etiqueta del GeoTIFF"))
    return ('<details class="mc-detalles"><summary>Procedencia y archivo</summary>'
            + "".join(filas) + "</details>")


def leyenda_html(res: ResultadoSAR) -> str:
    if not res.dibujable:
        return ""
    filas = []
    for valor, etiqueta, color in res.perfil.clases:
        if color:
            filas.append(f'<div class="visor-leyenda-clase"><i style="background:{color}"></i>'
                         f"{valor} · {escape(etiqueta)}</div>")
        else:
            filas.append(f'<div class="visor-leyenda-clase"><i class="mc-transparente"></i>'
                         f"{valor} · {escape(etiqueta)} (transparente)</div>")
    filas.append('<div class="visor-leyenda-clase"><i class="mc-transparente"></i>Sin dato (NoData) '
                 "(transparente)</div>")
    return (f'<div class="visor-leyenda mc-leyenda-res"><div class="mc-res-leyenda-titulo">'
            f"{escape(res.nombre)}</div>{''.join(filas)}"
            f'<div class="visor-leyenda-nota">{escape(res.perfil.nota)}</div></div>')


def fechas_activas(resultados: list[ResultadoSAR], activos: dict[str, float]) -> list[str] | None:
    """Fechas T₁/T₂ declaradas por una ficha válida, si hay un único resultado activo."""
    elegidos = [r for r in resultados if r.dibujable and r.id in activos]
    if len(elegidos) != 1 or not elegidos[0].capa.procedencia.es_real:
        return None
    fechas = ((elegidos[0].ficha or {}).get("procedencia") or {}).get("fechas")
    return list(fechas) if isinstance(fechas, list) and len(fechas) == 2 else None


@st.cache_data(show_spinner=False, max_entries=8)
def _paquete_qgis(ruta: str, firma: tuple, clases: tuple, nombre: str) -> tuple[str, bytes]:
    return qgis.exportar(ruta, clases, nombre)


def boton_qgis(res: ResultadoSAR) -> None:
    """Descarga del paquete QGIS del resultado (GeoTIFF original + estilo + ficha + manifiesto).
    No escribe nada en el servidor ni modifica el archivo."""
    if not res.dibujable:
        return
    try:
        nombre, datos = _paquete_qgis(str(res.ruta), _firma(res.ruta), tuple(res.perfil.clases), res.nombre)
    except qgis.ErrorExportacion as e:
        st.caption(str(e))
        return
    st.download_button(
        "Exportar para QGIS", datos, file_name=nombre, mime="application/zip", key=f"qgis_{res.id}",
        icon=":material/download:", on_click="ignore", type="tertiary",
        help="ZIP con el GeoTIFF original (mismo SHA-256), estilo .qml, ficha, leyenda y manifiesto.",
    )
