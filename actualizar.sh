#!/usr/bin/env bash
# Actualiza este proyecto desde GitHub sin perder nada.
#
#   bash actualizar.sh                 trae lo nuevo de la rama actual
#   bash actualizar.sh main            cambia a main (versión estable) y la actualiza
#   bash actualizar.sh feature/x       cambia a una rama de pruebas y la actualiza
#   bash actualizar.sh --guardar [rama]  igual, pero antes aparta tus cambios locales (git stash)
#   bash actualizar.sh --volver        regresa a la versión que había antes de la última actualización
#
# Garantías:
#   - Nunca descarta cambios locales: si los hay, se detiene y te dice qué hacer.
#   - Solo avanza la rama (fast-forward); no reescribe ni fusiona historia.
#   - No toca los Secrets de Replit: viven en el Repl, no en Git.
#   - Después de actualizar prepara las dependencias (bash start.sh --verificar).
set -euo pipefail
cd "$(dirname "$0")"

# Todo va dentro de una función para que bash lea el guion completo antes de
# ejecutarlo: al cambiar de rama este mismo archivo puede cambiar o desaparecer.
principal() {
    ANTERIOR=".visor_anterior"
    fallo() { echo "ERROR: $*" >&2; exit 1; }

    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fallo "esta carpeta no es un repositorio Git."

    GUARDAR=0; VOLVER=0; RAMA=""
    for arg in "$@"; do
        case "$arg" in
            --guardar) GUARDAR=1 ;;
            --volver) VOLVER=1 ;;
            -*) fallo "opción desconocida: $arg" ;;
            *) RAMA="$arg" ;;
        esac
    done

    rama_actual() { git symbolic-ref --quiet --short HEAD 2>/dev/null || echo ""; }

    # Las versiones antiguas (v1.0) no tienen el arranque automático: su start.sh
    # no admite --verificar y se deja tal cual.
    preparar_dependencias() {
        if [ -f start.sh ] && grep -q -- "--verificar" start.sh; then
            bash start.sh --verificar
        else
            echo "Esta versión no prepara dependencias automáticamente; se deja como está."
        fi
    }

    # --- 1. Cambios locales: nunca se descartan ---------------------------------
    # Se miran los archivos que Git ya sigue. Los archivos nuevos sin registrar no
    # corren riesgo: Git se niega a actualizar si alguno fuera a ser reemplazado.
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        echo "Tienes cambios locales sin guardar en Git:"
        git status --short --untracked-files=no
        if [ "$GUARDAR" = 1 ]; then
            nombre="visor-antes-de-actualizar-$(date +%Y%m%d-%H%M%S)"
            git stash push --message "$nombre" >/dev/null
            echo "Se apartaron con git stash como '$nombre'."
            echo "Para recuperarlos después:  git stash pop"
        else
            echo
            echo "No se actualizó nada. Elige una opción:"
            echo "  a) Guardarlos en Git:        git add -A && git commit -m \"mis cambios\""
            echo "  b) Apartarlos y actualizar:  bash actualizar.sh --guardar ${RAMA}"
            exit 2
        fi
    fi

    # --- 2. Volver a la versión anterior -----------------------------------------
    if [ "$VOLVER" = 1 ]; then
        [ -f "$ANTERIOR" ] || fallo "no hay una versión anterior registrada. Para la versión estable: bash actualizar.sh main"
        read -r rama_previa commit_previo < "$ANTERIOR"
        if [ "$rama_previa" != "-" ] && [ "$(git rev-parse --verify --quiet "$rama_previa" || true)" = "$commit_previo" ]; then
            git checkout --quiet "$rama_previa"
            echo "De vuelta en la rama $rama_previa ($(git rev-parse --short HEAD))."
        else
            git checkout --quiet --detach "$commit_previo"
            echo "De vuelta en el commit $(git rev-parse --short HEAD) (modo de solo consulta, sin rama)."
            echo "Para retomar el trabajo normal:  bash actualizar.sh <rama>"
        fi
        echo "Preparando dependencias de esa versión…"
        preparar_dependencias
        echo "Listo. Pulsa Run."
        exit 0
    fi

    # --- 3. Descargar y avanzar ---------------------------------------------------
    [ -n "$RAMA" ] || RAMA="$(rama_actual)"
    [ -n "$RAMA" ] || fallo "no estás en ninguna rama. Indica una: bash actualizar.sh main"

    previa="$(rama_actual)"
    echo "${previa:--} $(git rev-parse HEAD)" > "$ANTERIOR"

    echo "Descargando '$RAMA' desde GitHub…"
    git fetch --quiet origin "+refs/heads/$RAMA:refs/remotes/origin/$RAMA" \
        || fallo "no se pudo descargar la rama '$RAMA'. Revisa el nombre y la conexión."

    if git show-ref --verify --quiet "refs/heads/$RAMA"; then
        git checkout --quiet "$RAMA" || fallo "Git no pudo cambiar a '$RAMA'. No se perdió nada; revisa el mensaje de arriba."
    else
        git checkout --quiet -b "$RAMA" --track "origin/$RAMA" \
            || fallo "Git no pudo cambiar a '$RAMA'. No se perdió nada; revisa el mensaje de arriba."
    fi

    antes="$(git rev-parse --short HEAD)"
    if ! git merge --quiet --ff-only "origin/$RAMA" 2>/dev/null; then
        echo "ERROR: tu copia de '$RAMA' tiene commits propios que no están en GitHub." >&2
        echo "No se cambió nada. Súbelos a GitHub desde el panel Git, o pide ayuda antes de continuar." >&2
        exit 3
    fi
    despues="$(git rev-parse --short HEAD)"

    if [ "$antes" = "$despues" ]; then
        echo "Ya estabas al día en '$RAMA' ($despues)."
    else
        echo "Actualizado '$RAMA': $antes → $despues"
        git log --oneline "$antes..$despues" | head -n 10
    fi

    # --- 4. Dependencias ----------------------------------------------------------
    echo
    if preparar_dependencias; then
        echo
        echo "Listo. Pulsa Run. Si la app ya estaba abierta, pulsa antes Stop: durante la"
        echo "actualización Streamlit puede mezclar archivos viejos y nuevos en memoria"
        echo "(p. ej. «cannot import name ...»). Reiniciar lo resuelve; no toca data/."
        echo "Para comprobar esta versión con tus datos reales (solo lectura): bash verificar.sh"
    else
        echo
        echo "La nueva versión no pasó la verificación." >&2
        echo "Para regresar a la anterior:  bash actualizar.sh --volver" >&2
        exit 1
    fi
}

principal "$@"
exit $?
