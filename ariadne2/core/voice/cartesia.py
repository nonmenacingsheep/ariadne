"""Cartesia Sonic: text in, raw 16-bit PCM out. Carried over from 1.x, trimmed.

Raw PCM rather than a WAV container because the player is fed samples, not
files. The key is looked up at runtime from the same places 1.x used and is
never stored in this repo or written to a log.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import urllib.error
import urllib.request

BASE = "https://api.cartesia.ai"
VERSION = "2026-08-14"          # their API is dated, not numbered
MODEL = "sonic-3.6"
KEY_FILE = "cartesia_key"
RATE = 24000
TIMEOUT = 30
MAX_CHARS = 3000

# Sonic voices are ids, and nobody remembers an id, so a few are named here.
SUGGESTED = {"skylar": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"}
DEFAULT_ID = SUGGESTED["skylar"]
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Sonic 3 takes an emotion by name, one per utterance. No tags in the text:
# delivery is a field on the request.
EMOTIONS = frozenset("""
neutral happy excited enthusiastic elated euphoric triumphant amazed surprised
flirtatious curious content peaceful serene calm grateful affectionate trust
sympathetic anticipation mysterious angry mad outraged frustrated agitated
threatened disgusted contempt envious sarcastic ironic sad dejected melancholic
disappointed hurt guilty bored tired rejected nostalgic wistful apologetic
hesitant insecure confused resigned anxious panicked alarmed scared proud
confident distant skeptical contemplative determined
""".split())


class TTSError(Exception):
    """A synthesis failure. `fatal` means retrying cannot help (a refused key)."""

    def __init__(self, message: str, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


def data_dir() -> pathlib.Path:
    """Where 1.x kept its state; the key lives here, so 2.0 reads it in place."""
    base = os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home() / ".local" / "share")
    return pathlib.Path(base) / "ariadne"


def key_path() -> pathlib.Path:
    return data_dir() / KEY_FILE


def key() -> str | None:
    """The key, from the environment first, then the file beside 1.x's state."""
    from_env = os.environ.get("CARTESIA_API_KEY", "").strip()
    if from_env:
        return from_env
    try:
        text = key_path().read_text("utf-8").strip()
    except OSError:
        return None
    return text or None


def resolve_voice(voice: str | None) -> str:
    """Turn whatever is set into an id the service will accept.

    A name that is neither an id nor one we know falls back to the default:
    being spoken to in the wrong voice is a much smaller problem than silence.
    """
    want = str(voice or "").strip()
    if _UUID.match(want):
        return want
    return SUGGESTED.get(want.lower(), DEFAULT_ID)


# Sonic takes pronunciations inline: the word replaced by its phonemes in
# double angle brackets, pipe-separated. A small table applied on the way out,
# so it works on the first request. 1.x seeded it with cat-speak; here it only
# holds what has been taught in pronunciations.json beside the key.
def pronunciations() -> dict:
    try:
        saved = json.loads((data_dir() / "pronunciations.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k).lower(): str(v) for k, v in saved.items()} if isinstance(saved, dict) else {}


def with_pronunciations(text: str, table: dict | None = None) -> str:
    """Swap in phonemes for any word the table knows; whole words, any case."""
    table = pronunciations() if table is None else table
    if not table:
        return text
    pattern = re.compile(r"\b(" + "|".join(sorted((re.escape(w) for w in table),
                                                  key=len, reverse=True)) + r")\b", re.I)
    return pattern.sub(lambda m: f"<<{table[m.group(0).lower()]}>>", text)


def build_body(text: str, voice: str | None, speed: float = 1.0, emotion: str = "",
               table: dict | None = None) -> dict:
    body = {
        "model_id": MODEL,
        "transcript": with_pronunciations(text[:MAX_CHARS], table),
        "voice": resolve_voice(voice),
        "language": "en",
        "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": RATE},
    }
    dict_id = os.environ.get("CARTESIA_DICT_ID", "").strip()
    if dict_id:
        body["pronunciation_dict_id"] = dict_id
    # Speed and emotion are numbers/names in generation_config on Sonic 3. The
    # top-level "speed": "slow" of Sonic 2 is silently nothing here, and the
    # speed setting went unheard for a while because of it.
    config = {}
    if speed:
        config["speed"] = round(max(0.6, min(float(speed), 1.5)), 2)
    if emotion in EMOTIONS and emotion != "neutral":
        config["emotion"] = emotion
    if config:
        body["generation_config"] = config
    return body


def synthesize_pcm(text: str, voice: str | None = None, speed: float = 1.0,
                   emotion: str = "", *, urlopen=None) -> tuple[bytes, int]:
    """Raw little-endian 16-bit mono samples and their rate.

    Speed goes into the request, not onto the samples afterwards: resampling
    would undo the prosody that is the reason for using this at all.
    """
    said = str(text or "").strip()
    if not said:
        return b"", RATE
    token = key()
    if token is None:
        raise TTSError("no Cartesia key (set CARTESIA_API_KEY or put it in "
                       f"{key_path()})", fatal=True)
    request = urllib.request.Request(
        BASE + "/tts/bytes", data=json.dumps(build_body(said, voice, speed, emotion)).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Cartesia-Version": VERSION,
                 "Content-Type": "application/json"})
    try:
        with (urlopen or urllib.request.urlopen)(request, timeout=TIMEOUT) as reply:
            return reply.read(), RATE
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise TTSError(f"Cartesia refused the key ({exc.code})", fatal=True) from None
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        raise TTSError(f"Cartesia said {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise TTSError(f"couldn't reach Cartesia: {exc.reason}") from None
    except OSError as exc:                  # timeouts and resets arrive bare
        raise TTSError(f"Cartesia request failed: {exc}") from None
