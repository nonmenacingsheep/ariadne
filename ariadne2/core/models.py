"""Talking to the model, the way 1.x does.

1.x uses the `anthropic` Python SDK with an API key (never the Claude Code
login): the ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN environment variable if
set, else the file 1.x saved at ~/.local/share/ariadne/api_key. An `ant auth
login` profile works when no key exists, and an identity-linked key needs a
workspace id (ANTHROPIC_WORKSPACE_ID, or workspace_id in 1.x's state.json).
DeepSeek speaks the same wire format at its own base URL, with its own key.

Keys are read at call time and handed to the client; they are never copied
anywhere, put in os.environ, or logged.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

log = logging.getLogger("ariadne2.core.models")

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 2048              # chat replies are a line or two; this is headroom
TIMEOUT = 90.0
DEFAULT_BASES = {"https://api.anthropic.com", "https://api.anthropic.com/v1"}

PROVIDERS = {
    "anthropic": {"base_url": None, "key_file": "api_key",
                  "env": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
                  "label": "Anthropic"},
    "deepseek": {"base_url": "https://api.deepseek.com/anthropic",
                 "key_file": "deepseek_key", "env": ("DEEPSEEK_API_KEY",),
                 "label": "DeepSeek"},
}

# Each model spells "no thinking before the first word" differently and
# refuses the others (measured in 1.x, 2026-10-24). Chat wants words at once.
_THINKING_OFF = {"claude-sonnet-5-5": {"type": "between_tools"},
                 "claude-haiku-5-5": {"type": "disabled"},
                 "claude-opus-5-5": None}        # can't be turned off


class ModelError(Exception):
    """The model couldn't be reached. `message` is plain English for a person."""

    def __init__(self, message: str, kind: str = "internal") -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind


@dataclass
class ToolUse:
    """The model asked for a tool; yielded by `stream` after its text."""
    id: str
    name: str
    input: dict = field(default_factory=dict)


@dataclass
class Done:
    """End of one model call: the full assistant content, exactly as received
    (thinking blocks must go back to the API unmodified in a tool loop)."""
    content: list
    stop_reason: str | None = None


def provider_for(model: str) -> str:
    return "deepseek" if model.startswith("deepseek") else "anthropic"


def data_dir() -> Path:
    """Where keys live: 1.x's folder when it exists (so its saved keys keep
    working), else 2.0's own (a fresh install)."""
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "ariadne" if (base / "ariadne").is_dir() else base / "ariadne2"


def find_key(provider: str) -> str | None:
    spec = PROVIDERS[provider]
    for var in spec["env"]:
        value = os.environ.get(var, "").strip()
        if value:
            return value
    try:
        return (data_dir() / spec["key_file"]).read_text("utf-8").strip() or None
    except OSError:
        return None


def _oauth_profile() -> bool:
    base = os.environ.get("ANTHROPIC_CONFIG_DIR")
    creds = (Path(base) if base else Path.home() / ".config" / "anthropic") / "credentials"
    try:
        return creds.is_dir() and any(creds.glob("*.json"))
    except OSError:
        return False


def _workspace_id() -> str | None:
    env = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    if env:
        return env
    try:
        saved = json.loads((data_dir() / "state.json").read_text("utf-8"))
        return (saved.get("workspace_id") or "").strip() or None
    except (OSError, ValueError, AttributeError):
        return None


def client_kwargs(provider: str) -> dict:
    """Constructor arguments for the client, or ModelError if there's no way in."""
    spec = PROVIDERS[provider]
    kwargs: dict = {"max_retries": 2, "timeout": TIMEOUT}
    if spec["base_url"]:
        kwargs["base_url"] = spec["base_url"]
    key = find_key(provider)
    if key:
        kwargs["api_key"] = key
    if provider == "anthropic":
        base = (os.environ.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
        if "api_key" not in kwargs and base and base not in DEFAULT_BASES:
            kwargs["api_key"] = "via-gateway"      # a gateway does its own auth
        if "api_key" not in kwargs and not _oauth_profile():
            raise ModelError(
                "I don't have an API key. Set ANTHROPIC_API_KEY, or save one in "
                f"{data_dir() / spec['key_file']}.", "credentials")
        workspace = _workspace_id()
        if workspace:
            kwargs["default_headers"] = {"anthropic-workspace-id": workspace}
    elif "api_key" not in kwargs:
        raise ModelError(
            f"I don't have a {spec['label']} key. Set {spec['env'][0]}, or save one "
            f"in {data_dir() / spec['key_file']}.", "credentials")
    return kwargs


_clients: dict[str, object] = {}


def _client(provider: str):
    if provider not in _clients:
        try:
            import anthropic
        except ImportError as e:
            raise ModelError("the anthropic package isn't installed here "
                             "(pip install --user anthropic).", "missing") from e
        _clients[provider] = anthropic.AsyncAnthropic(**client_kwargs(provider))
    return _clients[provider]


def classify(exc: Exception) -> ModelError:
    """Turn an SDK exception into a sentence a person can act on."""
    name = exc.__class__.__name__
    text = str(exc)
    if "workspace" in text.lower():
        return ModelError("the key is tied to an identity, so it needs a workspace "
                          "id (ANTHROPIC_WORKSPACE_ID).", "workspace")
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return ModelError("the API rejected my key.", "credentials")
    if name in ("APIConnectionError", "APITimeoutError", "ConnectError"):
        return ModelError("I couldn't reach the API; check the network.", "network")
    if name in ("RateLimitError", "InternalServerError", "OverloadedError"):
        return ModelError("the API is busy or rate limited right now.", "busy")
    if name == "NotFoundError":
        return ModelError("the API doesn't know that model.", "model")
    return ModelError(f"the model call failed ({name}).", "internal")


async def stream(system: str, messages: list[dict], model: str = DEFAULT_MODEL,
                 tools: list[dict] | None = None) -> AsyncIterator:
    """Yield the reply's text deltas as they arrive, then a ToolUse per tool call and
    a final Done. Raises ModelError."""
    provider = provider_for(model)
    client = _client(provider)
    sys_block = {"type": "text", "text": system}
    if provider == "anthropic":
        sys_block["cache_control"] = {"type": "ephemeral"}
    kwargs: dict = dict(model=model, max_tokens=MAX_TOKENS, system=[sys_block],
                        messages=messages)
    if tools:
        # The mark on the last tool caches all of them with the system prompt.
        tools = [dict(t) for t in tools]
        if provider == "anthropic":
            tools[-1]["cache_control"] = {"type": "ephemeral"}
        kwargs["tools"] = tools
    # extra_body so an SDK that doesn't know a thinking mode yet still sends it.
    if provider == "deepseek":
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    elif _THINKING_OFF.get(model):
        kwargs["extra_body"] = {"thinking": _THINKING_OFF[model]}
    try:
        async with client.messages.stream(**kwargs) as s:
            async for chunk in s.text_stream:
                yield chunk
            final = await s.get_final_message()
        for block in final.content:
            if block.type == "tool_use":
                yield ToolUse(block.id, block.name, dict(block.input or {}))
        yield Done([b.model_dump(exclude_none=True) for b in final.content], final.stop_reason)
    except ModelError:
        raise
    except Exception as e:
        log.exception("model call failed")
        raise classify(e) from e
