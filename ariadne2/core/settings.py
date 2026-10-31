"""Every setting she has, in one place: the schema the desk draws, the file they live in, the checks, and
what each change does to the running core.

    s = Settings()                       # ~/.config/ariadne2/settings.json (sounds.json migrated in once)
    bind_core(s, conversation=c, voice=v, ears=e)
    s.apply_all()                        # make the running parts match the file
    s.set("voice", "speed", 1.2)         # validated, saved, applied; raises SettingsError

Sections: general, models, voice, desktop, avatar. The file is `{section: {key: value}}`, every key written, so
the pet (which polls its mtime) and the desk read their parts without knowing the defaults. docs/SETTINGS.md
lists every key and the ranges the pet should expect.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
import threading
from pathlib import Path

from .. import protocol
from . import prompt

log = logging.getLogger("ariadne2.core.settings")

SECTIONS = ("general", "models", "voice", "desktop", "avatar")

# Where the desk's synthesised sound effects are switched (sounds.js KINDS).
SOUND_KINDS = ("send", "done", "fail", "flow", "spotify", "steam", "browser", "dolphin",
               "claude", "mic", "raise", "drop")
_SOUND_LABELS = {
    "send": "Sending a message", "done": "A job finishing", "fail": "A job failing",
    "flow": "A flow firing", "spotify": "Spotify", "steam": "Steam", "browser": "The browser",
    "dolphin": "Dolphin (files moving)", "claude": "Claude hands", "mic": "The mic opening or closing",
    "raise": "The desk rising", "drop": "The desk dropping away",
}

CONVERSATION_MODELS = (("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-opus-5-5", "Opus 5.5"),
                       ("deepseek-flash", "DeepSeek Flash"), ("deepseek-v4-pro", "DeepSeek V4 Pro"))
EYES_MODELS = (("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-haiku-5-5", "Haiku 5.5"),
               ("claude-opus-5-5", "Opus 5.5"), ("deepseek-flash", "DeepSeek Flash"))

# What can open a wake phrase; the same list the ears match (ears/wake.py GREETINGS).
GREETINGS = ("hey there", "hey", "hay", "hi", "high", "okay", "ok", "yo")
_NAME = re.compile(r"[A-Za-z0-9' ]{1,24}")
_VOICE_NAMES = {"skylar": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_DEVICE = re.compile(r"[A-Za-z0-9_.:@+\-]{1,120}")
TEXT_MAX = 200


class SettingsError(ValueError):
    """A value that can't be a setting; the message is plain English."""


def _entry(section, key, label, type_, default, help_, **extra) -> dict:
    return {"section": section, "key": key, "label": label, "type": type_, "default": default,
            "help": help_, **extra}


def _choices(pairs) -> list[dict]:
    return [{"value": v, "label": t} for v, t in pairs]


def personalities() -> list[str]:
    """The personality files she can wear: the names in personalities/, without .md."""
    try:
        return sorted(p.stem for p in prompt.PERSONALITIES.glob("*.md")
                      if re.fullmatch(r"[A-Za-z0-9_-]+", p.stem))
    except OSError:
        return [prompt.DEFAULT_PERSONALITY]


LIVE2D_MODELS = Path(__file__).resolve().parents[1] / "pet2d" / "web" / "models"


def bodies() -> list[tuple[str, str]]:
    """The bodies she can wear: the 3D one (pet/) and each Live2D model folder (pet2d/)."""
    vrm = Path(__file__).resolve().parents[2] / "pet" / "models" / "aries.vrm"
    out = [("aries", "Aries (3D, walks about)" if vrm.exists() else "Aries (3D: needs pet/models/aries.vrm)")]
    try:
        for d in sorted(LIVE2D_MODELS.iterdir()):
            if d.is_dir() and any(d.glob("*.model3.json")):
                try:
                    name = json.loads((d / "about.json").read_text()).get("name") or d.name
                except (OSError, ValueError):
                    name = d.name
                core = LIVE2D_MODELS.parent / "vendor" / "live2dcubismcore.min.js"
                out.append((d.name, f"{name} (Live2D)" if core.exists() else f"{name} (Live2D: needs Live2D support)"))
    except OSError:
        pass
    return out


