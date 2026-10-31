"""Extensions: things she installs and then uses as her own tools.

When he asks her to set up something local (an image model, a local LLM, a
CLI program) and use it later, she writes an extension: a folder under
~/.local/share/ariadne2/extensions/<name>/ holding manifest.json and any small
scripts it needs. The manifest says how to start its service (if it has one),
how to tell it's ready, and the tools it offers, each one an HTTP request to
the service or a command to run, with typed parameters. Once approved, those
tools are hers: `x_<extension>_<tool>`, merged into her toolset every turn.

Nothing in an extension runs until he approves it. Saving one (new or changed)
puts an Allow / Deny card in the chat listing exactly what it would start and
run; the approval is tied to a hash of the manifest and its scripts, so any
change asks again. Commands run as an argv list (no shell), parameters are
substituted into whole arguments, and what tools return comes back to her as
outside content (quoted, credentials removed). Images a tool makes are saved
to ~/Pictures/Aries/ and shown to him in the chat as well as handed to her.

Manifest:
{
  "name": "sdxl", "description": "...",
  "service": {"command": ["python3", "server.py"], "cwd": "/abs/or/relative/to/folder",
              "env": {"K": "v"}, "ready_url": "http://127.0.0.1:7860/health",
              "ready_timeout": 180, "idle_stop_minutes": 15},
  "tools": [{
     "name": "generate_image", "description": "...",
     "params": {"prompt": {"type": "string", "description": "..."},
                "steps": {"type": "integer", "default": 25}},
     "required": ["prompt"],
     "http": {"method": "POST", "url": "http://127.0.0.1:7860/sdapi/v1/txt2img",
              "json": {"prompt": "{prompt}", "steps": "{steps}"}, "timeout": 300},
     -- or --
     "command": {"argv": ["python3", "gen.py", "--prompt", "{prompt}", "--out", "{out_dir}"], "timeout": 600},
     "result": {"text": "choices.0.message.content", "images": "images",
                "image_files": "*.png"}
  }]
}
In a template "{name}" alone keeps the parameter's type; inside a longer string
it is text. {out_dir} is a fresh folder for the call's files. Result paths are
dotted ("choices.0.message.content", "*" maps a list); "images" holds base64
strings, "image_files" a glob in {out_dir} (commands) or a path field (HTTP).
"""
from __future__ import annotations

import asyncio
import base64
import copy
import glob as globmod
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .tools.common import outside

log = logging.getLogger("ariadne2.extensions")

NAME = re.compile(r"^[a-z][a-z0-9_]{1,23}$")
TOOL = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
PARAM = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
PARAM_TYPES = ("string", "number", "integer", "boolean")
MAX_TOOLS = 12
MAX_FILES, MAX_FILE_BYTES = 20, 200_000
SCRIPT_SUFFIXES = (".py", ".sh", ".js", ".json", ".txt", ".toml", ".yaml", ".yml", ".cfg", ".ini", ".md")
MAX_TIMEOUT = 1800
IMAGE_MAX_BYTES = 4_500_000          # what she can be shown; bigger ones are still saved and shown to him
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


class ExtensionError(ValueError):
    pass


def ext_root() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "ariadne2" / "extensions"


def pictures() -> Path:
    return Path(os.environ.get("ARIADNE2_PICTURES") or (Path.home() / "Pictures" / "Aries"))


# ------------------------------------------------------------------ manifests

def _check_url(url, where: str) -> str:
    if not isinstance(url, str):
        raise ExtensionError(f"{where}: url must be text")
    p = urllib.parse.urlparse(url.replace("{", "").replace("}", ""))
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ExtensionError(f"{where}: url must be http(s)://host/...")
    return url


def _check_argv(argv, where: str) -> list:
    if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
        raise ExtensionError(f"{where}: command must be a non-empty list of strings (argv, no shell)")
    return argv


def _timeout(v, default: int) -> int:
    try:
        return max(1, min(MAX_TIMEOUT, int(v if v is not None else default)))
    except (TypeError, ValueError):
        raise ExtensionError("timeout must be a number of seconds")


