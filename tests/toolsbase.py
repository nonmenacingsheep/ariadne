"""Shared setup for the general-tools tests: a temp world, nothing real touched."""
import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ariadne2.core.tools import common


class ToolsCase(unittest.TestCase):
    def setUp(self):
        # Under /tmp so every path is inside the read and write roots.
        self.tmp = Path(tempfile.mkdtemp(prefix="a2t_"))
        self.data = self.tmp / "data"
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(common, "DATA_OVERRIDE", self.data)
        p.start()
        self.addCleanup(p.stop)
        # A test that forgot a stub gets a refusal, not a screenshot of his desktop.
        p = mock.patch.dict(os.environ, {"ARIADNE_NO_SCREEN": "1"})
        p.start()
        self.addCleanup(p.stop)

    def path(self, *parts) -> Path:
        return self.tmp.joinpath(*parts)

    def put(self, name: str, text: str) -> Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")
        return p


def run(coro):
    return asyncio.run(coro)
