"""What goes to the voice: marks, skips, what nobody reads aloud, and where to cut.

Carried over from 1.x voice.py, trimmed. Her delivery lives in the text she
writes, as double-bracket marks -- ((excited)), ((slow)), ((skip))...((/skip))
-- so this module is the whole of "how she colours a line". Nothing here
touches audio or the network, which is why it is easy to test.
"""
from __future__ import annotations

import re

from .cartesia import EMOTIONS

MAX_CHARS = 1200

# ---------------------------------------------------------------- the marks
# Deliberately ugly to type by accident: a double bracket around one word is
# not something that turns up in prose, and if one slips through it is obvious
# what happened. Anything else in double brackets is ordinary text.
ANY_MARK = re.compile(r"\(\(([a-z/]+)\)\)", re.I)
RATES = {"fast": 1.25, "slow": 0.78, "normal": 1.0}
MARK_WORDS = frozenset({"fast", "slow", "normal", "skip", "/skip"} | set(EMOTIONS))
_DELIVERY = frozenset(RATES) | {"skip", "/skip"}


def strip_marks(text: str) -> tuple[str, float, str]:
    """The words without her marks, the rate asked for, and the emotion
    asked for ("" when none). The first of each in a chunk wins."""
    rate, emotion = 1.0, ""
    for m in ANY_MARK.finditer(text or ""):
        name = m.group(1).lower()
        if name in RATES:
            if rate == 1.0:
                rate = RATES[name]
        elif name in MARK_WORDS and name not in _DELIVERY and not emotion:
            emotion = name
    clean = ANY_MARK.sub(lambda m: "" if m.group(1).lower() in MARK_WORDS else m.group(0),
                         text or "")
    return clean, rate, emotion


class BareMarks:
    """She sometimes writes a voice mark bare: "amazed Wait, what?" for
    "((amazed)) Wait, what?". Then nothing reached her voice or her face, and
    the voice read "amazed" aloud. At the start of each sentence, a known
    emotion word followed by a capitalised word is taken as the mark it was
    meant to be. Text arrives in pieces, so a sentence's first word is held
    until it's whole."""

    HOLD = 24

    def __init__(self) -> None:
        self.buf = ""
        self.at_start = True

    def feed(self, text: str) -> str:
        out = []
        for ch in text or "":
            if self.at_start:
                self.buf += ch
                m = re.match(r"(\s*)([a-z]+)(\s+)(\S)", self.buf)
                if m:
                    word, nxt = m.group(2), m.group(4)
                    if word in EMOTIONS and nxt.isupper():
                        out.append(f"{m.group(1)}(({word})) {nxt}")
                    else:
                        out.append(self.buf)
                    self.buf, self.at_start = "", False
                elif len(self.buf) > self.HOLD or not re.fullmatch(r"\s*[a-z]*\s*", self.buf):
                    out.append(self.buf)          # not a bare mark: a bracket, a capital, too long
                    self.buf, self.at_start = "", False
                continue
            out.append(ch)
            if ch in ".!?\n":
                self.at_start = True
        return "".join(out)

    def flush(self) -> str:
        rest, self.buf, self.at_start = self.buf, "", True
        return rest