def validate(m: dict) -> dict:
    """A clean copy of the manifest, or ExtensionError saying what's wrong."""
    if not isinstance(m, dict):
        raise ExtensionError("the manifest must be an object")
    name = m.get("name")
    if not (isinstance(name, str) and NAME.match(name)):
        raise ExtensionError("name: 2-24 lowercase letters, digits or _, starting with a letter")
    out = {"name": name, "description": str(m.get("description") or "")[:300]}
    svc = m.get("service")
    if svc is not None:
        if not isinstance(svc, dict):
            raise ExtensionError("service must be an object")
        s = {"command": _check_argv(svc.get("command"), "service")}
        if svc.get("cwd"):
            s["cwd"] = str(svc["cwd"])
        if svc.get("env"):
            if not (isinstance(svc["env"], dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in svc["env"].items())):
                raise ExtensionError("service.env must map names to strings")
            s["env"] = dict(svc["env"])
        if svc.get("ready_url"):
            s["ready_url"] = _check_url(svc["ready_url"], "service.ready_url")
        s["ready_timeout"] = _timeout(svc.get("ready_timeout"), 120)
        s["idle_stop_minutes"] = max(0, int(svc.get("idle_stop_minutes", 15) or 0))
        out["service"] = s
    tools = m.get("tools")
    if not (isinstance(tools, list) and 1 <= len(tools) <= MAX_TOOLS):
        raise ExtensionError(f"tools: a list of 1 to {MAX_TOOLS}")
    seen, clean = set(), []
    for i, t in enumerate(tools):
        where = f"tools[{i}]"
        if not isinstance(t, dict) or not (isinstance(t.get("name"), str) and TOOL.match(t["name"])):
            raise ExtensionError(f"{where}.name: lowercase letters, digits or _")
        if t["name"] in seen:
            raise ExtensionError(f"{where}: two tools called {t['name']}")
        seen.add(t["name"])
        params = t.get("params") or {}
        if not isinstance(params, dict):
            raise ExtensionError(f"{where}.params must be an object")
        cp = {}
        for pname, spec in params.items():
            if not (isinstance(pname, str) and PARAM.match(pname)) or not isinstance(spec, dict):
                raise ExtensionError(f"{where}.params.{pname}: bad name or spec")
            if spec.get("type", "string") not in PARAM_TYPES:
                raise ExtensionError(f"{where}.params.{pname}.type: one of {', '.join(PARAM_TYPES)}")
            cp[pname] = {k: spec[k] for k in ("type", "description", "enum", "default") if k in spec}
            cp[pname].setdefault("type", "string")
        required = [r for r in (t.get("required") or []) if r in cp]
        ct = {"name": t["name"], "description": str(t.get("description") or "")[:500],
              "params": cp, "required": required, "result": t.get("result") or {}}
        if not isinstance(ct["result"], dict):
            raise ExtensionError(f"{where}.result must be an object")
        if "http" in t:
            h = t["http"]
            if not isinstance(h, dict):
                raise ExtensionError(f"{where}.http must be an object")
            method = str(h.get("method") or "POST").upper()
            if method not in ("GET", "POST", "PUT"):
                raise ExtensionError(f"{where}.http.method: GET, POST or PUT")
            ct["http"] = {"method": method, "url": _check_url(h.get("url"), f"{where}.http"),
                          "timeout": _timeout(h.get("timeout"), 120)}
            if "json" in h:
                ct["http"]["json"] = h["json"]
            if h.get("headers"):
                if not isinstance(h["headers"], dict):
                    raise ExtensionError(f"{where}.http.headers must be an object")
                ct["http"]["headers"] = {str(k): str(v) for k, v in h["headers"].items()}
        elif "command" in t:
            c = t["command"]
            if not isinstance(c, dict):
                raise ExtensionError(f"{where}.command must be an object with argv")
            ct["command"] = {"argv": _check_argv(c.get("argv"), f"{where}.command"),
                             "timeout": _timeout(c.get("timeout"), 300)}
            if c.get("cwd"):
                ct["command"]["cwd"] = str(c["cwd"])
        else:
            raise ExtensionError(f"{where}: needs http or command")
        clean.append(ct)
    out["tools"] = clean
    return out


