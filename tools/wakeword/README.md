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
| `setup.sh` | one time: the training venv and ~20 GB of data under `$WW` |
| `train.sh` | synthesise, augment, train, evaluate: the recipe that shipped (resumable) |
| `make_clips.py` | the positive and near-miss clips (`--voices`: round 2's voice mix) |
| `augment.py` | rooms, noise and features for one folder, so all four run at once (`--also` appends earlier features) |
| `voices.py` | round 2: every speaker's pitch, to find the low (male-range) voices |
| `prepare_background.py` | AudioSet parquet shards to 16 kHz WAVs |
| `wake_aries.yml` | openWakeWord's training config (paths point at `$WW`) |
| `generate_samples.py` | a stand-in train.py imports; the clips come from `make_clips.py` |
| `evaluate.py` | false accepts per hour, recall, near-miss rate at several thresholds |
| `unseen_clips.py` | test clips in six Piper voices no training clip uses |
| `ears_sweep.py` | those clips through her real ears (Ears, Listener, Spotter) over room noise, at every threshold; run it with the core's venv |

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

`THRESHOLD` in `ariadne2/core/ears/wakeword.py` (default 0.1). Lower hears him from further
away or mumbling, and wakes on the room more often; `evaluate.py` and `ears_sweep.py` print
both at 0.05 to 0.9. 0.05 still keeps under half a false wake an hour (0.44) and hears a little
more (86% through the ears); below that the false wakes climb fast (0.8 an hour at 0.02).
After a wake the model starts afresh, so one phrase can't wake her twice.

`train.sh` ends in a traceback about `onnx_tf`: train.py's tflite step runs whatever its flag
says (its default is the string "False"). The `.onnx` is already written by then.

## The model that shipped (2026-11-05)

`max_negative_weight: 1500`, 50,000 steps plus the two shorter refinement passes; training
itself took 10 minutes on the 4070. (train.py always doubles the negative weight twice for those
passes, whatever `target_false_positives_per_hour` says: `best_val_fp` is never updated upstream.
So the weight really ends at 6,000.) Figures from `evaluate.py` (11.3 h validation set; 3,000
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
worst case, not his desk. At 0.05, 0.08 and 0.15 the false accepts are 0.44, 0.35 and 0.18 an
hour.

Through her real ears (`ears_sweep.py`, three room-noise seeds pooled; low room noise costs a
few clips against digital silence, and moves the count by about 3 of 54 from seed to seed):

| threshold | "wake Aries" woke her | with a command after | near misses woke her |
|---|---|---|---|
| 0.05 | 139/162 (86%) | 53/54 | 5/540 |
| **0.1** | **136/162 (84%)** | **53/54** | **4/540** |
| 0.2 | 130/162 (80%) | 51/54 | 3/540 |
| 0.5 | 112/162 (69%) | 47/54 | 1/540 |

Misses are mostly two male voices (en_GB-alan, en_US-joe) saying it quickly or with a comma
("Wake, Aries!"); the near miss that wakes her is "Wake Harry." Shipped at 0.2 first, then
lowered to 0.1 (0.27 false accepts an hour) after round 2.

A second run at `max_negative_weight: 500` heard more (unseen 0.89 at 0.5) but woke on the
room 1.8 times an hour at 0.5 and was no better than this one at equal false accepts (0.27/h
at 0.9: unseen 0.87, clean 0.88). It is kept as `$WW/run/wake_aries_w500.onnx`.

## Round 2 (2026-11-06): weighted to male voices -- did worse, not shipped

Aimed at the misses above, since Ronald is male: `voices.py` sorted every speaker by pitch
(522 of the generator's 904 under 155 Hz; 523 low speakers across 17 Piper voices, including
VCTK, CMU Arctic, L2-Arctic and both LibriTTS voices, the six test voices left out), then
`make_clips.py --voices` made 30k positives and 30k near misses where three in four clips are a
low voice, a third come from Piper's own voices, speeds reach 0.62, a fifth are muffled and
quieter, and the phrase also comes with a pause ("wake, Aries", "wake... Aries") or at the end
of a sentence ("okay, wake Aries"). New near misses: "wake Harry", "wake Ari", "wake carries",
"make Aries" and their pause and lead-in forms (`NEAR_MISSES_2`). Trained on those plus round 1's
clips (60k of each, `augment.py --also`), 100,000 steps, at three negative weights:

| model | false accepts / h at the threshold below | through the ears (162) | unseen, clip by clip |
|---|---|---|---|
| shipped, 0.1 | 0.27 | 136 (84%) | 0.85 |
| round 2, weight 1500, 0.2 | 0.18 | 90 (56%) | 0.80 |
| round 2, weight 1000, 0.2 | <= 0.18 | 117 (72%) | -- |
| round 2, weight 500, 0.5 | 0.27 | 116 (72%) | 0.85 |
| round 2, weight 500, 0.2 | 0.71 | 125 (77%) | 0.93 |

On its own held-out clips (the new mix) round 2 does better than round 1 (clean recall 0.79 vs
0.68 at 0.2), so it learned what it was shown; it just doesn't carry to voices it never heard.
The likeliest reason is the near misses: "make Aries", "wake, Harry" and "wake, Ari" in the same
voices and with the same pauses as the positives leave it little but one consonant to go on, and
the weighting step above then pushes it to say no. The models, clips and features are in
`$WW/run2*` if anyone wants to try round 2's positives without `NEAR_MISSES_2`. (To reproduce:
`voices.py --voices $WW/data/train_voices`, `make_clips.py --voices`, `augment.py --also` for the
two training folders, `output_dir: .../run2`, `steps: 100000`.)
