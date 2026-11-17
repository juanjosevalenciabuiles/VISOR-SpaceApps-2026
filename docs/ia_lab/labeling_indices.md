# Labeling: indices and classes

## Why L-band

NISAR L-band (λ ≈ 24 cm) goes through much of the canopy:

| Mechanism | Where | Signal |
|---|---|---|
| Specular reflection | Open calm water | HH and HV very low (black) |
| Volume scattering | Forest canopy | HV high, HH medium |
| Double bounce | Water under forest, buildings | HH very high |

- Flooding shows up two opposite ways: open water darkens, flooded forest brightens in HH. In the middle Atrato most of the floodplain is forest, so flooded vegetation is the key class.
- HV over water falls to the noise floor (≈ −23 dB); HV < −24 dB is not interpreted.
- Products are provisional (1–2 dB banding), so labeling relies on change within the same stack.
- Wet soil raises backscatter 1–3 dB: a change counts from ±3 dB.
- Under very dense forest, intensity underestimates flooding: it is a minimum, not the total.

## Preprocessing

1. Read `frequencyA` `HHHH` and `HVHV` (γ0, terrain-corrected) only inside the area window.
2. Mosaic the two frames of each pass; drop 25 px from each frame border.
3. Put everything on the same 20 m grid (EPSG:32618); 10 m data averaged 2 × 2 in linear.
4. Floor at 0.001 (−30 dB) before the logarithm.
5. Lee 5 × 5 speckle filter, the same for all dates.
6. Averages and ratios in linear; thresholds and display in dB.

## Indices

| Index | Formula | Scale |
|---|---|---|
| `HH_dB`, `HV_dB` | `10*log10(HH)`, `10*log10(HV)` | −25 to 0 / −30 to −8 dB |
| `Q` | `HH_dB − HV_dB` | 0 to 15 dB |
| `HH_ref`, `HV_ref` | median of the stack's no-event dates | normal state of each pixel |
| `HH_min`, `HH_max` | min / max of `HH_dB` over all dates | always bright / always dark |
| `LR_ref_HH`, `LR_ref_HV` | during − ref | −10 to +10 dB |

`LR_ref` is used instead of during − pre because the E6 pre-event scene is the E5 post-event scene and may still be wet.

## Classes

| Code | Class | Color | Starting rule |
|---|---|---|---|
| 1 | Permanent water | `#08306B` | dark on every date (`HH_max` < −18 dB) |
| 2 | New open water | `#41B6C4` | dark now and `LR_ref_HH` ≤ −3 dB |
| 3 | Permanent flooded vegetation | `#9E9AC8` | bright on every date (`HH_min` > −4 dB) |
| 4 | New flooded vegetation | `#54278F` | `HH` > −4 dB, `Q` > 8 dB and `LR_ref_HH` ≥ +3 dB |
| 5 | Non-flooded forest | `#1B7837` | `HV` −14 to −10 dB, `Q` 4 to 7 dB |
| 6 | Low vegetation / pasture / soil | `#C2E699` | `HH` −15 to −8 dB, `HV` < −16 dB |
| 7 | Urban | `#737373` | always bright and highly textured |
| 8 | Urban with increase | `#E6550D` | urban and `LR_ref_HH` ≥ +3 dB |
| 9 | Doubtful | `#FFD92F` | nothing fits or rules conflict |

Classes 2, 4 and 8 are the flood evidence. The pairs 1/2 and 3/4 keep the river and wetlands from being flagged as an emergency.

In notebook 03 the thresholds are set per date (Otsu for water, the scene's forest as anchor), and without a DEM flooded vegetation is accepted only within 3 km and urban within 2 km of permanent water.