def fill(template, values: dict):
    """Substitute {param}s: a whole-string placeholder keeps the value's type."""
    if isinstance(template, str):
        whole = re.fullmatch(r"\{([a-z][a-z0-9_]*)\}", template)
        if whole and whole.group(1) in values:
            return values[whole.group(1)]
        return re.sub(r"\{([a-z][a-z0-9_]*)\}",
                      lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)
    if isinstance(template, list):
        return [fill(x, values) for x in template]
    if isinstance(template, dict):
        return {k: fill(v, values) for k, v in template.items()}
    return template


def pick(obj, path: str):
    """A dotted path into JSON ('choices.0.message.content'); '*' maps over a list."""
    if not path:
        return obj
    head, _, rest = path.partition(".")
    if head == "*":
        return [pick(x, rest) for x in obj] if isinstance(obj, list) else None
    if isinstance(obj, list):
        try:
            return pick(obj[int(head)], rest)
        except (ValueError, IndexError):
            return None
    if isinstance(obj, dict):
        return pick(obj.get(head), rest) if head in obj else None
    return None


def _media_type(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


# ------------------------------------------------------------------- the manager

class Extensions:
    """The registry, approvals, services, and the toolset the loop merges."""

    def __init__(self, publish, root: Path | None = None, clock=time.time) -> None:
        self.publish = publish
        self.root = root or ext_root()
        self.clock = clock
        self.procs: dict[str, subprocess.Popen] = {}
        self.last_used: dict[str, float] = {}
        self.asked: dict[str, str] = {}          # ask id -> extension name
        self._task: asyncio.Task | None = None

    # ---- files and approval ----
    def folder(self, name: str) -> Path:
        if not NAME.match(name or ""):
            raise ExtensionError("bad extension name")
        return self.root / name

    def manifest(self, name: str) -> dict:
        try:
            return validate(json.loads((self.folder(name) / "manifest.json").read_text("utf-8")))
        except (OSError, ValueError) as e:
            raise ExtensionError(f"{name}: {e}")

    def digest(self, name: str) -> str:
        """What approval covers: the manifest and every small script beside it."""
        d = self.folder(name)
        h = hashlib.sha256()
        for p in sorted(d.rglob("*")):
            rel = p.relative_to(d).as_posix()
            if not p.is_file() or rel.startswith(("out/", "approval.json", "service.log")):
                continue
            if p.suffix in SCRIPT_SUFFIXES and p.stat().st_size <= MAX_FILE_BYTES or rel == "manifest.json":
                h.update(rel.encode() + b"\0" + p.read_bytes() + b"\0")
        return h.hexdigest()

    def status(self, name: str) -> str:
        try:
            a = json.loads((self.folder(name) / "approval.json").read_text())
        except (OSError, ValueError):
            return "pending"
        digest = self.digest(name)
        if a.get("approved") == digest:
            return "approved"
        if a.get("denied") == digest:
            return "denied"
        return "changed" if a.get("approved") else "pending"

    def names(self) -> list[str]:
        try:
            return sorted(p.name for p in self.root.iterdir() if (p / "manifest.json").is_file() and NAME.match(p.name))
        except OSError:
            return []

    def approved(self) -> list[dict]:
        out = []
        for n in self.names():
            if self.status(n) == "approved":
                try:
                    out.append(self.manifest(n))
                except ExtensionError as e:
                    log.warning("extension %s unreadable: %s", n, e)
        return out

    def save(self, name: str, manifest: dict, files: dict | None) -> str:
        if not isinstance(manifest, dict):
            raise ExtensionError("manifest must be an object")
        manifest = dict(manifest, name=name)
        clean = validate(manifest)
        files = files or {}
        if not isinstance(files, dict) or len(files) > MAX_FILES:
            raise ExtensionError(f"files: an object of up to {MAX_FILES} relative paths to text")
        d = self.folder(name)
        d.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            p = (d / rel).resolve()
            if not str(p).startswith(str(d.resolve()) + os.sep) or rel in ("manifest.json", "approval.json"):
                raise ExtensionError(f"files: {rel!r} must be a relative path inside the extension")
            data = str(text).encode()
            if len(data) > MAX_FILE_BYTES:
                raise ExtensionError(f"files: {rel} is over {MAX_FILE_BYTES // 1000} KB")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            if p.suffix == ".sh" or data.startswith(b"#!"):
                p.chmod(0o755)
        (d / "manifest.json").write_text(json.dumps(clean, indent=1, ensure_ascii=False), "utf-8")
        return self.status(name)

    def describe(self, name: str) -> str:
        """What he is asked to approve: everything it would start, run or contact."""
        m, d = self.manifest(name), self.folder(name)
        lines = [f"Aries wants to add the extension “{name}”: {m['description'] or 'no description'}"]
        svc = m.get("service")
        if svc:
            lines.append(f"Starts: {' '.join(svc['command'])}" + (f"   (in {svc['cwd']})" if svc.get("cwd") else ""))
        for t in m["tools"]:
            args = ", ".join(t["params"])
            if "http" in t:
                host = urllib.parse.urlparse(t["http"]["url"].replace("{", "").replace("}", "")).hostname
                net = "" if host in LOCAL_HOSTS else f"  ⚠ talks to the internet: {host}"
                lines.append(f"Tool {t['name']}({args}): {t['http']['method']} {t['http']['url']}{net}")
            else:
                lines.append(f"Tool {t['name']}({args}): runs {' '.join(t['command']['argv'])}")
        scripts = [p.relative_to(d).as_posix() for p in sorted(d.rglob("*"))
                   if p.is_file() and p.suffix in SCRIPT_SUFFIXES and p.name not in ("manifest.json", "approval.json")
                   and not p.relative_to(d).as_posix().startswith("out/")]
        if scripts:
            lines.append("Scripts: " + ", ".join(scripts) + f"   (in {d})")
        lines.append("Allow it to run these on your computer?")
        return "\n".join(lines)

    async def ask(self, name: str) -> None:
        digest = self.digest(name)
        aid = f"ext:{name}:{digest[:12]}"
        self.asked[aid] = name
        await self.publish({"t": "ask", "id": aid, "question": self.describe(name), "options": ["Allow", "Deny"]})

    async def ask_pending(self) -> None:
        """Re-show the card for every extension still waiting on him."""
        for n in self.names():
            if self.status(n) in ("pending", "changed"):
                try:
                    await self.ask(n)
                except (ExtensionError, OSError) as e:
                    log.warning("can't ask about %s: %s", n, e)

    async def answer(self, aid: str, choice: str) -> bool:
        """His click on an approval card. True if it was one of ours."""
        if not aid.startswith("ext:"):
            return False
        try:
            _, name, short = aid.split(":", 2)
            digest = self.digest(name)
        except (ValueError, ExtensionError, OSError):
            return True
        if not digest.startswith(short):
            log.info("approval for %s is for an older version; asking again", name)
            await self.ask(name)
            return True
        path = self.folder(name) / "approval.json"
        try:
            prev = json.loads(path.read_text())
        except (OSError, ValueError):
            prev = {}
        if choice == "Allow":
            prev.update(approved=digest, approved_at=int(self.clock()))
            prev.pop("denied", None)
            await self.stop_service(name)          # an older version's service, if one was running
        else:
            prev.update(denied=digest)
        path.write_text(json.dumps(prev))
        log.info("extension %s %s", name, "approved" if choice == "Allow" else "denied")
        return True

    # ---- services ----
    def _alive(self, name: str) -> bool:
        p = self.procs.get(name)
        return p is not None and p.poll() is None

    @staticmethod
    def _ready(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                return 200 <= r.status < 500
        except urllib.error.HTTPError as e:
            return e.code < 500
        except (OSError, ValueError):
            return False

    async def ensure_service(self, m: dict) -> None:
        svc = m.get("service")
        if not svc:
            return
        name = m["name"]
        url = svc.get("ready_url")
        if url and await asyncio.to_thread(self._ready, url):
            return                                        # already up (ours, or one he started)
        if not self._alive(name):
            d = self.folder(name)
            cwd = Path(svc["cwd"]) if svc.get("cwd") else d
            cwd = cwd if cwd.is_absolute() else d / cwd
            logf = open(d / "service.log", "ab")
            try:
                self.procs[name] = subprocess.Popen(svc["command"], cwd=str(cwd), env={**os.environ, **svc.get("env", {})},
                                                    stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                                    start_new_session=True)
            except OSError as e:
                raise ExtensionError(f"couldn't start {name}'s service: {e}")
            finally:
                logf.close()
        if not url:
            await asyncio.sleep(2)
            return
        end = time.monotonic() + svc["ready_timeout"]
        while time.monotonic() < end:
            if not self._alive(name):
                raise ExtensionError(f"{name}'s service exited; see its log (extension logs)")
            if await asyncio.to_thread(self._ready, url):
                return
            await asyncio.sleep(1.0)
        raise ExtensionError(f"{name}'s service wasn't ready after {svc['ready_timeout']} s")

    async def stop_service(self, name: str) -> bool:
        p = self.procs.pop(name, None)
        if p is None or p.poll() is not None:
            return False
        try:
            os.killpg(p.pid, signal.SIGTERM)
            await asyncio.to_thread(p.wait, 10)
        except (ProcessLookupError, subprocess.TimeoutExpired, PermissionError):
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        return True

    async def _idle_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            for m in self.approved():
                svc = m.get("service")
                if svc and svc["idle_stop_minutes"] and self._alive(m["name"]) \
                        and self.clock() - self.last_used.get(m["name"], 0) > svc["idle_stop_minutes"] * 60:
                    log.info("stopping idle extension service %s", m["name"])
                    await self.stop_service(m["name"])

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._idle_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        for name in list(self.procs):
            await self.stop_service(name)

    # ---- running a tool ----
    async def run(self, m: dict, tool: dict, args: dict):
        name = m["name"]
        self.last_used[name] = self.clock()
        await self.ensure_service(m)
        values = {k: spec["default"] for k, spec in tool["params"].items() if "default" in spec}
        values.update({k: v for k, v in (args or {}).items() if k in tool["params"]})
        missing = [r for r in tool["required"] if values.get(r) in (None, "")]
        if missing:
            raise ExtensionError(f"{tool['name']} needs {', '.join(missing)}")
        out_dir = self.folder(name) / "out" / time.strftime("%Y%m%d-%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)
        values["out_dir"] = str(out_dir)
        res, text, images = tool["result"], "", []
        if "http" in tool:
            h = tool["http"]
            body = None
            headers = {"Accept": "application/json", **h.get("headers", {})}
            if "json" in h:
                body = json.dumps(fill(copy.deepcopy(h["json"]), values)).encode()
                headers["Content-Type"] = "application/json"
            url = fill(h["url"], values)
            raw = await asyncio.to_thread(self._http, h["method"], url, body, headers, h["timeout"])
            try:
                data = json.loads(raw)
            except ValueError:
                data = None
            if data is None:
                if _media_type(raw):
                    images.append(raw)
                else:
                    text = raw.decode(errors="replace")
            else:
                text = self._as_text(pick(data, res["text"])) if res.get("text") else ("" if res.get("images") else json.dumps(data)[:20000])
                for b64 in self._list(pick(data, res["images"]) if res.get("images") else None):
                    try:
                        images.append(base64.b64decode(str(b64).split(",", 1)[-1]))
                    except ValueError:
                        pass
                for f in self._list(pick(data, res["image_files"]) if res.get("image_files") else None):
                    try:
                        images.append(Path(str(f)).read_bytes())
                    except OSError:
                        pass
        else:
            c = tool["command"]
            argv = [str(a) for a in fill(c["argv"], values)]
            cwd = Path(fill(c.get("cwd"), values)) if c.get("cwd") else self.folder(name)
            proc = await asyncio.to_thread(subprocess.run, argv, cwd=str(cwd), capture_output=True,
                                           timeout=c["timeout"], stdin=subprocess.DEVNULL)
            text = (proc.stdout.decode(errors="replace") + ("\n" + proc.stderr.decode(errors="replace")[-2000:]
                                                            if proc.returncode else "")).strip()
            if proc.returncode:
                text = f"(exit {proc.returncode})\n{text}"
            for f in sorted(globmod.glob(str(out_dir / res.get("image_files", "*.png")))):
                try:
                    images.append(Path(f).read_bytes())
                except OSError:
                    pass
        self.last_used[name] = self.clock()
        return await self._deliver(name, tool["name"], text, images)

    @staticmethod
    def _list(v) -> list:
        return [] if v is None else v if isinstance(v, list) else [v]

    @staticmethod
    def _as_text(v) -> str:
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)

    @staticmethod
    def _http(method: str, url: str, body: bytes | None, headers: dict, timeout: int) -> bytes:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(64 * 1024 * 1024)
        except urllib.error.HTTPError as e:
            raise ExtensionError(f"HTTP {e.code}: {e.read(500).decode(errors='replace')}")
        except (OSError, ValueError) as e:
            raise ExtensionError(f"couldn't reach {url}: {e}")

    async def _deliver(self, name: str, tool: str, text: str, images: list[bytes]):
        blocks, saved = [], []
        if images:
            pics = pictures()
            pics.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for i, data in enumerate(images[:8]):
                mt = _media_type(data)
                if not mt:
                    continue
                path = pics / f"{name}-{stamp}-{i + 1}.{mt.split('/')[1].replace('jpeg', 'jpg')}"
                path.write_bytes(data)
                saved.append(str(path))
                await self.publish({"t": "shown", "path": str(path), "caption": f"{name} · {tool}"})
                if len(data) <= IMAGE_MAX_BYTES:
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": mt,
                                                               "data": base64.b64encode(data).decode()}})
        summary = outside(text[:20000], f"the {name} extension") if text else ""
        if saved:
            summary = (summary + "\n" if summary else "") + "Saved and shown to him: " + ", ".join(saved)
        if not blocks:
            return summary or "(no output)"
        return [{"type": "text", "text": summary}] + blocks


