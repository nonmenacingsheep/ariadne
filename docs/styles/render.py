"""Render each desk-style sample to PNGs off-screen (run under xvfb-run)."""
import sys, gi
gi.require_version("Gtk", "4.0"); gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, WebKit, GLib

PAGE, OUT, BG = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "bright")
W, H = 1500, 600
app = Gtk.Application(application_id="io.ariadne2.render")
SHOTS = [("idle", 700), ("packet", 300), ("work", 1450), ("mend", 2700)]

def run(app):
    win = Gtk.ApplicationWindow(application=app); win.set_default_size(W, H)
    view = WebKit.WebView(); win.set_child(view); win.present()
    queue = []
    for i in [int(x) for x in __import__("os").environ.get("STAGES","0,1,2,3,4,5,6,7").split(",")]:
        queue.append(("js", f"""
          document.querySelectorAll('.sample').forEach((s,k)=>s.style.display = k=={i} ? '' : 'none');
          document.querySelector('header.top').style.display='none'; document.querySelector('.controls').style.display='none';
          document.querySelector('.page').style.padding='0'; document.querySelectorAll('.sample .cap,.sample .pitch,.sample .notes').forEach(e=>e.style.display='none');
          document.querySelector('.sample').style.margin='0';
          document.body.className='bg-{BG}'; AUTO=false; stages.forEach(s=>{{s.visible=false; s.phase='idle';}});
          stages[{i}].visible=true; stages[{i}].resize(); stages[{i}].dirty=true; window.scrollTo(0,0); 1"""))
        t = 0
        for name, at in SHOTS:
            if name == "packet":
                queue.append(("js", f"stages[{i}].start(performance.now()); 1")); t = 0
            queue.append(("wait", at - t)); t = at
            queue.append(("shot", f"{OUT}/s{i+1}_{name}.png"))
        queue.append(("wait", 1500))
    def nxt(*_):
        if not queue: app.quit(); return False
        kind, arg = queue.pop(0)
        if kind == "js":
            view.evaluate_javascript(arg, -1, None, None, None, lambda v, r: nxt(), )
        elif kind == "wait":
            GLib.timeout_add(max(1, arg), nxt)
        else:
            def done(v, res, path=arg):
                tex = v.get_snapshot_finish(res); tex.save_to_png(path); nxt()
            view.get_snapshot(WebKit.SnapshotRegion.VISIBLE, WebKit.SnapshotOptions.NONE, None, done)
        return False
    view.connect("load-changed", lambda v, e: e == WebKit.LoadEvent.FINISHED and GLib.timeout_add(2500, nxt))
    view.load_uri("file://" + PAGE)
    GLib.timeout_add_seconds(150, lambda: app.quit())

app.connect("activate", run); app.run([])
