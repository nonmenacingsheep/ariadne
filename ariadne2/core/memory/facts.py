"""Facts about him (DESIGN §6): dated records, superseded not stacked, with reasons.

One record per line in facts.jsonl:
  {"id", "text", "kind", "date", "source", "status", "replaces", "replaced_by", "because", "rejected"}
Appends are one fsynced line; anything that changes an existing record rewrites
the file through a temp file and os.replace, so it is never half written.
Credentials are redacted before anything is saved.
"""
from __future__ import annotations

import dataclasses
import json
import os
import threading
from pathlib import Path

from ...adapters.redact import redact_secrets
from . import when
from .embed import AUTO, Vectors, data_dir, overlap, scores, words

KINDS = ("preference", "fact", "plan", "decision", "event")
STATUSES = ("current", "replaced", "done")
SAID, INFERRED = "said in chat", "inferred by her"
MAX_TEXT = 400
# Days for a record's weight to halve: events and plans fade over about a month,
# decisions more slowly, preferences and facts barely until something replaces them.
HALF_LIFE = {"event": 14.0, "plan": 21.0, "decision": 90.0, "preference": 1500.0, "fact": 1500.0}
MEANING, WORDS = 0.36, 0.4          # relevance bars (1.x's measured ones)
SAME_SUBJECT = 0.6                  # "closest existing facts" on save


def default_path() -> Path:
    return data_dir() / "facts.jsonl"


def age_weight(kind: str, date, now=None) -> float:
    days = max(0, when.days_between(date, now))
    return 0.5 ** (days / HALF_LIFE.get(kind, 1500.0))


def clean_rejected(rejected) -> list[str]:
    """Rejected options as 'option -- reason' strings (accepts strings or {option, reason})."""
    if isinstance(rejected, (str, dict)):
        rejected = [rejected]
    out = []
    for r in rejected or []:
        if isinstance(r, dict):
            opt, why = str(r.get("option") or r.get("what") or "").strip(), str(r.get("reason") or r.get("why") or "").strip()
            r = f"{opt} -- {why}" if opt and why else opt
        r = " ".join(str(r).split())
        if r:
            out.append(redact_secrets(r)[0][:MAX_TEXT])
    return out


@dataclasses.dataclass
class Hit:
    rec: dict
    relevance: float
    weight: float
    how: str                        # "meaning" or "words"

    @property
    def score(self) -> float:
        return self.relevance * self.weight


