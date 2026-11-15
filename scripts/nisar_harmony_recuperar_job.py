#!/usr/bin/env python3
"""Reutilizar un trabajo NASA Harmony YA exitoso y recuperar un TIFF con seguridad.

No envía nuevas solicitudes Harmony. Sin --ejecutar, solo metadatos.
No imprime el valor de EARTHDATA_TOKEN ni las URLs firmadas.
Ejemplo:
  python scripts/nisar_harmony_recuperar_job.py --job-id UUID
  python scripts/nisar_harmony_recuperar_job.py --job-id UUID --ejecutar --max-mb 64
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils import nisar_harmony as h  # noqa: E402

AOI_PILOTO = (-76.80, 7.55, -76.55, 7.80)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job-id", type=uuid.UUID, required=True)
    ap.add_argument("--max-mb", type=int, default=64)
    ap.add_argument("--ejecutar", action="store_true", help="autorizar descargar un TIFF existente")
    a = ap.parse_args(argv)

    if not 1 <= a.max_mb <= 128:
        print("El presupuesto debe ser de 1 a 128 MiB.", file=sys.stderr)
        return 2
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        print("Configura EARTHDATA_TOKEN solo en Replit Secrets.", file=sys.stderr)
        return 2

    try:
        from harmony import Client

        client = Client(token=token, download_timeout=60)
        status = client.status(str(a.job_id))
        estado = str(status.get("status") or "").lower()
        print("Estado:", estado)
        print("Progreso:", status.get("progress", "no informado"))
        if estado != "successful":
            print("No se descargará nada hasta que Harmony complete el trabajo.")
            return 1
        urls = list(client.result_urls(str(a.job_id)))
        print("Archivos listados:", len(urls))
        if len(urls) != 1:
            raise h.ErrorHarmony("La prueba admite únicamente un resultado HHHH.")
        url = urls[0]
        h._url_datos(url)
        capa = h._etiqueta(url, ("HHHH",))
        if capa != "HHHH":
            raise h.ErrorHarmony("La capa generada no corresponde a HHHH.")
        print("Variable reconocida:", capa)
        if not a.ejecutar:
            print("No se transfirieron archivos. Usa --ejecutar para descargar un GeoTIFF.")
            return 0
        carpeta = ROOT / "tmp_harmony_recuperado"
        carpeta.mkdir(exist_ok=True)
        if shutil.disk_usage(carpeta).free < (a.max_mb + 32) * 1024**2:
            raise h.ErrorHarmony("Espacio insuficiente para la prueba, se impide la transferencia.")
        destino = carpeta / f"gcov_{a.job_id.hex}_HHHH.tif"
        if destino.exists():
            raise h.ErrorHarmony("La prueba ya tiene un archivo con ese nombre; no se sobrescribe.")
        try:
            tam, digest = h._descargar_cota(
                url, destino, a.max_mb * 1024**2, cliente=client,
            )
            info = h._validar_cog(destino, AOI_PILOTO, "HHHH")
        except Exception:
            destino.unlink(missing_ok=True)
            raise
        resultado = {
            "estado": "COG_HHHH_VERIFICADO_SIN_INTERPRETAR",
            "archivo": str(destino.relative_to(ROOT)),
            "bytes": tam, "mib": round(tam / 1024**2, 3),
            "sha256": digest, "geotiff": info,
            "nota": "Radar gamma0 de potencia; NO confirma inundaciones",
        }
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
        return 0
    except h.ErrorHarmony as exc:
        print("Validación detenida:", str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        # Las excepciones HTTP pueden contener URL firmada: NO imprimir str(exc).
        print("La descarga autenticada no se completó:", type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
