#!/usr/bin/env python3
"""Buscar y PREPARAR automáticamente NISAR GCOV para inundaciones (ASF/CMR).

    python scripts/nisar_auto.py --inicio 2026-10-21 --fin 2026-11-14
    python scripts/nisar_auto.py --inicio 2026-10-21 --fin 2026-11-14 --ejecutar

Sin --ejecutar: SOLO consulta y muestra plan. Con --ejecutar: requiere
EARTHDATA_TOKEN en entorno/Secrets. No solicita HDF5 manual, no sobrescribe.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from utils import nisar_auto, nisar_catalogo  # noqa: E402
from utils.config import DATA_DIR  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inicio", default="2026-10-21", help="YYYY-MM-DD, no anterior a VALIDATED")
    ap.add_argument("--fin", default=datetime.now(timezone.utc).date().isoformat())
    ap.add_argument("--bbox", nargs=4, type=float, default=[-76.8, 7.55, -76.55, 7.80],
                    metavar=("OESTE", "SUR", "ESTE", "NORTE"))
    ap.add_argument("--max-gb", type=float, default=nisar_auto.MAX_AUTO_GB)
    ap.add_argument("--cobertura-minima", type=float, default=nisar_auto.MIN_COBERTURA_PAR)
    ap.add_argument("--ejecutar", action="store_true", help="autoriza transferencia de datos, hasta --max-gb")
    a = ap.parse_args(argv)
    try:
        resultado = nisar_catalogo.buscar(*a.bbox, a.inicio, a.fin, madurez="VALIDATED")
        plan = nisar_auto.planear(resultado, max_gb=a.max_gb, cobertura_minima=a.cobertura_minima)
        print(json.dumps({"total_catalogo": resultado.total_catalogo, "plan": plan.resumen()},
                         indent=2, ensure_ascii=False))
        if not a.ejecutar:
            print("Solo metadatos; agrega --ejecutar si el presupuesto de datos y disco es aceptable.")
            return 0
        registro = nisar_catalogo.registro_json(resultado)
        carpeta = DATA_DIR / "nisar" / "catalogo"
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / f"auto_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}.json"
        with ruta.open("x", encoding="utf-8") as fd:
            json.dump(registro, fd, indent=2, ensure_ascii=False)
        salida = nisar_auto.preparar(plan, ruta, notificar=lambda etapa, nombre: print(f"{etapa}: {nombre}", flush=True))
        informe = carpeta / f"preparacion_{uuid.uuid4().hex}.json"
        with informe.open("x", encoding="utf-8") as fd:
            json.dump(salida, fd, indent=2, ensure_ascii=False)
        print(f"Insumos NISAR preparados; informe: {informe}. NO son mapas de inundación.")
        return 0
    except Exception:
        # No imprimir URLs firmadas, tokens o trazas que incluyan credenciales.
        print(f"No fue posible preparar NISAR: {type(e).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
