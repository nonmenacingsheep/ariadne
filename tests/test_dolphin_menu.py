"""The Dolphin adapter's right-click menu: open with, copy/paste, rename, duplicate, archives,
properties, and the one-off `menu` messages."""
import io
import os
import tarfile
import time
import unittest
import zipfile
from pathlib import Path

from ariadne2 import protocol
from ariadne2.adapters import AdapterError, dolphin_menu as dm

from tests.test_dolphin import AdapterBase, touch


def desktop(name, mimes="", exec_="app %U", extra=""):
    return (f"[Desktop Entry]\nType=Application\nName={name}\nName[de]=Deutsch {name}\nIcon={name.lower()}\n"
            f"Exec={exec_}\nMimeType={mimes}\n{extra}\n[Desktop Action x]\nName=Other\n")


class MenuBase(AdapterBase):
    def setUp(self):
        super().setUp()
        self.launched, self.launched_with, self.clip = [], [], []
        self.apps = self.root / "apps"
        self.apps.mkdir()

        async def launcher(p):
            self.launched.append(p)

        async def app_launcher(desktop_file, p):
            self.launched_with.append((desktop_file, p))

        async def clipboard(text):
            self.clip.append(text)
        self.a._launch, self.a._launch_with, self.a._to_clipboard = launcher, app_launcher, clipboard
        self.a._app_dirs = [self.apps]
        self.a._mimeapps = []

    def menus(self):
        return [m for m in self.sent if m["t"] == "menu"]

    def actions(self):
        return [m for m in self.sent if m["t"] == "action"]


