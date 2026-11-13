"""Flujo NISAR (banda L) sobre recortes GCOV locales de `data/nisar/`.

- Pares: solo recortes con el mismo track, frame, dirección, frecuencia,
  término y CRID (`analisis_sar.bloqueos_nisar`). Si no hay ninguno, se dice
  por qué y se ofrece la escena única: no se inventa un par temporal.
- Análisis temporal: el motor SAR común (alineación, media móvil en POTENCIA,
  10·log10, Δ = posterior − anterior, ≤ 0 inválido) con umbrales
  EXPERIMENTALES que se piden explícitamente (no los de Sentinel-1).
- Escena única: gamma0 de una fecha en dB, sin umbral ni interpretación.

Nunca se mezclan con los RTC Sentinel-1 de `data/sar/`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio

from utils.analisis_sar import (
    ADVERTENCIA,
    LIMITACIONES_BANDA_L,
    NODATA_DB,
    VERSION_MOTOR,
    Cuadricula,
    ErrorSAR,
    EscenaRTC,
    ParametrosCambio,
    ResultadoAnalisis,
    a_potencia,
    analizar_par,
    bloqueos_nisar,
    describir_escena,
    exportar_geotiff,
    leer_en_cuadricula,
    potencia_a_db,
    prefijo_libre,
)
from utils.config import DATA_DIR
from utils.procedencia import sha256_archivo

CARPETA_NISAR = DATA_DIR / "nisar"
CARPETA_ANALISIS = DATA_DIR / "analisis"
TIPO_ESCENA_UNICA = "retrodispersion_db"


@dataclass
class ParLocal:
    antes: EscenaRTC
    despues: EscenaRTC

    @property
    def clave(self) -> str:
        return f"{self.antes.ruta.name}|{self.despues.ruta.name}"

    @property
    def dias(self) -> float:
        return (self.despues.fecha - self.antes.fecha).total_seconds() / 86_400


@dataclass
class InventarioNISAR:
    recortes: list[EscenaRTC] = field(default_factory=list)
    pares: list[ParLocal] = field(default_factory=list)
    bloqueos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def recortes_locales(carpeta: Path | None = None) -> tuple[list[EscenaRTC], list[str]]:
    """Recortes NISAR válidos (`nisar_gcov_*.tif` con SENSOR=NISAR) y avisos de los que no lo son."""
    carpeta = Path(carpeta) if carpeta is not None else CARPETA_NISAR
    recortes, avisos = [], []
    if not carpeta.is_dir():
        return recortes, avisos
    for ruta in sorted(carpeta.glob("nisar_gcov_*.tif")):
        try:
            e = describir_escena(ruta)
        except ErrorSAR as err:
            avisos.append(f"{ruta.name}: {err}")
            continue
        if not e.es_nisar:
            avisos.append(f"{ruta.name}: no declara SENSOR=NISAR; se ignora.")
            continue
        if e.fecha is None:
            avisos.append(f"{ruta.name}: sin fecha de adquisición; no puede formar un par.")
        recortes.append(e)
    return recortes, avisos


def inventario(carpeta: Path | None = None) -> InventarioNISAR:
    recortes, avisos = recortes_locales(carpeta)
    inv = InventarioNISAR(recortes=recortes, avisos=avisos)
    fechados = sorted((r for r in recortes if r.fecha), key=lambda r: r.fecha)
    for i, a in enumerate(fechados):
        for d in fechados[i + 1:]:
            motivos = bloqueos_nisar(a, d)
            if (d.fecha - a.fecha).total_seconds() < 43_200:
                motivos.append("misma toma o mismo día")
            if motivos:
                inv.bloqueos.append(f"{a.ruta.name} ↔ {d.ruta.name}: {'; '.join(motivos)}")
            else:
                inv.pares.append(ParLocal(a, d))
    if recortes and not inv.pares:
        inv.avisos.append("No hay ningún par NISAR compatible: solo se puede ver una escena única, sin cálculo de cambio.")
    return inv


def analizar(par: ParLocal, aoi: tuple[float, float, float, float] | None, parametros: ParametrosCambio,
             carpeta_salida: Path | None = None) -> ResultadoAnalisis:
    """Cambio temporal NISAR con el motor común. `parametros` es obligatorio (umbrales experimentales)."""
    if parametros is None:
        raise ErrorSAR("Indica umbrales experimentales para banda L.")
    return analizar_par(par.antes.ruta, par.despues.ruta, carpeta_salida or CARPETA_ANALISIS, aoi=aoi,
                        parametros=parametros)


def escena_unica(recorte: EscenaRTC, carpeta_salida: Path | None = None) -> Path:
    """gamma0 de una sola fecha en dB (10·log10 de la potencia; ≤ 0 sin dato).
    No hay umbral ni clasificación: es la señal medida, no un cambio."""
    if not recorte.es_nisar:
        raise ErrorSAR(f"{recorte.ruta.name} no es un recorte NISAR.")
    carpeta = Path(carpeta_salida) if carpeta_salida is not None else CARPETA_ANALISIS
    carpeta.mkdir(parents=True, exist_ok=True)
    g = recorte.geometria
    fecha = f"{recorte.fecha:%Y%m%d}" if recorte.fecha else "sinfecha"
    base = prefijo_libre(carpeta, f"nisar_gamma0_{g['frecuencia']}{g['termino']}_{fecha}_T{g['track']}_F{g['frame']}")
    cuad = Cuadricula(recorte.crs, recorte.transform, recorte.ancho, recorte.alto)
    datos, _ = leer_en_cuadricula(recorte, cuad)
    db = potencia_a_db(a_potencia(datos, recorte.escala))
    if db.count() == 0:
        raise ErrorSAR(f"{recorte.ruta.name} no tiene ningún píxel válido.")
    dia = f"{recorte.fecha:%Y-%m-%d}" if recorte.fecha else "fecha desconocida"
    producto = f"Retrodispersión gamma0 {recorte.polarizacion} (dB) · NISAR banda L"
    fuente = (f"NISAR L2 GCOV banda L, frecuencia {g['frecuencia']}, {g['termino']} · track {g['track']}, "
              f"frame {g['frame']}, CRID {g['crid']} · ASF · derivado por V.I.S.O.R.")
    etiquetas = {
        "VISOR_ANALISIS": "1", "TIPO_PRODUCTO": TIPO_ESCENA_UNICA, "MOTOR_VERSION": VERSION_MOTOR,
        "SENSOR": "NISAR", "BANDA": "L", "FUENTE": fuente, "FECHA": dia, "POLARIZACION": recorte.polarizacion,
        "PRODUCTO": producto, "UNIDADES": "dB", "ENTRADA": recorte.ruta.name, "ADVERTENCIA": ADVERTENCIA,
        **({"VISOR_DEMO": "1"} if recorte.es_demo else {}),
    }
    ruta = exportar_geotiff(carpeta / f"{base}_db.tif", db.astype("float32"), cuad, NODATA_DB, etiquetas,
                            {"fuente": fuente, "fecha": dia, "producto": producto, "unidades": "dB"})
    validos = db.compressed()
    informe = {
        "motor": "V.I.S.O.R. · utils/nisar_flujo.py (escena única)",
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sensor": "NISAR", "banda": "L", "advertencia": ADVERTENCIA,
        "entrada": {**recorte.resumen(), "sha256": sha256_archivo(recorte.ruta)},
        "metodo": ["Lectura del recorte GCOV en gamma0 de potencia lineal, sin remuestreo.",
                   "Conversión a decibelios: 10·log10(potencia); nulos y no positivos quedan sin dato.",
                   "Sin filtro, sin umbral y sin clasificación: es la señal de una fecha, no un cambio."],
        "salida": ruta.name, "huella_sha256": sha256_archivo(ruta),
        "estadisticas_db": {"pixeles_validos": int(validos.size),
                            "percentiles": {str(q): round(float(np.percentile(validos, q)), 3) for q in (2, 25, 50, 75, 98)}},
        "limitaciones": [*LIMITACIONES_BANDA_L, "Una sola fecha: no muestra ningún cambio."],
    }
    (carpeta / f"{base}_analisis.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    with rasterio.open(ruta) as src:            # comprobación inmediata de lo escrito
        if src.nodata != NODATA_DB or src.crs != recorte.crs:
            raise ErrorSAR("La escena única no se escribió con el CRS o el NoData esperados.")
    return ruta