class MarkStream:
    """Takes the marks out of text as it arrives, for the screen.

    A stream is cut wherever the network felt like cutting it, so "((slow))"
    can arrive as "((sl" and then "ow))". Anything that could still become a
    mark is held back until it completes or turns out to be ordinary text, so
    a half-written mark never reaches the screen and no plain bracket is lost.
    """

    MAX_HOLD = 18                        # len("((contemplative))")

    _MARK_SPACE = re.compile(r"\(\(([a-z/]+)\)\)( ?)", re.I)

    def __init__(self) -> None:
        self._held = ""
        self._eat = False                # a mark ended the last piece: its space may start this one
        self._prev = ""                  # the last character already shown

    def feed(self, chunk: str) -> str:
        out = self._held + (chunk or "")
        if self._eat and out.startswith(" "):
            out = out[1:]
        self._eat = False
        ended = []

        def cut(m):
            if m.group(1).lower() not in MARK_WORDS:
                return m.group(0)
            # The space after goes too only when the mark stands alone (at the
            # start, or after a space); "x((/skip)) done" keeps its gap.
            before = out[m.start() - 1] if m.start() else self._prev
            alone = not before or before.isspace()
            if alone and m.end() == len(out) and not m.group(2):
                ended.append(True)
            return "" if alone else m.group(2)
        out = self._MARK_SPACE.sub(cut, out)
        self._eat = bool(ended)
        keep = 0
        for n in range(1, min(self.MAX_HOLD, len(out)) + 1):
            tail = out[-n:].lower()
            if any(("((" + w + "))").startswith(tail) for w in MARK_WORDS):
                keep = n
        self._held = out[len(out) - keep:] if keep else ""
        shown = out[:len(out) - keep] if keep else out
        if shown:
            self._prev = shown[-1]
        return shown

    def flush(self) -> str:
        """A partial mark that never completed is ordinary text after all."""
        rest, self._held = self._held, ""
        return rest


class SkipTracker:
    """((skip))...((/skip)) across chunks: the words stay on screen, never reach the voice.

    1.x handled this per chunk, so a chunk wholly inside a skipped span was
    read out. The state has to live across chunks.
    """

    def __init__(self) -> None:
        self.inside = False

    def reset(self) -> None:
        self.inside = False

    def apply(self, text: str) -> str:
        out, low, i = [], text.lower(), 0
        while i < len(text):
            if self.inside:
                j = low.find("((/skip))", i)
                if j < 0:
                    break
                self.inside, i = False, j + len("((/skip))")
            else:
                j = low.find("((skip))", i)
                if j < 0:
                    out.append(text[i:])
                    break
                out.append(text[i:j] + " ")
                self.inside, i = True, j + len("((skip))")
        return "".join(out)


# ------------------------------------------------------------- speakable
# What a person would not read out: they would say "the link", "that long
# number", "the ID", and carry on. Each becomes the phrase a person would use.
_CODE = re.compile(r"```.*?```", re.S)
_URL = re.compile(r"https?://([\w.-]+)[^\s)]*")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_HEX = re.compile(r"\b[0-9a-f]{16,}\b", re.I)
_LONG_NUMBER = re.compile(r"(?<![\w.])\d[\d ,.-]{6,}\d(?![\w.])")
# letters and digits mixed, long, no spaces: a tracking number, a key, a token
_IDISH = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{12,}\b")
_INLINE = re.compile(r"[`*_#>]+")
_PATHY = re.compile(r"(?<![\w/])(/[\w./-]{6,})")


def speakable(text: str) -> str:
    """Trim what would sound absurd read out loud. Marks are left alone;
    strip_marks has already taken them (or will)."""
    text = _CODE.sub(" (code omitted) ", str(text))
    text = _INLINE.sub("", text)
    text = _URL.sub(lambda m: m.group(1).replace("www.", ""), text)
    text = _EMAIL.sub("an email address", text)
    text = _UUID.sub("an ID", text)
    text = _HEX.sub("a hash", text)
    text = _PATHY.sub(lambda m: m.group(1).rstrip("/").split("/")[-1], text)
    text = _IDISH.sub("an ID", text)
    text = _LONG_NUMBER.sub("a long number", text)
    return re.sub(r"\s+", " ", text).strip()[:MAX_CHARS]


# ------------------------------------------------------------- chunking
_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n{2,}")
_ABBREV = re.compile(r"\b(mr|mrs|ms|dr|prof|st|e\.g|i\.e|etc|vs|fig|no)\.$", re.I)
_CLAUSE = re.compile(r"(?<=[,;:])\s+|\s+[—–-]\s+")

