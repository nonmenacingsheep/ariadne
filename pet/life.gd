extends Node
# Her life between jobs: needs that drift (energy, fun, affection), things you
# can give her (a ring of items on right-click, and real files dropped on
# her), and what she does with them. It nudges pet.gd's choices; pet.gd still
# owns her body. Her needs are written to a small file the core reads, so when
# you talk to her she knows how she feels; a dropped file is told to the core
# through an inbox it watches (never as your words; see core/pet_inbox.py).

const STATE_FILE := "/.local/share/ariadne2/pet/state.json"
const INBOX_FILE := "/.local/share/ariadne2/pet/inbox.jsonl"
const SAVE_FILE := "user://needs.json"
const ITEMS := ["cookie", "drink", "ball", "plush"]
const BALL_R := 0.09

var pet                                   # pet.gd (her body)
var needs := {"energy": 0.8, "fun": 0.6, "affection": 0.6, "hunger": 0.7}   # hunger: 1 = full
# Drain multipliers, set from the Avatar settings (1 = normal).
var rates := {"energy": 1.0, "fun": 1.0, "affection": 1.0, "hunger": 1.0}
var tick_in := 1.0
var save_in := 30.0
var holding := ""                          # item in her hands
var holding_node: MeshInstance3D
var ring: Control
var ring_open := false
var ball: MeshInstance3D
var ball_pos := Vector2.ZERO
var ball_vel := Vector2.ZERO
var ball_live := false
var home := OS.get_environment("HOME")


func setup(body_owner) -> void:
	pet = body_owner
	_load()
	_make_ring()
	ball = _item_mesh("ball")
	ball.visible = false
	pet.add_child.call_deferred(ball)
	get_window().files_dropped.connect(_on_files)
	DirAccess.make_dir_recursive_absolute(home + "/.local/share/ariadne2/pet")


# --- needs ------------------------------------------------------------------
# Per-minute drift while awake; sleep restores energy, music and play restore
# fun, attention restores affection.
func _process(delta: float) -> void:
	_ball_frame(delta)
	_hold_frame()
	tick_in -= delta
	if tick_in > 0.0:
		return
	tick_in = 1.0
	var m := 1.0 / 60.0
	if pet.state == "sleep":
		needs["energy"] += 0.05 * m
	else:
		needs["energy"] -= 0.009 * m * rates["energy"] * (1.4 if needs["hunger"] < 0.2 else 1.0)
	needs["fun"] += (0.06 if pet.state == "dance" else -0.012 * rates["fun"]) * m
	needs["affection"] -= 0.007 * m * rates["affection"]
	needs["hunger"] -= 0.008 * m * rates["hunger"]
	for k in needs:
		needs[k] = clampf(needs[k], 0.0, 1.0)
	save_in -= 1.0
	if save_in <= 0.0:
		save_in = 30.0
		_save()


func bump(need: String, amount: float) -> void:
	needs[need] = clampf(needs[need] + amount, 0.0, 1.0)


func mood() -> String:
	if needs["hunger"] < 0.15:
		return "hungry"
	if needs["energy"] < 0.2:
		return "sleepy"
	if needs["affection"] < 0.25:
		return "lonely"
	if needs["fun"] < 0.25:
		return "bored"
	if needs["energy"] > 0.6 and needs["fun"] > 0.6 and needs["affection"] > 0.6:
		return "happy"
	return "content"


# What she'd like to do now, if anything: pet.gd asks before choosing.
func wish() -> String:
	if needs["energy"] < 0.15:
		return "sleep"
	if needs["affection"] < 0.25 and randf() < 0.5:
		return "find_him"
	if needs["fun"] < 0.3 and randf() < 0.4:
		return "dance" if pet.spotify_playing else "ball"
	return ""


func _save() -> void:
	var data := {"needs": needs, "mood": mood(), "holding": holding, "state": pet.state,
		"updated": Time.get_unix_time_from_system()}
	var f := FileAccess.open(home + STATE_FILE, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(data))
	var g := FileAccess.open(SAVE_FILE, FileAccess.WRITE)
	if g:
		g.store_string(JSON.stringify(needs))


func _load() -> void:
	var f := FileAccess.open(SAVE_FILE, FileAccess.READ)
	if f:
		var d = JSON.parse_string(f.get_as_text())
		if d is Dictionary:
			for k in needs:
				if d.has(k):
					needs[k] = clampf(float(d[k]), 0.0, 1.0)


# --- the item ring ----------------------------------------------------------
# Right-click her: four items around her head; pick one and it's hers.
func _make_ring() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	ring = Control.new()
	ring.visible = false
	layer.add_child(ring)
	for i in ITEMS.size():
		var b := Button.new()
		b.text = ITEMS[i].to_upper()
		b.custom_minimum_size = Vector2(88, 34)
		b.add_theme_font_size_override("font_size", 13)
		var sb := StyleBoxFlat.new()
		sb.bg_color = Color(0.06, 0.04, 0.12, 0.9)
		sb.border_color = Color(1.0, 0.16, 0.24)
		sb.set_border_width_all(1)
		sb.set_corner_radius_all(0)
		b.add_theme_stylebox_override("normal", sb)
		var hov := sb.duplicate()
		hov.bg_color = Color(0.35, 0.05, 0.1, 0.95)
		b.add_theme_stylebox_override("hover", hov)
		b.add_theme_stylebox_override("pressed", hov)
		b.pressed.connect(give.bind(ITEMS[i]))
		var a := -PI / 2 + (i - 1.5) * 0.7
		b.position = Vector2(cos(a), sin(a)) * 120.0 - b.custom_minimum_size / 2
		ring.add_child(b)


