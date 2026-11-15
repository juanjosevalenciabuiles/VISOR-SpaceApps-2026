"""HDF5 NISAR L2 GCOV SINTÉTICOS para pruebas (no son datos de la misión).

Reproducen la estructura observada en `isce3/tests/data/nisar_129_gcov_crop.h5`
(ISCE3, procesador oficial) y lo que documentan ASF e ISCE3:
- identificación como cadenas de bytes en `/science/LSAR/identification`;
- `projection` int32 con atributo `epsg_code`; `xCoordinates`/`yCoordinates`
  como centros de píxel; relleno NaN; máscara uint8 (255 fuera del radar,
  0 no válido, 1…N subfranja).
Los valores son inventados y por defecto `missionId` es "NISAR_SINTETICO".
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# UTM 18N cerca de Chigorodó (−76.68, 7.67 ≈ x 315 000, y 848 000)
X0, Y0, PASO = 300_010.0, 862_990.0, 20.0


def gcov(ruta: Path, *, mision: str = "NISAR_SINTETICO", fecha: str = "2026-10-24T23:15:00",
         track: int = 48, frame: int = 12, direccion: str = "Ascending", crid: str | None = "P05036",
         n: int = 1500, x0: float = X0, y0: float = Y0, paso: float = PASO, epsg: int = 32618,
         terminos=("HHHH", "HVHV"), cruzados=("HHHV",), valor: dict | None = None,
         parche: tuple[slice, slice, float] | None = None, mascara: bool = True,
         frecuencia_b: bool = False, semilla: int = 3) -> Path:
    import h5py

    rng = np.random.default_rng(semilla)
    valor = valor or {"HHHH": 10 ** (-7 / 10), "HVHV": 10 ** (-14 / 10), "VVVV": 10 ** (-8 / 10)}
    with h5py.File(ruta, "w") as f:
        ident = f.create_group("/science/LSAR/identification")
        for k, v in {"missionId": mision, "productType": "GCOV", "trackNumber": str(track),
                     "frameNumber": str(frame), "orbitPassDirection": direccion,
                     "zeroDopplerStartTime": f"{fecha}.000000", "zeroDopplerEndTime": f"{fecha[:-2]}50.000000",
                     "productVersion": "1.0.0", "listOfFrequencies": None}.items():
            if v is not None:
                ident.create_dataset(k, data=np.bytes_(v))
        if crid:
            ident.create_dataset("compositeReleaseId", data=np.bytes_(crid))
        frecuencias = [("A", paso, n)] + ([("B", paso * 4, n // 4)] if frecuencia_b else [])
        for letra, p, tam in frecuencias:
            g = f.create_group(f"/science/LSAR/GCOV/grids/frequency{letra}")
            g.create_dataset("xCoordinates", data=x0 + p * np.arange(tam))
            g.create_dataset("yCoordinates", data=y0 - p * np.arange(tam))
            pr = g.create_dataset("projection", data=np.int32(epsg))
            pr.attrs["epsg_code"] = np.int64(epsg)
            g.create_dataset("radiometricTerrainCorrectionFlag", data=np.True_)
            g.create_dataset("listOfCovarianceTerms", data=np.array([t.encode() for t in terminos]))
            for t in terminos:
                datos = (valor[t] * rng.gamma(8, 1 / 8, size=(tam, tam))).astype("float32")
                if parche is not None and letra == "A":
                    filas, cols, factor = parche
                    datos[filas, cols] *= factor
                datos[:5, :] = np.nan                      # borde sin dato (relleno NaN)
                d = g.create_dataset(t, data=datos, chunks=(min(tam, 256), min(tam, 256)), compression="gzip")
                d.attrs["long_name"] = np.bytes_("radar backscatter gamma0")
            for t in cruzados:
                g.create_dataset(t, data=np.ones((tam, tam), dtype="complex64"))
            if mascara:
                m = np.ones((tam, tam), dtype="uint8")
                m[:, :3] = 255                              # fuera de la cuadrícula de radar
                m[10:12, 10:12] = 0                         # muestra no válida
                g.create_dataset("mask", data=m)
    return ruta
