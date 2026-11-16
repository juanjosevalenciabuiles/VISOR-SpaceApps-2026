# V.I.S.O.R. — desplegar fuera de Replit

> Estado: **configuración preparada, NO despliegue externo certificado**.
> Esta rama propone infraestructura reproducible. No cambia el procesamiento SAR.
> La experiencia que mostraron a los jurados debe validarse en el navegador
> antes de considerarla «versión final publicada».

## 1. ¿Qué se está publicando?

- Entrada: `app.py` (Streamlit); Docker instala `requirements.txt` con Python 3.12.
- Pantallas: `components/`, `pages/`, `assets/`, `static/`.
- Datos públicos ligeros: `data/contexto/`, las tres capas DEMO etiquetadas y
  `data/ia_lab/` (mapa histórico del experimento E6, **no inferencia en vivo**).
- **NO se incluyen** los productos reales de `data/analisis/`, `data/sar/`,
  `data/nisar/`, `data/trabajos/` ni credenciales locales. Son datos de cada
  instalación y están excluidos de Git y de Docker.
- El análisis SAR requiere observaciones reales compatibles y preparación;
  una fecha indicada por el usuario no garantiza una escena en NISAR/ASF.
- Los resultados SAR muestran indicios de cambio de retrodispersión,
  **no inundaciones verificadas**.

## 2. Probar localmente con Docker

Requiere Docker instalado (Windows Docker Desktop, macOS o Linux).

```bash
docker build -t visor-jurados:local .
docker run --rm -p 8501:8501 -e PORT=8501 visor-jurados:local
```

Abre `http://localhost:8501`. Para disponer de un volumen externo:

```bash
docker run --rm -p 8501:8501 -e PORT=8501 \
  -e VISOR_DATA_DIR=/app/storage/data \
  -v visor-datos:/app/storage visor-jurados:local
```

El primer arranque **copia solo los recursos públicos faltantes** a ese volumen;
nunca sobrescribe un GeoTIFF o JSON que ya exista. Revisa la procedencia antes
de colocar datos reales en `visor-datos`. El Dockerfile usa un usuario sin
privilegios y ejecuta un único proceso Streamlit.

## 3. Publicar en Render (Docker)