# The first chunk is the one being waited on, so it may be short; everything
# after it is made while earlier audio plays, so it can be a whole sentence.
# Measured on the cloud voice: 0.82s to first sound at 50/120, no gaps.
FIRST_CHUNK = 28
MIN_CHUNK = 50
MAX_CHUNK = 120
# A first sentence 118 chars long put first sound at 1.4s; breaking at its
# first comma put it nearer 0.8. Only the first chunk breaks on a clause.
FIRST_CLAUSE_MAX = 80
# "Good to know." is a fine first thing to say; waiting for more only delays it.
FIRST_SENTENCE_MIN = 12


def next_chunk(buffer: str, first: bool = False, final: bool = False) -> tuple[str | None, str]:
    """Pull one speakable chunk off the front of text that is still arriving.

    Returns (chunk_or_None, remainder). The tail of the buffer may be half a
    word and must not be spoken until a sentence has actually ended past the
    floor, or the buffer has outgrown one breath. `final` releases the rest.
    """
    text = (buffer or "").lstrip()
    if not text:
        return None, ""
    if final:
        return text, ""
    floor = FIRST_CHUNK if first else MIN_CHUNK

    sentence_floor = FIRST_SENTENCE_MIN if first else floor
    for match in _SENTENCE.finditer(text):
        end = match.start()
        if end + 1 < sentence_floor:
            continue
        head = text[:match.end()].strip()
        if _ABBREV.search(head):
            continue                      # "e.g." is not the end of a sentence
        if first and end > FIRST_CLAUSE_MAX:
            break                         # a clause break gets her talking sooner
        return head, text[match.end():]

    first_end = next((m.start() for m in _SENTENCE.finditer(text)
                      if m.start() + 1 >= FIRST_SENTENCE_MIN
                      and not _ABBREV.search(text[:m.end()].strip())), None)
    if first and (first_end is None or first_end > FIRST_CLAUSE_MAX):
        for match in _CLAUSE.finditer(text):
            end = match.start()
            if end + 1 < floor:
                continue
            if end > FIRST_CLAUSE_MAX:
                break
            return text[:end].strip(), text[match.end():]

    if len(text) > MAX_CHUNK:             # longer than anyone says in one breath
        cut = text.rfind(" ", 0, MAX_CHUNK)
        cut = cut if cut > floor else MAX_CHUNK
        return text[:cut].strip(), text[cut:]
    return None, text


def chunks(text: str) -> list[str]:
    """Split finished text with the same cuts the streaming path makes."""
    pieces, buffer, first = [], (text or "").strip(), True
    while buffer:
        piece, buffer = next_chunk(buffer, first=first)
        if piece is None:
            piece, buffer = next_chunk(buffer, first=first, final=True)
        if piece:
            pieces.append(piece)
        first = False
    return pieces


def ends_sentence(text: str) -> bool:
    """Whether a chunk stopped at a sentence end rather than mid-sentence."""
    return bool(re.search(r"[.!?…][\"')\]]*\s*$", text or ""))


def split_at_marks(text: str) -> list[str]:
    """Cut text where a delivery or emotion mark opens, so each part carries
    its own. A chunk can hold more than one sentence, and "Fine. ((sarcastic))
    Oh, brilliant." must not be said in one voice."""
    cuts = [m.start() for m in ANY_MARK.finditer(text)
            if m.group(1).lower() in MARK_WORDS and m.group(1).lower() not in ("skip", "/skip")]
    cuts = [c for c in cuts if text[:c].strip()]          # a mark at the very start is not a cut
    parts, last = [], 0
    for c in cuts + [len(text)]:
        parts.append(text[last:c])
        last = c
    return [p for p in parts if p.strip()]


def split_first_sentence(text: str) -> tuple[str, str]:
    """(first sentence, the rest). A mark holds for the sentence it opens."""
    for m in _SENTENCE.finditer(text):
        if not _ABBREV.search(text[:m.end()].strip()):
            return text[:m.start()], text[m.end():]
    return text, ""
