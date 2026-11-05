// Keeps the Ariadne 2 desk layer pinned to the ultrawide, below every window,
// and owns Meta+A. The desk loads this for as long as it runs.
//
// Wayland won't let a client place itself, stay below others or skip the
// taskbar, so all of that is asked of KWin here. Raised or not is read from
// the window's own keepAbove, so the desk can drop the layer with a one-shot
// script and this one never holds stale state.

var TITLE = "ariadne2-desk";
var PET = "ariadne2-pet";               // her body (pet/), which lives on the desk with her
var OUTPUT = "";                         // kwin.py fills this from ARIADNE2_OUTPUT; empty = the biggest screen
var SERVICE = "io.ariadne2.desk";
var PATH = "/io/ariadne2/desk";
var IFACE = "io.ariadne2.Layer";

function layer() {
    var list = workspace.windowList();
    for (var i = 0; i < list.length; i++)
        if (list[i].caption === TITLE) return list[i];
    return null;
}

// Godot adds " (DEBUG)" to the title when run from the editor binary.
function isPet(w) { return String(w.caption).indexOf(PET) === 0; }

// Her 3D body lives in a room behind the screen, so the widgets (on the
// glass) stack in front of it, unless his "In front of widgets" setting
// renames its window "-front"; her Live2D body stands on the widgets, over them.
function behind(w) {
    var c = String(w.caption);
    return isPet(w) && c.indexOf(PET + "-l2d") !== 0 && c.indexOf(PET + "-front") !== 0;
}

// Her bodies: the 3D one (pet/, Godot) and the Live2D one (ariadne2/pet2d);
// both windows exist, whichever is hidden draws nothing.
function pets() {
    var list = workspace.windowList(), out = [];
    for (var i = 0; i < list.length; i++)
        if (isPet(list[i])) out.push(list[i]);
    return out;
}

function settlePet(p) {
    p.noBorder = true;
    p.onAllDesktops = true;
    p.skipTaskbar = true;
    p.skipPager = true;
    p.skipSwitcher = true;
    p.keepAbove = false;
    p.keepBelow = true;
    // The ultrawide's usable area (above the panel), so her floor is the
    // panel's top, whatever state the desk window is in.
    var o = output();
    if (o) {
        var a = workspace.clientArea(KWin.MaximizeArea, o, workspace.currentDesktop);
        p.frameGeometry = { x: a.x, y: a.y, width: a.width, height: a.height };
    }
}

// KWin sometimes keeps a new window at the size it first gave it (on the
// smaller monitor) without ever reporting a change, so the pin is repeated
// on timers shortly after a window appears.
function later(ms, fn) {
    try {
        var timer = new QTimer();
        timer.singleShot = true;
        timer.interval = ms;
        timer.timeout.connect(fn);
        timer.start();
    } catch (e) {}
}

function settleSoon(w) {
    [500, 1500, 4000].forEach(function (ms) {
        later(ms, function () {
            if (isPet(w)) settlePet(w);
            else if (w.caption === TITLE) {
                var o = output(), g = o ? o.geometry : null, f = w.frameGeometry;
                if (g && (f.width !== g.width || f.x !== g.x)) pin(w);
            }
        });
    });
}

function output() {
    var outs = workspace.screens, best = null;
    for (var i = 0; i < outs.length; i++) {
        if (OUTPUT && outs[i].name === OUTPUT) return outs[i];
        var g = outs[i].geometry;
        if (!best || g.width * g.height > best.geometry.width * best.geometry.height) best = outs[i];
    }
    return best;
}

function tell(up) { callDBus(SERVICE, PATH, IFACE, "Raised", up); }

function drop(w) {
    w.keepAbove = false; w.keepBelow = true;
    pets().forEach(function (p) { p.keepAbove = false; p.keepBelow = true; });
    tell(false);
}

