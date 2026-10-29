"""Bring 1.x's memory over (DESIGN §6 "From 1.x").

  python3 -m ariadne2.core.memory.import_1x [--dry-run] [--src DIR] [--dest DIR]

Facts come over with their dates, marked current and sourced "carried over from 1.x".
Obvious duplicates are merged (newest kept). Pairs that look like they contradict each
other are NOT resolved: they're listed in import_1x_contradictions.json for him to
settle. 1.x's retired facts that were replaced by a fact still held come over as the
replaced history behind it. The transcript comes over row for row (same format).
Idempotent: a ledger (import_1x.json) remembers what was brought, so a re-run adds
nothing and never resurrects what he has since forgotten or edited.
Writes only under the 2.0 data folder; 1.x's folder is read, never written.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from . import when
from .embed import Vectors, data_dir, overlap, scores, words
from .facts import Facts
from .talk import Talk

SOURCE = "carried over from 1.x"
LEDGER, CONTRADICTIONS = "import_1x.json", "import_1x_contradictions.json"
DUP_JACCARD, DUP_COSINE, SUBJECT_COSINE = 0.8, 0.93, 0.7

_I = re.I
_EVENT = re.compile(r"\b(just finished|turned off|asked about|is now removed|so it is removed|finished season)\b", _I)
_DECISION = re.compile(r"\b(decided|chose|settled on|instead of)\b", _I)
_PLAN = re.compile(r"\b(when they get|plans? to|planning to|going to|want to run)\b", _I)
_PREF = re.compile(r"\b(prefers?|rather|likes?|loves?|wants?|would rather|enjoys?|hates?|never|doesn't want|"
                   r"don't want|do not|asks? me to|they'd)\b", _I)
_NEG = frozenset("not no never cannot can't doesn't don't isn't won't without".split())


def src_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "ariadne"


def guess_kind(text: str) -> str:
    """A cautious guess; anything unclear stays a plain fact (which barely ages)."""
    for kind, rx in (("event", _EVENT), ("decision", _DECISION), ("plan", _PLAN), ("preference", _PREF)):
        if rx.search(text):
            return kind
    return "fact"


def norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower()))


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def load_1x(src: Path) -> dict:
    state = {}
    try:
        state = json.loads((src / "state.json").read_text("utf-8"))
    except (OSError, ValueError):
        pass
    created = state.get("created")
    fallback = when.to_date(created) if created else when.to_date()
    when_of = state.get("fact_when") or {}
    facts = [{"text": " ".join(f.split()), "date": when.to_date(when_of[f]) if when_of.get(f) else fallback,
              "dated": bool(when_of.get(f))} for f in state.get("facts", []) if str(f).strip()]
    retired = [r for r in state.get("retired", []) if r.get("kind") == "fact" and r.get("text")]
    rows = []
    try:
        with (src / "transcript.jsonl").open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("text") and r.get("role") in ("user", "assistant") and r.get("ts"):
                    rows.append({"ts": float(r["ts"]), "role": r["role"], "text": str(r["text"])})
    except OSError:
        pass
    return {"facts": facts, "retired": retired, "rows": rows}


def merge_duplicates(items: list[dict], vectors: Vectors) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """Newest first; a fact that's a restatement of one already kept is merged into it."""
    kept, merged = [], []
    order = sorted(items, key=lambda f: f["date"], reverse=True)
    vecs = vectors.get([f["text"] for f in order]) if vectors.available and order else None
    kept_i: list[int] = []
    for i, f in enumerate(order):
        fw, hit = words(f["text"]), None
        for j in kept_i:
            g = order[j]
            if norm(g["text"]) == norm(f["text"]) or (min(len(fw), len(words(g["text"]))) >= 4
                                                        and jaccard(fw, words(g["text"])) >= DUP_JACCARD):
                hit = g
            elif vecs is not None and scores(vecs[i], [vecs[j]])[0] >= DUP_COSINE:
                hit = g
            if hit:
                break
        if hit:
            merged.append((hit, f))
        else:
            kept.append(f)
            kept_i.append(i)
    return sorted(kept, key=lambda f: f["date"]), merged


def find_contradictions(items: list[dict], vectors: Vectors) -> list[dict]:
    """Same-subject pairs that differ in a way that smells like a change. Listed, never settled."""
    out = []
    vecs = vectors.get([f["text"] for f in items]) if vectors.available and items else None
    for i, a in enumerate(items):
        sims = scores(vecs[i], vecs) if vecs is not None else None
        for j in range(i + 1, len(items)):
            b = items[j]
            aw, bw = words(a["text"]), words(b["text"])
            same = sims[j] >= SUBJECT_COSINE if sims is not None else (
                min(len(aw), len(bw)) >= 4 and overlap(aw, bw) >= 0.5)
            if not same:
                continue
            why = []
            if bool(_NEG & set(re.findall(r"[a-z']+", a["text"].lower()))) != \
                    bool(_NEG & set(re.findall(r"[a-z']+", b["text"].lower()))):
                why.append("one says not / never, the other doesn't")
            an, bn = set(re.findall(r"\d+(?:\.\d+)*", a["text"])), set(re.findall(r"\d+(?:\.\d+)*", b["text"]))
            if an and bn and an != bn and (an - bn) and (bn - an):
                why.append(f"different numbers ({', '.join(sorted(an - bn))} vs {', '.join(sorted(bn - an))})")
            if why:
                out.append({"a": {"text": a["text"], "date": a["date"].isoformat()},
                            "b": {"text": b["text"], "date": b["date"].isoformat()}, "why": why})
    return out


