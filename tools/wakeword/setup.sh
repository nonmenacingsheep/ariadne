#!/bin/bash
# One-time: the training venv and ~19 GB of data, all under $WW (Ronald's Storage drive).
# Safe to rerun: downloads resume and finished steps are skipped.
set -euo pipefail
WW=${WW:-/var/mnt/storage/Software/AI/wakeword}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WW/data/mit_rirs" "$WW/data/audioset_raw" "$WW/.pipcache" "$WW/tmp"
cd "$WW"
export PIP_CACHE_DIR=$WW/.pipcache TMPDIR=$WW/tmp
HF=https://huggingface.co/datasets

[ -d openWakeWord ] || git clone https://github.com/dscripka/openWakeWord.git
[ -d piper-sample-generator ] || git clone https://github.com/rhasspy/piper-sample-generator.git
[ -d venv ] || python3.12 -m venv venv
P=$WW/venv/bin/pip
$P install -q --upgrade pip setuptools wheel
# torch 2.5 keeps torchaudio's file loading, which openWakeWord's augmenter uses.
$P install -q torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
$P install -q -e openWakeWord -e piper-sample-generator
# scipy 1.14: acoustics (the coloured-noise augmenter) imports sph_harm, gone in 1.15;
# setuptools<81 still has pkg_resources, which torchmetrics 0.x imports.
$P install -q mutagen torchinfo "torchmetrics<1" "speechbrain<1" audiomentations==0.33.0 \
    torch-audiomentations==0.11.0 acoustics==0.2.6 pronouncing pyyaml "datasets<3" soundfile \
    onnx onnxscript "scipy==1.14.1" "numpy<2.3" "setuptools<81"

# The TTS generator: LibriTTS-R, 904 speakers.
wget -q -c -O piper-sample-generator/models/en_US-libritts_r-medium.pt \
    https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/en_US-libritts_r-medium.pt
# openWakeWord's shared front end (melspectrogram + speech embedding).
R=openWakeWord/openwakeword/resources/models; mkdir -p $R
for f in melspectrogram.onnx embedding_model.onnx; do
    wget -q -c -O $R/$f https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/$f
done
# Precomputed negatives (~2,000 h of ACAV100M, 17 GB) and the ~11 h false-accept validation set.
for f in openwakeword_features_ACAV100M_2000_hrs_16bit.npy validation_set_features.npy; do
    wget -q -c -O data/$f $HF/davidscripka/openwakeword_features/resolve/main/$f
done
# Room impulse responses (MIT survey, 16 kHz).
curl -s "https://huggingface.co/api/datasets/davidscripka/MIT_environmental_impulse_responses/tree/main/16khz" \
    | "$WW/venv/bin/python" -c "import json,sys; print('\n'.join(x['path'] for x in json.load(sys.stdin) if x['path'].endswith('.wav')))" \
    | while read -r p; do wget -q -c -P data/mit_rirs "$HF/davidscripka/MIT_environmental_impulse_responses/resolve/main/$p"; done
# Background audio: three shards of balanced AudioSet (~4 h of rooms, music, TV, traffic).
for n in 00 07 19; do
    wget -q -c -O data/audioset_raw/$n.parquet $HF/agkphysics/AudioSet/resolve/main/data/bal_train/$n.parquet
done
"$WW/venv/bin/python" -I "$HERE/prepare_background.py" data/audioset_raw/*.parquet --out data/audioset_16k
echo "setup done: $(du -sh "$WW" | cut -f1) in $WW"
