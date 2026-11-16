"""Procesamiento por ventanas de cambio GCOV NISAR L; no detecta inundaciones."""
from __future__ import annotations

import json
import math
import tempfile
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import transform as window_transform

from utils.procedencia import sha256_archivo


class QAInsuficiente(ValueError):
    """No publicar un producto sin QA suficiente."""


def _validar(a: dict, b: dict) -> None:
    campos = ("sensor", "banda", "orbita", "stack", "madurez", "polarizacion",
              "observed_at", "granule", "cog", "qa_mask", "looks")
    if any(not e.get(k) and e.get(k) != 0 for e in (a, b) for k in campos):
        raise QAInsuficiente("SIN_QA: metadatos, máscaras o looks faltantes")
    for k in ("sensor", "banda", "orbita", "stack", "madurez", "polarizacion"):
        if a[k] != b[k]:
            raise QAInsuficiente(f"SIN_PAR: incompatibilidad {k}")
    if (a["sensor"], a["banda"]) != ("NISAR", "L"):
        raise QAInsuficiente("SIN_PAR: solo NISAR L GCOV")
    if a["polarizacion"] not in ("HHHH", "HVHV", "VVVV", "VHVH"):
        raise QAInsuficiente("SIN_QA: polarización gamma0 desconocida")
    if str(a["madurez"]).upper() not in ("VALIDATED", "PROVISIONAL"):
        raise QAInsuficiente("SIN_QA: madurez sin control")
    try:
        f1 = datetime.fromisoformat(str(a["observed_at"]).replace("Z", "+00:00"))
        f2 = datetime.fromisoformat(str(b["observed_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise QAInsuficiente("SIN_QA: fechas inválidas") from exc
    if f1 >= f2 or a["granule"] == b["granule"]:
        raise QAInsuficiente("SIN_PAR: fechas pre/post o adquisiciones inválidas")


def procesar_par(antes: dict, despues: dict, destino: str | Path, *,
                 minimo_looks: float = 1.0, minimo_validos: int = 1,
                 aoi: tuple[float, float, float, float] | None = None) -> dict:
    """GeoTIFF ΔdB=10log10(post/pre) y ficha; máscara QA 1=apto, resto inválido.

    Exige gamma0 lineal, máscaras QA y looks efectivos por fecha, ya verificados
    externamente. No infiere QA de huellas de catálogo. No remuestrea.
    """
    _validar(antes, despues)
    if not math.isfinite(minimo_looks) or minimo_looks <= 0 or minimo_validos < 1:
        raise ValueError("Umbrales QA inválidos")
    destino = Path(destino)
    ficha_ruta = destino.with_suffix(".json")
    if destino.exists() or ficha_ruta.exists():
        raise FileExistsError("No sobrescribir productos existentes")
    if not destino.parent.is_dir():
        raise FileNotFoundError("Carpeta de destino inexistente")
    entradas = [Path(e[k]) for e in (antes, despues) for k in ("cog", "qa_mask", "looks")]
    if len({str(p.resolve()) for p in entradas}) != 6:
        raise QAInsuficiente("SIN_QA: rutas duplicadas")
    with ExitStack() as stack:
        rasters = [stack.enter_context(rasterio.open(p)) for p in entradas]
        base = rasters[0]
        if (base.crs is None or not base.crs.is_projected or any(
                r.crs != base.crs or r.transform != base.transform
                or r.width != base.width or r.height != base.height or r.count != 1
                for r in rasters)):
            raise QAInsuficiente("SIN_QA: cuadrículas no compatibles")
        if any(not rasters[i].dtypes[0].startswith("float") for i in (0, 2, 3, 5)):
            raise QAInsuficiente("SIN_QA: gamma0/looks deben ser flotantes")
        if any(rasters[i].dtypes[0] not in ("uint8", "uint16", "int16", "int32")
               for i in (1, 4)):
            raise QAInsuficiente("SIN_QA: máscara QA debe ser entera")
        aoi_proyectado = None
        if aoi is not None:
            try:
                o, s, e, n = map(float, aoi)
                if not (-180 <= o < e <= 180 and -90 <= s < n <= 90):
                    raise ValueError("bounds")
                aoi_proyectado = transform_geom(
                    "EPSG:4326", base.crs,
                    {"type": "Polygon", "coordinates": [
                        [[o, s], [e, s], [e, n], [o, n], [o, s]]
                    ]},
                )
            except (ValueError, TypeError, rasterio.errors.RasterioError) as exc:
                raise QAInsuficiente("SIN_QA: AOI inválido para medir píxeles válidos") from exc
        profile = base.profile.copy()
        profile.update(driver="GTiff", dtype="float32", count=1, nodata=-9999.0,
                       compress="deflate", predictor=3,
                       tiled=base.width >= 16 and base.height >= 16)
        with tempfile.TemporaryDirectory(dir=destino.parent, prefix=".visor-qa-") as td:
            temporal = Path(td) / "delta.tif"
            validos = 0
            pixeles_aoi = 0
            validos_aoi = 0
            with rasterio.open(temporal, "w", **profile) as salida:
                for _, ventana in base.block_windows(1):
                    pre, qpre, lpre, post, qpost, lpost = [
                        r.read(1, window=ventana, masked=True) for r in rasters]
                    valido = np.ones(pre.shape, dtype=bool)
                    for arr in (pre, qpre, lpre, post, qpost, lpost):
                        valido &= ~np.ma.getmaskarray(arr)
                        valido &= np.isfinite(arr.data)
                    valido &= (pre.data > 0) & (post.data > 0)
                    # Máscara NISAR GCOV: 0=inválido, 255=fuera de radar,
                    # 1..254=identificador de subfranja válida (ISCE3).
                    valido &= (qpre.data >= 1) & (qpre.data < 255)
                    valido &= (qpost.data >= 1) & (qpost.data < 255)
                    valido &= (lpre.data >= minimo_looks) & (lpost.data >= minimo_looks)
                    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                        calc = 10 * (np.log10(post.data.astype(np.float64))
                                     - np.log10(pre.data.astype(np.float64)))
                    valido &= np.isfinite(calc)
                    validos += int(valido.sum())
                    if aoi_proyectado is not None:
                        dentro = geometry_mask(
                            [aoi_proyectado], out_shape=pre.shape,
                            transform=window_transform(ventana, base.transform),
                            invert=True,
                        )
                        pixeles_aoi += int(dentro.sum())
                        validos_aoi += int((valido & dentro).sum())
                    delta = np.full(pre.shape, -9999.0, dtype=np.float32)
                    delta[valido] = calc[valido].astype(np.float32)
                    salida.write(delta, 1, window=ventana)
            if validos < minimo_validos:
                raise QAInsuficiente("SIN_QA: sin píxeles aptos")
            if aoi_proyectado is not None and (
                pixeles_aoi == 0 or validos_aoi < minimo_validos
            ):
                raise QAInsuficiente(
                    "SIN_QA: las escenas no tienen píxeles válidos simultáneos dentro del AOI"
                )
            sha = sha256_archivo(temporal)
            ficha = {
                "esquema": "visor.ficha.v1", "tipo_producto": "diferencia_db",
                "titulo": "Cambio de retrodispersión NISAR L (dB), no inundación",
                "procedencia": {
                    "estado": "real_sin_validar", "sensor": "NISAR",
                    "fechas": [antes["observed_at"], despues["observed_at"]],
                    "polarizaciones": [antes["polarizacion"]],
                    "metodo": "10log10(gamma0_post/gamma0_pre), QA=1 y looks; sin remuestreo",
                    "entradas": [{
                        "granule": e["granule"], "madurez": e["madurez"],
                        "cog_sha256": sha256_archivo(e["cog"]),
                        "qa_sha256": sha256_archivo(e["qa_mask"]),
                        "looks_sha256": sha256_archivo(e["looks"]),
                    } for e in (antes, despues)],
                    "generado_por": "VISOR V9 IA1 cambio_cog",
                    "archivo": {"sha256": sha},
                },
                "qa": {
                    "pixeles_validos": validos, "minimo_looks": minimo_looks,
                    "minimo_validos": minimo_validos, "mascara": "1..254=apto",
                    # Solo cuenta píxeles dentro de la AOI solicitada. Las áreas
                    # fuera o sin datos no se convierten en inundaciones.
                    "pixeles_en_aoi": pixeles_aoi if aoi_proyectado is not None else None,
                    "pixeles_validos_en_aoi": validos_aoi if aoi_proyectado is not None else None,
                    "cobertura_qa_aoi_fraccion": (
                        round(validos_aoi / pixeles_aoi, 6)
                        if aoi_proyectado is not None and pixeles_aoi else None
                    ),
                },
                "advertencias": ["Cambio SAR exploratorio; NO mapa de inundación.",
                                 "No hay verificación independiente ni clasificación de agua."],
                "creado_utc": datetime.now(timezone.utc).isoformat(),
            }
            temporal.replace(destino)
            try:
                with ficha_ruta.open("x", encoding="utf-8") as f:
                    json.dump(ficha, f, ensure_ascii=False, indent=2)
            except Exception:
                destino.unlink(missing_ok=True)
                raise
    return {"estado": "CAMBIO_DB_EXPLORATORIO", "raster": str(destino),
            "ficha": str(ficha_ruta), "pixeles_validos": validos,
            "pixeles_aoi": pixeles_aoi if aoi_proyectado is not None else None,
            "cobertura_qa_aoi_fraccion": (
                round(validos_aoi / pixeles_aoi, 6)
                if aoi_proyectado is not None and pixeles_aoi else None
            ),
            "sha256": sha, "advertencia": "No representa inundación confirmada"}
