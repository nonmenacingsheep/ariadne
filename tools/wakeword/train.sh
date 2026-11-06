#!/bin/bash
# Retrain "wake Aries" (after setup.sh), the recipe that shipped. Each step resumes: delete
# $WW/run to start over. Ronald games on this machine: every GPU step waits at godot-gate.sh
# until CPU and GPU are under 65%, and threads are capped so it never takes the whole box.
# Check nvidia-smi first. (Round 2's male-weighted recipe is in README.md; it did worse.)
set -euo pipefail
WW=${WW:-/var/mnt/storage/Software/AI/wakeword}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=$WW/venv/bin/python
GATE=$HOME/.local/bin/godot-gate.sh
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
cd "$WW"
R=$WW/run/wake_aries
mkdir -p "$R"
# 1. Synthesise: 30k positives and 30k near misses, plus 3k of each held out (~10 min).
$GATE "$PY" "$HERE/make_clips.py" --piper "$WW/piper-sample-generator" --out "$R" --batch 12
# 2. Rooms, noise and features, the four folders side by side (~15 min).
for d in positive_train negative_train positive_test negative_test; do
    $GATE "$PY" "$HERE/augment.py" "$R/$d" "$R/${d%_*}_features_${d#*_}.npy" \
        --rirs data/mit_rirs --background data/audioset_16k &
done
wait
# 3. Train (~10 min on a 4070), writing $WW/run/wake_aries.onnx, with logging on so its
#    accuracy/recall/false-positive summary is printed. It ends in a traceback about onnx_tf:
#    train.py's tflite step runs whatever its flag says. The .onnx is written by then.
$GATE "$PY" -c 'import logging, runpy, sys
logging.basicConfig(level=logging.INFO, format="%(message)s")
script, sys.argv = sys.argv[1], ["train.py", "--training_config", sys.argv[2], "--train_model"]
runpy.run_path(script, run_name="__main__")' \
    "$WW/openWakeWord/openwakeword/train.py" "$HERE/wake_aries.yml" || true
# 4. The figures: false accepts per hour, recall, near misses, and voices it never heard.
"$PY" "$HERE/evaluate.py" --model "$WW/run/wake_aries.onnx" --run "$R" \
    --val "$WW/data/validation_set_features.npy" --unseen "$WW/data/smoke" --json "$WW/run/metrics.json"
echo "if those beat the shipped model: cp $WW/run/wake_aries.onnx $HERE/../../ariadne2/core/ears/models/"
