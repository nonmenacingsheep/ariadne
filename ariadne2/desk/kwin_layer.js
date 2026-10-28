// Keeps the Ariadne 2 desk layer pinned to the ultrawide, below every window,
// and owns Meta+A. The desk loads this for as long as it runs.
//
// Wayland won't let a client place itself, stay below others or skip the
// taskbar, so all of that is asked of KWin here. Raised or not is read from
// the window's own keepAbove, so the desk can drop the layer with a one-shot
// script and this one never holds stale state.

var TITLE = "ariadne2-desk";
var OUTPUT = "DP-2";
var SERVICE = "io.ariadne2.desk";
var PATH = "/io/ariadne2/desk";
var IFACE = "io.ariadne2.Layer";

function layer() {
    var list = workspace.windowList();
    for (var i = 0; i < list.length; i++)
        if (list[i].caption === TITLE) return list[i];
    return null;
}

function output() {
    var outs = workspace.screens;
    for (var i = 0; i < outs.length; i++)
        if (outs[i].name === OUTPUT) return outs[i];
    return outs.length ? outs[0] : null;
}

function tell(up) { callDBus(SERVICE, PATH, IFACE, "Raised", up); }

function drop(w) { w.keepAbove = false; w.keepBelow = true; tell(false); }

function raise(w) {
    w.keepBelow = false;
    w.keepAbove = true;
    workspace.activeWindow = w;
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

registerShortcut("Ariadne2 Raise", "Ariadne 2: bring to front", "Meta+A",
    function () {
        var w = layer();
        if (!w) return;
        if (w.keepAbove) drop(w); else raise(w);
    });

// Click away: any other window taking focus while she's up drops her.
workspace.windowActivated.connect(function (active) {
    var w = layer();
    if (w && w.keepAbove && active && active !== w) drop(w);
});

workspace.windowAdded.connect(function (w) {
    if (w.caption === TITLE) pin(w);
});

var existing = layer();
if (existing) pin(existing);
