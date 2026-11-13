"""Cobertura de un AOI regional por escenas Sentinel-1: pasadas, pares y huecos.

Un AOI grande (p. ej. Chigorodó–Carepa–Apartadó–Turbo) casi nunca cabe en una
sola escena. Este módulo responde, SOLO con metadatos del catálogo:

- qué fracción del polígono (no de su recuadro) cubre cada escena;
- qué escenas pertenecen a la misma pasada del satélite (misma plataforma y
  órbita absoluta: cuadros consecutivos) y, por tanto, podrían formar un
  mosaico válido de una fecha;
- qué pares de pasadas son comparables (misma órbita relativa y dirección,
  polarización común) y cuánto del AOI y de cada municipio cubren LAS DOS;
- dónde quedan huecos.

No se combinan órbitas relativas distintas: miran el terreno con otra
geometría y su retrodispersión no es comparable sin una metodología
explícita. Si ninguna órbita cubre todo el AOI, se dice; no se rellena.

Nada de aquí descarga ni procesa: una cobertura de catálogo no garantiza que
exista el RTC. Los pares son siempre «sin validar».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from utils import buscador_sar as bus
from utils.buscador_sar import Escena
from utils.regiones import AOI

COBERTURA_COMPLETA = 0.999
MAX_SEGUNDOS_ENTRE_CUADROS = 90        # cuadros consecutivos de una pasada IW (~25 s cada uno)


def fraccion(huella: BaseGeometry | None, zona: BaseGeometry) -> float:
    """Fracción de `zona` cubierta por `huella` (0–1), en grados: suficiente para áreas regionales."""
    if huella is None or zona.is_empty or not zona.area:
        return 0.0
    return float(min(1.0, huella.intersection(zona).area / zona.area))


@dataclass
class Pasada:
    """Cuadros consecutivos de un mismo paso del satélite: candidatos a un mosaico de una fecha."""
    escenas: list[Escena]
    huella: BaseGeometry = field(repr=False)
    cobertura: float                              # fracción del AOI
    cobertura_zonas: dict[str, float]

    @property
    def plataforma(self) -> str:
        return self.escenas[0].plataforma

    @property
    def orbita_relativa(self) -> int:
        return self.escenas[0].orbita_relativa

    @property
    def direccion(self) -> str:
        return self.escenas[0].direccion

    @property
    def inicio(self):
        return self.escenas[0].inicio

    @property
    def polarizaciones(self) -> tuple[str, ...]:
        comunes = set(self.escenas[0].polarizaciones)
        for e in self.escenas[1:]:
            comunes &= set(e.polarizaciones)
        return tuple(p for p in self.escenas[0].polarizaciones if p in comunes)

    @property
    def tamano_bytes(self) -> int | None:
        tamanos = [e.tamano_bytes for e in self.escenas]
        return sum(tamanos) if all(t is not None for t in tamanos) else None

    def resumen(self) -> dict:
        return {"fecha_utc": self.inicio.isoformat(), "plataforma": self.plataforma,
                "orbita_relativa": self.orbita_relativa, "direccion": self.direccion,
                "polarizaciones": list(self.polarizaciones), "escenas": [e.nombre for e in self.escenas],
                "cobertura_aoi": round(self.cobertura, 4),
                "cobertura_zonas": {k: round(v, 4) for k, v in self.cobertura_zonas.items()},
                "tamano_bytes": self.tamano_bytes}


@dataclass
class ParPasadas:
    antes: Pasada
    despues: Pasada
    dias: float
    polarizaciones: tuple[str, ...]
    cobertura_comun: float                        # fracción del AOI cubierta por LAS DOS fechas
    cobertura_zonas: dict[str, float]
    avisos: list[str]
    estado: str = "Compatible (sin validar)"

    @property
    def completo(self) -> bool:
        return self.cobertura_comun >= COBERTURA_COMPLETA

    def resumen(self) -> dict:
        return {"estado": self.estado, "antes": self.antes.resumen(), "despues": self.despues.resumen(),
                "dias": round(self.dias, 2), "polarizaciones": list(self.polarizaciones),
                "cobertura_comun_aoi": round(self.cobertura_comun, 4),
                "cobertura_comun_zonas": {k: round(v, 4) for k, v in self.cobertura_zonas.items()},
                "requiere_mosaico": len(self.antes.escenas) > 1 or len(self.despues.escenas) > 1,
                "avisos": self.avisos}


@dataclass
class CoberturaRegional:
    aoi: AOI
    escenas: list[tuple[Escena, float]]           # (escena, fracción del AOI)
    pasadas: list[Pasada]
    pares: list[ParPasadas]
    orbitas: dict[tuple[int, str], float]         # mejor cobertura de una pasada por órbita y dirección
    avisos: list[str]

    @property
    def mejor_par(self) -> ParPasadas | None:
        return self.pares[0] if self.pares else None

    def resumen(self) -> dict:
        return {"aoi": self.aoi.resumen(),
                "escenas": [{"nombre": e.nombre, "cobertura_aoi": round(c, 4)} for e, c in self.escenas],
                "pasadas": [p.resumen() for p in self.pasadas],
                "pares": [p.resumen() for p in self.pares],
                "mejor_cobertura_por_orbita": [{"orbita_relativa": o, "direccion": d, "cobertura_aoi": round(c, 4)}
                                               for (o, d), c in sorted(self.orbitas.items())],
                "avisos": self.avisos,
                "nota": "Solo metadatos del catálogo: no garantiza que existan los RTC ni valida ningún par."}


def agrupar_pasadas(escenas: list[Escena], aoi: AOI) -> list[Pasada]:
    """Agrupa cuadros de la misma plataforma y órbita absoluta, contiguos en el tiempo."""
    actual: dict[tuple, list[Escena]] = {}
    grupos: list[list[Escena]] = []
    for e in sorted(escenas, key=lambda e: e.inicio):
        clave = (e.plataforma, e.orbita_absoluta, e.orbita_relativa, e.direccion)
        lista = actual.get(clave)
        # Misma órbita absoluta pero no contiguos en el tiempo: no se asume un mosaico continuo.
        if lista is None or (e.inicio - lista[-1].fin).total_seconds() > MAX_SEGUNDOS_ENTRE_CUADROS:
            lista = actual[clave] = []
            grupos.append(lista)
        lista.append(e)
    pasadas = []
    for lista in grupos:
        union = unary_union([e.huella for e in lista])
        pasadas.append(Pasada(lista, union, fraccion(union, aoi.geometria),
                              {z.codigo: fraccion(union, z.geometria) for z in aoi.zonas}))
    return sorted(pasadas, key=lambda p: p.inicio)


def emparejar_pasadas(pasadas: list[Pasada], aoi: AOI, min_cobertura: float = 0.0) -> list[ParPasadas]:
    pares = []
    nombres = {z.codigo: z.nombre for z in aoi.zonas}
    for i, a in enumerate(pasadas):
        for b in pasadas[i + 1:]:
            if (a.orbita_relativa, a.direccion) != (b.orbita_relativa, b.direccion):
                continue
            comunes = tuple(p for p in a.polarizaciones if p in b.polarizaciones)
            dias = (b.inicio - a.inicio).total_seconds() / 86_400
            if not comunes or dias < 0.5:
                continue
            ambas = a.huella.intersection(b.huella)
            comun = fraccion(ambas, aoi.geometria)
            if comun <= min_cobertura:
                continue
            zonas = {z.codigo: fraccion(ambas, z.geometria) for z in aoi.zonas}
            avisos = []
            if comun < COBERTURA_COMPLETA:
                avisos.append(f"El par cubre el {comun:.0%} del AOI: el {1 - comun:.0%} restante queda SIN DATO "
                              "(no es «sin cambio»).")
            sin = [nombres[c] for c, f in zonas.items() if f <= 0]
            parciales = [f"{nombres[c]} {f:.0%}" for c, f in zonas.items() if 0 < f < COBERTURA_COMPLETA]
            if sin:
                avisos.append(f"Sin cobertura en: {', '.join(sin)}.")
            if parciales:
                avisos.append(f"Cobertura parcial: {', '.join(parciales)}.")
            if len(a.escenas) > 1 or len(b.escenas) > 1:
                avisos.append("Hace falta un mosaico por fecha (varios cuadros de la misma pasada).")
            if a.plataforma != b.plataforma:
                avisos.append(f"Satélites distintos ({a.plataforma} y {b.plataforma}).")
            if dias > 36:
                avisos.append(f"{dias:.0f} días entre fechas: pueden acumularse cambios ajenos al evento.")
            pares.append(ParPasadas(a, b, dias, comunes, comun, zonas, avisos))
    return sorted(pares, key=lambda p: (-round(p.cobertura_comun, 3), p.antes.plataforma != p.despues.plataforma, p.dias))


def evaluar(escenas: list[Escena], aoi: AOI) -> CoberturaRegional:
    """Cobertura del AOI por las escenas dadas (ya filtradas por el buscador)."""
    con_cobertura = sorted(((e, fraccion(e.huella, aoi.geometria)) for e in escenas),
                           key=lambda t: (t[0].inicio, t[0].nombre))
    utiles = [e for e, c in con_cobertura if c > 0]
    pasadas = agrupar_pasadas(utiles, aoi)
    pares = emparejar_pasadas(pasadas, aoi)
    orbitas: dict[tuple[int, str], float] = {}
    for p in pasadas:
        clave = (p.orbita_relativa, p.direccion)
        orbitas[clave] = max(orbitas.get(clave, 0.0), p.cobertura)
    avisos = []
    if not utiles:
        avisos.append("Ninguna escena del catálogo toca el AOI en este período.")
    elif not pares:
        avisos.append("No hay dos fechas de la misma órbita relativa y dirección sobre el AOI: sin par comparable.")
    elif not pares[0].completo:
        avisos.append(f"Ningún par cubre todo el AOI; el mejor cubre el {pares[0].cobertura_comun:.0%}. "
                      "No se combinan órbitas distintas para rellenar huecos.")
    if orbitas and max(orbitas.values()) < COBERTURA_COMPLETA and len(orbitas) > 1:
        avisos.append("El AOI cae entre varias órbitas relativas: cada una lo cubre en parte y sus geometrías "
                      "no son comparables entre sí.")
    return CoberturaRegional(aoi, con_cobertura, pasadas, pares, orbitas, avisos)


def buscar(aoi: AOI, inicio, fin, abrir=None, hoy: date | None = None,
           max_resultados: int = bus.MAX_RESULTADOS) -> tuple[bus.ResultadoBusqueda, CoberturaRegional]:
    """Consulta ASF con el recuadro del AOI (solo metadatos) y mide la cobertura sobre el polígono."""
    o, s, e, n = aoi.limites
    resultado = bus.buscar(o, s, e, n, inicio, fin, min_cobertura=0.0, max_resultados=max_resultados,
                           abrir=abrir, hoy=hoy)
    cobertura = evaluar(resultado.escenas, aoi)
    if resultado.truncado:
        cobertura.avisos.append("El catálogo devolvió el máximo de resultados: puede haber más escenas. "
                                "Reduce el período.")
    return resultado, cobertura
