"""Estado de procedencia científica de una capa.

Cuatro estados, de menor a mayor respaldo:

    DEMO                 datos sintéticos (etiqueta VISOR_DEMO=1 dentro del GeoTIFF)
    NO DECLARADA         no hay ficha de procedencia suficiente: no se sabe de dónde sale
    REAL SIN VALIDAR     derivado de datos satelitales reales, con trazabilidad completa
    VALIDADO             además, con una verificación independiente documentada

La regla central: REAL SIN VALIDAR y VALIDADO NUNCA se asignan por defecto.
Solo los obtiene un GeoTIFF acompañado de una ficha JSON (`<nombre>.json`) que
declara el estado, trae todos los campos de trazabilidad y lleva el SHA-256 del
propio GeoTIFF, de modo que la ficha no se pueda reutilizar para otro archivo.
Cualquier carencia baja el estado a NO DECLARADA (o a REAL SIN VALIDAR si lo
que falta es la evidencia de validación) y se explica el motivo.

Este módulo no depende de Streamlit.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

DEMO = "demo"
NO_DECLARADA = "no_declarada"
REAL_SIN_VALIDAR = "real_sin_validar"
VALIDADO = "validado"
ESTADOS = (DEMO, NO_DECLARADA, REAL_SIN_VALIDAR, VALIDADO)

ETIQUETAS = {
    DEMO: "DEMO · DATOS SINTÉTICOS",
    NO_DECLARADA: "PROCEDENCIA NO DECLARADA",
    REAL_SIN_VALIDAR: "REAL SIN VALIDAR",
    VALIDADO: "VALIDADO",
}
DESCRIPCIONES = {
    DEMO: "Datos sintéticos generados para probar la interfaz. No son observaciones.",
    NO_DECLARADA: "No hay ficha de procedencia completa: no se puede afirmar de qué datos ni de qué "
                  "proceso sale la capa.",
    REAL_SIN_VALIDAR: "Producto derivado de datos satelitales reales, con trazabilidad completa. "
                      "Resultado exploratorio: nadie lo ha verificado de forma independiente.",
    VALIDADO: "Producto con trazabilidad completa y una verificación independiente documentada.",
}

ESQUEMA_FICHA = "visor.ficha.v1"
# Campos de `procedencia` sin los cuales no hay trazabilidad.
CAMPOS_TRAZABILIDAD = ("sensor", "fechas", "polarizaciones", "metodo", "entradas", "generado_por", "archivo")
# Campos de `procedencia.validacion` sin los cuales no se acepta VALIDADO.
CAMPOS_VALIDACION = ("responsable", "fecha", "metodo", "referencia")


@dataclass(frozen=True)
class Procedencia:
    estado: str
    motivo: str
    faltantes: tuple[str, ...] = ()
    declarado: str | None = None       # estado que pedía la ficha, si lo había
    avisos: tuple[str, ...] = field(default_factory=tuple)

    @property
    def etiqueta(self) -> str:
        return ETIQUETAS[self.estado]

    @property
    def descripcion(self) -> str:
        return DESCRIPCIONES[self.estado]

    @property
    def es_real(self) -> bool:
        return self.estado in (REAL_SIN_VALIDAR, VALIDADO)


def sha256_archivo(ruta: str | Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _vacio(valor) -> bool:
    return valor is None or (isinstance(valor, (str, list, tuple, dict)) and len(valor) == 0)


def evaluar(es_demo: bool, ficha: dict | None, sha256: str | None = None) -> Procedencia:
    """Estado de procedencia de un archivo.

    es_demo  marca VISOR_DEMO=1 leída del propio GeoTIFF (una ficha no puede quitarla).
    ficha    contenido del JSON lateral, o None si no existe o no se pudo leer.
    sha256   huella del GeoTIFF; necesaria para aceptar la ficha.
    """
    if es_demo:
        return Procedencia(DEMO, "El GeoTIFF lleva la marca de datos sintéticos (VISOR_DEMO=1).")
    if not isinstance(ficha, dict):
        return Procedencia(NO_DECLARADA, "No hay ficha de procedencia junto al GeoTIFF.")
    bloque = ficha.get("procedencia")
    if not isinstance(bloque, dict):
        return Procedencia(NO_DECLARADA, "La ficha JSON no tiene un bloque `procedencia`.")

    declarado = str(bloque.get("estado", "")).strip().lower() or None
    if declarado == DEMO:
        return Procedencia(DEMO, "La ficha declara datos de demostración.", declarado=declarado)
    if declarado not in (REAL_SIN_VALIDAR, VALIDADO):
        return Procedencia(NO_DECLARADA, "La ficha no declara un estado reconocido "
                           "(real_sin_validar o validado).", declarado=declarado)

    faltantes = tuple(c for c in CAMPOS_TRAZABILIDAD if _vacio(bloque.get(c)))
    if faltantes:
        return Procedencia(NO_DECLARADA, "La ficha está incompleta: faltan campos de trazabilidad.",
                           faltantes, declarado)

    archivo = bloque.get("archivo")
    esperado = archivo.get("sha256") if isinstance(archivo, dict) else None
    if not esperado:
        return Procedencia(NO_DECLARADA, "La ficha no trae el SHA-256 del GeoTIFF que describe.",
                           ("archivo.sha256",), declarado)
    if sha256 is None:
        return Procedencia(NO_DECLARADA, "No se pudo calcular la huella del GeoTIFF para cotejarla "
                           "con la ficha.", declarado=declarado)
    if str(esperado).lower() != sha256.lower():
        return Procedencia(NO_DECLARADA, "La ficha no corresponde a este archivo: el SHA-256 no coincide "
                           "(el GeoTIFF cambió o la ficha es de otro producto).", declarado=declarado)

    if declarado == VALIDADO:
        validacion = bloque.get("validacion")
        sin = tuple(f"validacion.{c}" for c in CAMPOS_VALIDACION
                    if not isinstance(validacion, dict) or _vacio(validacion.get(c)))
        if sin:
            return Procedencia(REAL_SIN_VALIDAR, "La ficha declara VALIDADO, pero no documenta la "
                               "validación; se muestra como REAL SIN VALIDAR.", sin, declarado)
        return Procedencia(VALIDADO, "Trazabilidad completa y validación documentada en la ficha.",
                           declarado=declarado)
    return Procedencia(REAL_SIN_VALIDAR, "Trazabilidad completa en la ficha; sin validación independiente.",
                       declarado=declarado)
