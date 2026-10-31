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
            await self._say(said + (" She's wearing it now." if wear else " Pick it in Avatar > Model."))
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

    async def _loop(self) -> None:
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
