"""Her `settings` tool: the app's settings, as his settings panel shows them.

list / get read them; set changes one through Settings.set, so it's checked
exactly as the panel checks it, applied at once (the hooks run), and every
desk is told so the panel moves too. Two lines held here, not just asked of
her: API keys are never read or written (she sees only whether one is set),
and nothing changes unless his own words this turn asked for it (a flow, a
dropped file or a page she read can't flip a setting).
"""
from __future__ import annotations

from ..adapters import AdapterError
from . import settings as settings_mod
from .tools.common import need_him, ToolError

TOOL = {
    "name": "settings",
    "description": (
        "Ariadne's own settings, the ones in the settings panel and the Avatar widget: list them (all, or "
        "one section: general, models, voice, desktop, avatar), get one, or set one. Change one only when "
        "he asks. API keys can't be read or set here; he enters those in Settings > Models himself. "
        "Buttons (check for updates, connect Spotify...) are set to true to press them. hide / show put "
        "a desk widget into the drawer or back out (key: chat, spotify, steam, browser, dolphin, claude, "
        "system, flows, tasks, avatar). Common ones, "
        "to set straight away: voice.speed (0.6-1.5), voice.volume (0-100), voice.sounds_master (sound "
        "effects on/off), general.wake_word (listen for your name on/off), general.wake_phrase, "
        "models.conversation_model (your brain), avatar.model (your body), avatar.size (200-840), "
        "avatar.pinned, avatar.dance_to_music, desktop.body (body shown or not)."),
    "input_schema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["list", "get", "set", "hide", "show"]},
        "section": {"type": "string", "enum": list(settings_mod.SECTIONS)},
        "key": {"type": "string", "description": "the setting's key, as list shows it; for hide/show, the widget"},
        "value": {"description": "for set: the new value (on/off, a number, one of the choices, text)"},
    }, "required": ["action"]},
}


def _shown(spec: dict, value) -> str:
    if spec.get("secret"):
        return "set" if value else "not set"
    if spec["type"] == "choice":
        label = next((o["label"] for o in spec.get("options", []) if o["value"] == value), value)
        return f"{label}" if label == value else f"{label} [{value}]"
    if spec["type"] == "bool":
        return "on" if value else "off"
    if spec["type"] == "number":
        return f"{value:g}{spec.get('unit', '')}" if isinstance(value, (int, float)) else str(value)
    return str(value) if value not in (None, "") else "(empty)"


def _range(spec: dict) -> str:
    if spec.get("readonly"):
        return "read-only"
    if spec.get("his_only"):
        return "his to change, not yours"
    if spec.get("secret"):
        return "he sets it himself"
    if spec.get("action"):
        return "button: set true to press"
    if spec["type"] == "choice":
        return "one of: " + ", ".join(o["value"] for o in spec.get("options", []))
    if spec["type"] == "number":
        return f"{spec['min']:g} to {spec['max']:g}{spec.get('unit', '')}"
    if spec["type"] == "bool":
        return "on/off"
    return "text"


def _coerce(spec: dict, value):
    """What a model tends to send ("on", "75", "Opus 5.5") as the type the setting wants."""
    t = spec["type"]
    if spec.get("action"):
        return True
    if t == "bool":
        if isinstance(value, bool):
            return value
        v = str(value).strip().lower()
        if v in ("true", "on", "yes", "1", "enable", "enabled"):
            return True
        if v in ("false", "off", "no", "0", "disable", "disabled"):
            return False
        raise ToolError(f"{spec['label']} is on or off")
    if t == "number":
        try:
            return float(str(value).strip().rstrip("%xpx/mfpsin "))
        except ValueError:
            raise ToolError(f"{spec['label']} needs a number ({_range(spec)})")
    if t == "choice":
        v = str(value).strip()
        for o in spec.get("options", []):
            if v.lower() in (str(o["value"]).lower(), str(o["label"]).lower()):
                return o["value"]
        hits = [o["value"] for o in spec.get("options", []) if v.lower() in str(o["label"]).lower()]
        if len(hits) == 1:
            return hits[0]
        raise ToolError(f"{spec['label']} is {_range(spec)}")
    return value if isinstance(value, str) else str(value)


