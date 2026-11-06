# The "wake Aries" model

Her ears listen for "wake Aries" (said *wake AIR-eez*) with a small model of their own,
`ariadne2/core/ears/models/wake_aries.onnx`, run by [openWakeWord](https://github.com/dscripka/openWakeWord)
on the CPU. Whisper isn't loaded until it fires (see `ariadne2/core/ears/wakeword.py`).
This folder is how that model was made, and how to make it again.

It is trained on synthetic speech only: 30,000 "wake Aries" clips from Piper's LibriTTS-R
generator (904 speakers, every clip a fresh blend of two, at speeds from quick to slow),
30,000 near misses ("make a ruse", "wake up", "Aries", "hey Aries", "wait, Harry's", ...; the
list is `NEAR_MISSES` in `make_clips.py`, plus openWakeWord's phoneme-overlap generator),
mixed into rooms (MIT impulse responses) and noise (balanced AudioSet), against ~2,000 hours
of precomputed generic negatives (ACAV100M).

## Files

| file | what |
|---|---|
| `setup.sh` | one time: the training venv and ~19 GB of data under `$WW` |
| `train.sh` | synthesise, augment, train, evaluate (resumable) |
| `make_clips.py` | the positive and near-miss clips |
| `prepare_background.py` | AudioSet parquet shards to 16 kHz WAVs |
| `wake_aries.yml` | openWakeWord's training config (paths point at `$WW`) |
| `generate_samples.py` | a stand-in train.py imports; the clips come from `make_clips.py` |
| `evaluate.py` | false accepts per hour, recall, near-miss rate at several thresholds |

`$WW` is `/var/mnt/storage/Software/AI/wakeword` (Ronald's Storage drive; nothing goes on the
nearly full games drive). The data, the venv and every run stay there; only these scripts and
the finished `.onnx` are in the repo.

## Retraining

```sh
tools/wakeword/setup.sh            # once (~19 GB, ~10 min on a fast line)
nvidia-smi                         # he games on this machine: utilisation under 30%, no game running
tools/wakeword/train.sh            # ~50 min (35 of it CPU-bound augmenting); GPU steps wait at godot-gate.sh
cp /var/mnt/storage/Software/AI/wakeword/run/wake_aries.onnx ariadne2/core/ears/models/
```

To change what it must not wake on, add to `NEAR_MISSES` in `make_clips.py`, delete
`$WW/run/wake_aries/negative_*` and the `*_features_*.npy` beside them, and run `train.sh`
again (it regenerates only what is missing). A different phrase means a new `target_phrase`,
`POSITIVE` and `model_name`, and `PHRASE`/`NAME`/`MODEL` in `ears/wakeword.py`.

## Sensitivity

`THRESHOLD` in `ariadne2/core/ears/wakeword.py` (default 0.2). Lower hears him from further
away or mumbling, and wakes on the room more often; `evaluate.py` prints both at 0.1 to 0.9.
After a wake the model starts afresh, so one phrase can't wake her twice.

`train.sh` ends in a traceback about `onnx_tf`: train.py's tflite step runs whatever its flag
says (its default is the string "False"). The `.onnx` is already written by then.

## The model that shipped (2026-11-05)

`max_negative_weight: 1500`, 50,000 steps plus the two shorter refinement passes; training
itself took 10 minutes on the 4070. Figures from `evaluate.py` (11.3 h validation set; 3,000
held-out positives and near misses; "unseen" is 54 "wake Aries" and 180 near-miss clips in six
Piper voices it never heard, end to end):

| threshold | false accepts / h | recall, augmented | recall, clean | near-miss accepts | unseen recall | unseen near-miss accepts |
|---|---|---|---|---|---|---|
| 0.1 | 0.27 | 0.32 | 0.93 | 0.6% | 0.85 | 0 |
| **0.2** | **0.18** | **0.30** | **0.92** | **0.4%** | **0.83** | **0** |
| 0.3 | 0.18 | 0.28 | 0.91 | 0.3% | 0.82 | 0 |
| 0.5 | 0.18 | 0.25 | 0.90 | 0.3% | 0.76 | 0 |
| 0.7 | 0 | 0.23 | 0.87 | 0.2% | 0.70 | 0 |

"Augmented" is the held-out clips buried in noise at -10 to 15 dB SNR and room reverb: the
worst case, not his desk. Through the real ears at 0.2 (Ears, Listener and Spotter, a fake
recorder playing the unseen clips over room noise): 42 of 54 woke her, all 18 "wake Aries,
play some music" did, and 1 of 180 near misses did ("Wake Harry." in one male voice). Misses
were mostly two male voices saying it quickly or with a comma ("Wake, Aries!").

A second run at `max_negative_weight: 500` heard more (unseen 0.89 at 0.5) but woke on the
room 1.8 times an hour at 0.5 and was no better than this one at equal false accepts (0.27/h
at 0.9: unseen 0.87, clean 0.88). It is kept as `$WW/run/wake_aries_w500.onnx`.
