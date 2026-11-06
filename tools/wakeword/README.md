# The "hey Aries" model

Her ears listen for "hey Aries" (said *hey AIR-eez*) with a small model of their own,
`ariadne2/core/ears/models/hey_aries.onnx`, run by [openWakeWord](https://github.com/dscripka/openWakeWord)
on the CPU. Whisper isn't loaded until it fires (see `ariadne2/core/ears/wakeword.py`).
This folder is how that model was made, and how to make it again.

It is trained on 30,000 synthetic "hey Aries" clips from Piper's LibriTTS-R generator (904 speakers,
every clip a fresh blend of two, at speeds from quick to slow) plus 157 of Ronald's own takes at 40
copies each (6,280), against 30,000 synthetic near misses plus his own near-miss lines and normal
talking (1,371); all of it mixed into rooms (MIT impulse responses) and noise (balanced AudioSet), and
~2,000 hours of precomputed generic negatives (ACAV100M). The near misses are `NEAR_MISSES` in
`make_clips.py` ("hey there", "hey Harry", "hey Siri", "Aries", "okay Aries", "wake Aries", ...) plus
openWakeWord's phoneme-overlap generator. His recordings and everything cut from them stay in
`$WW/data/ronald`, never in the repo.

## Files

| file | what |
|---|---|
| `setup.sh` | one time: the training venv and ~20 GB of data under `$WW` |
| `train.sh` | synthesise, augment, train, evaluate on synthetic voices alone: round 1's recipe (resumable; `OUT`/`NAME` choose the run folder and model) |
| `ronald_train.sh` | the model that shipped: `train.sh`'s clips plus his recordings (below) |
| `recording_script.md`, `recording_part_c.md` | what he was asked to record |
| `ronald_segment.py` | his Part A+B recording split at silences, each take transcribed (Whisper, CPU) |
| `ronald_build.py` | the takes labelled by block and transcript, a fifth held out, training clips made |
| `ronald_eval.py` | his held-out takes, near misses and talking through her real ears, by block and threshold |
| `make_clips.py` | the synthetic positives and near misses (`--voices`: round 2's voice mix) |
| `augment.py` | rooms, noise and features for one folder, so all four run at once (`--also` appends earlier features) |
| `voices.py` | round 2: every speaker's pitch, to find the low (male-range) voices |
| `prepare_background.py` | AudioSet parquet shards to 16 kHz WAVs |
| `hey_aries.yml` | openWakeWord's training config (paths point at `$WW`) |
| `generate_samples.py` | a stand-in train.py imports; the clips come from `make_clips.py` |
| `evaluate.py` | false accepts per hour, recall, near-miss rate at several thresholds |
| `unseen_clips.py` | test clips in six Piper voices no training clip uses, plus the retired "wake Aries" |
| `ears_sweep.py` | those clips through her real ears (Ears, Listener, Spotter) over room noise, at every threshold; run it with the core's venv |

`$WW` is `/var/mnt/storage/Software/AI/wakeword` (Ronald's Storage drive; nothing goes on the
nearly full games drive). The data, the venv and every run stay there; only these scripts and
the finished `.onnx` are in the repo.

## Retraining

```sh
tools/wakeword/setup.sh            # once (~19 GB, ~10 min on a fast line)
nvidia-smi                         # he games on this machine: utilisation under 30%, no game running
tools/wakeword/train.sh            # synthetic voices only, ~35 min -> $WW/run_hey/hey_aries.onnx
# his own voice on top (recordings in ~/Downloads, copied to $WW/data/ronald as ab16.wav and c16.wav, mono 16 kHz):
core-venv/python tools/wakeword/ronald_segment.py $WW/data/ronald    # ~10 min on the CPU
$WW/venv/bin/python tools/wakeword/unseen_clips.py $WW/data/voices $WW/data/smoke_hey
$WW/venv/bin/python tools/wakeword/ronald_build.py $WW/data/ronald   # then ronald_train.sh, ~15 min
cp $WW/run_hey2/hey_aries.onnx ariadne2/core/ears/models/
```

`ronald_build.py` has the block ranges of his recording (segment indices), so a new recording needs
`BLOCKS`, `A7_PAIRS` and `NEAR` checked against `segs2.json` (print it: index, time, transcript).
To change what it must not wake on, add to `NEAR_MISSES` in `make_clips.py`, delete
`$WW/run_hey/hey_aries/negative_*` and the `*_features_*.npy` beside them, and run `train.sh`
again (it regenerates only what is missing). A different phrase means a new `target_phrase`,
`POSITIVE` and `model_name`, and `PHRASE`/`NAME`/`MODEL` in `ears/wakeword.py`.

## Sensitivity

`THRESHOLD` in `ariadne2/core/ears/wakeword.py` (0.3). Lower hears him from further away or
mumbling, and wakes on the room more often; `evaluate.py` and `ronald_eval.py` print both at 0.05
to 0.9. After a wake the model starts afresh, so one phrase can't wake her twice.

`train.sh` ends in a traceback about `onnx_tf`: train.py's tflite step runs whatever its flag
says (its default is the string "False"). The `.onnx` is already written by then.

## The model that shipped (2026-11-06): "hey Aries", with his own voice

Why his voice: the same recipe on synthetic voices alone (run `$WW/run_hey`) reached only 60% through
the ears (98/162 at 0.1, 0.8 false accepts an hour, "Hey Harry" waking half the time) and was not
shipped. Piper's voices are not his mouth or his mic.

**What he recorded** (headset mic through EasyEffects, mono 44.1 kHz FLAC, 7:41 for Parts A and B and
4:13 for Part C). He left about a second between takes, not two, so the split is at gaps of 0.2 s over a
floor that follows the room, and a transcript of each stretch (Whisper writes "Aries" as Ares, areas,
Arius...) plus its position decides what it is: blocks are told apart by gaps of five seconds or more
(all eight turned up, in order). A stretch whose transcript doesn't look like "hey Aries" was left out (about 8,
mostly mumbled ones Whisper heard as "Here's" or "Who those?"), and so was a lone "Aries" in a7. Takes: 197 "hey Aries" (a1 26, a2 23, a3 24, a4 26, a5 25, a6 24, a7 23, a8 26;
a4's trained on the phrase alone, cut where Whisper's word timestamps put the end of "Aries"). **Part B
was recorded only in part**: hey Harry x2, hey Ari x2, hey Siri x2, wake Aries x2, "hey, what's going on?",
"hey, why'd you do that?", "hey" (14 stretches, of the ~70 asked for: no "hey Ares", "hey arrays",
b2 or b3 sentences). Part C: 253 s of normal talking.

