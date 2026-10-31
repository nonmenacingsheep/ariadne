"""New Live2D bodies, from the drop folder or the Files menu (pet2d/importer.py).

~/Aries Models is the drop folder: a model download (zip, rar, 7z or an
unpacked folder) put there is added within half a minute and appears in the
Avatar widget's Model list. Each download is imported once (by name, size and
time), so it can stay there. The Files widget's "Use as her body" does the
same for any download and switches her to it.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
from pathlib import Path

from .. import protocol
from ..pet2d import importer

log = logging.getLogger("ariadne2.body_models")

EVERY = 30.0
REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "ariadne2" / "pet2d" / "web" / "vendor" / "live2dcubismcore.min.js"
CORE_URL = "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"
NEEDS_CORE = ("Live2D models need Live2D's Cubism Core to show. Get it in the Avatar widget > "
              "Live2D support > Download (free, under Live2D's licence).")
NO_BODY = ("I don't have a body on screen yet. For a Live2D one, put a model download in ~/Aries Models "
           "(or right-click it in Files > Use as her body). For the 3D one, a VRoid .vrm goes at "
           "pet/models/aries.vrm and needs Godot 4 (install.sh can fetch it).")
README = """Put a Live2D model here to give Aries a new body.

Drop the download in as it came: a .zip, .rar or .7z, or the unpacked
folder (anything with a .model3.json inside, like VTube Studio models).
Within half a minute it's added, and you can pick it in the Avatar widget
(the drawer under ARIES) > Model.

You can also right-click a download in her Files widget > Use as her body.
"""
_ids = itertools.count(1)


def drop_folder() -> Path:
    return Path(os.environ.get("ARIADNE2_MODELS_DIR") or (Path.home() / "Aries Models"))


def _seen_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "ariadne2" / "imported_models.json"


def _key(p: Path) -> str:
    st = p.stat()
    return f"{p.name}|{st.st_size if p.is_file() else 0}|{int(st.st_mtime)}"


class BodyModels:
    def __init__(self, publish, settings) -> None:
        self.publish = publish
        self.settings = settings
        self._task: asyncio.Task | None = None
        self._busy = asyncio.Lock()

    async def _say(self, text: str) -> None:
        await self.publish(protocol.chat(f"models-{next(_ids)}", "aries", text, done=True))

    async def add(self, path: str | Path, wear: bool = False) -> str | None:
        """Import one download; with wear, switch her body to it. Says how it went in the chat."""
        async with self._busy:
            try:
                slug, said = await asyncio.to_thread(importer.import_model, Path(path))
            except importer.ImportError_ as e:
                await self._say(f"Couldn't add that model: {e}")
                return None
            except Exception as e:
                log.exception("importing %s", path)
                await self._say(f"Couldn't add that model: {e}")
                return None
            if wear:
                try:
                    self.settings.set("avatar", "model", slug)
                except Exception as e:
                    log.warning("couldn't switch to %s: %s", slug, e)
            await self.publish(self.settings.message())        # the Model list now has it
            await self._say(said + (" She's wearing it now." if wear else " Pick it in Avatar > Model.")
                            + ("" if CORE.exists() else " " + NEEDS_CORE))
            return slug

    async def scan(self) -> None:
        folder = drop_folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            readme = folder / "README.txt"
            if not readme.exists():
                readme.write_text(README)
            entries = sorted(p for p in folder.iterdir() if p.name != "README.txt" and not p.name.startswith("."))
        except OSError as e:
            log.warning("drop folder %s: %s", folder, e)
            return
        seen_path = _seen_path()
        try:
            seen = set(json.loads(seen_path.read_text()))
        except (OSError, ValueError):
            seen = set()
        for p in entries:
            try:
                key = _key(p)
            except OSError:
                continue
            if key in seen or not await asyncio.to_thread(importer.is_candidate, p):
                continue
            seen.add(key)                       # once, even if it fails: no retry loop on a bad file
            seen_path.parent.mkdir(parents=True, exist_ok=True)
            seen_path.write_text(json.dumps(sorted(seen)))
            await self.add(p)

    def _three_d_ready(self) -> bool:
        import shutil
        godot = (os.environ.get("ARIADNE2_GODOT") or shutil.which("godot4") or shutil.which("godot")
                 or (REPO / "tools" / "godot" / "godot").exists()
                 or Path("/var/mnt/games/DevTools/godot-4.7.2/Godot_v4.7.2-stable_linux.x86_64").exists())
        return (REPO / "pet" / "models" / "aries.vrm").exists() and bool(godot)

    def core_status(self) -> str:
        return "Installed" if CORE.exists() else "Not installed"

    async def get_core(self) -> None:
        """His click on Download: fetch Cubism Core from Live2D (the click accepts its licence)."""
        import urllib.request
        if CORE.exists():
            await self._say("Live2D support is already installed.")
            return

        def fetch() -> bytes:
            # Live2D's server refuses Python's default User-Agent (403); curl's
            # and browsers' get through, so say who's asking.
            req = urllib.request.Request(CORE_URL, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Ariadne/2"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read(5_000_000)
        try:
            data = await asyncio.to_thread(fetch)
            if b"Live2D Cubism Core" not in data[:2000]:
                raise ValueError("that wasn't the Cubism Core file")
            CORE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CORE.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(CORE)
        except Exception as e:
            await self._say(f"Couldn't download Live2D support: {e}")
            return
        await self.publish(self.settings.message())
        await self._say("Live2D support is installed. Live2D bodies show now (pick one in Avatar > Model).")

    def _live2d_ready(self) -> list[str]:
        if not (REPO / "ariadne2" / "pet2d" / "web" / "vendor" / "live2dcubismcore.min.js").exists():
            return []
        try:
            return sorted(p.name for p in importer.MODELS.iterdir() if any(p.glob("*.model3.json")))
        except OSError:
            return []

    async def check_body(self) -> None:
        """A body that can't run shows nothing at all: switch to one that can, or say what to add."""
        try:
            av = self.settings.get("avatar", "model")
            body_on = self.settings.get("desktop", "body")
        except Exception:
            return
        if not body_on:
            return
        live2d = await asyncio.to_thread(self._live2d_ready)
        if av == "aries" and self._three_d_ready() or av in live2d:
            return
        if av != "aries" and not CORE.exists() and (importer.MODELS / av).is_dir():
            await self._say(NEEDS_CORE)            # a Live2D body is chosen; the library is what's missing
            return
        if live2d:
            self.settings.set("avatar", "model", live2d[0])
            await self.publish(self.settings.message())
            await self._say(f"My 3D body can't run here, so I'm wearing the Live2D one ({live2d[0]}). "
                            "Switch in Avatar > Model.")
            return
        flag = _seen_path().with_name("told_no_body")
        if not flag.exists():
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text("1")
            await self._say(NO_BODY)

    async def _loop(self) -> None:
        await asyncio.sleep(15)            # the desk connects first, so she can be heard
        try:
            await self.check_body()
        except Exception:
            log.exception("body check failed")
        while True:
            try:
                await self.scan()
            except Exception:
                log.exception("drop folder scan failed")
            await asyncio.sleep(EVERY)

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