class OpenTests(MenuBase):
    async def test_open_with_a_path_object_uses_the_default_app_silently(self):
        f = touch(self.home / "a.png")
        await self.a.press("open", {"path": str(f)})
        self.assertEqual(self.launched, [f])
        self.assertEqual(self.opened, [])
        self.assertEqual(self.actions(), [])
        await self.a.press("open", str(f))                 # the recents list still just shows it in Dolphin
        self.assertEqual(self.opened, [f])

    async def test_reveal_shows_it_selected(self):
        f = touch(self.home / "a.png")
        await self.a.press("reveal", {"path": str(f)})
        self.assertEqual(self.opened, [f])
        self.assertEqual(self.actions(), [])

    async def test_open_and_reveal_are_guarded(self):
        for control in ("open", "reveal"):
            with self.assertRaises(AdapterError):
                await self.a.press(control, {"path": "/etc/hostname"})
        self.assertEqual(self.launched + self.opened, [])

    async def test_apps_for_lists_apps_for_the_mime_type(self):
        (self.apps / "org.kde.kate.desktop").write_text(desktop("Kate", "text/plain;text/x-python;"))
        (self.apps / "org.kde.gwenview.desktop").write_text(desktop("Gwenview", "image/png;image/jpeg;"))
        (self.apps / "hidden.desktop").write_text(desktop("Ghost", "text/plain;", extra="NoDisplay=true"))
        (self.apps / "nofile.desktop").write_text(desktop("Nofile", "text/plain;", exec_="nofile --daemon"))
        (self.apps / "org.kde.dolphin.desktop").write_text(desktop("Dolphin", "inode/directory;"))
        (self.apps / "sub").mkdir()
        (self.apps / "sub" / "vim.desktop").write_text(desktop("Vim", "text/plain;"))
        t = touch(self.home / "a.txt")
        img = touch(self.home / "b.png")
        (self.home / "Docs").mkdir()
        self.assertEqual(await self.a.press("apps_for", {"path": str(t)}), "done")
        await self.a.press("apps_for", {"path": str(img)})
        await self.a.press("apps_for", {"path": str(self.home / "Docs")})
        text, png, folder = self.menus()
        self.assertEqual(text, {"t": "menu", "widget": "dolphin", "path": str(t), "apps": [
            {"id": "org.kde.kate.desktop", "name": "Kate", "icon": "kate"},
            {"id": "sub-vim.desktop", "name": "Vim", "icon": "vim"}]})
        self.assertEqual([x["id"] for x in png["apps"]], ["org.kde.gwenview.desktop"])
        self.assertEqual([x["id"] for x in folder["apps"]], ["org.kde.dolphin.desktop"])
        for m in self.menus():
            self.assertEqual(protocol.decode(protocol.encode(m)), m)
        self.assertEqual(self.actions(), [])

    async def test_text_with_odd_extension_still_offers_text_editors_and_defaults_come_first(self):
        (self.apps / "a.desktop").write_text(desktop("Alpha", "text/plain;"))
        (self.apps / "z.desktop").write_text(desktop("Zed", "text/plain;"))
        rc = self.root / "mimeapps.list"
        rc.write_text("[Default Applications]\ntext/plain=z.desktop;\n")
        self.a._mimeapps = [rc]
        f = touch(self.home / "notes.weirdext", "just words")
        await self.a.press("apps_for", {"path": str(f)})
        self.assertEqual([x["id"] for x in self.menus()[0]["apps"]], ["z.desktop", "a.desktop"])

    async def test_apps_for_is_guarded_and_nothing_is_published(self):
        with self.assertRaises(AdapterError):
            await self.a.press("apps_for", {"path": "/etc/hostname"})
        self.assertEqual(self.menus(), [])

    async def test_earlier_dir_shadows_later_and_hidden_copy_hides_it(self):
        other = self.root / "apps2"
        other.mkdir()
        (self.apps / "k.desktop").write_text(desktop("Mine", "text/plain;"))
        (other / "k.desktop").write_text(desktop("Theirs", "text/plain;"))
        (self.apps / "h.desktop").write_text(desktop("Hid", "text/plain;", extra="Hidden=true"))
        (other / "h.desktop").write_text(desktop("Back", "text/plain;"))
        self.a._app_dirs = [self.apps, other]
        await self.a.press("apps_for", {"path": str(touch(self.home / "a.txt"))})
        self.assertEqual([x["name"] for x in self.menus()[0]["apps"]], ["Mine"])

    async def test_open_with_launches_that_desktop_file(self):
        (self.apps / "org.kde.kate.desktop").write_text(desktop("Kate", "text/plain;"))
        f = touch(self.home / "a.txt")
        await self.a.press("open_with", {"path": str(f), "app": "org.kde.kate.desktop"})
        await self.a.press("open_with", {"path": str(f), "app": "org.kde.kate"})
        self.assertEqual(self.launched_with, [(self.apps / "org.kde.kate.desktop", f)] * 2)
        self.assertEqual(self.actions(), [])

    async def test_open_with_refuses_unknown_apps_and_bad_paths(self):
        f = touch(self.home / "a.txt")
        for app in ("nope", "../../bin/sh", "/usr/bin/sh"):
            with self.assertRaises(AdapterError):
                await self.a.press("open_with", {"path": str(f), "app": app})
        (self.apps / "k.desktop").write_text(desktop("K", "text/plain;"))
        with self.assertRaises(AdapterError):
            await self.a.press("open_with", {"path": "/etc/hostname", "app": "k"})
        with self.assertRaises(AdapterError):
            await self.a.press("open_with", {"path": str(f)})
        self.assertEqual(self.launched_with, [])