# API keys, entered in the Models section. Never stored in settings.json and never
# sent to the desk: the key goes to a 0600 file (the one models.py and
# cartesia.py read), and the desk only ever sees whether it's set (and its last 4).
API_KEYS = {   # setting key: (file, environment variable, label, help)
    "anthropic_key": ("api_key", "ANTHROPIC_API_KEY", "Anthropic API key",
                      "Her brain, from console.anthropic.com."),
    "deepseek_key": ("deepseek_key", "DEEPSEEK_API_KEY", "DeepSeek API key",
                     "Optional, for DeepSeek models."),
    "cartesia_key": ("cartesia_key", "CARTESIA_API_KEY", "Cartesia API key",
                     "Her voice, from play.cartesia.ai."),
}
KEY_CHARS = re.compile(r"^[A-Za-z0-9_\-.:+/=]{8,300}$")


def _key_path(key: str) -> Path:
    from . import models
    return models.data_dir() / API_KEYS[key][0]


def key_status(key: str) -> str:
    """What the desk may know about a key: "env", "set:…abcd", or ""."""
    _file, env, _label, _help = API_KEYS[key]
    if os.environ.get(env, "").strip():
        return "env"
    try:
        text = _key_path(key).read_text("utf-8").strip()
    except OSError:
        return ""
    return f"set:…{text[-4:]}" if text else ""


def save_api_key(key: str, value: str) -> str:
    """Write (or, for "", remove) a key file; returns the new status."""
    path = _key_path(key)
    if value:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value + "\n")
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    from . import models                      # the next call builds its client with the new key
    models._clients.clear()
    return key_status(key)


