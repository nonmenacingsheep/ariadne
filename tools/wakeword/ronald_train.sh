#!/bin/bash
# Retrain "hey Aries" with Ronald's own recordings added (what shipped, 2026-11-06). Needs round 1's
# synthetic run in $WW/run_hey (train.sh, or at least its clips and features) and his takes cut by
# ronald_segment.py + ronald_build.py into $WW/data/ronald/clips. Nothing from his voice goes in the repo.
# Check nvidia-smi first; every heavy step waits at godot-gate.sh.
set -euo pipefail
WW=${WW:-/var/mnt/storage/Software/AI/wakeword}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=$WW/venv/bin/python
CORE=${CORE:-$HOME/Claude\ Projects/ariadne/.venv-3.12/bin/python}
GATE=$HOME/.local/bin/godot-gate.sh
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
cd "$WW"
O=$WW/run_hey2/hey_aries
mkdir -p "$O"
# The synthetic clips and the held-out features are round 1's (linked, not copied).
for d in positive_train positive_test negative_train negative_test; do ln -sfn "$WW/run_hey/hey_aries/$d" "$O/$d"; done
for f in positive_features_test negative_features_test; do ln -sf "$WW/run_hey/hey_aries/$f.npy" "$O/$f.npy"; done
# His training clips (40 copies of each take, a random speed each; Part C windows) get rooms and
# noise like the rest, and are put in front of round 1's 30,000 + 30,000.
for k in positive negative; do
    src=pos; [ $k = negative ] && src=neg
    $GATE "$PY" "$HERE/augment.py" "data/ronald/clips/${src}_train" "$O/${k}_features_train.npy" \
        --rirs data/mit_rirs --background data/audioset_16k --also "run_hey/hey_aries/${k}_features_train.npy" &
done
wait
sed 's#wakeword/run_hey"#wakeword/run_hey2"#' "$HERE/hey_aries.yml" > run_hey2/hey_aries.yml
$GATE "$PY" -c 'import logging, runpy, sys
logging.basicConfig(level=logging.INFO, format="%(message)s")
script, sys.argv = sys.argv[1], ["train.py", "--training_config", sys.argv[2], "--train_model"]
runpy.run_path(script, run_name="__main__")' \
    "$WW/openWakeWord/openwakeword/train.py" "$WW/run_hey2/hey_aries.yml" || true      # onnx_tf traceback: ignore
"$PY" "$HERE/evaluate.py" --model "$WW/run_hey2/hey_aries.onnx" --run "$O" \
    --val "$WW/data/validation_set_features.npy" --unseen "$WW/data/smoke_hey" --json "$WW/run_hey2/metrics.json"
$GATE "$CORE" "$HERE/ronald_eval.py" "$WW/run_hey2/hey_aries.onnx" "$WW/data/ronald/clips" "$WW/data/smoke_hey"
