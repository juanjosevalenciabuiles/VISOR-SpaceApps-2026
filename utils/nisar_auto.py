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

    @property
    def granules(self) -> tuple[str, ...]:
        return tuple(c.granule for c in self.candidatos)

    def resumen(self) -> dict:
        return {
            "tipo": self.tipo, "sensor": "NISAR", "banda": "L",
            "aoi": list(self.aoi), "granules": list(self.granules),
            "cobertura_catalogo_fraccion": round(self.cobertura, 4),
            "tamano_total_gb": round(self.tamano_bytes / 1e9, 3),
            "frecuencia": "A", "termino": self.termino,
            "avisos": list(self.avisos), "estado": "PLAN_NO_DESCARGADO",
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
            cobertura_minima: float = MIN_COBERTURA_PAR, aceptar_escena_unica: bool = True) -> Plan:
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
    limite = int(max_gb * 1e9)
    viables = []
    for p in resultado.pares:
        if p.cobertura_comun < cobertura_minima:
            continue
        cand = (p.antes, p.despues)
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
        return Plan("PAR", cand, area, cobertura, tam, termino, tuple(avisos))
    if aceptar_escena_unica:
        solos = []
        for c in resultado.candidatos:
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
                         "UNA imagen NISAR NO permite identificar un cambio temporal ni confirmar inundaciones.",))
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
                destino = desc.descargar(registro, c.granule, carpeta_crudos,
                                        float(c.tamano_bytes) / 1e9 + 0.02)
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