1. Abre [Render](https://render.com/) → **New → Web Service** y conecta el
   repositorio GitHub `juanjosevalenciabuiles/VISOR-SpaceApps-2026`.
2. En **Branch** selecciona la rama de despliegue ya revisada; **no elijas
   `main`** sin confirmar que su UI corresponde a la vista de jurados.
3. Selecciona **Runtime: Docker** y el `Dockerfile` raíz.
4. Activa **Manual Deploy** o desactiva **Auto-Deploy** hasta pasar QA.
5. Health check path: `/_stcore/health`. Render define `PORT` y el arranque
   portable lo respeta sin fijarlo a 5000.
6. En **Environment** configura las claves opcionales (p. ej. `CARTO_API_KEY`)
   como secretos, **nunca** en `.env` público ni en Git.
7. Usa el dominio HTTPS que Render asigne y comprueba mapa, zoom, historial,
   Leyenda/Información, selector de AOI y Laboratorio IA si existe en esa rama.

**Limitación del plan gratuito:** los contenedores pueden suspenderse tras
inactividad; el almacenamiento local es efímero. Por ello **no sirve para
garantizar la conservación de análisis SAR ejecutados en producción**.
Los discos persistentes de Render corresponden a planes de pago.

Para persistencia, monta un disco en `/app/storage` y define
`VISOR_DATA_DIR=/app/storage/data`. Los datos en ese volumen sobreviven a
reinicios según las condiciones del proveedor. Con disco y un solo proceso
Streamlit evitas perder resultados de un despliegue anterior; no equivale a
un almacén de objetos ni a una cola de procesamiento científico.

## 4. Publicar en Railway

1. Conecta el mismo repositorio y selecciona la rama de despliegue.
2. Railway detecta `Dockerfile` automáticamente.
3. Configura un dominio público y las variables necesarias en el panel
   de Railway. El lanzador reconoce su variable `PORT`.
4. Si vas a conservar datos SAR, añade un volumen y define
   `VISOR_DATA_DIR=/app/storage/data` (montaje `/app/storage`).
5. Verifica la instancia pública desde un navegador sin iniciar sesión,
   sin depender del entorno Replit.

Los planes, límites y costos dependen de Railway: revísalos antes de activar
un despliegue de larga duración.

## 5. Alternativa Streamlit Community Cloud

Puede servir para **exhibición ligera** conectando directamente la rama GitHub,
`app.py` y `requirements.txt`. No usa `Dockerfile` y no debe asumirse
almacenamiento persistente ni recursos suficientes para raster SAR pesado.
Comprobar compatibilidad, dependencia de bibliotecas geoespaciales, dominio,
recurso y funcionamiento real antes de publicar el enlace en NASA.

## 6. Migrar los datos reales sin romper el historial

Este paso es manual y separado del Git público. Requiere contar con licencias,
derechos de uso y datos apropiados:

- Copia al destino los **GeoTIFF auténticos más sus JSON de procedencia**,
  incluyendo fechas, sensor, metodología y huellas SHA-256.
- Conserva la estructura relativa de `data/analisis/`, `data/nisar/`
  y `data/sar/` que utiliza V.I.S.O.R. para analizar o reproducir.
- Si usas un volumen con `VISOR_DATA_DIR`, prepara esos archivos **bajo ese
  directorio**, por ejemplo `/app/storage/data/analisis`.
- No publiques `data/trabajos/` con información confidencial o trazas de
  trabajos incompletos; se puede comenzar con una carpeta vacía.
- Nunca subas tokens Earthdata, archivos `.env`, `.streamlit/secrets.toml`,
  ni cookies/sesiones a GitHub o a la imagen pública.
- Antes y después, calcula los hashes originales; no cambies etiquetas DEMO
  a REAL SIN VALIDAR sin ficha y trazabilidad.
- **Subir el código no traslada automáticamente los GeoTIFF de Replit**.

## 7. QA antes de compartir el enlace a NASA

1. Conservar SHA exacto de la rama desplegada y comprobar que coincide con
   lo que mostró el jurado local; si no hay evidencia, indicarlo.
2. Docker build exitoso y health check `/_stcore/health` en verde.
3. Abrir la URL pública sin cuenta, permiso ni contraseña, en ventana privada.
4. Buscar Chigorodó, abrir Herramientas SAR y seleccionar AOI; comprobar
   que la segunda selección reemplaza la anterior.
5. Mantener zoom y capa GeoTIFF real al activar capas o abrir Información.
6. Verificar que el historial presente **productos reales** SOLO si se
   migraron sus archivos y fichas originales.
7. Confirmar funcionamiento de Laboratorio IA y advertencias históricas.
8. Verificar leyendas, atribuciones de mapas y créditos/licencias de recursos.
9. No presentar un cambio SAR como inundación confirmada.
10. Probar reinicio/redespliegue con un GeoTIFF de prueba NO sintético y
    comprobar persistencia si se prometen análisis guardados.
11. Guardar captura, URL pública y SHA. **Publicar en NASA solo después de
    abrir ambas URLs públicas: proyecto y demo de ≤30 segundos o ≤7 diapositivas.**

## 8. Volver atrás

El despliegue **no requiere fusionar** la rama experimental a `main`.
En Render/Railway conserva el commit del despliegue anterior y vuelve a él si
hay una regresión. Mantén sin tocar el respaldo
`respaldo/demo-jurados-2026-11-15-157c129`. Replit conserva `.replit` y
`start.sh`; Docker utiliza `scripts/arranque_portable.py` y no los modifica.

## Fuentes oficiales

- [Streamlit — Deploy using Docker](https://docs.streamlit.io/deploy/tutorials/docker)
- [Render — Web Services y PORT](https://render.com/docs/web-services)
- [Render — Discos persistentes](https://render.com/docs/disks)
- [Railway — Dockerfiles](https://docs.railway.com/builds/dockerfiles)
