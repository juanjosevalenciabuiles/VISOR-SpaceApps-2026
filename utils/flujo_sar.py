"""Flujo de Herramientas SAR: catálogo ASF (GRD) → productos RTC locales → motor → resultados.

Conecta el buscador (`utils/buscador_sar.py`) con el motor (`utils/analisis_sar.py`)
y la combinación VV/VH (`utils/combinacion_sar.py`) sin duplicarlos:

1. El buscador encuentra escenas Sentinel-1 **GRD** y recomienda un par.
2. Aquí se buscan en `data/sar/` los productos **RTC de HyP3** que derivan de
   esas escenas. HyP3 nombra el RTC con el satélite y la hora de inicio de la
   escena de origen, así que la asociación es:
       exacta      mismo satélite y misma hora de inicio (±2 s)
       mismo día   mismo satélite y mismo día UTC: probable, hay que verificarla
   Nunca se asocia por parecido de nombre ni entre satélites distintos.
3. Con un par RTC completo por polarización se corre el motor; si salen VV y
   VH, se combinan. Las salidas van a `data/analisis/` con nombres que
   **nunca sobrescriben** archivos existentes (se añade _r2, _r3…).
4. Se guarda un registro JSON que enlaza escenas GRD del catálogo, RTC
   usados, AOI, parámetros y archivos producidos.

Este módulo NO descarga, NO llama a HyP3 y NO usa credenciales: si falta un
RTC, lo dice (la generación bajo demanda es la Fase D, ver docs/).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from utils.analisis_sar import (
    ErrorSAR, EscenaRTC, ParametrosCambio, analizar_par, describir_escena, prefijo_libre,
)
from utils.buscador_sar import ParEscenas
from utils.combinacion_sar import combinar_vv_vh
from utils.config import DATA_DIR

CARPETA_SAR = DATA_DIR / "sar"
CARPETA_ANALISIS = DATA_DIR / "analisis"
TOLERANCIA_S = 2
EXACTA, MISMO_DIA = "exacta", "mismo día"


def _utc_ingenua(fecha: datetime) -> datetime:
    return fecha.astimezone(timezone.utc).replace(tzinfo=None) if fecha.tzinfo else fecha


def rtc_locales(carpeta: Path | None = None) -> tuple[list[EscenaRTC], list[str]]:
    """RTC de HyP3 en la carpeta y avisos sobre los archivos que no se pueden asociar."""
    carpeta = CARPETA_SAR if carpeta is None else Path(carpeta)
    escenas, avisos = [], []
    if not carpeta.is_dir():
        return [], [f"No existe `{carpeta.name}/`: copia ahí los RTC (excluida de Git)."]
    for ruta in sorted(p for p in carpeta.iterdir() if p.suffix.lower() in (".tif", ".tiff")):
        try:
            e = describir_escena(ruta)
        except ErrorSAR as err:
            avisos.append(f"{ruta.name}: {err}")
            continue
        if not (e.es_hyp3 and e.fecha and e.plataforma):
            avisos.append(f"{ruta.name}: el nombre no sigue la convención de HyP3; no se puede asociar a una "
                          "escena del catálogo (se puede analizar desde la página Analisis SAR).")
            continue
        escenas.append(e)
    return escenas, avisos


def coincidencia(rtc: EscenaRTC, plataforma: str, inicio: datetime) -> str | None:
    if rtc.plataforma != plataforma or rtc.fecha is None:
        return None
    a, b = _utc_ingenua(rtc.fecha), _utc_ingenua(inicio)
    if abs((a - b).total_seconds()) <= TOLERANCIA_S:
        return EXACTA
    return MISMO_DIA if a.date() == b.date() else None


def _mejor(rtcs: list[EscenaRTC], pol: str, plataforma: str, inicio: datetime) -> tuple[EscenaRTC | None, str | None]:
    candidatos = [(coincidencia(r, plataforma, inicio), r) for r in rtcs if r.polarizacion == pol]
    for tipo in (EXACTA, MISMO_DIA):
        elegidos = [r for t, r in candidatos if t == tipo]
        if elegidos:
            return sorted(elegidos, key=lambda r: r.ruta.name)[0], tipo
    return None, None


@dataclass
class Disponibilidad:
    polarizacion: str
    antes: EscenaRTC | None
    despues: EscenaRTC | None
    tipo_antes: str | None
    tipo_despues: str | None

    @property
    def completa(self) -> bool:
        return self.antes is not None and self.despues is not None

    @property
    def verificar(self) -> bool:
        return MISMO_DIA in (self.tipo_antes, self.tipo_despues)

    def resumen(self) -> dict:
        return {"polarizacion": self.polarizacion,
                "rtc_antes": self.antes.ruta.name if self.antes else None, "asociacion_antes": self.tipo_antes,
                "rtc_despues": self.despues.ruta.name if self.despues else None,
                "asociacion_despues": self.tipo_despues}


def disponibilidad(par: ParEscenas, rtcs: list[EscenaRTC]) -> list[Disponibilidad]:
    """Para cada polarización común del par: qué RTC locales corresponden a cada fecha."""
    salida = []
    for pol in par.polarizaciones_comunes:
        a, ta = _mejor(rtcs, pol, par.antes.plataforma, par.antes.inicio)
        d, td = _mejor(rtcs, pol, par.despues.plataforma, par.despues.inicio)
        salida.append(Disponibilidad(pol, a, d, ta, td))
    return salida


@dataclass
class InformeFlujo:
    analisis: dict[str, Path] = field(default_factory=dict)     # polarización → máscara
    combinado: Path | None = None
    registro: Path | None = None
    avisos: list[str] = field(default_factory=list)

    @property
    def archivos(self) -> list[Path]:
        return [*self.analisis.values(), *([self.combinado] if self.combinado else [])]


def analizar_disponibles(
    par: ParEscenas,
    disponibles: list[Disponibilidad],
    aoi: tuple[float, float, float, float],
    umbrales: dict[str, float],
    ventana_speckle: int = 5,
    carpeta_salida: Path | None = None,
    zona: str | None = None,
) -> InformeFlujo:
    """Corre el motor en cada polarización con RTC completos y combina VV/VH si hay ambas."""
    carpeta = CARPETA_ANALISIS if carpeta_salida is None else Path(carpeta_salida)
    carpeta.mkdir(parents=True, exist_ok=True)
    completas = [d for d in disponibles if d.completa]
    if not completas:
        raise ErrorSAR("No hay ningún par RTC completo para este par de escenas: faltan productos en data/sar/.")
    informe = InformeFlujo()
    sello = f"{par.antes.inicio:%Y%m%d}_{par.despues.inicio:%Y%m%d}"
    parametros_usados = {}
    for d in completas:
        if d.verificar:
            informe.avisos.append(f"{d.polarizacion}: la asociación RTC ↔ escena es por día, no por hora exacta; "
                                  "verifica que el RTC provenga de la escena del par.")
        parametros = ParametrosCambio(umbral_disminucion_db=float(umbrales.get(d.polarizacion, 3.0)),
                                      ventana_speckle=int(ventana_speckle))
        parametros_usados[d.polarizacion] = {"umbral_disminucion_db": parametros.umbral_disminucion_db,
                                             "ventana_speckle": parametros.ventana_speckle}
        prefijo = prefijo_libre(carpeta, f"cambio_{d.polarizacion}_{sello}")
        r = analizar_par(d.antes.ruta, d.despues.ruta, carpeta, aoi=aoi, parametros=parametros, prefijo=prefijo)
        informe.analisis[d.polarizacion] = r.mascara
        informe.avisos.extend(f"{d.polarizacion}: {a}" for a in r.avisos)
    if "VV" in informe.analisis and "VH" in informe.analisis:
        c = combinar_vv_vh(informe.analisis["VV"], informe.analisis["VH"], carpeta,
                           prefijo=prefijo_libre(carpeta, f"coincidencia_VV_VH_{sello}"), zona=zona)
        informe.combinado = c.geotiff
    registro = carpeta / f"{prefijo_libre(carpeta, f'flujo_{sello}')}_registro.json"
    registro.write_text(json.dumps({
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "par_catalogo_asf": par.para_motor(),
        "rtc": [d.resumen() for d in disponibles],
        "aoi_lonlat": list(aoi),
        "parametros": parametros_usados,
        "salidas": [p.name for p in informe.archivos],
        "avisos": informe.avisos,
        "nota": "Par recomendado por el buscador: no validado científicamente. Los resultados son indicios "
                "de cambio de retrodispersión, no inundaciones confirmadas.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    informe.registro = registro
    return informe