**Split.** One take in five of every block is held out (40 takes, 5 per block, never trained on).
Of Part B, one of each pair of hey Harry / hey Ari / hey Siri / wake Aries and "hey, why'd you do that"
is held out (5; the rest, 6 clips, train as negatives). Part C is held out in three 10 s stretches of
every ten (7 stretches, 70 s; the other 18 train as 377 windows of 1.9 s at a 0.4 s hop).

**Weighting.** His 157 training takes are repeated 40 times (6,280 clips, about 17% of the 36,280
positives, so about 17 of every 100 positives in a batch are him), each copy at a random speed
(0.9 to 1.1) and its own rooms and noise; his near-miss lines also 40 times, Part C windows 3 times
(1,371 negatives next to 30,000 synthetic). Round 1's settings otherwise (`max_negative_weight` 1500,
50,000 steps plus the two refinement passes; about 10 minutes on the 4070 once the features exist).

Through her real ears (`ronald_eval.py`: each held-out clip over low room noise, three noise seeds
pooled; "talk" is the 7 held-out stretches of Part C, 3.5 minutes pooled):

| threshold | his "hey Aries" (40 x 3) | per block a1..a8 | his near misses (5 x 3) | talk, 3.5 min | validation false accepts / h |
|---|---|---|---|---|---|
| 0.1 | 116/120 (97%) | 15 15 12 15 14 15 15 15 | 3 | 0 | 0.53 |
| 0.2 | 115/120 (96%) | 15 15 12 15 13 15 15 15 | 3 | 0 | 0.35 |
| **0.3** | **114/120 (95%)** | **15 15 12 15 12 15 15 15** | **3** | **0** | **0.35** |
| 0.5 | 114/120 (95%) | 15 15 12 15 12 15 15 15 | 3 | 0 | 0.18 |
| 0.9 | 112/120 (93%) | 15 15 10 15 12 15 15 15 | 3 | 0 | 0 |

Misses are a3 (quick, "heyAries") and a5 (game audio behind it). The three near-miss wakes at every
threshold are all one line, his second "hey Ari" (3 of 3 passes; hey Ari / hey Aries differ by the final
z); "hey Harry" (0/3), "hey Siri" (0/3 from 0.1), "wake Aries" (0/3) and "hey, why'd you do that" (0/3) did not wake her.
Four lines that never reached the test (hey Ares, hey arrays, b2, b3) are untested on his voice.

Compared with the "wake Aries" model (below) on the same clips: it wakes on none of his "hey Aries"
(0/120) and on his "wake Aries" 2 or 3 of 3 (0.05 to 0.7), the new one never. On the synthetic voices it
never heard, the new model is where the synthetic-only "hey Aries" run was (it has not collapsed onto
his voice): at 0.3, 96/162 "hey Aries" woke her (59%; 54 clips x 3 seeds), 13/540 near misses, 44/54 with
a command, 0/162 "wake Aries"; `evaluate.py` clip by clip 0.59 unseen recall at 0.3. Those voices are not
the figure that matters (they don't say it like he does); his held-out takes are.

## History: "wake Aries" (2026-11-05, replaced)

### The model that shipped (2026-11-05)

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

### Round 2 (2026-11-06): weighted to male voices -- did worse, not shipped

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