function raise(w) {
    w.keepBelow = false;
    w.keepAbove = true;
    workspace.activeWindow = w;
    pets().forEach(function (p) {   // she comes up with the desk
        p.keepBelow = false; p.keepAbove = true;
        try { workspace.raiseWindow(p); } catch (e) {}
    });
    petsAroundDesk();
    tell(true);
}

function pin(w) {
    var o = output();
    if (o) {
        var g = o.geometry;
        w.frameGeometry = { x: g.x, y: g.y, width: g.width, height: g.height };
    }
    w.noBorder = true;
    w.onAllDesktops = true;
    w.skipTaskbar = true;
    w.skipPager = true;
    w.skipSwitcher = true;
    drop(w);
    // The usable part of the screen (minus panels), relative to the layer,
    // so the desk can keep widgets out from under a panel.
    // Asked of the ultrawide itself, not the window: right after the move the
    // window can still count as being on another monitor.
    if (!o) return;
    var a = workspace.clientArea(KWin.MaximizeArea, o, workspace.currentDesktop);
    var g = o.geometry;
    callDBus(SERVICE, PATH, IFACE, "Area", Math.round(a.x - g.x),
             Math.round(a.y - g.y), Math.round(a.width), Math.round(a.height));
}

registerShortcut("Ariadne2 Talk", "Ariadne 2: talk (press, speak, press)", "Meta+S",
    function () { callDBus(SERVICE, PATH, IFACE, "Talk"); });

registerShortcut("Ariadne2 Raise", "Ariadne 2: bring to front", "Meta+A",
    function () {
        var w = layer();
        if (!w) return;
        if (w.keepAbove) drop(w); else raise(w);
    });

// Click away: any other window taking focus while she's up drops her.
workspace.windowActivated.connect(function (active) {
    var w = layer();
    if (w && w.keepAbove && active && active !== w && !isPet(active)) drop(w);
});

// KWin first places a new window on whichever monitor it likes and clamps
// its size there (1920 wide on the other screen); the first pin doesn't
// always stick. So whenever the layer's geometry drifts from the ultrawide's,
// put it back. Comparing first means our own correction doesn't loop.
function hold(w) {
    w.frameGeometryChanged.connect(function () {
        var o = output();
        if (!o) return;
        var g = o.geometry, f = w.frameGeometry;
        if (f.x !== g.x || f.y !== g.y || f.width !== g.width || f.height < g.height - 120)
            pin(w);
    });
}

// Whenever the stacking changes, put her bodies back where they belong: the
// 3D one just under the desk (the widgets in front of her; the desk only
// takes clicks on its widgets, so she can still be grabbed between them),
// the Live2D one on top of it. All stay below his windows unless raised.
function petsAroundDesk() {
    var w = layer();
    if (!w) return;
    var order = workspace.stackingOrder;
    var under = pets().filter(behind);
    if (under.some(function (p) { return order.indexOf(p) > order.indexOf(w); })) {
        try { workspace.raiseWindow(w); } catch (e) {}
        order = workspace.stackingOrder;
    }
    pets().forEach(function (p) {
        if (!behind(p) && order.indexOf(p) < order.indexOf(w)) {
            try { workspace.raiseWindow(p); } catch (e) {}
        }
    });
}
try { workspace.stackingOrderChanged.connect(petsAroundDesk); } catch (e) {}
workspace.windowActivated.connect(function () { petsAroundDesk(); });

workspace.windowAdded.connect(function (w) {
    if (w.caption === TITLE) { pin(w); hold(w); settleSoon(w); }
    if (isPet(w)) { settlePet(w); settleSoon(w); }
    // Godot sets its title just after mapping; catch the rename too.
    // (and a rename is also her moving in front of the widgets or back behind them)
    w.captionChanged.connect(function () { if (isPet(w)) { settlePet(w); settleSoon(w); petsAroundDesk(); } });
});

var existing = layer();
if (existing) { pin(existing); hold(existing); }
pets().forEach(settlePet);
petsAroundDesk();