class Facts:
    def __init__(self, path=None, embed=AUTO, vectors: Vectors | None = None) -> None:
        self.path = Path(path) if path else default_path()
        self.vectors = vectors or Vectors(embed)
        self._lock = threading.RLock()
        self._recs: list[dict] = []
        self._sig = None
        self.redactions = 0         # credentials removed by the last add, for the caller to mention

    # ---- reading ----

    def _stat(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _sync(self) -> None:
        """Reload when the file changed under us (the importer, the Memory page)."""
        sig = self._stat()
        if sig == self._sig and (self._recs or sig is None):
            return
        recs = []
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and isinstance(r.get("id"), int) and r.get("text"):
                        recs.append(self._shape(r))
        except OSError:
            pass
        self._recs, self._sig = recs, sig

    @staticmethod
    def _shape(r: dict) -> dict:
        kind = r.get("kind") if r.get("kind") in KINDS else "fact"
        return {"id": r["id"], "text": str(r["text"]), "kind": kind,
                "date": str(r.get("date") or when.to_date())[:10],
                "source": r.get("source") or SAID,
                "status": r.get("status") if r.get("status") in STATUSES else "current",
                "replaces": r.get("replaces"), "replaced_by": r.get("replaced_by"),
                "because": r.get("because") or None, "rejected": list(r.get("rejected") or [])}

    def all(self) -> list[dict]:
        with self._lock:
            self._sync()
            return [dict(r) for r in self._recs]

    def get(self, rid) -> dict | None:
        with self._lock:
            self._sync()
            return next((dict(r) for r in self._recs if r["id"] == rid), None)

    def live(self) -> list[dict]:
        """Records that count now: not replaced."""
        return [r for r in self.all() if r["status"] != "replaced"]

    def newest(self, n: int = 3) -> list[dict]:
        return sorted(self.live(), key=lambda r: (r["date"], r["id"]), reverse=True)[:n]

    def find_exact(self, text: str) -> dict | None:
        key = " ".join(text.lower().split()).rstrip(".")
        return next((r for r in self.live() if " ".join(r["text"].lower().split()).rstrip(".") == key), None)

    # ---- writing ----

    def _failed(self) -> None:
        """A write didn't land: forget what we changed in memory; the file is still the truth."""
        self._recs, self._sig = [], object()

    def _write_all(self) -> None:
        try:
            self._write_all_()
        except BaseException:
            self._failed()
            raise

    def _write_all_(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for r in self._recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        self._sig = self._stat()

    def _append(self, rec: dict) -> None:
        try:
            self._append_(rec)
        except BaseException:
            self._failed()
            raise

    def _append_(self, rec: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._sig = self._stat()

    def _by_id(self, rid):
        return next((r for r in self._recs if r["id"] == rid), None)

    def add(self, text: str, kind: str = "fact", *, because: str | None = None, rejected=None,
            replaces: int | None = None, source: str = SAID, date=None, now=None) -> dict:
        """Save a fact. With `replaces`, the old record is marked replaced and linked both ways.

        An identical current text isn't added twice: if `replaces` came with it, the
        existing record just gets the link (this is how she settles a "same subject?").
        Raises ValueError for anything that can't be saved.
        """
        text, n1 = redact_secrets(" ".join(str(text or "").split()))
        because, n2 = redact_secrets(" ".join(str(because or "").split()))
        self.redactions = n1 + n2
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        if text.replace("[redacted credential]", "").strip(" .,:;-") == "":
            raise ValueError("nothing to save there once credentials are removed")
        if len(text) > MAX_TEXT:
            raise ValueError(f"too long ({len(text)} characters); say it in under {MAX_TEXT}")
        rej = clean_rejected(rejected)
        with self._lock:
            self._sync()
            old = None
            if replaces is not None:
                old = self._by_id(replaces)
                if old is None:
                    raise ValueError(f"there is no #{replaces} to replace")
                if old["status"] == "replaced":
                    raise ValueError(f"#{replaces} was already replaced by #{old['replaced_by']}")
            dup = self.find_exact(text)
            if dup is not None:
                rec = self._by_id(dup["id"])
                changed = False
                if old is not None and rec["id"] != old["id"] and rec["replaces"] is None:
                    rec["replaces"], old["status"], old["replaced_by"] = old["id"], "replaced", rec["id"]
                    changed = True
                if because and not rec["because"]:
                    rec["because"], changed = because, True
                if rej and not rec["rejected"]:
                    rec["rejected"], changed = rej, True
                if changed:
                    self._write_all()
                return dict(rec)
            rec = {"id": max((r["id"] for r in self._recs), default=0) + 1, "text": text, "kind": kind,
                   "date": when.to_date(date if date is not None else now).isoformat(), "source": source,
                   "status": "done" if kind == "event" else "current",
                   "replaces": old["id"] if old else None, "replaced_by": None,
                   "because": because or None, "rejected": rej}
            self._recs.append(rec)
            if old is not None:
                old["status"], old["replaced_by"] = "replaced", rec["id"]
                self._write_all()
            else:
                self._append(rec)
            return dict(rec)

    def mark_done(self, rid: int) -> dict | None:
        """A plan that's finished (it stays, worded as past)."""
        with self._lock:
            self._sync()
            r = self._by_id(rid)
            if r is None or r["status"] == "replaced":
                return None
            r["status"] = "done"
            self._write_all()
            return dict(r)

    def forget(self, rid: int) -> dict | None:
        """Delete a record. Its neighbours lose the link; a replaced one stays replaced."""
        with self._lock:
            self._sync()
            r = self._by_id(rid)
            if r is None:
                return None
            self._recs.remove(r)
            for o in self._recs:
                if o["replaces"] == rid:
                    o["replaces"] = None
                if o["replaced_by"] == rid:
                    o["replaced_by"] = None
            self._write_all()
            return dict(r)

    # ---- finding ----

    @staticmethod
    def pieces(rec: dict) -> list[str]:
        """What a query can match: the text, the reason, each turned-down option."""
        return [rec["text"]] + ([rec["because"]] if rec["because"] else []) + list(rec["rejected"])

    def _relevance(self, query: str, recs: list[dict]) -> list[tuple[float, str]]:
        qwords = words(query)
        qvec = None
        if self.vectors.available and query.strip():
            try:
                qvec = self.vectors.one(query)
            except Exception:
                qvec = None
        out = []
        for r in recs:
            ps = self.pieces(r)
            word_score = max(overlap(qwords, words(p)) for p in ps)
            mean = 0.0
            if qvec is not None:
                try:
                    mean = max(scores(qvec, self.vectors.get(ps)))
                except Exception:
                    mean = 0.0
            m_ok, w_ok = mean >= MEANING, word_score >= WORDS
            if m_ok or w_ok:
                out.append((max(mean if m_ok else 0.0, word_score if w_ok else 0.0),
                            "meaning" if m_ok and mean >= word_score else "words"))
            else:
                out.append((0.0, ""))
        return out

    def recall(self, query: str, now=None, *, history: bool = False, k: int = 6,
               min_weight: float = 0.0) -> list[Hit]:
        """Relevant records, best first: relevance (meaning or words) times age weight.

        Replaced records are left out unless history=True. `min_weight` drops records that
        have faded (the per-turn context uses it; asking directly does not).
        """
        recs = self.all() if history else self.live()
        hits = []
        for r, (rel, how) in zip(recs, self._relevance(query, recs)):
            if rel <= 0:
                continue
            w = age_weight(r["kind"], r["date"], now)
            if w >= min_weight:
                hits.append(Hit(r, rel, w, how))
        hits.sort(key=lambda h: (-h.score, -h.rec["id"]))
        return hits[:k]

    def near(self, text: str, k: int = 3, threshold: float = SAME_SUBJECT,
             exclude: tuple = ()) -> list[tuple[dict, float]]:
        """Existing records about the same subject as `text` (meaning >= 0.6; words if no model)."""
        recs = [r for r in self.live() if r["id"] not in exclude]
        out = []
        tw = words(text)
        sims = None
        if self.vectors.available and recs:
            sims = scores(self.vectors.one(text), self.vectors.get([r["text"] for r in recs]))
        for i, r in enumerate(recs):
            if sims is not None:
                s = sims[i]
            else:
                rw = words(r["text"])
                s = overlap(tw, rw) if min(len(tw), len(rw)) >= 3 else 0.0
            if s >= threshold:
                out.append((r, s))
        out.sort(key=lambda p: -p[1])
        return out[:k]

    def chain(self, rid: int) -> list[dict]:
        """The history a record belongs to, oldest first (Firefox -> Opera GX -> ...)."""
        with self._lock:
            self._sync()
            r, seen = self._by_id(rid), set()
            if r is None:
                return []
            while r["replaces"] is not None and r["replaces"] not in seen and self._by_id(r["replaces"]):
                seen.add(r["id"])
                r = self._by_id(r["replaces"])
            out, seen = [], set()
            while r is not None and r["id"] not in seen:
                seen.add(r["id"])
                out.append(dict(r))
                r = self._by_id(r["replaced_by"]) if r["replaced_by"] is not None else None
            return out

    # ---- wording ----

    def describe(self, rec: dict, now=None, *, short_form: bool = False) -> str:
        """One line, dated; old events and plans are worded as past, never as now."""
        kind, date = rec["kind"], rec["date"]
        ago, day = when.ago(date, now), when.short(date, now)
        text = rec["text"] if len(rec["text"]) <= 240 else rec["text"][:239] + "…"
        if kind == "event" or rec["status"] == "done":
            line = f"#{rec['id']} [{'happened' if kind == 'event' else 'was planned'} {ago}, {day}] {text}"
        elif kind == "plan":
            line = f"#{rec['id']} [planned {ago}, {day}; may have moved on] {text}"
        elif kind == "decision":
            line = f"#{rec['id']} [decided {day}] {text}"
        else:
            line = f"#{rec['id']} {text} (since {day})"
        if short_form:
            return line
        if rec["because"]:
            line += f" -- because {rec['because']}"
        if rec["rejected"]:
            line += "; turned down: " + "; ".join(rec["rejected"])
        if rec["status"] == "replaced":
            by = self.get(rec["replaced_by"]) if rec["replaced_by"] is not None else None
            if by:
                why = f" ({by['because']})" if by["because"] else ""
                line += f" [replaced {when.short(by['date'], now)} by #{by['id']}{why}]"
            else:
                line += " [replaced]"
        return line