class ClipboardTests(MenuBase):
    async def test_copy_path_goes_to_the_clipboard(self):
        f = touch(self.home / "a b.txt")
        await self.a.press("copy_path", {"path": str(f)})
        self.assertEqual(self.clip, [str(f)])

    async def test_copy_path_without_a_tool_reports_the_path(self):
        async def none(text):
            raise AdapterError(f"no clipboard tool. The path is {text}")
        self.a._to_clipboard = none
        f = touch(self.home / "a.txt")
        with self.assertRaisesRegex(AdapterError, "a.txt"):
            await self.a.press("copy_path", {"path": str(f)})

    async def test_copy_path_guarded(self):
        with self.assertRaises(AdapterError):
            await self.a.press("copy_path", {"path": "/etc/hostname"})
        with self.assertRaises(AdapterError):
            await self.a.press("copy_path", {"path": str(self.home / "Vaults/API Keys")})
        self.assertEqual(self.clip, [])

    async def test_real_clipboard_function_reports_when_no_tool_exists(self):
        from ariadne2.adapters import dolphin
        real_which, real_prefix = dolphin.shutil.which, dolphin.host_prefix
        dolphin.shutil.which = lambda name: None
        dolphin.host_prefix = lambda: []
        try:
            with self.assertRaisesRegex(AdapterError, "/home/x/a.txt"):
                await dolphin.system_clipboard("/home/x/a.txt")
        finally:
            dolphin.shutil.which, dolphin.host_prefix = real_which, real_prefix


class CopyPasteTests(MenuBase):
    async def test_copy_then_paste_never_overwrites(self):
        src = touch(self.home / "Docs/a.txt", "mine")
        dst = self.home / "Dest"
        touch(dst / "a.txt", "theirs")
        await self.a.press("copy", {"path": str(src)})
        await self.a.press("paste", {"folder": str(dst)})
        await self.a.press("paste", {"folder": str(dst)})              # a copy stays on the clipboard
        self.assertEqual((dst / "a.txt").read_text(), "theirs")
        self.assertEqual((dst / "a (2).txt").read_text(), "mine")
        self.assertEqual((dst / "a (3).txt").read_text(), "mine")
        self.assertTrue(src.exists())
        self.assertEqual(self.actions(), [])

    async def test_paste_a_folder_tree_and_numbering_before_the_extension_only_for_files(self):
        d = self.home / "v1.2"
        touch(d / "in/x.txt", "x")
        other = self.home / "Other"
        (other / "v1.2").mkdir(parents=True)
        await self.a.press("copy", {"path": str(d)})
        await self.a.press("paste", {"folder": str(other)})
        self.assertEqual((other / "v1.2 (2)/in/x.txt").read_text(), "x")

    async def test_cut_then_paste_moves_once(self):
        src = touch(self.home / "Docs/a.txt", "mine")
        dst = self.home / "Dest"
        dst.mkdir()
        await self.a.press("cut", {"path": str(src)})
        await self.a.press("paste", {"folder": str(dst)})
        self.assertFalse(src.exists())
        self.assertEqual((dst / "a.txt").read_text(), "mine")
        with self.assertRaisesRegex(AdapterError, "nothing is copied"):
            await self.a.press("paste", {"folder": str(dst)})

    async def test_cut_into_its_own_folder_is_a_noop(self):
        src = touch(self.home / "Docs/a.txt")
        await self.a.press("cut", {"path": str(src)})
        with self.assertRaisesRegex(AdapterError, "already there"):
            await self.a.press("paste", {"folder": str(self.home / "Docs")})
        self.assertTrue(src.exists())

    async def test_pasting_onto_a_file_goes_beside_it(self):
        src = touch(self.home / "a.txt", "mine")
        beside = touch(self.home / "Dest/b.txt")
        await self.a.press("copy", {"path": str(src)})
        await self.a.press("paste", {"path": str(beside)})
        self.assertTrue((self.home / "Dest/a.txt").exists())

    async def test_a_folder_cannot_be_pasted_into_itself(self):
        d = self.home / "Dir"
        (d / "sub").mkdir(parents=True)
        for control in ("copy", "cut"):
            await self.a.press(control, {"path": str(d)})
            with self.assertRaisesRegex(AdapterError, "inside itself"):
                await self.a.press("paste", {"folder": str(d / "sub")})
        self.assertEqual(sorted(os.listdir(d)), ["sub"])

    async def test_paste_is_guarded_and_checks_the_source_again(self):
        src = touch(self.home / "a.txt")
        await self.a.press("copy", {"path": str(src)})
        for bad in ("/etc", "/tmp"):
            with self.assertRaises(AdapterError):
                await self.a.press("paste", {"folder": bad})
        src.unlink()
        with self.assertRaisesRegex(AdapterError, "nothing was pasted"):
            await self.a.press("paste", {"folder": str(self.home / "Downloads")})

    async def test_copy_and_cut_are_guarded(self):
        for control in ("copy", "cut"):
            with self.assertRaises(AdapterError):
                await self.a.press(control, {"path": "/etc/hostname"})
        with self.assertRaises(AdapterError):
            await self.a.press("cut", {"path": str(self.home)})            # not the home folder itself
        with self.assertRaisesRegex(AdapterError, "nothing is copied"):
            await self.a.press("paste", {"folder": str(self.home)})

    async def test_several_paths_at_once_and_state_shows_the_clipboard(self):
        a, b = touch(self.home / "a.txt"), touch(self.home / "b.txt")
        self.assertNotIn("clipboard", self.a.state())
        await self.a.press("copy", {"paths": [str(a), str(b)]})
        await self.a.refresh()
        self.assertEqual(self.a.state()["clipboard"], {"mode": "copy", "count": 2, "names": ["a.txt", "b.txt"]})
        await self.a.press("paste", {"folder": str(self.home / "Downloads")})
        self.assertEqual(sorted(os.listdir(self.home / "Downloads")), ["a.txt", "b.txt"])


