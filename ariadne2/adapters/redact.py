"""Strip credentials from text she reads out of pages and DMs.

Ported from 1.x memory.redact_secrets (the vendor token shapes) and widened for
what a logged-in browser can show: passwords in URLs, `password=`/`"token":`
pairs, Bearer headers, JWTs, Discord tokens. The 1.x "by value" pass (removing
the app's own saved keys) is not ported; 2.0 has no such files yet.
Pattern-matching can't catch everything, so this is a net, not a guarantee.
"""
from __future__ import annotations

import re

REDACTED = "[redacted credential]"

# Whole-token shapes: the match is replaced entirely.
_SHAPES = re.compile(r"""(
    sk-ant-[A-Za-z0-9_\-]{20,}                    # Anthropic
  | sk-(?:proj-)?[A-Za-z0-9_\-]{32,}              # OpenAI-style
  | sk_(?:live|test)_[A-Za-z0-9]{16,}             # Stripe secret
  | rk_(?:live|test)_[A-Za-z0-9]{16,}
  | gh[pousr]_[A-Za-z0-9]{20,}                    # GitHub
  | github_pat_[A-Za-z0-9_]{20,}
  | glpat-[A-Za-z0-9_\-]{16,}                     # GitLab
  | npm_[A-Za-z0-9]{30,}
  | xox[baprs]-[A-Za-z0-9\-]{10,}                 # Slack
  | AKIA[0-9A-Z]{16}                              # AWS access key id
  | AIza[0-9A-Za-z_\-]{30,}                       # Google
  | GOCSPX-[A-Za-z0-9_\-]{20,}                    # Google OAuth client secret
  | eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}   # JWT
  | [MNO][A-Za-z0-9_\-]{23,25}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,}   # Discord token
  | -----BEGIN[ A-Z]*PRIVATE\ KEY-----[\s\S]*?(?:-----END[ A-Z]*PRIVATE\ KEY-----|$)
  | (?i:bearer)\ +[A-Za-z0-9._~+/\-]{16,}=*      # Authorization: Bearer ...
)""", re.VERBOSE)

# user:password@ inside a URL: only the userinfo goes.
_URL_USERINFO = re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")

# name = value / "name": "value" for names that say they are secret.
_PAIR = re.compile(
    r"""(?ix)
    (\b(?:[\w.\-]*(?:password|passwd|pwd|secret|api[_\-]?key|apikey|access[_\-]?token|
        refresh[_\-]?token|auth[_\-]?token|token|authorization)[\w.\-]*)["']?\s*[:=]\s*["']?)
    ([^\s"'&,;<>]{6,})""")


def redact_secrets(text: str) -> tuple[str, int]:
    """The text with credentials removed, and how many were found."""
    body, total = text or "", 0
    body, n = _SHAPES.subn(REDACTED, body)
    total += n
    body, n = _URL_USERINFO.subn(REDACTED, body)
    total += n

    def pair(m: re.Match) -> str:
        return m.group(0) if m.group(2).startswith("[redacted") else m.group(1) + REDACTED
    hits = [m for m in _PAIR.finditer(body) if not m.group(2).startswith("[redacted")]
    if hits:
        body = _PAIR.sub(pair, body)
        total += len(hits)
    return body, total


def redact(text: str) -> str:
    return redact_secrets(text)[0]


def note(count: int) -> str:
    """The line appended to a result when something was removed."""
    return f"[{count} credential{'s' if count != 1 else ''} removed before you saw this]" if count else ""
