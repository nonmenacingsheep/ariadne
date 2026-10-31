"""Starting his apps by name."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ariadne2.adapters import launch
from ariadne2.adapters.base import AdapterError


def entry(d, file, name, generic="", keywords="", extra=""):
    (d / file).write_text(f"[Desktop Entry]\nType=Application\nName={name}\nExec=x %U\n"
                          f"GenericName={generic}\nKeywords={keywords}\n{extra}")


class LaunchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mine, self.host = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        entry(self.host, "com.spotify.Client.desktop", "Spotify", "Music Player", "music;")
        entry(self.host, "org.kde.konsole.desktop", "Konsole", "Terminal", "shell;")
        entry(self.host, "claude.desktop", "Claude", "", "terminal;")
        entry(self.host, "steam.desktop", "Steam")
        entry(self.host, "hidden.desktop", "Secret", extra="NoDisplay=true\n")
        entry(self.mine, "steam.desktop", "Steam (mine)")            # his own copy shadows the system one
        self.apps = launch.launchers([self.mine, self.host])

    def test_finding_by_name_kind_and_keyword(self):
        name = lambda q: [a.name for a in launch.find(q, self.apps)]
        self.assertEqual(name("spotify")[0], "Spotify")
        self.assertEqual(name("terminal")[0], "Konsole")             # its kind beats a keyword
        self.assertEqual(name("music")[0], "Spotify")
        self.assertEqual(name("steam"), ["Steam (mine)"])
        self.assertEqual(name("secret"), [])
        self.assertEqual(name(""), [])

    async def test_started_on_the_host_by_desktop_id(self):
        calls = []

        class Proc:
            returncode = 0
            async def communicate(self): return b"", b""

        async def fake_exec(*argv, **kw):
            calls.append(argv); return Proc()
        with mock.patch.object(launch, "host_prefix", return_value=["host-spawn"]), \
             mock.patch.object(launch, "find", return_value=[self.apps["com.spotify.Client.desktop"]]), \
             mock.patch("asyncio.create_subprocess_exec", fake_exec):
            out = await launch.open_app("spotify")
        self.assertEqual(out, "Opened Spotify.")
        self.assertEqual(calls[0], ("host-spawn", "gtk-launch", "com.spotify.Client"))

    async def test_nothing_found_says_so(self):
        with mock.patch.object(launch, "find", return_value=[]):
            with self.assertRaises(AdapterError):
                await launch.open_app("zzz")


if __name__ == "__main__":
    unittest.main()
