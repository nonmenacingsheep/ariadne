extends Node
# Her interactions (docs/PET_PLAY_PLAN.md): what she does when he pats her,
# tickles her, waves, goes away and comes back; what she does on her own and
# at the glass; how she takes his desktop's news. No props: just her. Each is a line
# of pet/play.json; this runs them, reads his pointer against her body, and
# floats a little emote over her head.

const FILE := "res://play.json"
const KINDS_SHE_PICKS := ["solo", "glass"]
const PLAYBACK := 0.85                     # Kimodo's takes are brisk: a touch slower reads cuter

var pet
var table := {}                            # name -> its entry in play.json
var cool_until := {}
var recent: Array[String] = []             # the last few she picked herself
var current := ""                          # what she's doing now, for her avatar tool

# his pointer
var trail: Array = []                      # [t, Vector2] for the last 2.5 s
var last_cursor := Vector2.ZERO
var seen_at := -99.0                       # when it last moved (pet.cursor_at, as of last frame)
var seen_any := false
var knocked_for_him := false               # knocked on the glass this time he's away
var night_done := -1                       # the day she last said goodnight
var holding_still := false                 # he's holding the button on her without dragging
var after_landing := ""                    # what she does once she's back on her feet (shaken: dizzy)

var emote: Node3D
var emote_at := -99.0
var emote_tex := {}
var bone_ids := {}


func setup(owner) -> void:
	pet = owner
	var f := FileAccess.open(FILE, FileAccess.READ)
	if f:
		var d = JSON.parse_string(f.get_as_text())
		if d is Dictionary:
			for k in d:
				if not String(k).begins_with("_"):
					table[k] = d[k]
	_make_emotes()


func entry(name: String) -> Dictionary:
	return table.get(name, {})


# Every interaction she has clips for (her avatar tool lists them).
var names_cache: Array = []
func names() -> Array:
	if names_cache.is_empty():
		names_cache = table.keys().filter(func(n): return _has_clips(n))
	return names_cache


func _has_clips(name: String) -> bool:
	for c in entry(name).get("clips", []):
		if pet.ap.has_animation(str(c[0])) or pet._variant_of(str(c[0])) != "":
			return true
	return false


func _needs_ok(e: Dictionary) -> bool:
	match str(e.get("needs", "")):
		"night": return pet.brain._night()
		"day": return not pet.brain._night()
		"music": return pet.spotify_playing
		"quiet": return not pet.spotify_playing
	return true


# --- doing one -----------------------------------------------------------------
# from_brain: her own choice (her plan goes on after it); otherwise it's him
# or his desktop, and whatever she was up to is dropped.
func run(name: String, from_brain := false) -> bool:
	var e := entry(name)
	if e.is_empty() or pet.t < float(cool_until.get(name, 0.0)) or not _has_clips(name):
		return false
	if pet.state in ["held", "fall", "knocked"] or pet.perched != "":
		return false
	if pet.state == "react" and current == name and pet.t < pet.state_until:
		return false                           # still at it (patting goes on while he strokes)
	if pet.state == "sleep":
		pet._stir()                            # woken by it: she comes to first, then it
		get_tree().create_timer(2.0).timeout.connect(run.bind(name, from_brain))
		return true
	var pick: String = pet._variant("play:" + name)
	if pick == "":
		return false
	cool_until[name] = pet.t + float(e.get("cool", 0.0))
	if pet.brain.logging:
		print("PLAY %.1f %s %s" % [pet.t, name, pick])
	if not from_brain:
		pet.brain.drop()
	var secs: float = pet.ap.get_animation(pick).length / PLAYBACK
	current = name
	pet._set_state("react", secs)
	pet._play_via(pick, "Idle", 0.5)
	pet.ap.speed_scale = PLAYBACK
	if str(e.get("kind", "")) in ["you", "desk"] or e.get("glass", false):
		pet._face_front(secs)
	if e.has("face"):
		var f := str(e["face"])
		pet._feel(f if pet.moods.has(f) else pet._look_key(f), 0.8, minf(secs, 3.0))
	if e.has("emote"):
		show_emote(str(e["emote"]))
	for k in e.get("gain", {}):
		pet.life.bump(k, float(e["gain"][k]))
	if e.has("mark"):
		var mk: Array = e["mark"]
		get_tree().create_timer(secs * float(mk[2])).timeout.connect(mark.bind(str(mk[0]), str(mk[1])))
	return true


