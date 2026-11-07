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


class WatchPid(IsGame):
    """Which process's end is the game's end (bin/ariadne2 waits on it)."""

    def test_steams_reaper_not_the_game_window_nor_steam(self):
        self.add(10, 1, "/home/r/.local/share/Steam/ubuntu12_32/steam")
        self.add(20, 10, "reaper", "SteamLaunch", "AppId=3321460", "--", "proton", "waitforexitandrun")
        self.add(30, 20, "S:\\steamapps\\common\\Crimson Desert\\bin64\\CrimsonDesert.exe")
        self.assertEqual(game.watch_pid(30, self.root), 20)

    def test_a_game_launcher_app_stays_open_so_its_game_is_watched(self):
        self.add(10, 1, "/app/bin/heroic", "--no-sandbox")
        self.add(20, 10, "/usr/bin/umu-run", "Game.exe")
        self.add(30, 20, "C:\\Games\\Game.exe")
        self.assertEqual(game.watch_pid(30, self.root), 20)

    def test_nothing_marked_above_it_is_the_window_itself(self):
        self.add(40, 1, "/opt/game/game.x86_64")
        self.assertEqual(game.watch_pid(40, self.root), 40)
