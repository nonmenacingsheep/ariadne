"""Meaning for memory: 1.x's MiniLM setup (DESIGN §8 "Recall"), plus the word-overlap fallback.

The model is the same quantised all-MiniLM-L6-v2 the 1.x app uses, run on the
CPU through onnxruntime. Its files are looked for in 2.0's own embed folder,
then in 1.x's (read only), then $ARIADNE2_EMBED_DIR. Without numpy, onnxruntime,
tokenizers or the files, `default_embedder()` is None and everything falls
back to word overlap, so remembering never depends on the model being there.

An embedder is any callable: list[str] -> list of unit-length vectors.
`Vectors` caches them by text (and keeps a cache file beside the model when
numpy is there), so a long transcript is embedded once, ever.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

try:                                    # the system python has no numpy; 1.x's venv does
    import numpy as np
except Exception:                       # pragma: no cover
    np = None

AUTO = object()                         # "use the real model, if it's here"
BATCH = 64
SAVE_EVERY = 32                         # new vectors before the cache file is rewritten
MAX_TOKENS = 256
MODEL_FILES = ("model.onnx", "tokenizer.json")

_STOP = frozenset("""
a an and are as at be but by can could do does for from get give go has have
how i if in is it its me my of on or please should so than that the their
then there these they this to up was what when where which who will with
would you your they them is are now still hey just want need able tell show
about know remember use used uses using try think say
""".split())


def words(text: str) -> set:
    """Content words, as 1.x counted them."""
    return {w for w in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if (len(w) >= 2 or w.isdigit()) and w not in _STOP}


def overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "ariadne2"


def model_dirs() -> list[Path]:
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    dirs = [Path(p) for p in [os.environ.get("ARIADNE2_EMBED_DIR")] if p]
    return dirs + [base / "ariadne2" / "embed", base / "ariadne" / "embed"]


def find_model() -> Path | None:
    return next((d for d in model_dirs() if all((d / f).is_file() for f in MODEL_FILES)), None)


class MiniLM:
    """The model, loaded once. Vectors are unit length."""

    def __init__(self, folder: Path) -> None:
        from tokenizers import Tokenizer
        import onnxruntime as ort
        self.tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.tok.enable_truncation(MAX_TOKENS)
        self.tok.enable_padding()
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.sess = ort.InferenceSession(str(folder / "model.onnx"), opts,
                                         providers=["CPUExecutionProvider"])

    def __call__(self, texts: list[str]):
        enc = self.tok.encode_batch([str(t) for t in texts])
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        out = self.sess.run(None, {"input_ids": ids, "attention_mask": mask,
                                   "token_type_ids": np.zeros_like(ids)})[0]
        m = mask[..., None].astype(np.float32)
        v = (out * m).sum(1) / np.maximum(m.sum(1), 1e-6)
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


_default = {"fn": None, "tried": False}
_default_lock = threading.Lock()


def default_embedder():
    """The real model, or None when meaning isn't available here."""
    with _default_lock:
        if not _default["tried"]:
            _default["tried"] = True
            folder = find_model() if np is not None else None
            if folder is not None:
                try:
                    _default["fn"] = MiniLM(folder)
                except Exception:
                    _default["fn"] = None
        return _default["fn"]


def _vec(v):
    return np.asarray(v, dtype=np.float32) if np is not None else [float(x) for x in v]


def dot(a, b) -> float:
    if np is not None:
        return float(np.dot(a, b))
    return float(sum(x * y for x, y in zip(a, b)))


def scores(q, vecs) -> list[float]:
    """Cosine (unit vectors) of q against each vector."""
    if not vecs:
        return []
    if np is not None:
        return np.asarray(vecs).dot(np.asarray(q)).tolist()
    return [dot(q, v) for v in vecs]


class Vectors:
    """Text -> vector, cached. `path` (optional, numpy only) persists the cache."""

    def __init__(self, embed=AUTO, path: Path | None = None) -> None:
        self._embed = embed
        self.path = Path(path) if path else None
        self.mem: dict[str, object] = {}
        self.fresh = 0
        self._lock = threading.RLock()
        self._loaded = False

    @property
    def fn(self):
        if self._embed is AUTO:
            self._embed = default_embedder()
        return self._embed

    @property
    def available(self) -> bool:
        return self.fn is not None

    def get(self, texts: list[str]) -> list:
        """Vectors for texts, in order. Only call when `available`."""
        fn = self.fn
        with self._lock:
            self._load()
            # shortest first: a batch pads to its longest line, so similar lengths waste less
            missing = sorted((t for t in dict.fromkeys(texts) if t not in self.mem), key=len)
            for i in range(0, len(missing), BATCH):
                chunk = missing[i:i + BATCH]
                for t, v in zip(chunk, fn(chunk)):
                    self.mem[t] = _vec(v)
            self.fresh += len(missing)
            if self.path and self.fresh >= SAVE_EVERY:
                self.save()
            return [self.mem[t] for t in texts]

    def one(self, text: str):
        return self.get([text])[0]

    def _load(self) -> None:
        if self._loaded or not (self.path and np is not None):
            self._loaded = True
            return
        self._loaded = True
        try:
            data = np.load(self.path, allow_pickle=False)
            keys = json.loads(str(data["keys"]))
            self.mem = dict(zip(keys, data["vecs"]))
        except Exception:
            self.mem = {}

    def save(self) -> None:
        if not (self.path and np is not None):
            return
        with self._lock:
            self.fresh = 0
            if not self.mem:
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_name(self.path.stem + ".tmp.npz")
                np.savez(tmp, keys=json.dumps(list(self.mem)), vecs=np.stack(list(self.mem.values())))
                os.replace(tmp, self.path)
            except Exception:
                pass