# One she'd like to do now, weighted by how she feels (her brain's "play").
func pick() -> String:
	var names_ := []
	var weights := []
	for n in table:
		var e: Dictionary = table[n]
		if str(e.get("kind", "")) not in KINDS_SHE_PICKS or n in recent or pet.t < float(cool_until.get(n, 0.0)):
			continue
		if e.get("widget", false) and pet.in_front:
			continue                           # in front of the widgets there's nothing to hide behind
		if not _needs_ok(e) or not _has_clips(n):
			continue
		var w = e.get("weight", 0.3)
		var wf: float = float(w) if (w is float or w is int) else pet._feeling(str(w))
		if wf > 0.0:
			names_.append(n)
			weights.append(wf)
	if names_.is_empty():
		return ""
	var total := 0.0
	for w in weights:
		total += w
	var r := randf() * total
	for i in names_.size():
		r -= weights[i]
		if r <= 0.0:
			recent.append(names_[i])
			if recent.size() > 4:
				recent.pop_front()
			return names_[i]
	return names_[-1]


# --- his pointer and his clicks --------------------------------------------------
func _bone(name: String) -> Vector3:
	if not bone_ids.has(name):
		bone_ids[name] = pet.skel.find_bone(name)
	var i: int = bone_ids[name]
	return pet.skel.global_transform * pet.skel.get_bone_global_pose(i).origin if i >= 0 else pet.body.global_position


func _scr(p: Vector3) -> Vector2:
	return pet.cam.unproject_position(p)


# How many pixels `metres` is at that point (sideways on screen).
func _px(p: Vector3, metres: float) -> float:
	return (_scr(p + Vector3(metres, 0, 0)) - _scr(p)).length()


func _chest() -> Vector2:
	return _scr(_bone("Spine").lerp(_bone("Neck"), 0.4))


# Which part of her is under a screen point: top (of her head), face, hand, belly, feet, or "".
func part_at(p: Vector2) -> String:
	if pet.cam == null or pet.skel == null:
		return ""
	var head := _bone("Head") + Vector3(0, 0.07, 0)
	var hs := _scr(head)
	var rh := _px(head, 0.14)
	if p.distance_to(hs) < rh:
		return "top" if p.y < hs.y - rh * 0.3 else "face"
	for h in ["LeftHand", "RightHand"]:
		var b := _bone(h)
		if p.distance_to(_scr(b)) < _px(b, 0.1):
			return "hand"
	for ft in ["LeftFoot", "RightFoot"]:
		var b := _bone(ft)
		if p.distance_to(_scr(b)) < _px(b, 0.12):
			return "feet"
	var a := _scr(_bone("Hips"))
	var c := _scr(_bone("Neck"))
	var on := Geometry2D.get_closest_point_to_segment(p, a, c)
	if p.distance_to(on) < _px(_bone("Spine"), 0.17):
		return "belly"
	return ""


# A click on her (no drag): what she does depends on where.
func clicked(part: String) -> bool:
	match part:
		"top": return run("bonk")
		"face": return run("cheek")
		"hand": return run("highfive")
		"belly": return run("tickle")
		"feet": return run("feet")
	return false


# A wiggle of his pointer near her (pet.gd counts them): tickling if it's on
# her, a wave back if she's near the glass, else she comes over to see.
func wiggled() -> void:
	var part := part_at(pet.cursor)
	if part != "":
		return                                 # on her: the tickle reader has it
	if pet.depth < -0.8 and pet.floor_y < 0.01:
		pet._noticed()
	else:
		pet._stir()
		run("wave_back")


func _process(_delta: float) -> void:
	if pet == null or pet.cam == null or pet.skel == null or not pet.shown or pet.snapshot_path != "" and not test:
		return
	var t: float = pet.t
	var moved: bool = pet.cursor != last_cursor
	last_cursor = pet.cursor
	if moved:
		trail.append([t, pet.cursor])
	trail = trail.filter(func(s): return t - float(s[0]) < 2.5)
	_away_and_back(t)
	_held_still(t)
	if pet.state in ["held", "fall", "knocked"]:
		return
	var free: bool = pet.state in pet.FREE or pet.state in ["rest", "react", "sleep"]
	if not free or pet.cursor_at < -50.0:
		return
	var part := part_at(pet.cursor) if t - pet.cursor_at < 0.5 else ""
	if OS.get_environment("PET_PLAY_DEBUG") != "" and Engine.get_process_frames() % 10 == 0:
		print("DBG %s part=%s path=%.0f speed=%.0f rev=%d trail=%d chest=%s cur=%s" % [pet.state, part,
				_path(1.0, func(p): return part_at(p) in ["top", "face"]), _speed(0.6),
				_reversals(1.0, func(p): return part_at(p) == "belly"), trail.size(), _chest(), pet.cursor])
	# Stroking her head: a slow-ish path over the top of it.
	if part in ["top", "face"] and _path(1.2, func(p): return part_at(p) in ["top", "face"]) > 70.0 \
			and _speed(0.6) < 1400.0:
		run("pat")
	# Tickling: quick back and forth over her middle.
	elif part == "belly" and _reversals(1.0, func(p): return part_at(p) == "belly") >= 4:
		trail.clear()
		run("tickle")
	# Round and round her: she follows it till she's dizzy.
	elif _circled():
		trail.clear()
		run("dizzy")
	# Racing about near her: she chases it.
	elif moved and _speed(0.3) > 3500.0 and pet.cursor.distance_to(_chest()) < pet.PPM * 3.0:
		run("chase")
	# Held still near her for a while: she reaches out and touches the glass at it.
	elif t - pet.cursor_at > 2.5 and t - pet.cursor_at < 3.0 and pet.depth > -0.7 and part == "" \
			and pet.cursor.distance_to(_chest()) < pet.PPM * 1.2 and pet.state in pet.FREE:
		run("touch")


