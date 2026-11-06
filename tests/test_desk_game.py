import tempfile
import unittest
from pathlib import Path

from ariadne2.desk import game


class IsGame(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, pid, ppid, *cmd):
        d = Path(self.root, str(pid))
        d.mkdir()
        d.joinpath("cmdline").write_bytes(b"\0".join(a.encode() for a in cmd) + b"\0")
        d.joinpath("stat").write_text(f"{pid} ({Path(cmd[0]).name[:15]}) S {ppid} 0 0")

    def test_a_steam_game_through_proton_is_one(self):
        self.add(10, 1, "/home/r/.local/share/Steam/ubuntu12_32/steam")
        self.add(20, 10, "reaper", "SteamLaunch", "AppId=3321460", "--", "proton", "waitforexitandrun")
        self.add(30, 20, "S:\\steamapps\\common\\Crimson Desert\\bin64\\CrimsonDesert.exe")
        self.assertTrue(game.is_game(30, self.root))

    def test_a_native_game_under_steams_reaper_is_one(self):
        self.add(20, 1, "/home/r/.local/share/Steam/ubuntu12_32/reaper", "SteamLaunch", "AppId=570")
        self.add(21, 20, "/home/r/games/dota2/game/bin/linuxsteamrt64/dota2")
        self.assertTrue(game.is_game(21, self.root))

    def test_fullscreen_videos_browsers_and_steam_itself_are_not(self):
        self.add(40, 1, "/usr/bin/mpv", "film.mkv")
        self.add(50, 1, "/app/opera-gx/opera-gx", "--type=gpu-process")
        self.add(60, 1, "/home/r/.local/share/Steam/ubuntu12_32/steam", "-gamepadui")
        for pid in (40, 50, 60):
            self.assertFalse(game.is_game(pid, self.root))

    def test_a_gone_process_is_not(self):
        self.assertFalse(game.is_game(999, self.root))
