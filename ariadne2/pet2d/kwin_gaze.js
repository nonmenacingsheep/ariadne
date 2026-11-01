// Tells her Live2D body where the pointer is, anywhere on the screen.
//
// Under Wayland a window only hears the pointer while it's over it, and her
// window takes input only in the box around her body, so she couldn't follow
// it anywhere else. KWin knows; this reads it 20 times a second and, when it
// moved, sends it to the body (ariadne2/pet2d) relative to her window.

var PET = "ariadne2-pet-l2d";
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
    callDBus("io.ariadne2.pet2d", "/io/ariadne2/pet2d", "io.ariadne2.Gaze", "Cursor", x, y);
});
timer.start();