func _path(window: float, keep: Callable) -> float:
	var t: float = pet.t
	var d := 0.0
	var last = null
	for s in trail:
		if t - float(s[0]) > window or not keep.call(s[1]):
			last = null
			continue
		if last != null:
			d += (s[1] as Vector2).distance_to(last)
		last = s[1]
	return d


func _speed(window: float) -> float:
	var t: float = pet.t
	var pts := trail.filter(func(s): return t - float(s[0]) <= window)
	if pts.size() < 2:
		return 0.0
	var d := 0.0
	for i in range(1, pts.size()):
		d += (pts[i][1] as Vector2).distance_to(pts[i - 1][1])
	return d / maxf(float(pts[-1][0]) - float(pts[0][0]), 0.05)


func _reversals(window: float, keep: Callable) -> int:
	var t: float = pet.t
	var n := 0
	var dir := 0.0
	var last = null
	for s in trail:
		if t - float(s[0]) > window or not keep.call(s[1]):
			continue
		if last != null:
			var dx: float = (s[1] as Vector2).x - (last as Vector2).x
			if absf(dx) > 5.0:
				if dir != 0.0 and signf(dx) != dir:
					n += 1
				dir = signf(dx)
		last = s[1]
	return n


func _circled() -> bool:
	if trail.size() < 12:
		return false
	var c := _chest()
	var r0 := _px(_bone("Spine"), 0.25)
	var turn := 0.0
	var last := 0.0
	var first := true
	for s in trail:
		var v: Vector2 = s[1] - c
		if v.length() < r0 or v.length() > r0 * 7.0:
			first = true
			turn = 0.0
			continue
		var a := v.angle()
		if not first:
			turn += wrapf(a - last, -PI, PI)
		last = a
		first = false
	return absf(turn) > TAU * 1.05


# He's been away (no pointer for ten minutes): she knocks on the glass once.
# Back: hello (good morning, after a night). Late at night: goodnight, then bed.
func _away_and_back(t: float) -> void:
	if pet.cursor_at == -99.0:                 # no pointer from the desk yet (its first value)
		return
	if pet.cursor_at != seen_at:
		var gap: float = pet.cursor_at - seen_at
		seen_at = pet.cursor_at
		seen_any = true
		if gap > 600.0 and seen_any and pet.state != "held":
			knocked_for_him = false
			var h: int = Time.get_time_dict_from_system()["hour"]
			run("morning" if gap > 4 * 3600.0 and h >= 5 and h < 12 else "hello")
		var d := Time.get_datetime_dict_from_system()
		if int(d["hour"]) < 4 and night_done != int(d["day"]) and pet.state in pet.FREE:
			night_done = int(d["day"])
			if run("goodnight"):
				get_tree().create_timer(6.0).timeout.connect(func():
					if pet.state in pet.FREE:
						pet._set_state("sleep", 1e9)
						pet._settle_to_sleep())
	elif t - pet.cursor_at > 600.0 and not knocked_for_him and pet.state in pet.FREE:
		knocked_for_him = true
		run("knock")


# The button held on her without dragging: a hug through the glass, or holding hands.
var press_part := ""
func _held_still(t: float) -> void:
	if pet.pressing and not pet.drag_moved and not holding_still and t - pet.press_at > 0.7:
		holding_still = true
		run("holdhand" if press_part == "hand" else "hug")
		pet._set_state("react", 1e9)           # as long as he holds on


func let_go() -> void:
	holding_still = false
	pet._set_state("idle", 0.5)
	pet._play("Idle", 0.4)


