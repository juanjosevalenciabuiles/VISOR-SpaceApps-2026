#!/usr/bin/env python3
"""Comprobar el catálogo PÚBLICO de capacidades Harmony GCOV, sin tokens.

Produce SOLO el estado de subsetting y las variables aplicables. No solicita
trabajos ni descarga datos. No modifica la aplicación ni data/.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://harmony.earthdata.nasa.gov/capabilities"
COL = "NISAR_L2_GCOV_V1"


def consultar(abrir=None):
    abrir = abrir or urllib.request.urlopen
    url = BASE + "?" + urllib.parse.urlencode({"shortName": COL})
    request = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "VISOR-NISAR-Harmony-Preflight/1.0",
    })
    with abrir(request, timeout=25) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not isinstance(result, dict) or not result.get("conceptId"):
        raise ValueError("Harmony no declaró una colección CMR válida")
    out = {k: result.get(k) for k in (
        "conceptId", "shortName", "variableSubset", "bboxSubset",
        "reproject", "outputFormats",
    )}
    vars_ = result.get("variables") or []
    out["variables"] = [
        {"name": v.get("name"), "id": v.get("id"), "fullPath": v.get("fullPath")}
        if isinstance(v, dict) else {"name": str(v)}
        for v in vars_ if any(p in str(v).lower()
                              for p in ("frequency", "hhhh", "hvhv", "mask", "numberoflooks"))
    ][:50]
    return out


def main():
    try:
        print(json.dumps(consultar(), ensure_ascii=False, indent=2))
    except (OSError, ValueError, urllib.error.URLError) as e:
        print(json.dumps({"estado": "NO VERIFICADO", "tipo_error": type(e).__name__}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
