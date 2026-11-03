#!/bin/bash
# Generate her clips with Kimodo and bring them into the 3D body.
#   pet/import/kimodo_batch.sh [prompts.txt] [seeds per line, default 1]
#   pet/import/kimodo_batch.sh --pack       (no generating: re-pack what's there)
# Each line "role|seconds|prompt" -> kimodo_gen (BVH, standard T-pose) ->
# pet/assets/anims/kimodo/kimodo.glb (one GLB, an action per clip) -> Godot import.
# The Llama text encoder runs on the CPU (it needs ~17 GB VRAM on the GPU).
set -e
HERE=$(cd "$(dirname "$0")" && pwd); PET=$(dirname "$HERE")
K=/var/mnt/games/AI/Kimodo; OUT=$K/clips/aries; mkdir -p "$OUT"
LIST=${1:-$HERE/kimodo_prompts.txt}; SEEDS=${2:-1}
# (pet/import/kimodo_check.py checks stance clips; kimodo_keyed.py re-makes
# ones that need a pinned start or end pose.)
export HF_HOME=/var/mnt/games/AI/hf TEXT_ENCODER_DEVICE=cpu
GATE=$HOME/.local/bin/godot-gate.sh; [ -x "$GATE" ] || GATE=
# --pack: skip generating, just (re)cut loops and stops and pack what's there.
PACK_ONLY=0; [ "${1:-}" = "--pack" ] && PACK_ONLY=1
if [ $PACK_ONLY = 0 ]; then
# Llama (16 GB) loads once, in Kimodo's text-encoder server on this machine
# only, with a share of the CPU; each kimodo_gen then just asks it.
OMP_NUM_THREADS=${KIMODO_THREADS:-8} GRADIO_SERVER_NAME=127.0.0.1 "$K/.venv/bin/kimodo_textencoder" > "$OUT/../encoder.log" 2>&1 &
ENC=$!; trap 'kill $ENC 2>/dev/null' EXIT
echo "loading the text encoder..."
for i in $(seq 1 180); do
  curl -s -o /dev/null http://127.0.0.1:9550/ && break
  kill -0 $ENC 2>/dev/null || { echo "the text encoder didn't start; see $OUT/../encoder.log"; exit 1; }
  sleep 5
done
grep -v '^\s*#' "$LIST" | grep '|' | while IFS='|' read -r role secs prompt; do
  for s in $(seq 1 "$SEEDS"); do
    name=$role; [ "$SEEDS" -gt 1 ] && name="${role}_s$s"
    [ -f "$OUT/$name.npz" ] && continue                     # already made: keep it
    echo "== $name: $prompt"
    OMP_NUM_THREADS=${KIMODO_THREADS:-8} $GATE "$K/.venv/bin/kimodo_gen" "$prompt" --duration "$secs" --seed "$s" --output "$OUT/$name" --bvh --bvh_standard_tpose
  done
done
fi
# Locomotion takes (walk_, stroll_, strafe_, jog_, carry_walk_) go in as
# seamless loops (kimodo_loop.py), stops as their last steps (kimodo_stop.py);
# everything else as generated.
LOOPS=$K/clips/loops; mkdir -p "$LOOPS"
for f in "$OUT"/*.npz; do
  n=$(basename "$f" .npz)
  case "$n" in
    walk_*|stroll_*|strafe_*|jog_*|carry_walk_*)
      [ -f "$LOOPS/$n.bvh" ] || "$K/.venv/bin/python" "$HERE/kimodo_loop.py" "$f" "$LOOPS/$n.bvh"
      rm -f "$OUT/$n.bvh" ;;
    stop_*)
      [ -f "$LOOPS/$n.bvh" ] || "$K/.venv/bin/python" "$HERE/kimodo_stop.py" "$f" "$LOOPS/$n.bvh"
      rm -f "$OUT/$n.bvh" ;;
  esac
done
# (not a take still being made or re-rolled: <name>_try.bvh)
$GATE blender -b --python "$HERE/bvh_to_glb.py" -- "$PET/assets/anims/kimodo/kimodo.glb" $(ls "$OUT"/*.bvh | grep -v '_try\.bvh$') "$LOOPS"/*.bvh
# (kimodo.glb.import, committed, holds the retarget settings)
rm -f "$PET"/.godot/imported/kimodo.glb-*
$GATE /var/mnt/games/DevTools/godot-4.7.2/Godot_v4.7.2-stable_linux.x86_64 --headless --path "$PET" --import >/dev/null 2>&1
echo "done: $(ls "$OUT"/*.bvh "$LOOPS"/*.bvh | wc -l) clips in $PET/assets/anims/kimodo/kimodo.glb"
