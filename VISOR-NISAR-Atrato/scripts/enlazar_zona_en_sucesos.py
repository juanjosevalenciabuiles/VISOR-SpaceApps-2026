# ========================================
# enlazar_zona_en_sucesos.py
# ========================================

import os
import re
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
FASE = {"pre": ("antes", "1_antes"), "durante": ("durante", "2_durante"), "post": ("despues", "3_despues")}
fases = pd.read_csv(BASE / "metadatos" / "fases_eventos.csv").fillna("")


def enlazar(origen, destino):
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino.unlink()
    try:
        os.link(origen, destino)
    except OSError as e:
        print(f"no se pudo enlazar {destino.name}: {e}")
        return 0
    return 1


n = 0
for tif in sorted((BASE / "etiquetado_zona").glob("*/*/clases/*_clases_*.tif")):
    m = re.match(r"([AD]_T\d{3})_(\d{8})_clases_(\w+)\.tif", tif.name)
    stack, f8, variante = m.groups()
    fecha = f"{f8[:4]}-{f8[4:6]}-{f8[6:]}"
    dir_st = tif.parent.parent
    archivos = [tif, tif.with_suffix(".json"), dir_st / "figuras" / tif.with_suffix(".png").name]
    archivos += sorted((dir_st / "durante").glob(f"{stack}_{f8}_*"))
    for r in fases[fases["stack"] == stack].itertuples():
        for col, (nombre, sub) in FASE.items():
            if fecha not in [x.strip() for x in str(getattr(r, col)).split(",")]:
                continue
            carpetas = sorted((BASE / "sucesos").glob(f"{r.evento}_*"))
            if not carpetas:
                continue
            destinos = [carpetas[0] / "por_region" / stack / sub / fecha]
            destinos += sorted((carpetas[0] / "cronologico").glob(f"{fecha}_*_{stack}_{nombre}_*"))
            for d in destinos:
                for a in archivos:
                    if a.exists():
                        n += enlazar(a, d / a.name)
print(f"Enlaces creados: {n}")