def build_schema(personality_names: list[str] | None = None) -> list[dict]:
    names = personality_names or [prompt.DEFAULT_PERSONALITY]
    s: list[dict] = []
    # ---- general (including everything that was Ears in 1.x) ----
    s.append(_entry("general", "personality", "Personality", "choice", prompt.DEFAULT_PERSONALITY,
                    "Which file in personalities/ she speaks as.", options=_choices((n, n) for n in names)))
    s.append(_entry("general", "wake_word", "Listen for her name", "bool", True,
                    "Keep the mic open for the wake phrase; off leaves push-to-talk only."))
    s.append(_entry("general", "wake_phrase", "Wake phrase", "text", "hey Aries",
                    "A greeting (hey, hi, okay, yo) then her name."))
    s.append(_entry("general", "ptt_key", "Push-to-talk key", "key", "Meta+S",
                    "Press, speak, press. Rebind it in System Settings, Shortcuts.", readonly=True))
    s.append(_entry("general", "mic", "Microphone", "text", "",
                    "A capture device from `pactl list short sources`; blank is the system default."))
    # ---- models ----
    s.append(_entry("models", "conversation_model", "Conversation model", "choice", "claude-sonnet-5-5",
                    "The model she talks with.", options=_choices(CONVERSATION_MODELS)))
    s.append(_entry("models", "eyes_model", "Window-control model", "choice", "claude-sonnet-5-5",
                    "Looks at a window and picks where to click when an app has no other way in.",
                    options=_choices(EYES_MODELS)))
    for key, (_f, env, label, help_) in API_KEYS.items():
        s.append(_entry("models", key, label, "secret", "",
                        "",
                        secret=True))
    s.append(_entry("models", "spotify_client_id", "Spotify Client ID", "text", "", ""))
    s.append(_entry("models", "spotify_connect", "Spotify", "bool", False, "", action=True, button="Connect"))
    s.append(_entry("models", "spotify_disconnect", "Disconnect Spotify", "bool", False, "", action=True,
                    confirm=True, button="Disconnect"))
    # ---- voice ----
    s.append(_entry("voice", "voice", "Voice", "text", "skylar",
                    "A Cartesia voice id, or a name she knows: skylar."))
    s.append(_entry("voice", "speed", "Speed", "number", 1.0, "How fast she talks.",
                    min=0.6, max=1.5, step=0.05, unit="x"))
    s.append(_entry("voice", "volume", "Voice volume", "number", 100, "How loud she is.",
                    min=0, max=100, step=5, unit="%"))
    s.append(_entry("voice", "sounds_master", "Sound effects", "bool", True,
                    "The little sounds the desk makes; off silences them all."))
    s.append(_entry("voice", "sounds_volume", "Sound effects volume", "number", 50,
                    "How loud the effects are.", min=0, max=100, step=5, unit="%"))
    for kind in SOUND_KINDS:
        s.append(_entry("voice", f"sound_{kind}", _SOUND_LABELS[kind], "bool", True,
                        "Play this sound; off mutes just this one."))
    s.append(_entry("general", "check_updates", "Check for updates", "bool", True,
                    "Look for a newer Ariadne on GitHub every few hours."))
    s.append(_entry("general", "auto_update", "Install updates automatically", "bool", True,
                    "Download them when found; a Restart button appears on her core. Never touches local edits."))
    s.append(_entry("general", "check_now", "Check for updates now", "bool", False,
                    "Look right away.", action=True))
    # ---- desktop ----
    s.append(_entry("desktop", "raise_key", "Raise hotkey", "key", "Meta+A",
                    "Lifts the desk over your windows. Rebind it in System Settings, Shortcuts.",
                    readonly=True))
    s.append(_entry("desktop", "reset_layout", "Reset the layout", "bool", False,
                    "Put every widget back where it starts.", action=True, confirm=True))
    s.append(_entry("desktop", "body", "Her body", "bool", True,
                    "Show her walking about on the desktop."))
    s.append(_entry("desktop", "quiet_fullscreen", "Quiet while fullscreen", "bool", True,
                    "No sound effects while a fullscreen window (a game) is focused. Her voice is unaffected."))
    s.append(_entry("desktop", "autostart", "Start when I log in", "bool", False,
                    "Open with the desktop."))
    # ---- avatar (the pet) ----
    s.append(_entry("avatar", "model", "Model", "choice", "aries",
                    "Which body she wears on the desktop.", options=_choices(bodies())))
    s.append(_entry("avatar", "live2d_core", "Live2D support", "bool", False,
                    "Live2D's Cubism Core, free under Live2D's licence (live2d.com/eula). Downloading accepts it.",
                    action=True, button="Download"))
    for key, label, what in (("energy_drain", "Energy drain", "how fast she tires"),
                             ("fun_drain", "Boredom", "how fast she gets bored"),
                             ("affection_drain", "Affection drain", "how fast she misses you"),
                             ("hunger_drain", "Hunger", "how fast she gets hungry")):
        s.append(_entry("avatar", key, label, "number", 1.0,
                        f"Rate multiplier: {what}. 1 is the normal pace.",
                        min=0.25, max=4.0, step=0.05, unit="x"))
    s.append(_entry("avatar", "size", "Size", "number", 300, "Screen pixels per metre; bigger is taller.",
                    min=200, max=840, step=10, unit="px/m"))
    s.append(_entry("avatar", "fps_cap", "Frame rate cap", "number", 30,
                    "Most frames a second while she is busy; idle is slower still.",
                    min=10, max=60, step=5, unit="fps"))
    s.append(_entry("avatar", "sleep_after", "Sleep after", "number", 8,
                    "Minutes of nothing before she dozes off.", min=1, max=120, step=1, unit="min"))
    for key, label, help_ in (
            ("wander", "Wander", "Walk about on her own."),
            ("pinned", "Pin in place", "She stays where you put her, even mid-air: no walking, hopping or "
                                         "falling. Drag her to move the pin."),
            ("sit_on_widgets", "Sit on widgets", "Perch on the edges of widgets."),
            ("walk_off_edges", "Walk off edges", "Step off a widget and drop to the floor."),
            ("dance_to_music", "Dance to music", "Dance when Spotify is playing."),
            ("play_ball", "Play ball", "Fetch the ball on her own when bored."),
            ("nap", "Nap", "Fall asleep when tired or left alone."),
            ("seek_cursor", "Come to the cursor", "Walk over to you when she is lonely."),
            ("react_to_work", "React to her work", "Hold the glowing slab while she works in an app."),
            ("lip_sync", "Lip sync", "Shape her mouth to what she says.")):
        s.append(_entry("avatar", key, label, "bool", key != "pinned", help_))
    return s


