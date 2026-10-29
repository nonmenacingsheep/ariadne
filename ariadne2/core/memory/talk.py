"""Old conversations (DESIGN §6): every turn kept on disk, found by meaning, recalled as past.

transcript.jsonl has one row per line, the same shape 1.x used so its file comes over
as it is: {"ts": <epoch>, "role": "user" | "assistant", "text": ...}. Credentials are
redacted before a line is written. Recall needs meaning >= 0.45 (1.x's measured bar;
the model's noise runs to about 0.42). Without the model it falls back to strong word
overlap. Everything recalled is dated and framed as past: "on 3 Oct you said: ...".
"""
from __future__ import annotations

import dataclasses
import json
import os
import threading
import time
from pathlib import Path

from ...adapters.redact import redact_secrets
from . import when
from .embed import AUTO, Vectors, data_dir, overlap, scores, words

FLOOR = 0.45
WORD_FLOOR, WORD_MIN_SHARED = 0.6, 2        # the fallback: stricter, since words are cruder
MAX_LINE = 2000                             # a turn longer than this is cut for the record
SHOW = 220                                  # characters of a recalled line


def default_path() -> Path:
    return data_dir() / "transcript.jsonl"


@dataclasses.dataclass
class TalkHit:
    row: dict
    score: float


class Talk:
    def __init__(self, path=None, embed=AUTO, vectors: Vectors | None = None, cache=None) -> None:
        self.path = Path(path) if path else default_path()
        cache = cache if cache is not None else (self.path.parent / "embed" / "turns-minilm.npz"
                                                 if embed is AUTO and vectors is None else None)
        self.vectors = vectors or Vectors(embed, cache)
        self._lock = threading.RLock()
        self._rows: list[dict] = []
        self._sig = None

    def _stat(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def rows(self) -> list[dict]:
        with self._lock:
            sig = self._stat()
            if sig != self._sig or (sig and not self._rows):
                rows = []
                try:
                    with self.path.open("r", encoding="utf-8") as fh:
                        for line in fh:
                            try:
                                r = json.loads(line)
                            except ValueError:
                                continue
                            if isinstance(r, dict) and r.get("text") and r.get("role") in ("user", "assistant"):
                                rows.append(r)
                except OSError:
                    pass
                self._rows, self._sig = rows, sig
            return self._rows

    # ---- writing ----

    def append(self, role: str, text: str, ts: float | None = None) -> bool:
        """One line to the record. Returns whether it was written."""
        text = " ".join(str(text or "").split())
        if role not in ("user", "assistant") or not text:
            return False
        text = redact_secrets(text[:MAX_LINE])[0]
        row = {"ts": float(ts or time.time()), "role": role, "text": text}
        with self._lock:
            self.rows()
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError:
                return False
            self._rows.append(row)
            self._sig = self._stat()
        return True

    def turn(self, user_text: str, reply: str, when_: float | None = None) -> None:
        """One exchange: his words, then hers (a hair later so the order is kept)."""
        t = float(when_ or time.time())
        self.append("user", user_text, t)
        self.append("assistant", reply, t + 0.001)

    # ---- finding ----

    def recall(self, query: str, k: int = 3, before: float | None = None,
               floor: float = FLOOR) -> list[TalkHit]:
        """Past lines that bear on the query. `before` leaves out lines at or after that
        time (what is already in front of her in the live thread)."""
        query = " ".join(str(query or "").split())
        rows = [r for r in self.rows() if before is None or r["ts"] < before]
        if not query or not rows:
            return []
        out: list[TalkHit] = []
        if self.vectors.available:
            try:
                sims = scores(self.vectors.one(query), self.vectors.get([r["text"] for r in rows]))
                out = [TalkHit(r, s) for r, s in zip(rows, sims) if s >= floor]
            except Exception:
                out = []
        else:
            qw = words(query)
            for r in rows:
                rw = words(r["text"])
                if len(qw & rw) >= WORD_MIN_SHARED and overlap(qw, rw) >= WORD_FLOOR:
                    out.append(TalkHit(r, overlap(qw, rw)))
        out.sort(key=lambda h: (-h.score, -h.row["ts"]))
        return out[:k]

    def warm(self) -> None:
        """Embed everything not yet embedded and save the cache (idle time, not a turn)."""
        if self.vectors.available:
            rows = self.rows()
            if rows:
                self.vectors.get([r["text"] for r in rows])
                self.vectors.save()

    @staticmethod
    def frame(row: dict, now=None) -> str:
        """'on 3 Oct (3 weeks ago) you said: "..."' -- past, never present."""
        d = when.to_date(row["ts"])
        text = row["text"] if len(row["text"]) <= SHOW else row["text"][:SHOW - 1] + "…"
        who = "you said" if row["role"] == "user" else "I told you"
        return f'on {when.short(d, now)} ({when.ago(d, now)}) {who}: "{text}"'
