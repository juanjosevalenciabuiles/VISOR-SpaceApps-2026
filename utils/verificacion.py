"""Verificación integral de V.I.S.O.R.: comprobaciones, criterios, veredicto e informe.

La usa `scripts/verificar_visor.py` (Replit, Windows o GitHub Actions). Todo lo
que toca datos reales es de SOLO LECTURA: se calcula una huella de cada archivo
de data/ antes y después, y cualquier cambio es un fallo crítico.

Estados de una comprobación:
    APROBADA      cumple el criterio
    FALLIDA       no lo cumple
    ADVERTENCIA   no bloquea, pero hay que mirarlo (p. ej. datos que cambiaron
                  respecto a la referencia verificada, cambios locales en Git)
    OMITIDA       no se pudo ejecutar aquí (falta Playwright, no hay datos…)

Veredicto:
    NO APTO                 alguna FALLIDA de nivel crítico o importante
    APTO CON ADVERTENCIAS   ninguna FALLIDA bloqueante, pero hay ADVERTENCIAS
                            u OMITIDAS críticas (lo no comprobado se dice)
    APTO                    todo lo crítico e importante aprobado
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

APROBADA, FALLIDA, ADVERTENCIA, OMITIDA = "APROBADA", "FALLIDA", "ADVERTENCIA", "OMITIDA"
CRITICO, IMPORTANTE, INFORMATIVO = "crítico", "importante", "informativo"
NO_APTO, APTO_ADVERTENCIAS, APTO = "NO APTO", "APTO CON ADVERTENCIAS", "APTO"
SIMBOLO = {APROBADA: "✅", FALLIDA: "❌", ADVERTENCIA: "⚠️", OMITIDA: "⏭️"}
MAX_BYTES_HUELLA_COMPLETA = 200 * 1024 * 1024


@dataclass
class Comprobacion:
    id: str
    categoria: str
    descripcion: str
    criterio: str
    nivel: str
    estado: str
    detalle: str = ""


@dataclass
class Informe:
    inicio_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    contexto: dict = field(default_factory=dict)
    comprobaciones: list[Comprobacion] = field(default_factory=list)

    def agregar(self, id, categoria, descripcion, criterio, nivel, estado, detalle="") -> Comprobacion:
        c = Comprobacion(id, categoria, descripcion, criterio, nivel, estado, str(detalle))
        self.comprobaciones.append(c)
        return c

    def si(self, cond: bool, id, categoria, descripcion, criterio, nivel, detalle_ok="", detalle_mal="",
           estado_mal: str = FALLIDA) -> Comprobacion:
        return self.agregar(id, categoria, descripcion, criterio, nivel,
                            APROBADA if cond else estado_mal, detalle_ok if cond else detalle_mal)

    @property
    def veredicto(self) -> str:
        if any(c.estado == FALLIDA and c.nivel in (CRITICO, IMPORTANTE) for c in self.comprobaciones):
            return NO_APTO
        if any(c.estado == ADVERTENCIA or (c.estado == OMITIDA and c.nivel == CRITICO) or
               (c.estado == FALLIDA and c.nivel == INFORMATIVO) for c in self.comprobaciones):
            return APTO_ADVERTENCIAS
        return APTO

    def conteo(self) -> dict[str, int]:
        return {e: sum(c.estado == e for c in self.comprobaciones) for e in (APROBADA, FALLIDA, ADVERTENCIA, OMITIDA)}

    def a_json(self) -> str:
        return json.dumps({"inicio_utc": self.inicio_utc, "veredicto": self.veredicto, "conteo": self.conteo(),
                           "contexto": self.contexto, "comprobaciones": [asdict(c) for c in self.comprobaciones]},
                          ensure_ascii=False, indent=2)

    def a_markdown(self) -> str:
        n = self.conteo()
        lineas = [
            "# Informe de verificación · V.I.S.O.R.", "",
            f"**Veredicto: {self.veredicto}**", "",
            f"{n[APROBADA]} aprobadas · {n[FALLIDA]} fallidas · {n[ADVERTENCIA]} advertencias · {n[OMITIDA]} omitidas", "",
            "| Contexto | |", "| --- | --- |",
            *(f"| {k} | {v} |" for k, v in self.contexto.items()), "",
        ]
        problemas = [c for c in self.comprobaciones if c.estado in (FALLIDA, ADVERTENCIA)]
        if problemas:
            lineas += ["## Requiere atención", ""]
            lineas += [f"- {SIMBOLO[c.estado]} **{c.id}** ({c.nivel}) {c.descripcion}: {c.detalle}" for c in problemas]
            lineas.append("")
        omitidas = [c for c in self.comprobaciones if c.estado == OMITIDA]
        if omitidas:
            lineas += ["## No comprobado en esta ejecución", ""]
            lineas += [f"- **{c.id}** {c.descripcion}: {c.detalle}" for c in omitidas]
            lineas.append("")
        lineas += ["## Todas las comprobaciones", "",
                   "| | Id | Categoría | Comprobación | Criterio de aprobación | Nivel | Detalle |",
                   "| --- | --- | --- | --- | --- | --- | --- |"]
        for c in self.comprobaciones:
            detalle = c.detalle.replace("|", "\\|").replace("\n", " ")[:300]
            lineas.append(f"| {SIMBOLO[c.estado]} | {c.id} | {c.categoria} | {c.descripcion} | {c.criterio} | "
                          f"{c.nivel} | {detalle} |")
        lineas += ["", "## Criterios del veredicto", "",
                   "- **NO APTO**: alguna comprobación crítica o importante falló. No actualizar Replit ni fusionar.",
                   "- **APTO CON ADVERTENCIAS**: nada bloqueante falló, pero hay advertencias o partes críticas sin "
                   "comprobar en este entorno; revisar la lista antes de integrar.",
                   "- **APTO**: todo lo crítico e importante se comprobó y aprobó.", "",
                   "Ninguna comprobación valida científicamente los resultados SAR: son indicios de cambio de "
                   "retrodispersión, no inundaciones confirmadas.", ""]
        return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Huellas de datos (solo lectura)
# ---------------------------------------------------------------------------

def huellas(carpeta: Path) -> dict[str, tuple]:
    """Tamaño, fecha de modificación y SHA-256 (si el archivo no es enorme) de cada archivo."""
    resultado = {}
    if not carpeta.is_dir():
        return resultado
    for p in sorted(carpeta.rglob("*")):
        if p.is_file():
            s = p.stat()
            sha = None
            if s.st_size <= MAX_BYTES_HUELLA_COMPLETA:
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for bloque in iter(lambda: f.read(1 << 20), b""):
                        h.update(bloque)
                sha = h.hexdigest()
            resultado[p.relative_to(carpeta).as_posix()] = (s.st_size, s.st_mtime_ns, sha)
    return resultado


def diferencias_huellas(antes: dict, despues: dict) -> list[str]:
    cambios = [f"modificado: {k}" for k in antes if k in despues and antes[k] != despues[k]]
    cambios += [f"eliminado: {k}" for k in antes if k not in despues]
    cambios += [f"nuevo: {k}" for k in despues if k not in antes]
    return cambios


# ---------------------------------------------------------------------------
# Datos reales de data/analisis/
# ---------------------------------------------------------------------------

def auditar_resultados(informe: Informe, carpeta: Path, referencia: dict | None) -> None:
    """Comprobaciones de solo lectura de cada GeoTIFF de resultados y de la referencia de Chigorodó."""
    from utils import procedencia
    from utils.auditoria import auditar
    from utils.combinacion_sar import umbrales_por_polarizacion
    from utils.qgis import ErrorExportacion, exportar, verificar_paquete
    from utils.resultados import leer_resultado, listar

    cat = "Datos reales"
    archivos = listar(carpeta)
    if not archivos:
        informe.agregar("DAT-00", cat, "Resultados en data/analisis/", "Hay al menos un GeoTIFF", INFORMATIVO,
                        OMITIDA, f"No hay GeoTIFF en {carpeta}")
        return
    ref = (referencia or {}).get("productos", {})
    cuadricula = (referencia or {}).get("cuadricula", {})
    for i, ruta in enumerate(archivos, 1):
        pre = f"DAT-{i:02d}"
        res = leer_resultado(ruta)
        informe.si(res.dibujable, f"{pre}a", cat, f"{ruta.name}: se carga y se reconoce su perfil",
                   "El visor lo puede dibujar", IMPORTANTE, res.nombre if res.dibujable else "",
                   res.error or "no dibujable",
                   estado_mal=ADVERTENCIA if res.error and "no reconocido" in res.error else FALLIDA)
        if not res.dibujable:
            continue
        if res.perfil.continuo:
            _auditar_continuo(informe, pre, ruta, res)
            continue
        a = auditar(ruta)
        e = a["clases"]
        otros = e.get("pixeles_otros_valores", 0)
        suma = sum(c["pixeles"] for c in e["clases"].values()) + otros
        informe.si(suma == e["pixeles_validos"] and a["archivo"]["nodata"] is not None,
                   f"{pre}b", cat, f"{ruta.name}: clases y NoData coherentes",
                   "Σ clases = píxeles válidos y NoData declarado", CRITICO,
                   f"{a['archivo']['crs']} · {a['archivo']['ancho']}×{a['archivo']['alto']} · válidos "
                   f"{e['pixeles_validos']} · NoData {e['pixeles_sin_dato']}",
                   f"Σ={suma} vs válidos={e['pixeles_validos']}, NoData={a['archivo']['nodata']}")
        if otros:
            informe.agregar(f"{pre}c", cat, f"{ruta.name}: valores fuera del perfil", "0 píxeles", IMPORTANTE,
                            ADVERTENCIA, f"{otros} píxeles")
        area = e.get("area_pixel_ha")
        if area:
            ok = all(c["area_ha"] is not None and abs(c["area_ha"] - c["pixeles"] * area) < 0.01
                     for c in e["clases"].values())
            informe.si(ok, f"{pre}d", cat, f"{ruta.name}: superficies", "ha = píxeles × área del píxel",
                       CRITICO, f"píxel de {area:.4f} ha", "hectáreas inconsistentes")

        # Procedencia: la ficha, si existe, debe corresponder al archivo.
        f = a["ficha"]
        if f.get("presente"):
            informe.si(f.get("sha256_coincide", False), f"{pre}e", "Procedencia",
                       f"{ruta.name}: SHA-256 del GeoTIFF = el de su ficha", "Coinciden", CRITICO,
                       f"estado efectivo {f['estado_efectivo']}",
                       f"{f.get('motivo')} (estado efectivo {f['estado_efectivo']})")
        else:
            informe.agregar(f"{pre}e", "Procedencia", f"{ruta.name}: ficha de procedencia",
                            "Sin ficha → PROCEDENCIA NO DECLARADA", INFORMATIVO,
                            APROBADA if f["estado_efectivo"] == procedencia.NO_DECLARADA else FALLIDA,
                            f"sin ficha · estado {f['estado_efectivo']}")

        # QGIS: paquete en memoria; la fuente no se toca (huella antes = después).
        antes = procedencia.sha256_archivo(ruta)
        try:
            _, zip_bytes = exportar(ruta, res.perfil.clases, res.nombre)
            problemas = verificar_paquete(zip_bytes, ruta, res.perfil.clases)
        except ErrorExportacion as err:
            problemas = [str(err)]
        problemas += [] if procedencia.sha256_archivo(ruta) == antes else ["la exportación modificó el original"]
        informe.si(not problemas, f"{pre}f", "QGIS", f"{ruta.name}: paquete QGIS",
                   "GeoTIFF idéntico, manifiesto y .qml correctos", IMPORTANTE, "correcto", "; ".join(problemas))

        # Referencia verificada por el equipo (si el archivo es uno de los conocidos).
        esperado = ref.get(ruta.name)
        if esperado:
            reales = {k: e["clases"][k]["pixeles"] for k in esperado["clases"]}
            geom = (a["archivo"]["crs"], a["archivo"]["ancho"], a["archivo"]["alto"], int(a["archivo"]["nodata"]),
                    e["pixeles_sin_dato"])
            geom_ref = (cuadricula.get("crs"), cuadricula.get("ancho"), cuadricula.get("alto"),
                        cuadricula.get("nodata"), cuadricula.get("pixeles_sin_dato"))
            informe.si(reales == esperado["clases"] and geom == geom_ref, f"{pre}g", "Referencia",
                       f"{ruta.name}: igual a lo verificado el 12-nov", "Clases, CRS, tamaño y NoData sin cambios",
                       IMPORTANTE, "sin cambios",
                       f"esperado {esperado['clases']} {geom_ref}, encontrado {reales} {geom}", estado_mal=ADVERTENCIA)
            informe.si(f["estado_efectivo"] == esperado["procedencia"], f"{pre}h", "Procedencia",
                       f"{ruta.name}: estado de procedencia esperado", esperado["procedencia"], IMPORTANTE,
                       f["estado_efectivo"], f"encontrado {f['estado_efectivo']}: {f.get('motivo')}",
                       estado_mal=ADVERTENCIA)
            if "umbrales_db" in esperado:
                umbrales = umbrales_por_polarizacion(res.ficha)
                informe.si(umbrales == esperado["umbrales_db"], f"{pre}i", "Procedencia",
                           f"{ruta.name}: umbrales declarados en la ficha", str(esperado["umbrales_db"]),
                           IMPORTANTE, str(umbrales), f"encontrado {umbrales}", estado_mal=ADVERTENCIA)

    comp = (referencia or {}).get("comparacion")
    if comp:
        a_ruta, b_ruta = carpeta / comp["a"], carpeta / comp["b"]
        if a_ruta.is_file() and b_ruta.is_file():
            c = auditar(a_ruta, comparar=b_ruta)["comparacion"]
            informe.si(c.get("misma_cuadricula") and not c.get("equivalentes")
                       and c.get("pixeles_distintos") == comp["pixeles_distintos"],
                       "DAT-CMP", "Referencia", f"Diferencia documentada entre {comp['a']} y {comp['b']}",
                       f"NO equivalentes, {comp['pixeles_distintos']} píxeles distintos (configuraciones "
                       "distintas; no se exige equivalencia)", IMPORTANTE,
                       f"{c.get('pixeles_distintos')} píxeles distintos, como se documentó",
                       f"misma cuadrícula={c.get('misma_cuadricula')}, equivalentes={c.get('equivalentes')}, "
                       f"distintos={c.get('pixeles_distintos')}", estado_mal=ADVERTENCIA)
        else:
            informe.agregar("DAT-CMP", "Referencia", "Diferencia documentada entre los dos productos VV/VH",
                            f"{comp['pixeles_distintos']} píxeles distintos", INFORMATIVO, OMITIDA,
                            "Falta alguno de los dos archivos en data/analisis/")


def _auditar_continuo(informe: Informe, pre: str, ruta: Path, res) -> None:
    """Diferencia en dB: unidades, NoData, distribución finita y coherente, ficha y paquete QGIS."""
    from utils import procedencia
    from utils.auditoria import ficha_de
    from utils.qgis import ErrorExportacion, exportar, verificar_paquete

    cat = "Datos reales"
    e = res.estadisticas or {}
    tags = res.capa.metadatos
    finito = all(isinstance(e.get(k), float) and e.get(k) == e.get(k) for k in ("minimo", "mediana", "maximo"))
    ok = (tags.get("UNIDADES", "").lower() == "db" and e.get("nodata") is not None and finito
          and e["pixeles_validos"] + e["pixeles_sin_dato"] == e["pixeles_totales"] and e["pixeles_validos"] > 0)
    informe.si(ok, f"{pre}b", cat, f"{ruta.name}: diferencia continua en dB coherente",
               "Unidades dB, NoData declarado, válidos + NoData = total, estadísticas finitas", CRITICO,
               f"{res.capa.crs_original} · {res.capa.forma_original[1]}×{res.capa.forma_original[0]} · Δ de "
               f"{e.get('minimo', float('nan')):+.2f} a {e.get('maximo', float('nan')):+.2f} dB, mediana "
               f"{e.get('mediana', float('nan')):+.2f} · NoData {e.get('pixeles_sin_dato')} px",
               f"unidades={tags.get('UNIDADES')}, nodata={e.get('nodata')}, estadísticas={e}")
    sha = procedencia.sha256_archivo(ruta)
    f = ficha_de(ruta, sha, tags.get("VISOR_DEMO") == "1")
    if f.get("presente") and f.get("sha256_en_ficha"):
        informe.si(f["sha256_coincide"], f"{pre}e", "Procedencia", f"{ruta.name}: SHA-256 = el de su ficha",
                   "Coinciden", CRITICO, f["estado_efectivo"], f.get("motivo", ""))
    else:
        informe.agregar(f"{pre}e", "Procedencia", f"{ruta.name}: ficha de procedencia",
                        "Sin ficha completa → PROCEDENCIA NO DECLARADA", INFORMATIVO,
                        APROBADA if f["estado_efectivo"] == procedencia.NO_DECLARADA else FALLIDA,
                        f"estado {f['estado_efectivo']} (el motor no escribe ficha para este producto)")
    try:
        _, zip_bytes = exportar(ruta, (), res.nombre, continuo=True)
        problemas = verificar_paquete(zip_bytes, ruta, (), continuo=True)
    except ErrorExportacion as err:
        problemas = [str(err)]
    problemas += [] if procedencia.sha256_archivo(ruta) == sha else ["la exportación modificó el original"]
    informe.si(not problemas, f"{pre}f", "QGIS", f"{ruta.name}: paquete QGIS (pseudocolor dB)",
               "GeoTIFF idéntico, manifiesto y .qml correctos", IMPORTANTE, "correcto", "; ".join(problemas))


def leer_referencia(ruta: Path) -> dict | None:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