# ---------------------------------------------------------------- files

def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "ariadne2"


def default_path() -> Path:
    override = os.environ.get("ARIADNE2_SETTINGS")
    return Path(override) if override else config_dir() / "settings.json"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def migrate_sounds(found) -> dict:
    """1.x-era sounds.json ({master, volume 0-1, muted: [kinds]}) as voice-section values."""
    out: dict = {}
    if not isinstance(found, dict):
        return out
    if isinstance(found.get("master"), bool):
        out["sounds_master"] = found["master"]
    vol = found.get("volume")
    if isinstance(vol, (int, float)) and not isinstance(vol, bool) and 0 <= vol <= 1:
        out["sounds_volume"] = int(round(vol * 100))
    muted = found.get("muted")
    if isinstance(muted, list):
        for kind in SOUND_KINDS:
            if kind in muted:
                out[f"sound_{kind}"] = False
    return out


def sounds_config(values: dict) -> dict:
    """What the page's Sounds.configure wants, from the whole values dict."""
    v = values.get("voice", {})
    return {"master": bool(v.get("sounds_master", True)),
            "volume": float(v.get("sounds_volume", 50)) / 100.0,
            "muted": [k for k in SOUND_KINDS if not v.get(f"sound_{k}", True)]}


# ---------------------------------------------------------------- the store

