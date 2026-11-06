#!/bin/bash
# Retrain "wake Aries" (after setup.sh). Each step resumes: delete $WW/run to start over.
# Ronald games on this machine: every GPU step waits at godot-gate.sh until CPU and GPU are
# under 65%, and threads are capped so it never takes the whole box. Check nvidia-smi first.
set -euo pipefail
WW=${WW:-/var/mnt/storage/Software/AI/wakeword}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=$WW/venv/bin/python
GATE=$HOME/.local/bin/godot-gate.sh
export OMP_NUM_THREADS=8 MKL_NUM_THREADS=8
cd "$WW"
# 1. Synthesise: 30k positives and 30k near misses, plus 3k of each held out (~10 min).
$GATE "$PY" "$HERE/make_clips.py" --piper "$WW/piper-sample-generator" --out "$WW/run/wake_aries" --batch 12
# 2. Mix in rooms and noise, and compute openWakeWord features (~15 min).
$GATE "$PY" "$WW/openWakeWord/openwakeword/train.py" --training_config "$HERE/wake_aries.yml" --augment_clips
# 3. Train (~30 min on a 4070), writing $WW/run/wake_aries.onnx.
$GATE "$PY" "$WW/openWakeWord/openwakeword/train.py" --training_config "$HERE/wake_aries.yml" --train_model
# 4. The figures: false accepts per hour, recall, near misses.
"$PY" "$HERE/evaluate.py" --model "$WW/run/wake_aries.onnx" --run "$WW/run/wake_aries" \
    --val "$WW/data/validation_set_features.npy" --json "$WW/run/metrics.json"
echo "if those are good: cp $WW/run/wake_aries.onnx $HERE/../../ariadne2/core/ears/models/"