class NameTests(MenuBase):
    async def test_rename(self):
        f = touch(self.home / "a.txt", "x")
        out = await self.a.press("rename", {"path": str(f), "name": "b.txt"})
        self.assertIn("b.txt", out)
        self.assertEqual((self.home / "b.txt").read_text(), "x")
        self.assertFalse(f.exists())
        self.assertEqual(self.actions(), [])

    async def test_rename_refusals(self):
        f = touch(self.home / "a.txt", "mine")
        touch(self.home / "b.txt", "theirs")
        for bad in ("b.txt", "a.txt", "x/y", "..", "", "  ", "x" * 300, "passwords.txt"):
            with self.assertRaises(AdapterError, msg=bad):
                await self.a.press("rename", {"path": str(f), "name": bad})
        with self.assertRaises(AdapterError):
            await self.a.press("rename", {"path": "/etc/hostname", "name": "h"})
        with self.assertRaises(AdapterError):
            await self.a.press("rename", {"path": str(self.home), "name": "h"})
        self.assertEqual((self.home / "b.txt").read_text(), "theirs")
        self.assertTrue(f.exists())

    async def test_her_rename_is_announced(self):
        f = touch(self.home / "a.txt")
        await self.a.run("rename", {"path": str(f), "name": "c.txt"})
        self.assertEqual(self.phases()[0], ("started", None))
        self.assertEqual(self.phases()[-1], ("done", None))

    async def test_duplicate_files_and_folders(self):
        f = touch(self.home / "a.txt", "x")
        await self.a.press("duplicate", {"path": str(f)})
        await self.a.press("duplicate", {"path": str(f)})
        self.assertEqual((self.home / "a (copy).txt").read_text(), "x")
        self.assertEqual((self.home / "a (copy 2).txt").read_text(), "x")
        d = touch(self.home / "Dir/in.txt", "y").parent
        out = await self.a.run("duplicate", {"path": str(d)})
        self.assertEqual((self.home / "Dir (copy)/in.txt").read_text(), "y")
        self.assertIn("Dir (copy)", out)
        with self.assertRaises(AdapterError):
            await self.a.press("duplicate", {"path": "/etc/hostname"})

    async def test_new_folder(self):
        await self.a.press("new_folder", {"folder": str(self.home), "name": "Fresh"})
        self.assertTrue((self.home / "Fresh").is_dir())
        await self.a.press("new_folder", {"folder": str(self.home)})
        await self.a.press("new_folder", {"folder": str(self.home)})
        self.assertTrue((self.home / "New Folder").is_dir() and (self.home / "New Folder (2)").is_dir())
        for args in ({"folder": str(self.home), "name": "Fresh"}, {"folder": str(self.home), "name": "a/b"},
                     {"folder": "/etc", "name": "x"}, {"folder": str(self.home), "name": "secret keys"}):
            with self.assertRaises(AdapterError, msg=args):
                await self.a.press("new_folder", args)
        touch(self.home / "f.txt")
        with self.assertRaises(AdapterError):
            await self.a.press("new_folder", {"folder": str(self.home / "f.txt"), "name": "x"})

    async def test_trash_by_his_click(self):
        f = touch(self.home / "a.txt")
        await self.a.press("trash", {"path": str(f)})
        self.assertEqual(self.trashed, [f])
        with self.assertRaises(AdapterError):
            await self.a.press("trash", {"path": "/etc/hostname"})