class Settings:
    def __init__(self, path: str | os.PathLike | None = None, sounds_path: str | os.PathLike | None = None,
                 personality_names=None) -> None:
        self.path = Path(path) if path else default_path()
        self.sounds_path = Path(sounds_path) if sounds_path else self.path.with_name("sounds.json")
        self._personalities = personality_names or personalities
        self._lock = threading.RLock()
        self.hooks: dict[tuple[str, str], object] = {}
        # An action row's status line (Spotify: "Connected as …"), shown beside its button.
        self.status_providers: dict[tuple[str, str], object] = {}
        self.listeners: list = []
        self._load()

    # ---- schema ----
    def schema(self) -> list[dict]:
        return build_schema(list(self._personalities()))

    def _spec(self, section: str, key: str) -> dict:
        for e in self.schema():
            if e["section"] == section and e["key"] == key:
                return e
        raise SettingsError(f"no setting {section}.{key}")

    @staticmethod
    def defaults() -> dict:
        out: dict = {sec: {} for sec in SECTIONS}
        for e in build_schema():
            if not e.get("action") and not e.get("secret"):
                out[e["section"]][e["key"]] = e["default"]
        return out

    # ---- load / save ----
    def _load(self) -> None:
        self.values = self.defaults()
        found = None
        try:
            found = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            self._migrate()
            return
        except (OSError, ValueError):
            log.warning("settings: %s is unreadable; using defaults", self.path)
            return
        if not isinstance(found, dict):
            return
        schema = {(e["section"], e["key"]): e for e in self.schema()}
        for section, items in found.items():
            if not isinstance(items, dict):
                continue
            for key, value in items.items():
                spec = schema.get((section, key))
                if spec is None or spec.get("action") or spec.get("readonly") or spec.get("secret"):
                    continue
                try:
                    self.values[section][key] = self._check(spec, value)
                except SettingsError as e:
                    log.warning("settings: ignoring %s.%s in the file: %s", section, key, e)

    def _migrate(self) -> None:
        """First run: pick up the old sounds.json, write settings.json, set the old file aside."""
        try:
            old = json.loads(self.sounds_path.read_text("utf-8"))
        except (OSError, ValueError):
            return
        schema = {(e["section"], e["key"]): e for e in self.schema()}
        for key, value in migrate_sounds(old).items():
            try:
                self.values["voice"][key] = self._check(schema[("voice", key)], value)
            except SettingsError:
                pass
        try:
            self.save()
            self.sounds_path.rename(self.sounds_path.with_name(self.sounds_path.name + ".migrated"))
            log.info("settings: migrated %s", self.sounds_path)
        except OSError:
            log.exception("settings: couldn't finish migrating %s", self.sounds_path)

    def save(self) -> None:
        with self._lock:
            _atomic_write(self.path, json.dumps(self.values, indent=2, sort_keys=False) + "\n")

    # ---- validation ----
    def _check(self, spec: dict, value):
        """The value as stored, or SettingsError."""
        t = spec["type"]
        label = spec["label"]
        if spec.get("readonly"):
            raise SettingsError(f"{label} is set in System Settings, Shortcuts")
        if t == "bool":
            if not isinstance(value, bool):
                raise SettingsError(f"{label} is on or off")
            return value
        if t == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise SettingsError(f"{label} needs a number")
            if not spec["min"] <= value <= spec["max"]:
                raise SettingsError(f"{label} runs from {spec['min']} to {spec['max']}")
            whole = all(float(spec[k]).is_integer() for k in ("min", "max", "step"))
            return int(round(value)) if whole else round(float(value), 4)
        if t == "choice":
            allowed = [o["value"] for o in spec["options"]]
            if value not in allowed:
                raise SettingsError(f"{label} must be one of: {', '.join(allowed)}")
            return value
        if t in ("text", "key"):
            if not isinstance(value, str):
                raise SettingsError(f"{label} needs text")
            value = value.strip()
            if len(value) > TEXT_MAX or any(ord(c) < 32 for c in value):
                raise SettingsError(f"{label} is too long or has odd characters")
            return _CHECKS.get((spec["section"], spec["key"]), lambda v, _l: v)(value, label)
        raise SettingsError(f"{label} has an unknown type")

    def validate(self, section: str, key: str, value):
        return self._check(self._spec(section, key), value)

    # ---- reading ----
    def get(self, section: str, key: str):
        with self._lock:
            return self.values[section][key]

    def snapshot(self) -> dict:
        """The values with the readonly and momentary keys filled in, as the desk shows them."""
        with self._lock:
            out = {sec: dict(items) for sec, items in self.values.items()}
        for e in self.schema():
            if e.get("readonly") or e.get("action"):
                out[e["section"]][e["key"]] = e["default"]
                provider = self.status_providers.get((e["section"], e["key"]))
                if provider is not None:
                    try:
                        out[e["section"]][e["key"]] = str(provider())
                    except Exception:
                        log.exception("status for %s.%s", e["section"], e["key"])
            elif e.get("secret"):
                out[e["section"]][e["key"]] = key_status(e["key"])
        return out

    def message(self) -> dict:
        """The `settings` protocol message for now."""
        return protocol.settings(self.schema(), self.snapshot())

    # ---- changing ----
    def set(self, section: str, key: str, value):
        """Validate, store, save, apply. Returns the value now in force. Raises SettingsError."""
        spec = self._spec(section, key)
        if spec.get("secret"):
            if not isinstance(value, str):
                raise SettingsError(f"{spec['label']} needs text")
            value = value.strip()
            if value and not KEY_CHARS.match(value):
                raise SettingsError(f"{spec['label']} doesn't look like an API key")
            status = save_api_key(key, value)
            self._apply(section, key, status)        # never the key itself
            self._notify(section, key, status)
            return status
        if spec.get("action"):
            if value is not True:
                raise SettingsError(f"{spec['label']} is a button")
            self._apply(section, key, True)
            self._notify(section, key, True)
            return False
        value = self._check(spec, value)
        with self._lock:
            changed = self.values[section][key] != value
            self.values[section][key] = value
            self.save()
        if changed:
            self._apply(section, key, value)
        self._notify(section, key, value)
        return value

    def _apply(self, section: str, key: str, value) -> None:
        hook = self.hooks.get((section, key))
        if hook is None:
            return
        try:
            hook(value)
        except Exception:
            log.exception("settings: applying %s.%s failed", section, key)

    def _notify(self, section: str, key: str, value) -> None:
        for fn in list(self.listeners):
            try:
                fn(section, key, value)
            except Exception:
                log.exception("settings: a listener failed")

    def apply_all(self, skip=()) -> None:
        """Run every hook once with the stored value, so the running parts match the file."""
        for (section, key), hook in list(self.hooks.items()):
            if (section, key) in skip or (section, key) in NOT_AT_START:
                continue
            self._apply(section, key, self.get(section, key))