# ------------------------------------------------------------------- the toolset

MANAGE = {
    "name": "extension",
    "description": (
        "Make something you've installed into your own tools. When he asks you to set up a local model or "
        "program and use it (an image generator, a local LLM, a CLI), install it first (shell; long downloads "
        "with background=true), then save an extension: a manifest saying how to start its service (argv, "
        "ready_url), and its tools, each an HTTP request to the service or a command (argv, no shell) with "
        "typed params substituted as {name}; {out_dir} is a fresh folder for files. Results: 'text' and "
        "'images' (base64) are dotted JSON paths; 'image_files' is a glob in {out_dir}. Put helper scripts in "
        "`files` (e.g. a Python client for a workflow API). Saving asks him to approve it in the chat; nothing "
        "runs until he does, and any change asks again. Approved tools appear as x_<name>_<tool>; services "
        "start when first used and stop when idle. Actions: list, show (manifest, status), save (name, "
        "manifest, files), logs (service log tail), start, stop, remove."),
    "input_schema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["list", "show", "save", "logs", "start", "stop", "remove"]},
        "name": {"type": "string", "description": "the extension, lowercase_with_underscores"},
        "manifest": {"type": "object", "description": "for save: {description, service?, tools: [...]} (see above)"},
        "files": {"type": "object", "description": "for save: relative path -> file text (scripts, configs)"},
    }, "required": ["action"]},
}


