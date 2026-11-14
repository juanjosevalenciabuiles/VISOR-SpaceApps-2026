# V.I.S.O.R. — SOLO INUNDACIONES, NISAR primero: adquisición automática ASF

**Estado:** desarrollo en la rama `feature/nisar-inundaciones-auto`. **No en main.** Esta fase prepara insumos; NO produce una máscara de inundación validada. Se conservaron los datos originales.

## Decisión del equipo

La interfaz pública tendrá solo **Inundaciones**. NISAR L2 GCOV (banda L) es
el proveedor principal. Sentinel-1C RTC (banda C) continúa como respaldo,
principalmente para fechas históricas y comparaciones metodológicas; nunca
se suman o restan intensidades entre bandas L y C.

El objetivo ambiental es identificar **posibles nuevas áreas de agua superficial**:
requiere observar fechas compatibles, calidad, referencia de agua permanente
(ej. JRC), y/o evidencia hidrológica oficial (IDEAM). Un cambio de gamma0 o
una escena única NO verifica una inundación.

## Lo reutilizado

Se trasladaron sin reescribir desde la PR #6 (aún abierta):
`utils/nisar_catalogo.py`, `utils/nisar_descarga.py`, `utils/nisar_gcov.py`
y `scripts/nisar.py`, además de sus tests de catálogo/descarga/lectura.

- Colección: `NISAR_L2_GCOV_V1` (**VALIDATED**, NASA ASF), disponible
  para adquisiciones a partir de **21-oct-2026**, según documentación oficial.
- Catálogo público CMR de NASA, consultado directamente por HTTPS.
- Descargas HDF5 desde `nisar.asf.earthdatacloud.nasa.gov` con
  `EARTHDATA_TOKEN` únicamente desde variables de entorno/Secrets;
  jamás imprimirlo, enviarlo a una URL ajena o guardarlo en la configuración.
- Se valida tamaño esperado, espacio libre, dominio HTTPS autorizado,
  y escritura `.h5.part` con publicación tras completar los bytes.
- Recorte: lectura de ventana de HDF5 auténtico, polarización
  diagonal `HHHH` o `VVVV` que realmente exista; `gamma0` en potencia,
  máscara y NoData. GeoTIFF resultado en `data/nisar/`; original permanece en
  `data/nisar/crudos/`.
- El motor Sentinel-1 y `data/sar/` no se modifican.

## Función nueva

`utils/nisar_auto.py`: seleccionar automáticamente el par compatible del
catálogo según cobertura, polarización y presupuesto de almacenamiento;
priorizar par de dos fechas, y si no cabe, una sola escena con una advertencia
explícita de que **no permite detectar cambios temporales**. No inventa
cobertura. El límite inicial es 5 GB y el mínimo de cobertura para explorar
pares es 40 % (la zona no cubierta queda SIN DATOS).

`components/nisar_auto_ui.py`: control principal en Herramientas SAR,
con la **misma AOI** confirmada que usa Sentinel. Dos pasos explícitos:
(1) buscar y mostrar tamaño/cobertura sin descargar; (2) autorizar descarga y
preparación. La cola existente `utils/trabajos.py` controla los estados y
las fases, y continúa en el servidor incluso si Streamlit actualiza el mapa.
Los datos HDF5 descargados pueden ocupar varios GB; si Replit no tiene espacio,
se bloquea antes de comenzar.

`scripts/nisar_auto.py`: interfaz CLI sin seleccionar HDF5 manualmente.

```bash
# En la rama experimental, NO en main hasta aprobación:
bash actualizar.sh --guardar feature/nisar-inundaciones-auto
bash start.sh --verificar
.venv/bin/python scripts/nisar_auto.py --inicio 2026-10-21 --fin 2026-11-14
# SOLO si Replit tiene espacio y EARTHDATA_TOKEN configurado en Secrets:
.venv/bin/python scripts/nisar_auto.py --inicio 2026-10-21 --fin 2026-11-14 --ejecutar
```

**Nunca escribir EARTHDATA_TOKEN en el chat, la Shell compartida, comandos,
GitHub ni logs**. Debe configurarse en el gestor de Secrets del despliegue.
El límite de cola de trabajos es por defecto 900 s (configurable); un par
de varios GB puede no caber en ese presupuesto de ejecución. No se ejecutó
una transferencia real de HDF5 en GitHub Actions por consumo y credenciales.

## Caso piloto Chigorodó: datos conocidos (de PR #6, 13-nov-2026)

- 11 granules NISAR GCOV VALIDATED en catálogo, sin lectura HDF5 real.
- El par del track 148 / frame 5, **22 oct → 3 nov 2026**, presenta solo
  ~41 % de cobertura común de la AOI. En modo mixto pesa
  aproximadamente **2 × 1,64 GB**; NO cubre el 59 % restante.
- Escena única track 112 / frame 85 del 31 oct, ~94 % del área, ~1,23 GB,
  sin fecha compatible para calcular un cambio.
- Estos porcentajes provienen de huellas de catálogo, no de píxeles válidos
  comprobados. El programa debe revisarlos sobre un GCOV real.

## Puertas de QA para declarar automatización lista

1. Un test de catálogo simulado y al menos una consulta real ASF/CMR en CI.
2. Selección determinista de par, límites de disco, token ausente, parcial
   inválido, HDF5 de otra misión, área fuera de Colombia, catálogo vacío.
3. Descarga HDF5 auténtica a almacenamiento aislado con credencial Earthdata
   y prueba de autorización/HTTP/tamaño; registrar SHA-256.
4. Inspección de frecuencia/polarización, grilla, CRS, tamaño de píxel,
   máscara y validez de gamma0 en HDF5 real.
5. Mapeo geográfico, cobertura real, distinción tierra/agua y validación con JRC
   e IDEAM; **aún no implementados para el flujo NISAR**.
6. QA en Replit, Chromium y Firefox, datos originales intactos, sin fusión
   de código científico o descarga a main sin autorización del equipo.

## Fuentes oficiales

- NASA NISAR disponibilidad: https://nisar-docs.asf.alaska.edu/availability-overview/
- Encontrar y descargar: https://nisar-docs.asf.alaska.edu/asf-search/
- Producto GCOV: https://nisar-docs.asf.alaska.edu/gcov/
- Subconjuntos NISAR con Harmony: https://nisar-docs.asf.alaska.edu/harmony/

**Alternativa técnica futura de menor almacenamiento:** Earthdata Harmony
puede entregar recortes de subconjuntos del GCOV como COG sin bajar todo el
HDF5; se deberá autenticar y validar por separado antes de reemplazar
la descarga HDF5. La descarga íntegra de HDF5 es un primer flujo controlado,
no la mejor estrategia definitiva para Replit.
