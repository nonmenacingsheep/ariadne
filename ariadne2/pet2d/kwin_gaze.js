// Tells her body where the pointer is, anywhere on the screen.
//
// Under Wayland a window only hears the pointer while it's over it, and her
// window takes input only in the box around her body, so she couldn't follow
// it anywhere else. KWin knows; this reads it 20 times a second and, when it
// moved, sends it relative to her window to the desk (ariadne2/desk, which
// always runs and loads this), and the desk passes it on to whichever body
// she wears: the 3D one (pet/pet.gd) or the Live2D one (ariadne2/pet2d).

var PET = "ariadne2-pet";                // her Live2D window or her 3D one (both cover the same area)
var last = "";

function body() {
    var list = workspace.windowList();
    for (var i = 0; i < list.length; i++)
        if (String(list[i].caption).indexOf(PET) === 0) return list[i];
    return null;
}

var timer = new QTimer();
timer.interval = 50;
timer.timeout.connect(function () {
    var p = workspace.cursorPos, w = body();
    if (!w) return;
    var g = w.clientGeometry;
    var x = Math.round(p.x - g.x), y = Math.round(p.y - g.y), key = x + "," + y;
    if (key === last) return;
    last = key;
    callDBus("io.ariadne2.desk", "/io/ariadne2/desk", "io.ariadne2.Layer", "Cursor", x, y);
});
timer.start();
