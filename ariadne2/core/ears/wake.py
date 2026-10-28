"""Her name, and the few whole-utterance words that mean something while she listens.

Carried over from 1.x ears.py with the name made configurable per instance
(1.x rebuilt module globals when she renamed herself) and the shutdown,
restart, media and conversation-mode words dropped: those were for the old
app's own control surface.
"""
from __future__ import annotations

import re

# The name on its own is a couple of phonemes and collides with ordinary words,
# so a greeting is required in front of it. That one extra syllable is most of
# the difference between a wake word you can live with and one that interrupts
# every conversation held near the machine.
GREETINGS = ("hey", "hay", "hi", "high", "okay", "ok", "yo", "hey there")

# What Whisper turns a name into when it is not expecting it. Hand-made,
# because guessing at mishearings of an arbitrary name produces the wrong ones,
# and a wrong one is a word that wakes her by accident all day. Only ever
# matched with a greeting in front. A name not in here gets itself and its
# possessive, which is enough: the model is also told the name in its prompt,
# and that does more for accuracy than any list. Add to this from a real
# mishearing in the log, not before. (The "aries" row is a first guess.)
KNOWN_MISHEARINGS = {
    "aries": ("ares", "aeries", "areas", "eris", "arees", "airies"),
    "ida": ("eda", "ada", "aida", "idah", "ita", "eider", "either", "eater", "ito", "edo"),
}

# Words that mean "now" or "drop it" when said alone while she is open.
SEND_WORDS = ("send", "send it", "send that", "sent", "go ahead", "do it",
              "okay send", "ok send", "send it now", "sending", "send now")
# One syllable, said flatly at the end of a sentence, comes back from the model
# as a real word that sounds the same, nearly always one of these. Listed
# rather than guessed at, so it can be argued with.
SEND_NEAR_MISSES = ("cent", "scent", "sen", "zen", "sand", "sind", "cend", "said", "end",
                    "sen'", "sende", "sinned", "sent it", "cent it", "sendit", "sends")
# Real words a letter away from "send" that someone might mean; the fuzzy rule
# would swallow them, so they are held back from it.
SEND_NOT = ("spend", "bend", "lend", "mend", "tend", "fend", "vend", "wend", "rend",
            "sends", "sending")
SEND_FUZZ = 1

# Said over the top of her: stop reading this out, and nothing more.
SKIP_WORDS = ("skip", "skip it", "shut up", "be quiet", "quiet", "stop talking",
              "stop reading", "enough", "shush", "hush")

# Whole utterances only: "nevermind, play the next one" is a command with a
# false start, not a dismissal.
DISMISS_WORDS = ("nevermind", "never mind", "forget it", "forget about it", "that's all",
                 "thats all", "that is all", "stop listening", "go to sleep", "go away",
                 "cancel that", "as you were", "dismissed", "okay nevermind", "ok nevermind",
                 "no nevermind")


def flatten(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def edit_distance(a: str, b: str, ceiling: int) -> int:
    """Levenshtein, abandoned once it is past `ceiling`. Small strings only."""
    if abs(len(a) - len(b)) > ceiling:
        return ceiling + 1
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        row = [i]
        for j, right in enumerate(b, 1):
            row.append(min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (left != right)))
        if min(row) > ceiling:
            return ceiling + 1
        previous = row
    return previous[-1]


class Names:
    """Everything that counts as her name, and the prompts Whisper is primed with."""

    def __init__(self, name: str = "Aries", aliases=()) -> None:
        self.name = (name or "Aries").strip() or "Aries"
        forms: list[str] = []
        for n in (self.name, *aliases):
            base = re.sub(r"[^a-z0-9' ]+", "", n.lower()).strip()
            if base:
                forms += [base, base + "'s", *KNOWN_MISHEARINGS.get(base, ())]
        self.forms = tuple(dict.fromkeys(forms))
        # Longest first so "hey there aries" is not "hey" plus a command "there aries".
        self.wake_words = tuple(sorted((f"{g} {n}" for g in GREETINGS for n in self.forms),
                                       key=len, reverse=True))
        self.phrase = f"hey {self.name}"
        # Whisper's prompt is the single most effective accuracy lever here:
        # told to expect her name it stopped hearing "hey Ida" as "hey either"
        # (1 in 3 wakes to 3 in 3).
        self.wake_hint = f"Hey {self.name}."
        self.interrupt_hint = f"Hey {self.name}. Skip. Stop talking."

    def heard_name(self, text: str) -> str | None:
        """The words after her name, "" for the name alone, None if she wasn't
        addressed. The name has to open the sentence: "Aries, do X" is for her;
        a name inside a sentence is nearly always about someone else."""
        flat = flatten(text)
        if not flat:
            return None
        for wake in self.wake_words:
            if flat == wake:
                return ""
            if flat.startswith(wake + " "):
                return flat[len(wake):].strip()
        return None

    def _matches(self, text: str, words) -> bool:
        """The whole utterance is one of `words`, with or without her name first."""
        flat = flatten(text)
        if flat in words:
            return True
        return any(flat.startswith(n + " ") and flat[len(n) + 1:] in words for n in self.forms)

    def addressed(self, text: str) -> bool:
        """Her name opens it, greeting or not (for "Aries, shut up")."""
        flat = flatten(text)
        return self.heard_name(text) is not None or any(flat.startswith(n + " ") for n in self.forms)

    def is_send(self, text: str) -> bool:
        """"Now do it", whatever the model made of it. Only consulted while she is
        already open and the utterance is short, so a false match sends a
        draft slightly early."""
        if self._matches(text, SEND_WORDS):
            return True
        flat = flatten(text)
        for n in self.forms:
            if flat.startswith(n + " "):
                flat = flat[len(n) + 1:].strip()
                break
        if not flat or " " in flat:
            return flat in SEND_WORDS or flat in SEND_NEAR_MISSES
        if flat in SEND_WORDS or flat in SEND_NEAR_MISSES:
            return True
        if flat in SEND_NOT:
            return False
        return edit_distance(flat, "send", SEND_FUZZ) <= SEND_FUZZ

    def is_skip(self, text: str) -> bool:
        return self._matches(text, SKIP_WORDS)

    def is_dismissal(self, text: str) -> bool:
        return self._matches(text, DISMISS_WORDS)
