# NISAR data · Middle Atrato (Chocó)

Area: lon −77.05 to −76.45, lat 5.55 to 7.20. NISAR L2 GCOV from ASF DAAC (search of 14 Nov 2026).

| Stack | Orbit | Frames | Local time | Data |
|---|---|---|---|---|
| A_T047 | Ascending | F004 + F005 | ~05:38 | Jun → Oct 2026, mode 4005 (40 MHz) |
| A_T148 | Ascending | F004 + F005 | ~05:47 | Jun → Oct 2026, mode 2005 (20 MHz), some mixed dates |
| D_T011 | Descending | F085 + F086 | ~18:28 | Beta Nov 2025 → Jan 2026, provisional Jun → Oct 2026, mode 4005 |
| D_T112 | Descending | F085 + F086 | ~18:37 | Jun → Oct 2026, F085 in 4005 and F086 in 2005 |

| Event | Date | Place |
|---|---|---|
| E1 | 2026-01-19 | Murindó |
| E2 | 2026-02-01 | Vigía del Fuerte |
| E3 | 2026-05-04 | Río Quito (Paimadó) / Quibdó |
| E4 | 2026-05-29 | Quibdó, Río Quito, Cértegui |
| E5 | 2026-07-19 | Middle Atrato (Beté) |
| E6 | 2026-08-28 | Quibdó (after the 10 Aug earthquake) |

- Provisional data since June 2026. Only E5 and E6 have pre, during and post scenes.
- One version per frame is kept (PR over UR, dual-pol over HH-only, dominant mode).
- Ascending and descending are never compared: each stack is processed on its own.
- Metadata: `metadatos/` (inventory, footprints, download plan, event phases).

## Downloaded files

50 complete GCOV files (231 GB) downloaded from NASA Earthdata (ASF DAAC), listed in `metadatos/nisar_gcov_downloaded.csv` with stack, date, frame, mode, polarizations, event role, size and download link.

| Stack | Files | Dates | Size |
|---|---|---|---|
| A_T047 | 13 | 7 | 93.8 GB |
| A_T148 | 14 | 5 | 22.3 GB |
| D_T011 | 14 | 7 | 99.7 GB |
| D_T112 | 9 | 5 | 15.4 GB |

The `.h5` files are not in the repository (up to 7.35 GB each). They are downloaded with `notebooks/01_descarga_nisar.ipynb` (NASA Earthdata account). The 6 urgent-response (UR) files have no link because the ASF search only returned the production (PR) versions.
