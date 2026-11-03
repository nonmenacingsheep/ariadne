#!/bin/bash
# Generate her clips with Kimodo and bring them into the 3D body.
#   pet/import/kimodo_batch.sh [prompts.txt] [seeds per line, default 1]
# Each line "role|seconds|prompt" -> kimodo_gen (BVH, standard T-pose) ->
# pet/assets/anims/kimodo/kimodo.glb (one GLB, an action per clip) -> Godot import.
# The Llama text encoder runs on the CPU (it needs ~17 GB VRAM on the GPU).
set -e
HERE=$(cd "$(dirname "$0")" && pwd); PET=$(dirname "$HERE")
K=/var/mnt/games/AI/Kimodo; OUT=$K/clips/aries; mkdir -p "$OUT"
LIST=${1:-$HERE/kimodo_prompts.txt}; SEEDS=${2:-1}
export HF_HOME=/var/mnt/games/AI/hf TEXT_ENCODER_DEVICE=cpu
GATE=$HOME/.local/bin/godot-gate.sh; [ -x "$GATE" ] || GATE=
grep -v '^\s*#' "$LIST" | grep '|' | while IFS='|' read -r role secs prompt; do
  for s in $(seq 1 "$SEEDS"); do
    name=$role; [ "$SEEDS" -gt 1 ] && name="${role}_s$s"
    [ -f "$OUT/$name.bvh" ] && continue                     # already made: keep it
    echo "== $name: $prompt"
    $GATE "$K/.venv/bin/kimodo_gen" "$prompt" --duration "$secs" --seed "$s" --output "$OUT/$name" --bvh --bvh_standard_tpose
  done
done
$GATE blender -b --python "$HERE/bvh_to_glb.py" -- "$PET/assets/anims/kimodo/kimodo.glb" "$OUT"/*.bvh
# (kimodo.glb.import, committed, holds the retarget settings)
rm -f "$PET"/.godot/imported/kimodo.glb-*
$GATE /var/mnt/games/DevTools/godot-4.7.2/Godot_v4.7.2-stable_linux.x86_64 --headless --path "$PET" --import >/dev/null 2>&1
echo "done: $(ls "$OUT"/*.bvh | wc -l) clips in $PET/assets/anims/kimodo/kimodo.glb"
