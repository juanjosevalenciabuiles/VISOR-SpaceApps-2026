"""QA de dos escenas Harmony sintetizadas; sin red, sin modificar data/."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from scripts.verificar_nisar_harmony_pares import ErrorAuditoria, auditar

CAPAS = ("HHHH", "mask", "numberOfLooks")
AOI = [-76.8, 7.55, -76.55, 7.8]


def _escena(raiz: Path, numero: int, *, desplazar=0):
    carpeta = raiz / "data" / "nisar" / "harmony" / f"escena_{numero}"
    carpeta.mkdir(parents=True)
    archivos = []
    bytes_ = 0
    for capa in CAPAS:
        destino = carpeta / f"{capa}.tif"
        dtype = "uint8" if capa == "mask" else "float32"
        datos = np.ones((32, 32), dtype=dtype)
        with rasterio.open(destino, "w", driver="GTiff", width=32, height=32, count=1,
                           dtype=dtype, crs="EPSG:32618",
                           transform=from_origin(310000 + desplazar, 850000, 20, 20)) as dst:
            dst.write(datos, 1)
        contenido = destino.read_bytes()
        bytes_ += len(contenido)
        archivos.append({"capa": capa, "archivo": destino.name, "bytes": len(contenido),
                         "sha256": hashlib.sha256(contenido).hexdigest()})
    meta = {"estado": "INSUMOS_GCOV_SIN_CLASIFICAR", "granule": f"GRANULE_{numero}",
            "aoi": AOI, "bytes_totales": bytes_, "archivos": archivos}
    (carpeta / "manifest.json").write_text(json.dumps(meta), encoding="utf-8")
    return {"granule": meta["granule"], "carpeta_relativa": carpeta.name,
            "bytes_totales": bytes_, "archivos": [a["archivo"] for a in archivos]}


def _reporte(raiz, escenas):
    carpeta = raiz / "data" / "nisar" / "catalogo"
    carpeta.mkdir(parents=True, exist_ok=True)
    informe = carpeta / "preparacion_test.json"
    informe.write_text(json.dumps({"estado": "NISAR_COG_PREPARADO_SIN_CLASIFICAR",
                                   "metodo": "NASA_HARMONY",
                                   "bytes_totales": sum(s["bytes_totales"] for s in escenas),
                                   "escenas": escenas}), encoding="utf-8")
    return informe


def test_par_autentico_estructural_y_sin_inundaciones(tmp_path):
    escenas = [_escena(tmp_path, 1), _escena(tmp_path, 2)]
    resultado = auditar(_reporte(tmp_path, escenas), tmp_path)
    assert resultado["fechas"] == 2 and resultado["archivos"] == 6
    assert resultado["grillas_temporales_iguales"] is True
    assert resultado["total_bytes"] == sum(s["bytes_totales"] for s in escenas)
    assert resultado["escenas"][0]["capas"]["HHHH"]["fraccion_hh_positiva_finita"] == 1.0
    assert "NO máscara QA" in resultado["advertencia"]


def test_tamper_hash_detectado(tmp_path):
    escenas = [_escena(tmp_path, 1), _escena(tmp_path, 2)]
    informe = _reporte(tmp_path, escenas)
    destino = tmp_path / "data" / "nisar" / "harmony" / "escena_2" / "mask.tif"
    with destino.open("ab") as f:
        f.write(b"X")
    with pytest.raises(ErrorAuditoria, match="SHA-256"):
        auditar(informe, tmp_path)


def test_grillas_distintas_se_reportan_no_se_confunden(tmp_path):
    escenas = [_escena(tmp_path, 1), _escena(tmp_path, 2, desplazar=20)]
    resultado = auditar(_reporte(tmp_path, escenas), tmp_path)
    assert resultado["grillas_temporales_iguales"] is False
    assert "DIFEREN" in resultado["advertencia_grillas"]


def test_no_traversal_de_cache(tmp_path):
    escenas = [_escena(tmp_path, 1), _escena(tmp_path, 2)]
    escenas[0]["carpeta_relativa"] = "../afuera"
    with pytest.raises(ErrorAuditoria, match="fuera del directorio"):
        auditar(_reporte(tmp_path, escenas), tmp_path)
