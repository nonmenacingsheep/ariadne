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


# ---- spending his Claude usage (consent="spend") ----
#
# Starting a Claude Code run spends the usage he watches closely, so it needs
# his say-so in the same way a message does: his own words this turn have to
# ask for it. Only his words count; page text and tool results never reach
# here. There is no recipient to name, so what must appear is Claude (or "a
# hand") together with a word that sets it to work, or "claude code" outright.

_CLAUDE = re.compile(r"\bclaude\b", re.I)
_CLAUDE_CODE = re.compile(r"\bclaude[\s\-]*code\b", re.I)
_HAND = re.compile(r"\b(?:second|other|another|extra|spare)\s+hands?\b|\bhand(?:s)?\s+(?:it|this|that|them)\s+(?:off|over)\b"
                   r"|\bhand\s*off\b|\bhand\s+(?:it|this|that)\s+to\b|\bdelegate\b", re.I)
_DO = re.compile(r"\b(have|get|let|ask|tell|make|start|run|launch|spin\s+up|spawn|kick\s+off|use|send|"
                 r"hand|delegate|put|set|give|call)\b", re.I)
# "don't use claude", "no claude for this", "without claude": a refusal, not a request.
_NOT = re.compile(r"\b(?:don'?t|do\s+not|dont|never|without|no|not|stop)\b[^.?!\n]{0,30}\b(?:claude|hands?)\b", re.I)


def allows_spend(his_words: str | None) -> bool:
    """True when his own words ask for Claude (or a hand) to be put to work."""
    words = his_words or ""
    if not words.strip() or _NOT.search(words):
        return False
    if _CLAUDE_CODE.search(words):
        return True
    return bool((_CLAUDE.search(words) or _HAND.search(words)) and _DO.search(words))


def spend_refusal() -> str:
    return ("Not started: that spends his Claude usage, and he didn't ask for Claude or a hand "
            "to do it in his own words this turn. Tell him what you'd have it do and let him say so.")
