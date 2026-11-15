#!/usr/bin/env bash
# Corta el video maestro de ECO en 4 bucles ligeros (sin audio) para la interfaz.
# Uso: bash scripts/preparar_eco.sh ruta/al/video_maestro.mp4
# Salida: static/eco/eco_0N_<estado>.{webm,mp4,webp}. El video maestro NO se versiona.
set -euo pipefail
V="${1:?Falta la ruta del video maestro}"
OUT="$(dirname "$0")/../static/eco"; mkdir -p "$OUT"
LADO=320; X=0.4                      # lado en px y duración del fundido de bucle (s)
RECORTE="crop=720:720:280:0,scale=${LADO}:${LADO}:flags=lanczos,fps=24"
# nombre inicio fin(con fundido)   El bucle sin costura: el final se funde con el inicio.
bucle() {
  local nombre=$1 ini=$2 fin=$3; local D; D=$(python3 -c "print(round($fin-$ini,3))")
  local OFF; OFF=$(python3 -c "print(round($D-2*$X,3))")
  local F="[0:v]${RECORTE},split[a][b];[a]trim=${X}:${D},setpts=PTS-STARTPTS[m];[b]trim=0:${X},setpts=PTS-STARTPTS[h];[m][h]xfade=transition=fade:duration=${X}:offset=${OFF},format=yuv420p[v]"
  codificar "$nombre" "$ini" "$D" "$F"
}
# Ida y vuelta (para gestos cortos como el pulgar arriba).
vaiven() {
  local nombre=$1 ini=$2 fin=$3; local D; D=$(python3 -c "print(round($fin-$ini,3))")
  local F="[0:v]${RECORTE},split[a][b];[b]reverse,trim=start_frame=1,setpts=PTS-STARTPTS[r];[a][r]concat=n=2:v=1,format=yuv420p[v]"
  codificar "$nombre" "$ini" "$D" "$F"
}
codificar() {
  local nombre=$1 ini=$2 D=$3 F=$4
  ffmpeg -v error -y -ss "$ini" -t "$D" -i "$V" -filter_complex "$F" -map "[v]" -an \
    -c:v libvpx-vp9 -b:v 0 -crf 40 -row-mt 1 -deadline good "$OUT/$nombre.webm"
  ffmpeg -v error -y -ss "$ini" -t "$D" -i "$V" -filter_complex "$F" -map "[v]" -an \
    -c:v libx264 -preset slow -crf 30 -movflags +faststart "$OUT/$nombre.mp4"
  ffmpeg -v error -y -i "$OUT/$nombre.mp4" -frames:v 1 -c:v libwebp -quality 80 "$OUT/$nombre.webp"
}
bucle  eco_01_saludo  0.0 2.4
bucle  eco_02_enfoque 2.0 4.4
bucle  eco_03_escaneo 5.2 7.6
vaiven eco_04_listo   9.0 10.0
ls -la "$OUT"
