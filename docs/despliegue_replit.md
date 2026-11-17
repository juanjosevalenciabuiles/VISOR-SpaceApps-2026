# Publicación en Replit (Autoscale) — causa de los fallos del 17-nov-2026 y procedimiento

## Causa raíz (comprobada)

- `.venv/pyvenv.cfg` en el Repl: `home = /home/runner/workspace/.pythonlibs/bin`.
  El Python de `.venv` es un enlace a `.pythonlibs/bin/python3.12`.
- Todas las `.replitignore` de la rama experimental `deploy/visor-3f67ecb-imagen-ligera-20261117`
  (desde su primer commit `88db71c`) excluían `.pythonlibs/`.
- En el contenedor publicado el enlace quedaba roto:
  - con `start.sh`: `.venv` parecía dañado → se recreaba → `pip install` contra PyPI, sin red en Autoscale → nunca se abría el puerto 5000 (error 2);
  - con `runtime_env` (también `home = .pythonlibs/bin`): `[[ -x runtime_env/bin/python ]]` falso →
    «runtime_env no esta disponible» → crash loop (error 4).
- La publicación `c482f32c` (15-nov, éxito) no tenía `.replitignore`: llevaba `.venv` y `.pythonlibs`
  completos y todavía cabía en 8 GiB. Después crecieron los cachés de Harmony (5,9 GiB) y `.git` (4,9 GiB)
  y se superó el límite (error 1).

## Corrección

Mismo `.replit` y mismo `start.sh` de `3f67ecb` (build `bash start.sh --verificar`, run `bash start.sh`),
más una `.replitignore` que excluye solo lo pesado e innecesario (`.git/`, `runtime_env/`,
`runtime_packages/`, cachés Harmony históricos) y **no** excluye `.venv/` ni `.pythonlibs/`.
`tests/test_publicacion_replit.py` impide repetir el error.

## Antes de publicar (Shell del Repl)

```bash
head -1 .venv/pyvenv.cfg                     # debe decir .pythonlibs/bin
readlink -f .venv/bin/python                 # debe existir (ruta /nix/store/...)
grep -n "ports" -A2 .replit                  # un solo puerto: 5000 -> 80
du -shc .venv .pythonlibs data/analisis data/contexto data/ia_lab data/nisar/catalogo \
  data/nisar/harmony/375d3135cd519661 data/nisar/harmony/3875345486d3a7c7 assets static | tail -1
bash start.sh --verificar
```

## Pendiente de verificar en producción

- Que Replit aplique `.replitignore` como en los intentos del 17-nov (la imagen pasó el límite de tamaño).
- Que las excepciones `!data/nisar/harmony/<id>/**` se respeten (si no, el modo jurado no tendrá el par
  de COG; los GeoTIFF de `data/analisis` sí).
- Secrets del despliegue (Earthdata/Harmony) para análisis nuevos en producción.
