"""Auditoría de solo lectura de GeoTIFF de clases SAR (compatible con la revisión en QGIS).

Integra en el repositorio las comprobaciones del paquete auxiliar
`visor_qa_geotiff.py` (paquete QGIS QA del 12-nov-2026), reutilizando las
funciones ya probadas de `utils/combinacion_sar.py`, y añade lo que ese
paquete dejaba aparte: cotejar la huella SHA-256 del GeoTIFF con su ficha
de procedencia (`utils/procedencia.evaluar`).

Comprobaciones:
    archivo      CRS, dimensiones, resolución, tipo, NoData, SHA-256, etiquetas
    clases       conteos, % de válidos, hectáreas, códigos fuera del perfil
    ficha        existe, estado declarado y estado efectivo (con su motivo)
    comparación  otra versión: misma cuadrícula, píxeles distintos y matriz
                 de transiciones «clase A → clase B»
    reconstrucción  desde las máscaras VV y VH (clase 1 = disminución)

Nada de esto escribe sobre los archivos auditados. La igualdad de píxeles
no demuestra validez científica: ninguna clase confirma una inundación.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import RasterioError

from utils import procedencia
from utils.analisis_sar import ErrorSAR
from utils.combinacion_sar import CLASES_COINCIDENCIA, clasificar, describir_clases

ADVERTENCIA = ("Auditoría técnica de archivos. Coincidir píxel a píxel no demuestra validez científica; "
               "ninguna clase confirma una inundación ni otro fenómeno ambiental.")


def _leer(ruta: Path) -> tuple[np.ndarray, dict]:
    try:
        with rasterio.open(ruta) as src:
            if src.count != 1:
                raise ErrorSAR(f"`{ruta.name}` tiene {src.count} bandas; se esperaba una.")
            datos = src.read(1)
            meta = {
                "archivo": ruta.name, "sha256": procedencia.sha256_archivo(ruta),
                "crs": src.crs.to_string() if src.crs else None, "ancho": src.width, "alto": src.height,
                "resolucion": [abs(src.transform.a), abs(src.transform.e)], "tipo": src.dtypes[0],
                "nodata": src.nodata, "transform": list(src.transform)[:6], "etiquetas": src.tags(),
            }
    except ErrorSAR:
        raise
    except (RasterioError, OSError, ValueError) as e:
        raise ErrorSAR(f"`{ruta.name}` no es un GeoTIFF válido o está dañado.") from e
    return datos, meta


def _misma_cuadricula(a: dict, b: dict) -> bool:
    return (a["crs"] == b["crs"] and (a["ancho"], a["alto"]) == (b["ancho"], b["alto"])
            and np.allclose(a["transform"], b["transform"], rtol=0, atol=1e-9))


def _sin_dato(datos: np.ndarray, meta: dict) -> np.ndarray:
    return np.zeros(datos.shape, bool) if meta["nodata"] is None else datos == meta["nodata"]


def transiciones(a: np.ndarray, b: np.ndarray, sin_dato: np.ndarray) -> dict[str, int]:
    """Cuántos píxeles válidos en ambos pasan de la clase x (en a) a la y (en b)."""
    validos = ~sin_dato
    pares, cuentas = np.unique(np.stack([a[validos], b[validos]]), axis=1, return_counts=True)
    return {f"{int(x)}->{int(y)}": int(n) for (x, y), n in zip(pares.T, cuentas, strict=True)}


def ficha_de(ruta: Path, sha256: str, es_demo: bool) -> dict:
    lateral = ruta.with_suffix(".json")
    if not lateral.is_file():
        estado = procedencia.evaluar(es_demo, None)
        return {"presente": False, "estado_efectivo": estado.estado, "motivo": estado.motivo}
    try:
        ficha = json.loads(lateral.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"presente": True, "legible": False, "estado_efectivo": procedencia.NO_DECLARADA,
                "motivo": "La ficha no se pudo leer."}
    bloque = ficha.get("procedencia") if isinstance(ficha, dict) else None
    estado = procedencia.evaluar(es_demo, ficha if isinstance(ficha, dict) else None, sha256)
    esperado = (bloque or {}).get("archivo", {}).get("sha256") if isinstance(bloque, dict) else None
    return {
        "presente": True, "legible": True, "archivo": lateral.name,
        "estado_declarado": (bloque or {}).get("estado") if isinstance(bloque, dict) else None,
        "estado_efectivo": estado.estado, "motivo": estado.motivo, "faltantes": list(estado.faltantes),
        "sha256_en_ficha": esperado, "sha256_coincide": (esperado or "").lower() == sha256.lower(),
        "parametros": ficha.get("parametros") if isinstance(ficha, dict) else None,
    }


def auditar(ruta: str | Path, comparar: str | Path | None = None,
            vv: str | Path | None = None, vh: str | Path | None = None) -> dict:
    """Informe completo (diccionario serializable a JSON)."""
    ruta = Path(ruta)
    datos, meta = _leer(ruta)
    informe = {
        "auditoria_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "archivo": meta,
        "clases": describir_clases(ruta, CLASES_COINCIDENCIA),
        "ficha": ficha_de(ruta, meta["sha256"], meta["etiquetas"].get("VISOR_DEMO") == "1"),
        "advertencia": ADVERTENCIA,
    }
    avisos = []
    if meta["nodata"] is None:
        avisos.append("El GeoTIFF no declara NoData: QGIS pintará como dato cualquier valor de relleno.")
    if informe["clases"].get("pixeles_otros_valores"):
        avisos.append("Hay valores fuera de las clases 0–3 y del NoData.")

    if comparar is not None:
        otro, meta_otro = _leer(Path(comparar))
        if not _misma_cuadricula(meta, meta_otro):
            informe["comparacion"] = {"archivo": meta_otro["archivo"], "misma_cuadricula": False,
                                      "aviso": "CRS, tamaño o transformación distintos: no se comparan píxeles."}
        else:
            sin = _sin_dato(datos, meta) | _sin_dato(otro, meta_otro)
            distintos = int(((datos != otro) & ~sin).sum())
            informe["comparacion"] = {
                "archivo": meta_otro["archivo"], "sha256": meta_otro["sha256"], "misma_cuadricula": True,
                "validos_en_ambos": int((~sin).sum()), "pixeles_distintos": distintos,
                "nodata_distinto": int((_sin_dato(datos, meta) != _sin_dato(otro, meta_otro)).sum()),
                "equivalentes": distintos == 0 and bool((_sin_dato(datos, meta) == _sin_dato(otro, meta_otro)).all()),
                "transiciones": transiciones(datos, otro, sin),
            }

    if (vv is None) != (vh is None):
        raise ErrorSAR("Para reconstruir se necesitan las dos máscaras: VV y VH.")
    if vv is not None:
        mvv, meta_vv = _leer(Path(vv))
        mvh, meta_vh = _leer(Path(vh))
        if not (_misma_cuadricula(meta, meta_vv) and _misma_cuadricula(meta, meta_vh)):
            informe["reconstruccion"] = {"misma_cuadricula": False,
                                         "aviso": "Las máscaras no comparten la cuadrícula del producto."}
        else:
            esperado = clasificar(mvv, mvh)
            informe["reconstruccion"] = {
                "misma_cuadricula": True, "vv": meta_vv["archivo"], "vh": meta_vh["archivo"],
                "pixeles_distintos": int((esperado != datos).sum()),
                "reproduce_el_producto": bool((esperado == datos).all()),
                "parametros_vv": meta_vv["etiquetas"].get("PARAMETROS"),
                "parametros_vh": meta_vh["etiquetas"].get("PARAMETROS"),
            }
    informe["avisos"] = avisos
    return informe
