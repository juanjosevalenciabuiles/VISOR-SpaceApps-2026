#!/usr/bin/env python3
"""Buscar y PREPARAR automáticamente NISAR GCOV para inundaciones (ASF/CMR + Harmony).

    python scripts/nisar_auto.py --inicio 2026-10-21 --fin 2026-11-14
    python scripts/nisar_auto.py --inicio 2026-10-21 --fin 2026-11-14 --ejecutar

Sin --ejecutar: SOLO consulta y muestra plan. Con --ejecutar: requiere
EARTHDATA_TOKEN en entorno/Secrets. Harmony por defecto, HDF5 con --metodo hdf5.
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
    ap.add_argument("--metodo", choices=("harmony", "hdf5"), default="harmony",
                    help="harmony descarga solo COG recortados; hdf5 es respaldo de varios GB")
    ap.add_argument("--max-mb", type=int, default=384, help="presupuesto Harmony, entre 64 y 512 MB")
    ap.add_argument("--max-gb", type=float, default=nisar_auto.MAX_AUTO_GB)
    ap.add_argument("--cobertura-minima", type=float, default=nisar_auto.MIN_COBERTURA_PAR)
    ap.add_argument("--punto-prioritario", nargs=2, type=float, metavar=("LON", "LAT"),
                    help="opcional: exigir que ambas huellas CMR cubran el punto; NO verifica QA")
    ap.add_argument("--ejecutar", action="store_true", help="autoriza transferencia, según --metodo")
    a = ap.parse_args(argv)
    try:
        resultado = nisar_catalogo.buscar(*a.bbox, a.inicio, a.fin, madurez="VALIDATED")
        plan = nisar_auto.planear(resultado, max_gb=15.0 if a.metodo == "harmony" else a.max_gb,
                                 cobertura_minima=a.cobertura_minima,
                                 aceptar_escena_unica=(a.punto_prioritario is None),
                                 punto_prioritario=tuple(a.punto_prioritario) if a.punto_prioritario else None)
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
        # Harmony consulta el estado cada 5 s. No imprimir la misma frase
        # indefinidamente: mostrar el porcentaje y solo repetir si cambia,
        # con un latido ocasional para evitar aparentar que está bloqueado.
        ultimo = {"mensaje": None, "repeticiones": 0}

        def mostrar_progreso(etapa, detalle):
            if etapa == "Harmony: preparando recorte":
                try:
                    progreso = f"{float(detalle):.0f} %"
                except (TypeError, ValueError):
                    progreso = "porcentaje no informado"
                mensaje = f"NASA Harmony preparando recorte: {progreso}"
            elif etapa == "Harmony":
                mensaje = f"NASA Harmony: {detalle}"
            elif etapa == "Descargando capa":
                mensaje = f"Descargando variable NISAR: {detalle}"
            else:
                mensaje = str(etapa)

            if mensaje != ultimo["mensaje"]:
                ultimo["mensaje"] = mensaje
                ultimo["repeticiones"] = 0
                print(mensaje, flush=True)
            else:
                ultimo["repeticiones"] += 1
                if ultimo["repeticiones"] % 12 == 0:
                    print(f"{mensaje} (sin cambios; seguimos consultando a NASA)", flush=True)

        if a.metodo == "harmony":
            # Un error Harmony no dispara una descarga de HDF5 completa.
            salida = nisar_auto.preparar_harmony(plan, max_mb=a.max_mb,
                                                notificar=mostrar_progreso)
        else:
            salida = nisar_auto.preparar(plan, ruta,
                                        notificar=lambda etapa, _detalle: print(etapa, flush=True))
        informe = carpeta / f"preparacion_{uuid.uuid4().hex}.json"
        with informe.open("x", encoding="utf-8") as fd:
            json.dump(salida, fd, indent=2, ensure_ascii=False)
        print(f"Insumos NISAR preparados; informe: {informe}. NO son mapas de inundación.")
        return 0
    except Exception as e:
        # No imprimir URLs firmadas, tokens o trazas que incluyan credenciales.
        print(f"No fue posible preparar NISAR: {type(e).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