func open_ring(at: Vector2) -> void:
	ring.position = at
	ring.visible = true
	ring_open = true


func close_ring() -> void:
	ring.visible = false
	ring_open = false


# The click area pet.gd sets while the ring is open, so the buttons get clicks.
func ring_rect() -> Rect2:
	return Rect2(ring.position - Vector2(180, 180), Vector2(360, 300))


func give(item: String) -> void:
	close_ring()
	pet._stir()
	bump("affection", 0.15)
	match item:
		"cookie", "drink":
			_hold(item)
			pet._set_state("eat", 3.2)
			pet._play("Consume", 0.25)
			pet._feel("joy", 0.8, 3.0)
			bump("energy", 0.12)
			bump("hunger", 0.45 if item == "cookie" else 0.25)
			get_tree().create_timer(3.0).timeout.connect(func(): _hold(""))
		"plush":
			_hold("plush")
			pet._set_state("hug", 12.0)
			pet._feel("joy", 0.9, 4.0)
			bump("fun", 0.15)
		"ball":
			play_ball()


func play_ball() -> void:
	_hold("ball")
	pet._set_state("throw", 1.3)
	pet._play("OverhandThrow", 0.2)
	pet._feel("fun", 0.8, 3.0)
	get_tree().create_timer(0.75).timeout.connect(_release_ball)


func _release_ball() -> void:
	_hold("")
	var dir := -1.0 if pet.pos.x > pet.screen.x / pet.PPM / 2.0 else 1.0
	ball_pos = pet.pos + Vector2(0.3 * dir, 1.4)
	ball_vel = Vector2(dir * randf_range(3.0, 6.0), randf_range(2.5, 4.0))
	ball_live = true
	ball.visible = true


# A bouncing ball she runs after, picks up, and is pleased about.
func _ball_frame(delta: float) -> void:
	if not ball_live:
		return
	ball_vel.y -= 9.0 * delta
	ball_pos += ball_vel * delta
	var right: float = pet.screen.x / pet.PPM - BALL_R
	if ball_pos.x < BALL_R or ball_pos.x > right:
		ball_pos.x = clampf(ball_pos.x, BALL_R, right)
		ball_vel.x *= -0.7
	if ball_pos.y < BALL_R:
		ball_pos.y = BALL_R
		ball_vel.y = absf(ball_vel.y) * 0.55
		ball_vel.x *= 0.85
		if ball_vel.y < 0.4:
			ball_vel = Vector2.ZERO
	ball.position = Vector3(ball_pos.x, ball_pos.y, 0.2)
	ball.rotation.z -= ball_vel.x * delta / BALL_R
	if ball_vel == Vector2.ZERO and pet.state not in ["fetch", "held", "fall", "knocked"]:
		pet.fetch(ball_pos.x)


func picked_up_ball() -> void:
	ball_live = false
	ball.visible = false
	_hold("ball")
	bump("fun", 0.25)
	pet._feel("joy", 0.8, 2.0)
	get_tree().create_timer(2.5).timeout.connect(func(): _hold(""))


# --- holding things ---------------------------------------------------------
func _hold(item: String) -> void:
	holding = item
	if holding_node:
		holding_node.queue_free()
		holding_node = null
	if item != "":
		holding_node = _item_mesh(item)
		pet.add_child(holding_node)


func _hold_frame() -> void:
	if not holding_node:
		return
	var skel: Skeleton3D = pet.skel
	var h := skel.find_bone("LeftHand" if holding == "plush" else "RightHand")
	if h >= 0:
		holding_node.global_position = skel.global_transform * skel.get_bone_global_pose(h).origin \
				+ Vector3(0, 0.02, 0.06)


func _item_mesh(item: String) -> MeshInstance3D:
	var m := MeshInstance3D.new()
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	match item:
		"cookie":
			var c := CylinderMesh.new()
			c.top_radius = 0.06; c.bottom_radius = 0.06; c.height = 0.02
			m.mesh = c
			m.rotation.x = PI / 2
			mat.albedo_color = Color(0.72, 0.48, 0.25)
		"drink":
			var c := CylinderMesh.new()
			c.top_radius = 0.045; c.bottom_radius = 0.035; c.height = 0.13
			m.mesh = c
			mat.albedo_color = Color(1.0, 0.55, 0.7)
		"ball":
			var s := SphereMesh.new()
			s.radius = BALL_R; s.height = BALL_R * 2
			m.mesh = s
			mat.albedo_color = Color(1.0, 0.16, 0.24)
		"plush":
			var s := CapsuleMesh.new()
			s.radius = 0.07; s.height = 0.2
			m.mesh = s
			mat.albedo_color = Color(0.98, 0.75, 0.82)
		_:
			var b := BoxMesh.new()
			b.size = Vector3(0.1, 0.1, 0.02)
			m.mesh = b
	m.material_override = mat
	return m


# --- real files dropped on her ----------------------------------------------
# She holds it up as a slab with its name, and the core hears that you handed
# it to her (an inbox file, one JSON line per drop).
func _on_files(files: PackedStringArray) -> void:
	if files.is_empty():
		return
	pet._stir()
	bump("affection", 0.1)
	var path: String = files[0]
	var name := path.get_file()
	pet._slab_show(name.substr(0, 24))
	pet._feel("surprised", 0.5, 1.0)
	get_tree().create_timer(4.0).timeout.connect(func(): pet.slab.visible = false)
	var f := FileAccess.open(home + INBOX_FILE, FileAccess.READ_WRITE)
	if not f:
		f = FileAccess.open(home + INBOX_FILE, FileAccess.WRITE)
	if f:
		f.seek_end()
		f.store_line(JSON.stringify({"t": "gave", "paths": Array(files), "at": Time.get_unix_time_from_system()}))
