"""Trabajo «Analizar» de Sentinel-1 con RTC ya existentes, dividido en fases reales.

Fases (las de `utils/trabajos.FASES`):
- Zona definida / Buscando escenas: ya hechas en la interfaz; el trabajo las recibe como APTO.
- Verificando datos: cada RTC del par existe, se abre, tiene CRS y cubre la zona.
- Preparando datos: elige el procesador (RTC existentes, sin SNAP) y comprueba que la
  carpeta de salida admite escritura y tiene espacio.
- Calculando: el motor existente (`flujo_sar.analizar_disponibles`), sin cambios científicos;
  se informa de cada polarización y de la combinación.
- Verificando: el resultado se lee, tiene píxeles válidos, su registro corresponde a esta
  ejecución (`run_id`) y se calcula el SHA-256 de cada archivo.
- Listo: lo marca `utils/trabajos` al cerrar.

Este módulo no importa Streamlit: se puede probar y ejecutar en un hilo aparte.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from utils import flujo_sar, procesadores, trabajos
from utils.analisis_sar import ErrorSAR
from utils.resultados import leer_resultado

ESPACIO_MINIMO_BYTES = 200 * 1024 * 1024


def verificar_salida(informe: flujo_sar.InformeFlujo, identificador: str) -> Path:
    """La ejecución solo se publica en el mapa si sus salidas existen, se leen, tienen píxeles
    válidos y su registro corresponde a ESTA ejecución. Si algo falla, ErrorSAR: no se muestra nada."""
    principal = informe.combinado or next(iter(informe.analisis.values()), None)
    if principal is None or not Path(principal).is_file():
        raise ErrorSAR("El análisis terminó sin producir un archivo de resultado.")
    res = leer_resultado(principal)
    if not res.dibujable:
        raise ErrorSAR(f"El resultado se generó pero no se puede leer: {res.error or 'formato no reconocido'}.")
    if not (res.estadisticas or {}).get("pixeles_validos"):
        raise ErrorSAR("El resultado no tiene ningún píxel válido en esta zona (las imágenes no la cubren).")
    try:
        registro = json.loads(Path(informe.registro).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raise ErrorSAR("El análisis no dejó un registro de procedencia legible.") from None
    if registro.get("run_id") != identificador or Path(principal).name not in (registro.get("salidas") or []):
        raise ErrorSAR("El registro de la ejecución no corresponde a la zona, el par y los parámetros elegidos.")
    return Path(principal)


def comprobar_rtc(ruta: Path, limites: tuple[float, float, float, float]) -> str:
    """Abre el RTC y comprueba CRS y cobertura de la zona. Devuelve un resumen corto."""
    import rasterio
    from rasterio.warp import transform_bounds
    if not ruta.is_file():
        raise ErrorSAR(f"{ruta.name}: el archivo no existe.")
    try:
        with rasterio.open(ruta) as ds:
            if ds.crs is None:
                raise ErrorSAR(f"{ruta.name}: no tiene sistema de coordenadas.")
            o, s, e, n = transform_bounds("EPSG:4326", ds.crs, *limites, densify_pts=21)
            b = ds.bounds
            if o >= b.right or e <= b.left or s >= b.top or n <= b.bottom:
                raise ErrorSAR(f"{ruta.name}: la imagen no cubre la zona elegida.")
            return f"{ds.crs.to_string()} · {ds.res[0]:.0f} m"
    except rasterio.errors.RasterioError as exc:
        raise ErrorSAR(f"{ruta.name}: no se puede leer ({exc}).") from None


def tarea_cambio_s1(par, disponibles, limites, parametros: dict, aceptar_mismo_dia: bool, run_id: str,
                    carpeta: Path | None = None):
    """Devuelve la función que ejecuta `utils/trabajos` en segundo plano."""
    carpeta = flujo_sar.CARPETA_ANALISIS if carpeta is None else Path(carpeta)

    def funcion(ctx: trabajos.Contexto) -> None:
        ctx.fase("datos", trabajos.EN_CURSO, "Abriendo los RTC del par")
        completas = [d for d in disponibles if d.completa]
        if not completas:
            ctx.fase("datos", trabajos.BLOQUEADO, "Faltan productos RTC del par en data/sar/")
            raise ErrorSAR("Faltan los productos RTC de este par en data/sar/.")
        resumenes = {comprobar_rtc(r, limites) for d in completas for r in (d.antes.ruta, d.despues.ruta)}
        ctx.fase("datos", trabajos.APTO, f"{2 * len(completas)} RTC legibles que cubren la zona · "
                                        + ", ".join(sorted(resumenes)))
        ctx.comprobar("preparación")

        ctx.fase("preparacion", trabajos.EN_CURSO, "Eligiendo el procesador")
        elegido = procesadores.elegir(tiene_rtc=True)
        carpeta.mkdir(parents=True, exist_ok=True)
        libre = shutil.disk_usage(carpeta).free
        if libre < ESPACIO_MINIMO_BYTES:
            raise ErrorSAR(f"Queda poco espacio en disco ({libre / 1e6:.0f} MB) para escribir el resultado.")
        ctx.fase("preparacion", trabajos.APTO, f"{elegido.nombre}: {elegido.motivo}")
        ctx.comprobar("cálculo")

        ctx.fase("calculo", trabajos.EN_CURSO, "Motor de cambio Sentinel-1")
        pols = [d.polarizacion for d in completas]

        def al_avanzar(paso: str, hechos: list[Path]) -> None:
            ctx.anotar_parciales(hechos)
            ctx.comprobar(paso)
            ctx.fase("calculo", trabajos.EN_CURSO, paso)

        inf = flujo_sar.analizar_disponibles(
            par, disponibles, limites, {p: parametros[p]["umbral_disminucion_db"] for p in pols},
            {p: parametros[p]["ventana_speckle"] for p in pols}, carpeta_salida=carpeta,
            aceptar_mismo_dia=aceptar_mismo_dia, al_avanzar=al_avanzar)
        ctx.anotar_parciales([*inf.archivos, inf.registro])
        ctx.fase("calculo", trabajos.APTO, f"{len(inf.archivos)} archivos escritos")
        ctx.comprobar("verificación")

        ctx.fase("verificacion", trabajos.EN_CURSO, "Leyendo el resultado y su registro")
        principal = verificar_salida(inf, run_id)
        ctx.resultado(principal, inf.registro, [*inf.archivos, inf.registro], inf.avisos)
        ctx.fase("verificacion", trabajos.APTO, "Resultado legible, registro coincidente, SHA-256 calculados")

    return funcion
