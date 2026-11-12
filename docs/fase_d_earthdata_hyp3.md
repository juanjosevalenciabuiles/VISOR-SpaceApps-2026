# Fase D · Earthdata / HyP3 bajo demanda (PLAN, no implementado)

**Estado (12-nov-2026):** solo planificación. Nada de esto está en el código: la app no
descarga, no envía trabajos a HyP3, no usa credenciales y no consume créditos. Implementarlo
requiere **autorización expresa** del equipo.

## Para qué

Hoy el paso 03 de Herramientas SAR solo analiza RTC que alguien copió a `data/sar/`. La
Fase D cierra el hueco GRD → RTC: a partir del par recomendado, pedir los RTC a ASF HyP3,
seguir los trabajos y descargar únicamente lo necesario.

## Datos verificados (hyp3-docs.asf.alaska.edu, consultado el 12-nov-2026)

- HyP3 Basic: **8.000 créditos por usuario y mes**, gratis con cuenta de NASA Earthdata
  (reducido a 8.000 desde el 1-dic-2025).
- RTC a **30 m: 5 créditos por escena** (20 m: 15; 10 m: 60). Un par VV+VH a 30 m son
  2 trabajos (cada trabajo RTC de una escena DV entrega VV y VH): **10 créditos**.
- Los productos de HyP3 Basic se conservan **14 días**; HyP3+ (de pago) 30 días.
- ASF recomienda considerar antes **OPERA RTC-S1** (30 m, cobertura casi global desde
  2016): podría evitar el procesamiento. Hay que evaluar formato (por ráfaga) y
  compatibilidad con el motor antes de adoptarlo.

Antes de implementar, volver a consultar costos y límites: cambian.

## Diseño propuesto

| Pieza | Qué hace | Notas |
| --- | --- | --- |
| `utils/hyp3.py` | Cliente mínimo: créditos disponibles, enviar RTC, estado de trabajos, URL de descarga | Decidir entre `hyp3_sdk` (dependencia nueva) y la API REST con `urllib` como hace el buscador |
| Credencial | Token de Earthdata en **Replit Secrets** (`EARTHDATA_TOKEN`) | Nunca en código, logs, JSON de procedencia ni GitHub. Si falta, el paso lo dice y no ofrece enviar |
| Consentimiento | Diálogo previo a cada envío: escenas, resolución, nº de trabajos, **créditos estimados**, créditos disponibles, retención | Botón de confirmación explícito por envío. Sin envíos automáticos |
| Límites | Máx. 2 trabajos por confirmación (un par), 30 m por defecto, AOI obligatoria para recortar tras descargar | Configurables solo en `utils/config.py`, revisados por el equipo |
| Seguimiento | Guardar en `data/hyp3/trabajos.json` id, nombre de escena, fecha de envío, estado, caducidad | Permite **recuperar** trabajos tras reiniciar Replit; nunca reenviar si ya existe un trabajo del mismo granulo y parámetros |
| Espera | Consultar estado al pulsar «Actualizar» (sin bucles en segundo plano) | Mostrar estado real de HyP3 (PENDING/RUNNING/SUCCEEDED/FAILED); sin barras de progreso inventadas |
| Descarga | ZIP del producto → extraer solo `*_VV.tif`, `*_VH.tif` y metadatos a `data/sar/` | Verificar tamaño antes (aviso si > 1 GB); espacio libre; nunca sobrescribir |
| Procedencia | Añadir a la ficha: id de trabajo HyP3, versión del procesador, parámetros RTC, fecha de descarga, SHA-256 de los RTC | Sin el token, claro |

## Flujo en Mission Control

1. Paso 02 elige el par (sin cambios).
2. Paso 03 detecta los RTC que faltan y ofrece «Solicitar RTC en HyP3», deshabilitado si no
   hay token.
3. Diálogo de consentimiento con el costo; al confirmar, se envían los trabajos y se
   registran.
4. «Actualizar estado» consulta HyP3. Cuando terminan: «Descargar a data/sar/».
5. El análisis existente continúa sin cambios.

## Pruebas previstas

- Cliente con respuestas guardadas (sin red), como el buscador.
- Sin token: ningún envío posible. Con token falso: error legible, sin exponerlo.
- No se reenvía un trabajo existente; recuperación tras reinicio.
- Estimación de créditos = nº de trabajos × costo de la tabla vigente.
- Una prueba manual, **autorizada**, con un solo par a 30 m (10 créditos).

## Fuera de alcance de esta fase

- **NISAR (GCOV, HDF5):** reservado para el hackathon del 14–15 de noviembre. No se descarga
  ni se procesa antes; este plan no lo cubre.
- InSAR, coherencia u otros métodos: el motor solo hace diferencia de retrodispersión.
