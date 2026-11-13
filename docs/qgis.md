# QGIS en V.I.S.O.R.

QGIS Desktop es una herramienta **opcional y local** del equipo (Windows). La app de Replit
no lo instala ni depende de él: se comunican por archivos.

| Herramienta | Uso en el proyecto |
| --- | --- |
| ASF Search (buscador) | Buscar escenas Sentinel-1 y recomendar pares |
| ASF HyP3 | RTC desde GRD, con autorización (Fase D, sin implementar) |
| GDAL / Rasterio / NumPy | Análisis reproducible, auditoría numérica, fichas de procedencia |
| **QGIS Desktop** | Inspección visual independiente, contexto (DEM, ríos, vías), comparación de versiones y cartografía para la presentación |
| Mission Control | Visualización interactiva, procedencia, línea temporal |

## 1. Exportar desde Mission Control

Activar un resultado en Explorador → Resultados SAR. En su ficha (panel Información) pulsar
**Exportar para QGIS**. Se descarga `<nombre>_QGIS.zip` con:

- el GeoTIFF **original, byte a byte** (mismo SHA-256 que en `data/analisis/`);
- `<nombre>.qml`, que QGIS aplica solo al abrir el `.tif` (clases 1–3 en cian, naranja y
  violeta; 0 y 255 transparentes);
- la ficha `.json` original (si existe), una leyenda `.csv`, el AOI `.geojson` (solo si la
  ficha la declara), `LEEME_QGIS.txt` y `manifiesto.json` con la huella de cada archivo.

Desde la Shell: `.venv/bin/python scripts/exportar_qgis.py data/analisis/<archivo>.tif`
(deja el ZIP en `exportaciones/`, fuera de Git).

## 2. Revisar en QGIS (≥ 3.28)

1. Descomprimir la carpeta completa y arrastrar el `.tif`.
2. Propiedades → Información: EPSG:32618, 924 × 926, ~30 m, NoData 255 (para Chigorodó).
3. Identificar píxeles para verificar clases; comparar con la otra versión activando y
   desactivando capas.
4. Reproyectar solo con **vecino más cercano**. Bilineal o cúbica crean clases inexistentes.
5. No guardar encima del `.tif`: cambiaría su SHA-256 y la ficha dejaría de valer.
6. Guardar el proyecto `.qgz` con rutas relativas y anotar las versiones de QGIS y GDAL.

## 2b. Lista de comprobación manual en QGIS Desktop

Lo automático verifica el paquete (SHA-256, estructura del `.qml`, CRS y NoData leídos con
GDAL); **no** puede abrir QGIS. Antes de una demostración, una persona del equipo marca:

| # | Comprobación | Máscara (`coincidencia_…`, `…_mascara`) | Diferencia en dB (`…_dif_db`) |
| --- | --- | --- | --- |
| Q1 | El estilo se aplica solo al arrastrar el `.tif` | Paleta de valores únicos | Pseudocolor, rampa azul–gris–rojo (azul = disminuye) |
| Q2 | Propiedades → Información: CRS y tamaño de píxel | EPSG del UTM, ~30 m | Igual que la máscara del mismo par |
| Q3 | NoData transparente | 255 | −9999 |
| Q4 | Clases sin cambio invisibles | 0 con alfa 0 | Δ≈0 casi transparente |
| Q5 | Identificar un píxel coincide con la ficha | Clase 1–3 y su etiqueta | Valor en dB con signo (negativo = disminuye) |
| Q6 | Rango de la leyenda | — | ±10 dB, centrado en 0 |
| Q7 | Nombres sin errores al descomprimir en Windows | ✔ | ✔ |
| Q8 | `manifiesto.json` coincide (`Get-FileHash` en Windows, `sha256sum` en Linux/macOS) | ✔ | ✔ |

Registrar versión de QGIS, de GDAL y sistema operativo. Un fallo en Q1–Q5 bloquea el uso
del paquete en la demostración.

## 3. Auditoría numérica (complemento de la revisión visual)

```bash
.venv/bin/python scripts/auditar_geotiff.py data/analisis/coincidencia_VV_VH_20260924_20261006.tif \
    --comparar data/analisis/coincidencia_VV_VH_Chigorodo.tif \
    --vv data/analisis/cambio_VV_20260924_20261006_mascara.tif \
    --vh data/analisis/cambio_VH_20260924_20261006_mascara.tif \
    --salida auditoria_chigorodo.json
```

Informa cuadrícula, clases, **coincidencia del SHA-256 con la ficha**, píxeles distintos,
matriz de transiciones (p. ej. `3->2`: píxeles que eran clase 3 y pasan a 2) y si las
máscaras reproducen el producto. Es de solo lectura.

Integra lo útil del paquete auxiliar `visor_qa_geotiff.py` (12-nov) sobre las funciones del
repositorio; el paquete suelto ya no es necesario para estas comprobaciones.

## Caso Chigorodó: dos productos que NO son equivalentes

| | Exploratorio | Reproducible |
| --- | --- | --- |
| Archivo | `coincidencia_VV_VH_Chigorodo.tif` | `coincidencia_VV_VH_20260924_20261006.tif` |
| Ficha | No | Sí (REAL SIN VALIDAR) |
| Umbral VV / VH | No documentado | −7,5 dB / −3,0 dB |
| Clase 3 | 27.433 px | 12.293 px (≈ 1.106 ha) |

Según el equipo, 15.860 píxeles difieren y toda la diferencia viene de VV. Se conservan los
dos y no se fuerza la equivalencia. Ninguno confirma inundaciones.