def history_chains(retired: list[dict], keep: list[dict]) -> dict[str, list[dict]]:
    """For each held fact, the retired facts that led to it, oldest first."""
    held = {norm(f["text"]) for f in keep}
    by_new: dict[str, dict] = {}
    for r in retired:
        if r.get("replaced_by") and norm(r["text"]) not in held:
            cur = by_new.get(norm(r["replaced_by"]))
            if cur is None or (r.get("until") or 0) > (cur.get("until") or 0):
                by_new[norm(r["replaced_by"])] = r
    chains = {}
    for f in keep:
        chain, key, seen = [], norm(f["text"]), set()
        while key in by_new and key not in seen:
            seen.add(key)
            r = by_new[key]
            chain.insert(0, r)
            key = norm(r["text"])
        if chain:
            chains[norm(f["text"])] = chain
    return chains


def run(src: Path, dest: Path, dry_run: bool = False, embed=None, say=print) -> dict:
    """Do (or, with dry_run, only count) the import. Returns the counts."""
    from .embed import AUTO
    data = load_1x(src)
    vectors = Vectors(AUTO if embed is None else embed)
    facts = Facts(dest / "facts.jsonl", vectors=vectors)
    talk = Talk(dest / "transcript.jsonl", vectors=Vectors(None))
    ledger_path = dest / LEDGER
    try:
        ledger = json.loads(ledger_path.read_text("utf-8"))
    except (OSError, ValueError):
        ledger = {"facts": []}
    seen = set(ledger["facts"])
    have = {norm(r["text"]) for r in facts.all()}

    fresh = [f for f in data["facts"] if norm(f["text"]) not in seen and norm(f["text"]) not in have]
    kept, merged = merge_duplicates(fresh, vectors)
    contradictions = find_contradictions(kept, vectors)
    chains = history_chains(data["retired"], kept)

    existing = {(round(r["ts"], 3), r["role"], r["text"]) for r in talk.rows()}
    new_rows = [r for r in data["rows"] if (round(r["ts"], 3), r["role"], r["text"]) not in existing]
    counts = {"facts_in_1x": len(data["facts"]), "facts_imported": len(kept), "duplicates_merged": len(merged),
              "history_links": sum(len(c) for c in chains.values()), "contradictions_listed": len(contradictions),
              "already_there": len(data["facts"]) - len(fresh),
              "undated_given_install_date": sum(1 for f in kept if not f["dated"]),
              "kinds": {k: sum(1 for f in kept if guess_kind(f["text"]) == k)
                        for k in ("preference", "fact", "plan", "decision", "event")},
              "transcript_rows_in_1x": len(data["rows"]), "transcript_rows_imported": len(new_rows),
              "transcript_user_turns_imported": sum(1 for r in new_rows if r["role"] == "user")}
    if dry_run:
        counts["dry_run"] = True
        return counts

    ids: dict[str, int] = {}
    for f in kept:
        prev = None
        for old in chains.get(norm(f["text"]), []):
            rec = facts.add(old["text"], guess_kind(old["text"]), replaces=prev, source=SOURCE,
                            date=old.get("since") or f["date"])
            prev = rec["id"]
        rec = facts.add(f["text"], guess_kind(f["text"]), replaces=prev, source=SOURCE, date=f["date"])
        ids[norm(f["text"])] = rec["id"]
    ledger["facts"] = sorted(seen | {norm(f["text"]) for f in kept} | {norm(g["text"]) for _, g in merged})
    if new_rows:
        merged_rows = sorted(talk.rows() + new_rows, key=lambda r: r["ts"])
        tmp = dest / "transcript.jsonl.tmp"
        dest.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as fh:
            for r in merged_rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest / "transcript.jsonl")
    if contradictions:
        for c in contradictions:
            for side in ("a", "b"):
                c[side]["id"] = ids.get(norm(c[side]["text"]))
        _write_json(dest / CONTRADICTIONS, {
            "about": "Pairs from 1.x that may contradict each other. Nothing was changed; settle each "
                     "by replacing or forgetting one (remember with replaces=<id>, or forget).",
            "pairs": contradictions})
    _write_json(ledger_path, ledger)
    return counts


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, path)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ariadne2.core.memory.import_1x")
    p.add_argument("--dry-run", action="store_true", help="count only; write nothing")
    p.add_argument("--src", type=Path, default=src_dir(), help="1.x data folder (read only)")
    p.add_argument("--dest", type=Path, default=data_dir(), help="2.0 data folder")
    args = p.parse_args(argv)
    counts = run(args.src, args.dest, args.dry_run)
    print(json.dumps(counts, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