def widget_states() -> tuple[list[str], list[str]]:
    """(shown, in the drawer), from the desk's own files."""
    import json
    from pathlib import Path
    from .. import protocol
    try:
        hidden = set(json.loads((Path.home() / ".config" / "ariadne2" / "hidden.json").read_text()))
    except (OSError, ValueError):
        hidden = set()
    names = [w for w in protocol.WIDGETS if w != "core"]
    return [w for w in names if w not in hidden], [w for w in names if w in hidden]


class SettingsTools:
    def __init__(self, settings, publish) -> None:
        self.settings = settings
        self.publish = publish

    def tools(self) -> list[dict]:
        return [TOOL]

    def _spec(self, section, key) -> dict:
        key = str(key or "")
        if "." in key:                         # "voice.speed", as the list and the description write it
            section, key = key.split(".", 1)
        if not section or not key:
            raise ToolError("say which setting: section and key (list shows them)")
        try:
            return self.settings._spec(str(section), str(key))
        except settings_mod.SettingsError:
            raise ToolError(f"there's no setting {section}.{key}; list shows them")

    async def call(self, name: str, args: dict, his_words: str | None = None):
        a = args or {}
        try:
            return await self._run(a, his_words)
        except (ToolError, settings_mod.SettingsError) as e:
            raise AdapterError(str(e))

    async def _run(self, a: dict, his_words):
        action = a.get("action")
        if action in ("hide", "show"):
            return await self._widget(action, str(a.get("key") or a.get("section") or ""), his_words)
        snap = self.settings.snapshot()
        if action == "list":
            section = a.get("section")
            rows = []
            for spec in self.settings.schema():
                if section and spec["section"] != section:
                    continue
                if spec.get("action"):
                    v = ""
                else:
                    v = " = " + _shown(spec, snap.get(spec["section"], {}).get(spec["key"]))
                rows.append(f"{spec['section']}.{spec['key']} ({spec['label']}){v}  [{_range(spec)}]")
            if not section or section == "widgets":
                shown, hidden = widget_states()
                rows.append(f"widgets: shown {', '.join(shown) or 'none'}; in the drawer {', '.join(hidden) or 'none'}"
                            "  [hide / show]")
            return "\n".join(rows) or "No settings there."
        spec = self._spec(a.get("section"), a.get("key"))
        if action == "get":
            return f"{spec['label']}: {_shown(spec, snap.get(spec['section'], {}).get(spec['key']))} ({_range(spec)})"
        if action == "set":
            need_him(his_words, "changing his settings")
            if spec.get("secret"):
                raise ToolError("API keys are his to enter, in Settings > Models; I don't touch them")
            if spec.get("his_only"):
                raise ToolError(f"{spec['label']} is his alone to change, in Settings")
            if spec.get("readonly"):
                raise ToolError(f"{spec['label']} is changed in System Settings, Shortcuts")
            if "value" not in a and not spec.get("action"):
                raise ToolError("set needs a value")
            value = _coerce(spec, a.get("value"))
            self.settings.set(spec["section"], spec["key"], value)
            await self.publish(self.settings.message())              # the panel moves too
            if spec.get("action"):
                return f"Pressed {spec['label']}."
            now = self.settings.snapshot()[spec["section"]][spec["key"]]
            return f"{spec['label']} is now {_shown(spec, now)}."
        raise ToolError("action is list, get, set, hide or show")

    async def _widget(self, op: str, name: str, his_words) -> str:
        from .. import protocol
        need_him(his_words, "rearranging his desk")
        name = name.strip().lower()
        if name == "core":
            raise ToolError("her core stays on the desk")
        if name not in protocol.WIDGETS:
            raise ToolError(f"no widget {name!r}; there's {', '.join(w for w in protocol.WIDGETS if w != 'core')}")
        shown, hidden = widget_states()
        if op == "hide" and name in hidden:
            return f"{name} is already in the drawer."
        if op == "show" and name in shown:
            return f"{name} is already on the desk."
        await self.publish({"t": "desk_do", "op": op, "widget": name})
        return f"{'Put' if op == 'hide' else 'Brought'} {name} {'in the drawer' if op == 'hide' else 'back onto the desk'}."
