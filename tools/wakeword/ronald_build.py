"""Cut Ronald's own recordings into training and test clips (his voice: never commit the output).

    python ronald_build.py <dir>            # <dir> = $WW/data/ronald, holding the files below

Input, made by ronald_segment.py from his two recordings (mono 16 kHz WAVs):
  ab16.wav, c16.wav   Part A+B in one file, and Part C (normal talking)
  segs2.json          the silence-split segments of ab16.wav, each with a transcript
  cuts_a4.json        where "hey Aries" ends in the takes that run on into a command

Output under <dir>/clips:
  pos_train/   training takes, REPEAT copies of each, each at a random speed (0.9 to 1.1)
  neg_train/   his near-miss lines (REPEAT copies) and Part C windows (C_COPIES copies)
  test/pos/    held-out "hey Aries" takes, named a<block>_<n>.wav (a4 keeps its command)
  test/near/   held-out near-miss lines
  test/c/      held-out 10 s stretches of Part C
  takes.json   what went where

The takes are labelled by position (the blocks of recording_script.md, which are separated by
gaps of five seconds or more) and by transcript: a segment whose transcript does not look like
"hey Aries" is left out, so is anything ambiguous. One take in five of each block is held out.
Part B was recorded only in part, so each near-miss phrase has one take in training and one in
test where he said it twice.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SR = 16000
PAD = 0.12
REPEAT = 40                      # copies of each of his training takes (each gets rooms and noise later)
C_COPIES = 3
HOP, WIN = 0.4, 1.9              # Part C windows
CHUNK = 10.0                     # Part C is held out in stretches of this length
C_TEST_CHUNKS = (2, 5, 8)        # of every ten: 30% of Part C

# Segment index ranges in segs2.json (his recording: a block starts after a gap of 5 s or more).
BLOCKS = {1: (0, 26), 2: (27, 51), 3: (52, 76), 4: (77, 120), 5: (122, 146), 6: (147, 173),
          7: (176, 207), 8: (208, 234)}
# a7 (a pause in the middle) comes as two segments: "hey", then "Aries".
A7_PAIRS = ((177, 178), (179, 180), (185, 186), (197, 198), (199, 200), (202, 203), (206, 207))
A7_SKIP = {176, 204}             # a lone "Aries", an "um"
HEY = re.compile(r"^(hey|he|hate|hay|eight|the|i hate|um hey|uh hey)\b.{0,4}(ares|aries|areas|arius|arias|aerie)")
# Part B as he recorded it (segment indices); each phrase twice, one for training and one for test.
NEAR = {"hey_harry": [(235, 236), (237, 238)], "hey_ari": [(239,), (240,)], "hey_siri": [(241,), (242,)],
        "wake_aries": [(243,), (244,)], "hey_whats_going_on": [(245,)], "hey_why_did_you": [(247,)],
        "hey": [(249,)]}
NEAR_TEST = {"hey_harry": 1, "hey_ari": 1, "hey_siri": 1, "wake_aries": 1, "hey_why_did_you": 0}


def clean(t: str) -> str:
    return re.sub(r"[^a-z' ]", " ", t.lower()).strip()


def write(path: Path, x) -> None:
    sf.write(path, np.clip(x, -1, 1).astype("float32"), SR, subtype="PCM_16")


def main() -> None:
    d = Path(sys.argv[1])
    out = d / "clips"
    rng = np.random.default_rng(11)
    ab = sf.read(d / "ab16.wav")[0].astype("float32")
    segs = json.load(open(d / "segs2.json"))
    cuts = {int(k): v for k, v in json.load(open(d / "cuts_a4.json")).items()}
    for sub in ("pos_train", "neg_train", "test/pos", "test/near", "test/c"):
        (out / sub).mkdir(parents=True, exist_ok=True)
        for f in (out / sub).glob("*.wav"):
            f.unlink()

    def cut(a: float, b: float):
        return ab[max(0, int((a - PAD) * SR)):int((b + PAD) * SR)]

    def varied(x):
        f = rng.uniform(0.9, 1.1)
        return resample_poly(x, 100, int(round(100 * f)))

    info = {"pos": {}, "near": {}, "c": {}}
    # ---- "hey Aries": (train clip, test clip) per take
    for block, (lo, hi) in BLOCKS.items():
        takes = []
        if block == 7:
            used = {i for p in A7_PAIRS for i in p}
            for k in range(lo, hi + 1):
                if k in A7_SKIP:
                    continue
                if k in used:
                    pair = next((p for p in A7_PAIRS if p[0] == k), None)
                    if pair is None:                  # the second half of a pair
                        continue
                    takes.append((segs[pair[0]]["s"], segs[pair[1]]["e"], segs[pair[0]]["s"], segs[pair[1]]["e"]))
                elif k not in used and HEY.match(clean(segs[k]["text"])):
                    takes.append((segs[k]["s"], segs[k]["e"], segs[k]["s"], segs[k]["e"]))
        else:
            for k in range(lo, hi + 1):
                s = segs[k]
                if not HEY.match(clean(s["text"])):
                    continue
                end = cuts[k]["end"] if k in cuts and cuts[k]["end"] else s["e"]
                tend = s["e"]
                if block == 4:                    # the command after it stays on the test clip
                    j = k + 1
                    while j <= hi and not HEY.match(clean(segs[j]["text"])) and segs[j]["s"] - tend < 0.9:
                        tend = segs[j]["e"]
                        j += 1
                takes.append((s["s"], end, s["s"], max(tend, s["e"])))
        n_test = 0
        for i, (s, e, ts, te) in enumerate(takes):
            test = i % 5 == 2
            if test:
                write(out / "test/pos" / f"a{block}_{i:02d}.wav", cut(ts, te))
                n_test += 1
            else:
                x = cut(s, e)
                for c in range(REPEAT):
                    write(out / "pos_train" / f"a{block}_{i:02d}_{c:02d}.wav", varied(x))
        info["pos"][block] = {"takes": len(takes), "test": n_test}
    # ---- near misses (Part B)
    for name, items in NEAR.items():
        for j, idx in enumerate(items):
            s, e = segs[idx[0]]["s"], segs[idx[-1]]["e"]
            if NEAR_TEST.get(name) == j:
                write(out / "test/near" / f"{name}_{j}.wav", cut(s, e))
                info["near"].setdefault(name, []).append("test")
            else:
                x = cut(s, e)
                for c in range(REPEAT):
                    write(out / "neg_train" / f"near_{name}_{j}_{c:02d}.wav", varied(x))
                info["near"].setdefault(name, []).append("train")
    # ---- Part C
    c = sf.read(d / "c16.wav")[0].astype("float32")
    n_chunks = int(len(c) / SR // CHUNK)
    nwin = 0
    for ch in range(n_chunks):
        a0 = int(ch * CHUNK * SR)
        piece = c[a0:a0 + int(CHUNK * SR)]
        if ch % 10 in C_TEST_CHUNKS:
            write(out / "test/c" / f"c_{ch:02d}.wav", piece)
            continue
        for w0 in np.arange(0, CHUNK - WIN, HOP):
            win = piece[int(w0 * SR):int((w0 + WIN) * SR)]
            if np.sqrt((win ** 2).mean()) < 0.004:        # silence teaches nothing
                continue
            for k in range(C_COPIES):
                write(out / "neg_train" / f"c_{ch:02d}_{int(w0 * 10):03d}_{k}.wav", win)
            nwin += 1
    info["c"] = {"chunks": n_chunks, "test_chunks": len(list((out / "test/c").glob("*.wav"))), "train_windows": nwin}
    info["counts"] = {sub: len(list((out / sub).glob("*.wav"))) for sub in
                      ("pos_train", "neg_train", "test/pos", "test/near", "test/c")}
    json.dump(info, open(out / "takes.json", "w"), indent=1)
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