def read_zip(p):
    with zipfile.ZipFile(p) as z:
        return {n: (z.read(n) if not n.endswith("/") else None) for n in z.namelist()}


class ArchiveTests(MenuBase):
    async def test_compress_a_file_to_zip(self):
        f = touch(self.home / "Docs/a.txt", "hello")
        out = await self.a.press("compress", {"path": str(f)})
        self.assertIn("a.zip", out)
        self.assertEqual(read_zip(self.home / "Docs/a.zip"), {"a.txt": b"hello"})
        await self.a.press("compress", {"path": str(f)})
        self.assertTrue((self.home / "Docs/a (2).zip").exists())

    async def test_compress_a_folder_leaves_out_links_and_credentials(self):
        d = self.home / "Proj"
        touch(d / "src/main.py", "print(1)")
        touch(d / ".hidden", "h")
        touch(d / "id_rsa", "KEY")
        touch(d / "src/api_key.txt", "KEY")
        (d / "link").symlink_to("/etc/hostname")
        (d / "empty").mkdir()
        out = await self.a.run("compress", {"path": str(d)})
        got = read_zip(self.home / "Proj.zip")
        self.assertEqual(sorted(got), ["Proj/", "Proj/.hidden", "Proj/empty/", "Proj/src/", "Proj/src/main.py"])
        self.assertIn("3 link or private", out)
        self.assertEqual([m["phase"] for m in self.actions()][-1], "done")

    async def test_compress_to_targz(self):
        d = self.home / "Proj"
        touch(d / "a.txt", "aa")
        await self.a.press("compress", {"path": str(d), "format": "tar.gz"})
        with tarfile.open(self.home / "Proj.tar.gz") as tf:
            self.assertEqual(sorted(tf.getnames()), ["Proj", "Proj/a.txt"])
        self.assertEqual([n for n in os.listdir(self.home) if n.startswith(".")], [])    # no .part left over

    async def test_compress_refusals(self):
        f = touch(self.home / "a.txt")
        with self.assertRaisesRegex(AdapterError, "zip or tar.gz"):
            await self.a.press("compress", {"path": str(f), "format": "rar"})
        for bad in ("/etc/hostname", str(self.home), str(self.mnt / "games")):
            with self.assertRaises(AdapterError):
                await self.a.press("compress", {"path": bad})
        self.assertEqual(sorted(os.listdir(self.home)), ["Downloads", "a.txt"])

    async def test_extract_zip_with_one_top_folder_is_not_doubled(self):
        z = self.home / "Docs/proj.zip"
        z.parent.mkdir()
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("proj/a.txt", "a")
            zf.writestr("proj/sub/b.txt", "b")
        out = await self.a.press("extract", {"path": str(z)})
        self.assertEqual((self.home / "Docs/proj/sub/b.txt").read_text(), "b")
        self.assertIn("Docs/proj", out)
        await self.a.run("extract", {"path": str(z)})
        self.assertEqual((self.home / "Docs/proj (2)/a.txt").read_text(), "a")
        self.assertEqual(sorted(os.listdir(self.home / "Docs")), ["proj", "proj (2)", "proj.zip"])

    async def test_extract_loose_files_go_in_a_folder_named_for_the_archive(self):
        z = self.home / "stuff.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("a.txt", "a")
            zf.writestr("b.txt", "b")
        await self.a.press("extract", {"path": str(z)})
        self.assertEqual(sorted(os.listdir(self.home / "stuff")), ["a.txt", "b.txt"])

    async def test_extract_tar_gz(self):
        t = self.home / "x.tar.gz"
        with tarfile.open(t, "w:gz") as tf:
            for name, data in (("a.txt", b"a"), ("b.txt", b"b")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        await self.a.press("extract", {"path": str(t)})
        self.assertEqual((self.home / "x/b.txt").read_text(), "b")

    async def test_roundtrip_with_compress(self):
        d = self.home / "Proj"
        touch(d / "a/b.txt", "deep")
        await self.a.press("compress", {"path": str(d)})
        d2 = self.home / "Elsewhere"
        d2.mkdir()
        os.rename(self.home / "Proj.zip", d2 / "Proj.zip")
        await self.a.press("extract", {"path": str(d2 / "Proj.zip")})
        self.assertEqual((d2 / "Proj/a/b.txt").read_text(), "deep")

    async def test_zip_slip_is_refused_and_leaves_nothing(self):
        z = self.home / "evil.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("ok.txt", "ok")
            zf.writestr("../evil.txt", "bad")
        with self.assertRaisesRegex(AdapterError, "climb out"):
            await self.a.press("extract", {"path": str(z)})
        self.assertEqual(sorted(os.listdir(self.home)), ["Downloads", "evil.zip"])
        t = self.home / "evil.tar"
        with tarfile.open(t, "w") as tf:
            info = tarfile.TarInfo("/abs.txt")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
            link = tarfile.TarInfo("l")
            link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tf.addfile(link)
        with self.assertRaises(AdapterError):
            await self.a.press("extract", {"path": str(t)})
        self.assertEqual(sorted(os.listdir(self.home)), ["Downloads", "evil.tar", "evil.zip"])

    async def test_extract_refusals(self):
        f = touch(self.home / "a.txt")
        bad = self.home / "broken.zip"
        bad.write_text("not a zip")
        with self.assertRaisesRegex(AdapterError, "doesn't look like an archive"):
            await self.a.press("extract", {"path": str(f)})
        with self.assertRaisesRegex(AdapterError, "readable zip"):
            await self.a.press("extract", {"path": str(bad)})
        with self.assertRaisesRegex(AdapterError, "folder"):
            await self.a.press("extract", {"path": str(self.home / "Downloads")})
        with self.assertRaises(AdapterError):
            await self.a.press("extract", {"path": "/etc/hostname"})
        self.assertEqual(sorted(os.listdir(self.home)), ["Downloads", "a.txt", "broken.zip"])

    async def test_other_formats_need_a_tool(self):
        from ariadne2.adapters import dolphin_menu
        real = dolphin_menu.shutil.which
        dolphin_menu.shutil.which = lambda name: None
        try:
            f = touch(self.home / "a.7z", "x")
            with self.assertRaisesRegex(AdapterError, "7z or bsdtar"):
                await self.a.press("extract", {"path": str(f)})
        finally:
            dolphin_menu.shutil.which = real
        self.assertEqual(sorted(os.listdir(self.home)), ["Downloads", "a.7z"])


class PropertiesTests(MenuBase):
    async def test_file_properties(self):
        f = touch(self.home / "a.txt", "hello", age=100)
        os.chmod(f, 0o640)
        self.assertEqual(await self.a.press("properties", {"path": str(f)}), "done")
        m, = self.menus()
        self.assertEqual((m["t"], m["widget"], m["path"]), ("menu", "dolphin", str(f)))
        info = m["info"]
        self.assertEqual(set(info), {"size", "modified", "kind", "mime", "permissions"})
        self.assertEqual((info["size"], info["kind"], info["mime"]), (5, "doc", "text/plain"))
        self.assertEqual(info["permissions"], "rw-r----- (640)")
        self.assertAlmostEqual(info["modified"], time.time() - 100, delta=5)
        self.assertEqual(protocol.decode(protocol.encode(m)), m)

    async def test_folder_properties_have_items_and_total_size(self):
        d = self.home / "Dir"
        touch(d / "a.txt", "12345")
        touch(d / "sub/b.txt", "123")
        touch(d / ".h", "1")
        await self.a.press("properties", {"path": str(d)})
        info = self.menus()[0]["info"]
        self.assertEqual((info["kind"], info["mime"], info["items"], info["size"]),
                         ("folder", "inode/directory", 3, 9))
        self.assertNotIn("partial", info)

    async def test_properties_guarded_and_her_info_is_text_only(self):
        with self.assertRaises(AdapterError):
            await self.a.press("properties", {"path": "/etc/hostname"})
        f = touch(self.home / "a.png", "x")
        out = await self.a.run("info", {"path": str(f)})
        self.assertIn("image", out)
        self.assertIn("image/png", out)
        self.assertEqual(self.menus(), [])

    async def test_tree_size_stops_early(self):
        d = self.home / "Big"
        for i in range(5):
            touch(d / f"f{i}.txt", "x")
        size, partial = dm.tree_size(d, limit=2)
        self.assertTrue(partial)


class PressArgsTests(MenuBase):
    async def test_missing_arguments_are_plain_errors(self):
        f = str(touch(self.home / "a.txt"))
        for control, value in [("copy_path", None), ("copy_path", {}), ("rename", {"path": f}),
                               ("open_with", {"path": f}), ("new_folder", {"name": "x"}),
                               ("paste", {}), ("trash", "  "), ("properties", {"path": ""})]:
            with self.assertRaises(AdapterError, msg=(control, value)):
                await self.a.press(control, value)

    async def test_a_bare_string_is_a_path(self):
        f = touch(self.home / "a.txt")
        await self.a.press("copy_path", str(f))
        self.assertEqual(self.clip, [str(f)])

    async def test_his_verbs_are_not_her_tools(self):
        from ariadne2 import adapters
        names = {t["name"] for t in adapters.tools({"dolphin": self.a})}
        self.assertEqual(names, {f"dolphin_{v}" for v in
                                 ("open", "find", "list", "move", "sort", "trash", "rename", "duplicate",
                                  "compress", "extract", "info")})
        with self.assertRaises(AdapterError):
            await adapters.call_tool({"dolphin": self.a}, "dolphin_paste", {"folder": str(self.home)})


class NameHelperTests(unittest.TestCase):
    def test_split_ext(self):
        self.assertEqual(dm.split_ext("a.tar.gz"), ("a", ".tar.gz"))
        self.assertEqual(dm.split_ext("a.b.txt"), ("a.b", ".txt"))
        self.assertEqual(dm.split_ext(".bashrc"), (".bashrc", ""))
        self.assertEqual(dm.split_ext("v1.2", True), ("v1.2", ""))

    def test_archive_ext(self):
        self.assertEqual(dm.archive_ext("A.TAR.GZ"), ".tar.gz")
        self.assertEqual(dm.archive_ext("a.zip"), ".zip")
        self.assertEqual(dm.archive_ext("a.tar.zst"), ".tar.zst")
        self.assertIsNone(dm.archive_ext("a.txt"))


if __name__ == "__main__":
    unittest.main()