# Back on her feet after being thrown: dizzy if he shook her, a glare if it was hard.
func landed(hard: bool, after := -1.0) -> void:
	var n := after_landing if after_landing != "" else ("glare" if hard else "")
	after_landing = ""
	if n != "":
		get_tree().create_timer(after if after >= 0.0 else (3.4 if hard else 0.8)).timeout.connect(run.bind(n))


# --- marks on the glass -------------------------------------------------------------
# Her breath fogs the glass in front of her (a heart drawn in it, for "fog"),
# a fingertip or a palm leaves a print; each fades over a few seconds.
var marks: Array = []                      # [node, made at]


func mark(kind: String, bone: String) -> void:
	if pet.brain.logging:
		print("MARK %s %s depth=%.2f state=%s" % [kind, bone, pet.depth, pet.state])
	if pet.depth < -0.6 or pet.state != "react":
		return                                 # not at the glass (or he picked her up): nothing to leave
	var at := _bone(bone)
	var q := MeshInstance3D.new()
	var quad := QuadMesh.new()
	var size: float = {"heart": 0.34, "fog": 0.26, "hand": 0.13, "dot": 0.06}.get(kind, 0.1)
	quad.size = Vector2(size, size)
	q.mesh = quad
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	# premultiplied: over her transparent window a plain alpha blend leaves the
	# window's alpha at zero, and the fog vanishes off her onto his desktop
	m.blend_mode = BaseMaterial3D.BLEND_MODE_PREMULT_ALPHA
	m.albedo_texture = _fog_tex(kind)
	m.no_depth_test = true                     # on the glass: in front of her, whatever her clip does
	m.render_priority = 5
	q.material_override = m
	q.position = Vector3(at.x, at.y + (0.04 if kind == "heart" else 0.0), -0.01)
	pet.add_child(q)
	marks.append([q, pet.t])


func marks_frame() -> void:
	for mk in marks.duplicate():
		var age: float = pet.t - float(mk[1])
		var q: MeshInstance3D = mk[0]
		(q.material_override as StandardMaterial3D).albedo_color.a = 1.0 - smoothstep(4.0, 12.0, age)
		if age > 12.0:
			q.queue_free()
			marks.erase(mk)


var fog_cache := {}
func _fog_tex(kind: String) -> ImageTexture:
	if fog_cache.has(kind):
		return fog_cache[kind]
	var n := 96
	var img := Image.create(n, n, false, Image.FORMAT_RGBA8)
	for j in n:
		for i in n:
			var x := i / float(n - 1) * 2.0 - 1.0
			var y := 1.0 - j / float(n - 1) * 2.0
			var r := Vector2(x, y).length()
			var a := clampf(1.0 - r, 0.0, 1.0)
			a = a * a * (0.55 if kind in ["fog", "heart"] else 0.7)
			if kind == "heart":
				# the heart wiped through the fog with a fingertip
				var hx := x * 1.7
				var hy := y * 1.7 + 0.25
				var f := pow(hx * hx + hy * hy - 1.0, 3.0) - hx * hx * pow(hy, 3.0)
				if absf(f) < 0.12:
					a *= 0.1
			elif kind == "hand":                   # a palm and four fingers
				var palm := Vector2(x, y + 0.25).length() < 0.45
				var finger := y > 0.1 and y < 0.85 and absf(x) < 0.5 and fmod((x + 0.5) * 4.0, 1.0) < 0.6
				a = 0.5 if palm or finger else 0.0
			img.set_pixel(i, j, Color(0.92 * a, 0.95 * a, a, a))       # premultiplied
	fog_cache[kind] = ImageTexture.create_from_image(img)
	return fog_cache[kind]


# --- emotes ----------------------------------------------------------------------
# A little picture over her head for a second or two: a heart, a note, a
# sparkle... drawn here (no emoji font where she runs).
func show_emote(kind: String) -> void:
	if not emote_tex.has(kind):
		return
	var s := emote.get_child(0) as Sprite3D
	s.texture = emote_tex[kind]
	emote_at = pet.t
	emote.visible = true


func emote_frame() -> void:
	marks_frame()
	if emote == null or not emote.visible:
		return
	var age: float = pet.t - emote_at
	if age > 1.8 or pet.skel == null:
		emote.visible = false
		return
	emote.global_position = _bone("Head") + Vector3(0.12, 0.32 + age * 0.06, 0.0)
	var pop := 1.0 + 0.35 * sin(minf(age / 0.25, 1.0) * PI)      # pops in a little big
	emote.scale = Vector3.ONE * pop * minf(age / 0.12, 1.0)
	(emote.get_child(0) as Sprite3D).modulate.a = 1.0 - smoothstep(1.3, 1.8, age)