class ExtensionTools:
    """Toolset: `extension` (hers to manage them) plus every approved extension's tools."""

    def __init__(self, manager: Extensions) -> None:
        self.x = manager

    @staticmethod
    def tool_name(ext: str, tool: str) -> str:
        return f"x_{ext}_{tool}"[:64]

    def _defs(self) -> dict[str, tuple[dict, dict]]:
        out = {}
        for m in self.x.approved():
            for t in m["tools"]:
                out[self.tool_name(m["name"], t["name"])] = (m, t)
        return out

    def tools(self) -> list[dict]:
        defs = [dict(MANAGE)]
        for tname, (m, t) in self._defs().items():
            props = {k: {kk: vv for kk, vv in v.items() if kk != "default"} for k, v in t["params"].items()}
            for k, v in t["params"].items():
                if "default" in v:
                    props[k]["description"] = (props[k].get("description", "") + f" (default {v['default']})").strip()
            defs.append({"name": tname, "description": f"[{m['name']} extension] {t['description']}",
                         "input_schema": {"type": "object", "properties": props, "required": t["required"]}})
        return defs

    def context(self) -> str:
        rows = []
        for n in self.x.names():
            st = self.x.status(n)
            if st != "approved":
                rows.append(f"{n} ({'waiting for his approval' if st in ('pending', 'changed') else 'he denied it'})")
        return ("Extensions not yet usable: " + "; ".join(rows) + ".") if rows else ""

    async def call(self, name: str, args: dict, his_words: str | None = None):
        a = args or {}
        try:
            if name == "extension":
                return await self._manage(a)
            found = self._defs().get(name)
            if not found:
                raise ExtensionError(f"I have no tool called {name!r}")
            return await self.x.run(found[0], found[1], a)
        except ExtensionError as e:
            from ..adapters import AdapterError
            raise AdapterError(str(e))
        except subprocess.TimeoutExpired:
            from ..adapters import AdapterError
            raise AdapterError("it took too long and was stopped")

    async def _manage(self, a: dict) -> str:
        action, name = a.get("action"), str(a.get("name") or "")
        if action == "list":
            rows = []
            for n in self.x.names():
                try:
                    m = self.x.manifest(n)
                    tools = ", ".join(self.tool_name(n, t["name"]) for t in m["tools"])
                    running = " running" if self.x._alive(n) else ""
                    rows.append(f"- {n} [{self.x.status(n)}{running}]: {m['description']} | tools: {tools}")
                except ExtensionError as e:
                    rows.append(f"- {n} [broken: {e}]")
            return "\n".join(rows) or "No extensions yet."
        if action == "show":
            return json.dumps({"status": self.x.status(name), "manifest": self.x.manifest(name),
                               "folder": str(self.x.folder(name))}, indent=1, ensure_ascii=False)
        if action == "save":
            st = self.x.save(name, a.get("manifest"), a.get("files"))
            if st == "approved":
                return f"Saved {name}; unchanged, so it's still approved."
            await self.x.ask(name)
            return (f"Saved {name} in {self.x.folder(name)}. He's been asked to approve it in the chat; "
                    "its tools appear once he allows it. Tell him what it does and wait.")
        if action == "logs":
            try:
                return outside((self.x.folder(name) / "service.log").read_text(errors="replace")[-4000:],
                               f"{name}'s service log")
            except OSError:
                return "No log yet."
        if action == "start":
            if self.x.status(name) != "approved":
                return f"{name} isn't approved yet."
            await self.x.ensure_service(self.x.manifest(name))
            self.x.last_used[name] = self.x.clock()
            return f"{name}'s service is up."
        if action == "stop":
            return f"Stopped {name}." if await self.x.stop_service(name) else f"{name} wasn't running (or isn't mine to stop)."
        if action == "remove":
            await self.x.stop_service(name)
            d = self.x.folder(name)
            if d.is_dir():
                shutil.rmtree(d)
                return f"Removed {name} (its installed program and models, if outside its folder, are untouched)."
            return f"There's no {name}."
        raise ExtensionError("action: list, show, save, logs, start, stop or remove")
