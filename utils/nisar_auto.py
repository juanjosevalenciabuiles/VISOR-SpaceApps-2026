"""Adquisición automática y controlada NISAR L2 GCOV para inundaciones.

No ejecuta descargas al importar ni consultar el catálogo. Se activa al solicitar
explícitamente "Preparar imágenes NISAR", con límites duros de GB y disco.
Reutiliza los módulos de PR #6: nisar_catalogo, nisar_descarga y nisar_gcov.
Los recortes son señal gamma0 de banda L, NO mapas de inundación validados.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import Point

from utils import alcance_geografico, nisar_catalogo as cat, nisar_descarga as desc, nisar_gcov as gcov
from utils.config import DATA_DIR

MAX_AUTO_GB = 5.0
MIN_COBERTURA_PAR = 0.40
MIN_COBERTURA_UNICA = 0.80


class ErrorAutoNISAR(RuntimeError):
    """Descarga/preparación impedida sin comprometer resultados ni datos."""


@dataclass
class Plan:
    tipo: str                    # PAR o ESCENA_UNICA
    candidatos: tuple
    aoi: tuple[float, float, float, float]
    cobertura: float
    tamano_bytes: int
    termino: str
    avisos: tuple[str, ...]
    punto_prioritario: tuple[float, float] | None = None  # longitud, latitud WGS84
    id_par_seleccionado: str | None = None
    criterio_seleccion: str = "MAYOR_COBERTURA_COMUN"

    @property
    def granules(self) -> tuple[str, ...]:
        return tuple(c.granule for c in self.candidatos)

    def resumen(self) -> dict:
        return {
            "tipo": self.tipo, "sensor": "NISAR", "banda": "L",
            "aoi": list(self.aoi), "granules": list(self.granules),
            "cobertura_catalogo_fraccion": round(self.cobertura, 4),
            "id_par_seleccionado": self.id_par_seleccionado,
            "criterio_seleccion": self.criterio_seleccion,
            "tamano_total_gb": round(self.tamano_bytes / 1e9, 3),
            "frecuencia": "A", "termino": self.termino,
            "avisos": list(self.avisos), "estado": "PLAN_NO_DESCARGADO",
            "punto_prioritario": list(self.punto_prioritario) if self.punto_prioritario else None,
            "cobertura_punto": ("SOLO_HUELLAS_CMR_NO_QA" if self.punto_prioritario else "NO_SOLICITADA"),
        }


def _candidato_ok(c, limite_bytes: int) -> bool:
    return bool(c.url_h5 and c.tamano_bytes is not None and 0 < int(c.tamano_bytes) <= limite_bytes)


def _termino(polares) -> str:
    # Nunca relabel HH/HV as VV/VH. Only diagonal covariance power.
    if "HH" in polares:
        return "HHHH"
    if "VV" in polares:
        return "VVVV"
    raise ErrorAutoNISAR("Las escenas no tienen una polarización copolar HH/VV compatible en frecuencia A.")


def planear(resultado: cat.ResultadoNISAR, max_gb: float = MAX_AUTO_GB,
            cobertura_minima: float = MIN_COBERTURA_PAR, aceptar_escena_unica: bool = True,
            punto_prioritario: tuple[float, float] | None = None) -> Plan:
    """Plan sin efectos secundarios. Selección determinista por cobertura y tamaño.

    El mínimo de 40 % permite explorar el par NISAR conocido de Chigorodó,
    pero el área no cubierta NUNCA se interpreta como agua o inundación.
    """
    if max_gb <= 0 or max_gb > 15:
        raise ErrorAutoNISAR("Límite de transferencia fuera del rango seguro (0 a 15 GB).")
    if not 0.0 < cobertura_minima <= 1.0:
        raise ErrorAutoNISAR("Cobertura mínima inválida.")
    area = resultado.region.limites
    try:
        alcance_geografico.validar_limites(area)
    except alcance_geografico.FueraDeAlcance as exc:
        raise ErrorAutoNISAR(str(exc)) from None
    if punto_prioritario is not None:
        try:
            lon, lat = map(float, punto_prioritario)
        except (TypeError, ValueError) as exc:
            raise ErrorAutoNISAR("Punto prioritario inválido: usa longitud y latitud WGS84.") from exc
        if not (area[0] <= lon <= area[2] and area[1] <= lat <= area[3]):
            raise ErrorAutoNISAR("El punto prioritario queda fuera del AOI de búsqueda.")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ErrorAutoNISAR("Coordenadas de punto prioritario fuera de WGS84.")
        punto_prioritario = (lon, lat)
        ancla = Point(lon, lat)
    else:
        ancla = None
    limite = int(max_gb * 1e9)
    viables = []
    for p in resultado.pares:
        if p.cobertura_comun < cobertura_minima:
            continue
        cand = (p.antes, p.despues)
        # La cobertura media del AOI puede ser elevada aun si el sitio
        # prioritario queda fuera de TODAS las adquisiciones. Rechazar.
        if ancla is not None and any(
            getattr(c, "huella", None) is None or not c.huella.covers(ancla)
            for c in cand
        ):
            continue
        if not all(_candidato_ok(c, limite) for c in cand):
            continue
        tam = sum(int(c.tamano_bytes) for c in cand)
        if tam > limite:
            continue
        try:
            termino = _termino(p.polarizaciones_A)
        except ErrorAutoNISAR:
            continue
        # Preferir cobertura alta y, en empate, menos GB. No procesar sin confirmar calidad HDF5.
        viables.append((-p.cobertura_comun, tam, cand, termino))
    if viables:
        viables.sort(key=lambda x: (x[0], x[1], x[2][0].granule))
        cub, tam, cand, termino = viables[0]
        cobertura = -cub
        avisos = ["Par temporal CANDIDATO NO VALIDADO: falta inspeccionar HDF5 y congruencia radiométrica.",
                  f"Las huellas solo cubren {cobertura:.0%} de la AOI; NO declarar inundación fuera de esa zona.",
                  "Se descargan datos originales NISAR; no se calculan inundaciones automáticamente."]
        if ancla is not None:
            avisos.append(
                "El punto prioritario aparece en ambas HUELLAS CMR; "
                "esto NO verifica la cobertura QA del píxel. "
                "Antes de analizar inundaciones, validar mask/looks e intensidades en ambas fechas."
            )
        return Plan("PAR", cand, area, cobertura, tam, termino, tuple(avisos),
                    punto_prioritario=punto_prioritario)
    if aceptar_escena_unica:
        solos = []
        for c in resultado.candidatos:
            if ancla is not None and (getattr(c, "huella", None) is None or
                                      not c.huella.covers(ancla)):
                continue
            if c.cobertura < MIN_COBERTURA_UNICA or not _candidato_ok(c, limite):
                continue
            try:
                termino = _termino(c.nombre.pol_a)
            except ErrorAutoNISAR:
                continue
            solos.append((-c.cobertura, int(c.tamano_bytes), c, termino))
        if solos:
            solos.sort(key=lambda x: (x[0], x[1], x[2].granule))
            cub, tam, c, termino = solos[0]
            return Plan("ESCENA_UNICA", (c,), area, -cub, tam, termino,
                        ("Solo hay una fecha apta con suficiente cobertura.",
                         "UNA imagen NISAR NO permite identificar un cambio temporal ni confirmar inundaciones.",),
                        punto_prioritario=punto_prioritario)
    if ancla is not None:
        raise ErrorAutoNISAR(
            "No existe un par NISAR candidato cuyas dos huellas CMR cubran "
            "el punto prioritario con el presupuesto y la cobertura mínima actuales. "
            "Prueba ampliar el período o reducir --cobertura-minima (solo metadatos). "
            "NO descargar el par anterior para este punto."
        )
    raise ErrorAutoNISAR(
        "No se encontró un par NISAR comparable dentro de los límites de cobertura y almacenamiento. "
        "Amplía las fechas o selecciona una zona más pequeña; nunca se inventará un par."
    )


def preparar(plan: Plan, registro: Path, carpeta_crudos: Path | None = None,
             carpeta_recortes: Path | None = None, notificar=None) -> dict:
    """Descarga automática del PLAN ya seleccionado y recorta HDF5 auténticos.

    No sobrescribe HDF5 existentes ni archivos de análisis, y no usa Sentinel-1.
    Se comprueban tamaños y cabecera HDF5 para archivos que se reutilicen.
    """
    carpeta_crudos = Path(carpeta_crudos or (DATA_DIR / "nisar" / "crudos"))
    carpeta_recortes = Path(carpeta_recortes or (DATA_DIR / "nisar"))
    try:
        alcance_geografico.validar_limites(plan.aoi)
    except alcance_geografico.FueraDeAlcance as exc:
        raise ErrorAutoNISAR(str(exc)) from None
    if not os.environ.get(desc.VARIABLE_TOKEN, "").strip():
        raise ErrorAutoNISAR("Earthdata Login no está configurado. Define EARTHDATA_TOKEN en Secrets de Replit.")
    archivos = []
    pendientes = 0
    for c in plan.candidatos:
        destino = carpeta_crudos / f"{c.granule}.h5"
        if destino.is_file():
            if destino.stat().st_size != int(c.tamano_bytes):
                raise ErrorAutoNISAR(f"{destino.name}: el archivo local tiene un tamaño inesperado.")
            with destino.open("rb") as f:
                if f.read(8) != b"\x89HDF\r\n\x1a\n":
                    raise ErrorAutoNISAR(f"{destino.name}: cabecera HDF5 inválida; no se reutiliza.")
        else:
            pendientes += int(c.tamano_bytes)
    carpeta_crudos.mkdir(parents=True, exist_ok=True)
    libre = shutil.disk_usage(carpeta_crudos).free
    if libre < pendientes * 1.30 + 500_000_000:
        raise ErrorAutoNISAR(
            f"Replit no tiene espacio suficiente: faltan {((pendientes * 1.30 + 500_000_000) - libre)/1e9:.2f} GB. "
            "No se inicia una descarga incompleta."
        )
    for c in plan.candidatos:
        destino = carpeta_crudos / f"{c.granule}.h5"
        if not destino.exists():
            if notificar:
                notificar("descarga", c.granule)
            try:
                # Se confirmó un PLAN con GB máximos; no hace falta escribir el
                # nombre ni el tamaño manualmente para cada granule.
                destino = desc.descargar(
                    registro, c.granule, carpeta_crudos,
                    float(c.tamano_bytes) / 1e9 + 0.02,
                    avance=(lambda hecho, total: notificar("progreso", (hecho, total))) if notificar else None,
                )
            except desc.ErrorDescarga as exc:
                raise ErrorAutoNISAR(str(exc)) from None
        # Inspección REAL antes de recortar; no confundir un HDF5 sintético con NISAR.
        if notificar:
            notificar("inspeccion", c.granule)
        try:
            info = gcov.inspeccionar(destino)
        except gcov.ErrorGCOV as exc:
            raise ErrorAutoNISAR(f"No se puede inspeccionar {destino.name}: {exc}") from None
        if not info.es_nisar:
            raise ErrorAutoNISAR(f"{destino.name} no declara la misión NISAR. Archivo conservado sin analizar.")
        # Para un PAR, el geotiff seguirá etiquetado como señal radar, NO inundación.
        if notificar:
            notificar("recorte", c.granule)
        try:
            recorte = gcov.exportar_recorte(destino, plan.aoi, frecuencia="A",
                                          termino=plan.termino, carpeta=carpeta_recortes,
                                          madurez="VALIDATED")
        except gcov.ErrorGCOV as exc:
            raise ErrorAutoNISAR(f"{destino.name}: no pudo recortarse: {exc}") from None
        archivos.append({"granule": c.granule, "hdf5": destino.name, "geotiff": recorte.name})
    return {
        "estado": "NISAR_DESCARGADO_Y_RECORTADO", "sensor": "NISAR", "banda": "L",
        "resultado": "SEÑAL_RADAR_NO_INUNDACION", "escenas": archivos,
        "plan": plan.resumen(), "creado_utc": datetime.now(timezone.utc).isoformat(),
        "advertencia": "No se han generado mapas de inundación; solo insumos geocodificados auténticos."
    }



def _mensaje_seguro_error_red_harmony(exc: Exception) -> str:
    """Diagnóstico sin URLs firmadas, cookies ni cabeceras de autenticación."""
    respuesta = getattr(exc, "response", None)
    codigo = getattr(respuesta, "status_code", None)
    if codigo is None:
        codigo = getattr(exc, "code", None)
    try:
        codigo = int(codigo)
    except (ValueError, TypeError):
        codigo = None
    if codigo in (401, 403):
        return (
            f"NASA Harmony rechazó la autorización (HTTP {codigo}). "
            "Comprueba EARTHDATA_TOKEN y el acceso a Earthdata en Secrets."
        )
    if codigo == 404:
        return (
            "NASA Harmony devolvió HTTP 404: no encontró el recurso solicitado. "
            "Comprueba la disponibilidad del producto GCOV y la colección."
        )
    if codigo == 429:
        return "NASA Harmony devolvió HTTP 429: límite de solicitudes del servicio."
    if codigo is not None and 500 <= codigo <= 599:
        return f"NASA Harmony devolvió HTTP {codigo}: fallo del servicio remoto."
    if codigo is not None and 400 <= codigo <= 499:
        return f"NASA Harmony rechazó la petición con HTTP {codigo}."
    clase = type(exc).__name__.lower()
    if "timeout" in clase or isinstance(exc, TimeoutError):
        return "La conexión con NASA Harmony agotó el tiempo de respuesta."
    if "connection" in clase or "urlerror" in clase:
        return "No se pudo conectar con NASA Harmony durante la preparación."
    return (
        "NASA Harmony no completó el recorte: error no identificado en la red "
        "o el cliente. Revisa los registros del trabajo y el estado del servicio."
    )


def preparar_harmony(plan: Plan, carpeta: Path | None = None, notificar=None, comprobar=None,
                     max_mb: int = 512, caps: dict | None = None, cliente=None,
                     abrir=None, dormir=None) -> dict:
    """Primera opción: COG por AOI/variable con NASA Harmony SIN descargar HDF5.

    Nunca se cambia la resolución. Un fallo NO provoca descarga íntegra de GB.
    El archivo es insumo gamma0, no clasificador de agua/inundaciones.
    """
    from utils import nisar_harmony as harmony

    if not 64 <= max_mb <= 1024:
        raise ErrorAutoNISAR("Límite Harmony: selecciona entre 64 y 1024 MiB.")
    try:
        alcance_geografico.validar_limites(plan.aoi)
    except alcance_geografico.FueraDeAlcance as exc:
        raise ErrorAutoNISAR(str(exc)) from None
    if not os.environ.get("EARTHDATA_TOKEN", "").strip() and cliente is None:
        raise ErrorAutoNISAR("Para usar Harmony configura EARTHDATA_TOKEN en los Secrets de Replit.")
    madureces = {str(getattr(c, "madurez", "VALIDATED")).upper() for c in plan.candidatos}
    if len(madureces) != 1 or not madureces.issubset({"VALIDATED", "PROVISIONAL"}):
        raise ErrorAutoNISAR("No se pueden mezclar productos de madurez distinta en un par NISAR.")
    madurez = next(iter(madureces))
    try:
        caps = caps if caps is not None else harmony.capacidades(madurez=madurez)
    except harmony.ErrorHarmony as exc:
        raise ErrorAutoNISAR(str(exc)) from None
    if caps.get("madurez", "VALIDATED") != madurez:
        raise ErrorAutoNISAR("Harmony no ha validado capacidades para la colección " + madurez + ".")
    carpeta = Path(carpeta) if carpeta is not None else DATA_DIR / "nisar" / "harmony"
    # Comprobación por PAR antes de solicitar el primer COG. Los controles
    # individuales permanecen en harmony.obtener y el stream siempre tiene
    # límite por capa. Reservar al menos 512 MiB adicionales para metadatos,
    # staging y margen del entorno de ejecución; no asumir que un despliegue
    # publicado comparte el disco del workspace de Replit.
    presupuestado = max_mb * 1024**2
    carpeta.mkdir(parents=True, exist_ok=True)
    libre = shutil.disk_usage(carpeta).free
    reserva = 512 * 1024**2
    if libre < presupuestado + reserva:
        raise ErrorAutoNISAR(
            "Espacio insuficiente para el par NISAR: se necesitan "
            f"{(presupuestado + reserva) / 1024**2:.0f} MiB libres "
            "para descargar y preparar los COG de forma segura."
        )
    # Crear solo el mínimo de capas: copolar + máscara + looks cuando
    # el análisis temporal V9 ha confirmado un par específico.
    escenas = []
    usados = 0
    for c in plan.candidatos:
        if comprobar:
            comprobar()
        # En el selector visual V9 basta copolar + máscara + numberOfLooks.
        # Otras adquisiciones conservan HV/VH cuando corresponde.
        spec = harmony.especificar(
            c, plan.aoi, caps, solo_cambio=bool(plan.id_par_seleccionado)
        )
        restante = presupuestado - usados
        if restante < 64 * 1024**2:
            raise ErrorAutoNISAR("Se alcanzó el límite de almacenamiento para este par.")
        if notificar:
            notificar("Harmony", f"Recortando {c.granule}")
        kwargs = {"cliente": cliente, "abrir": abrir, "notificar": notificar,
                  "comprobar": comprobar, "limite_bytes": restante}
        if dormir is not None:
            kwargs["dormir"] = dormir
        try:
            salida = harmony.obtener(spec, carpeta, **kwargs)
        except harmony.ErrorHarmony as exc:
            raise ErrorAutoNISAR(str(exc)) from None
        except Exception as exc:
            from utils import trabajos
            if isinstance(exc, (trabajos.Cancelado, trabajos.TiempoAgotado)):
                raise
            # Persistir SOLO el código HTTP/tipo de error, nunca el detalle
            # bruto de requests (puede contener query params y URL firmada).
            raise ErrorAutoNISAR(_mensaje_seguro_error_red_harmony(exc)) from None
        usados += salida["bytes_totales"]
        escenas.append({
            "granule": c.granule, "metodo": "HARMONY_COG_SUBSET",
            "carpeta_relativa": salida["carpeta_relativa"],
            "archivos": [a["archivo"] for a in salida["archivos"]],
            "bytes_totales": salida["bytes_totales"],
        })
    return {
        "estado": "NISAR_COG_PREPARADO_SIN_CLASIFICAR", "sensor": "NISAR", "banda": "L",
        "resultado": "GAMMA0_POTENCIA_NO_INUNDACION",
        "metodo": "NASA_HARMONY", "madurez": madurez,
        "bytes_totales": usados, "escenas": escenas,
        "plan": plan.resumen(), "creado_utc": datetime.now(timezone.utc).isoformat(),
        "advertencia": "NISAR banda L, sin interpolación. No confirma agua ni inundación."
    }