func _make_emotes() -> void:
	emote = Node3D.new()
	var s := Sprite3D.new()
	s.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	s.pixel_size = 0.0028
	s.shaded = false
	s.no_depth_test = true
	s.render_priority = 10
	emote.add_child(s)
	emote.visible = false
	pet.add_child.call_deferred(emote)
	var red := Color(0.93, 0.2, 0.33)
	var gold := Color(1.0, 0.82, 0.25)
	var blue := Color(0.35, 0.65, 1.0)
	emote_tex = {
		"heart": _draw(func(x, y): return pow(x * x + y * y - 1.0, 3.0) - x * x * pow(y, 3.0) <= 0.0, red, 1.25),
		"star": _draw(func(x, y): return sqrt(absf(x)) + sqrt(absf(y)) < 1.0, gold, 1.05),
		"sparkle": _draw(func(x, y): return sqrt(absf(x)) + sqrt(absf(y)) < 1.0 or Vector2(x - 0.6, y - 0.6).length() < 0.18, gold, 1.05),
		"note": _draw(func(x, y): return Vector2(x + 0.25, y + 0.55).length() < 0.32 or (x > 0.0 and x < 0.15 and y > -0.55 and y < 0.85) \
				or (x > 0.0 and x < 0.6 and y > 0.55 and y < 0.85 - x * 0.3), Color(0.55, 0.4, 1.0), 1.05),
		"anger": _draw(func(x, y): return (absf(absf(x) - 0.45) < 0.13 or absf(absf(y) - 0.45) < 0.13) and absf(x) < 0.85 and absf(y) < 0.85 \
				and not (absf(x) < 0.25 or absf(y) < 0.25), red, 1.0),
		"drop": _draw(func(x, y): return Vector2(x, y + 0.3).length() < 0.55 or (y > -0.3 and y < 0.95 and absf(x) < 0.55 * (0.95 - y) / 1.25), blue, 1.05),
		"sun": _draw(func(x, y): return Vector2(x, y).length() < 0.5 or (Vector2(x, y).length() < 0.95 and fmod(atan2(y, x) + TAU, TAU / 8.0) < 0.22), gold, 1.05),
		"idea": _draw(func(x, y): return Vector2(x, y - 0.15).length() < 0.6 or (absf(x) < 0.25 and y < -0.35 and y > -0.85), gold, 1.05),
		"dizzy": _draw(func(x, y): return absf(fmod(Vector2(x, y).length() * 7.0 - atan2(y, x) * 7.0 / TAU + 20.0, 1.0) - 0.5) < 0.2 and Vector2(x, y).length() < 0.95, Color(0.6, 0.6, 0.9), 1.0),
		"exclaim": _draw(func(x, y): return (absf(x) < 0.16 + (y + 0.0) * 0.06 and y > -0.15 and y < 0.95) or Vector2(x, y + 0.6).length() < 0.18, red, 1.0),
		"question": _draw(func(x, y): return (absf(Vector2(x, y - 0.35).length() - 0.42) < 0.13 and not (x < 0.0 and y < 0.35)) \
				or (absf(x) < 0.12 and y > -0.35 and y < 0.0) or Vector2(x, y + 0.65).length() < 0.15, blue, 1.0),
		"zzz": _draw(func(x, y): return _zed(x + 0.4, y + 0.35, 0.45) or _zed(x - 0.35, y - 0.4, 0.35), Color(0.7, 0.75, 1.0), 1.0),
	}


func _zed(x: float, y: float, s: float) -> bool:
	if absf(x) > s or absf(y) > s:
		return false
	return y > s * 0.7 or y < -s * 0.7 or absf(x + y) < s * 0.28


# A 64 px picture of a shape (inside(x, y) over -1..1, y up), white-outlined.
func _draw(inside: Callable, col: Color, zoom: float) -> ImageTexture:
	var n := 64
	var img := Image.create(n, n, false, Image.FORMAT_RGBA8)
	var at := func(i: int, j: int) -> bool:
		var x := (i / float(n - 1) * 2.0 - 1.0) * zoom
		var y := (1.0 - j / float(n - 1) * 2.0) * zoom
		return inside.call(x, y)
	for j in n:
		for i in n:
			if at.call(i, j):
				img.set_pixel(i, j, col)
			elif at.call(i + 3, j) or at.call(i - 3, j) or at.call(i, j + 3) or at.call(i, j - 3):
				img.set_pixel(i, j, Color(1, 1, 1, 0.95))
	return ImageTexture.create_from_image(img)


var test := false                          # a test run (PET_SNAPSHOT) that drives the reader itself
