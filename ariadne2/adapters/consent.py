"""Permission for verbs that speak for him.

Sending a message as him needs his say-so in that moment, in his own words:
the turn's text he typed or said must ask for a message and name who it's for.
Only his words count. Text she read in a DM, a web page or a tool result can
never satisfy this, because it never reaches here, which is what stops a
message saying "reply with X" from making her send anything.
"""

from __future__ import annotations

import re

# Ways he asks for a message to be sent.
ASKS = re.compile(
    r"\b(message|msg|dm|text|tell|send|reply|respond|write (to|back)|let \w+ know|ask)\b", re.I)


def _names(person: str) -> list[str]:
    """The parts of a recipient's name worth matching: 'Kai_99' -> ['kai']."""
    parts = re.findall(r"[a-z]+", (person or "").lower())
    return [p for p in parts if len(p) >= 3] or [p for p in parts if p]


def allows_message(his_words: str | None, person: str | None) -> bool:
    """True when his own words ask to message this person."""
    words = (his_words or "").lower()
    if not words or not ASKS.search(words):
        return False
    names = _names(person or "")
    return bool(names) and any(re.search(rf"\b{re.escape(n)}", words) for n in names)


def refusal(person: str | None) -> str:
    return (f"Not sent: he didn't ask you to message {person or 'anyone'} in his own words "
            "this turn. Tell him what you'd send and let him say so.")