# Momentary or one-off: running them every start would be wrong (a reset, a write to autostart).
NOT_AT_START = {("desktop", "reset_layout"), ("desktop", "autostart"), ("general", "check_now"),
                ("models", "spotify_connect"), ("models", "spotify_disconnect"), ("avatar", "live2d_core")}


# ---- per-key checks for text settings ----

def parse_wake_phrase(text: str) -> str:
    """The name in "hey <name>" (original case), or ValueError."""
    flat = re.sub(r"\s+", " ", text.strip())
    low = flat.lower()
    for g in GREETINGS:
        if low.startswith(g + " "):
            name = flat[len(g) + 1:].strip()
            if not _NAME.fullmatch(name) or not re.search(r"[A-Za-z0-9]", name):
                raise ValueError("her name is letters and numbers, up to 24 characters")
            return name
    raise ValueError("start with a greeting: hey, hi, okay or yo")


def _check_wake_phrase(value: str, _label: str) -> str:
    try:
        return f"hey {parse_wake_phrase(value)}"
    except ValueError as e:
        raise SettingsError(f"Wake phrase: {e}")


def _check_voice(value: str, _label: str) -> str:
    if not value:
        return "skylar"
    if _UUID.match(value):
        return value.lower()
    if value.lower() in _VOICE_NAMES:
        return value.lower()
    raise SettingsError("Voice: use a Cartesia voice id or a name she knows (skylar)")


def _check_mic(value: str, _label: str) -> str:
    if value and not _DEVICE.fullmatch(value):
        raise SettingsError("Microphone: a device name, as `pactl list short sources` prints it")
    return value


_CHECKS = {("general", "wake_phrase"): _check_wake_phrase,
           ("voice", "voice"): _check_voice,
           ("general", "mic"): _check_mic}


# ---------------------------------------------------------------- hooks into the running core

def set_autostart(on: bool, directory: Path | None = None, template: Path | None = None) -> None:
    """Write or remove the login autostart entry (the desktop file shipped in docs/)."""
    directory = directory or (config_dir().parent / "autostart")
    target = directory / "ariadne2.desktop"
    if not on:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return
    template = template or Path(__file__).resolve().parents[2] / "docs" / "ariadne2.desktop"
    text = template.read_text("utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, text.rstrip("\n") + "\nX-GNOME-Autostart-enabled=true\n")


def bind_core(settings: Settings, conversation=None, voice=None, ears=None, operate=None,
              autostart=set_autostart, reset_layout=None, updater=None) -> None:
    """Wire each setting to the part of the running core it changes. Any part may be None (a quiet run)."""
    h = settings.hooks
    if conversation is not None:
        h[("models", "conversation_model")] = lambda v: setattr(conversation, "model_name", v)
        h[("general", "personality")] = lambda v: setattr(conversation, "personality", v)
    if operate is not None:
        h[("models", "eyes_model")] = lambda v: operate.EYES.__setitem__("model", v)
    if voice is not None:
        h[("voice", "voice")] = lambda v: setattr(voice, "voice", v)
        h[("voice", "speed")] = lambda v: setattr(voice, "speed", float(v))
        h[("voice", "volume")] = lambda v: setattr(voice, "volume", float(v) / 100.0)
    if ears is not None:
        h[("general", "wake_word")] = lambda v: (ears.set_wake_word(bool(v)) if bool(v) != ears.wake_word else None)

        def phrase(v):
            name = parse_wake_phrase(v)
            if name != ears.names.name:
                ears.set_name(name)
        h[("general", "wake_phrase")] = phrase
        h[("general", "mic")] = ears.set_mic
    h[("desktop", "autostart")] = lambda v: autostart(bool(v))
    if updater is not None:
        import asyncio
        h[("general", "check_now")] = lambda _v: asyncio.ensure_future(updater.check())
    if reset_layout is not None:
        h[("desktop", "reset_layout")] = lambda _v: reset_layout()
