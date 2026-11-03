extends Node
# Her life between jobs: needs that drift (energy, fun, affection), real files
# dropped on her, and what she holds. It nudges pet.gd's choices; pet.gd still
# owns her body. Her needs are written to a small file the core reads, so when
# you talk to her she knows how she feels; a dropped file is told to the core
# through an inbox it watches (never as your words; see core/pet_inbox.py).

const STATE_FILE := "/.local/share/ariadne2/pet/state.json"
const INBOX_FILE := "/.local/share/ariadne2/pet/inbox.jsonl"
const SAVE_FILE := "user://needs.json"

var pet                                   # pet.gd (her body)
var needs := {"energy": 0.8, "fun": 0.6, "affection": 0.6, "hunger": 0.7,   # hunger: 1 = full
		"fitness": 0.6, "purpose": 0.6}           # a workout and her work at the desk fill these
# Drain multipliers, set from the Avatar settings (1 = normal).
var rates := {"energy": 1.0, "fun": 1.0, "affection": 1.0, "hunger": 1.0}
var tick_in := 1.0
var save_in := 30.0
var holding := ""                          # item in her hands
# Her things (docs/PET_STATES_PLAN.md, phase 4): each has a home (the spot in
# room.gd it lives at); she carries one about, and sometimes leaves it where
# she used it (a book on the bed), saved, until she tidies it or picks it up there.
const THINGS := {"book": "shelf", "phone": "desk", "mug": "kitchen", "controller": "desk", "bowl": "kitchen"}
var left := {}                             # thing -> the spot it was left at
var left_nodes := {}
var holding_node: MeshInstance3D
var home := OS.get_environment("HOME")


func setup(body_owner) -> void:
	pet = body_owner
	_load()
	get_window().files_dropped.connect(_on_files)
	DirAccess.make_dir_recursive_absolute(home + "/.local/share/ariadne2/pet")


# --- needs ------------------------------------------------------------------
# Per-minute drift while awake; sleep restores energy, music and play restore
# fun, attention restores affection.
func _process(delta: float) -> void:
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
	needs["fitness"] -= 0.004 * m
	needs["purpose"] -= 0.006 * m
	if pet.state == "sleep" and pet.pstate.begins_with("Bed_"):
		needs["energy"] += 0.04 * m               # sleeps better in her bed
	if pet.state == "sleep" and needs["energy"] > 0.98 and not pet.brain._night():
		pet._stir()                              # slept her fill: up she gets
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


func _save() -> void:
	var data := {"needs": needs, "mood": mood(), "holding": holding, "state": pet.state,
		"updated": Time.get_unix_time_from_system()}
	var f := FileAccess.open(home + STATE_FILE, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(data))
	var g := FileAccess.open(SAVE_FILE, FileAccess.WRITE)
	if g:
		g.store_string(JSON.stringify(needs.merged({"_left": left})))


func _load() -> void:
	var f := FileAccess.open(SAVE_FILE, FileAccess.READ)
	if f:
		var d = JSON.parse_string(f.get_as_text())
		if d is Dictionary:
			for k in needs:
				if d.has(k):
					needs[k] = clampf(float(d[k]), 0.0, 1.0)
			if d.get("_left") is Dictionary:
				for k in d["_left"]:
					if THINGS.has(k):
						left[k] = str(d["_left"][k])


# --- holding things ---------------------------------------------------------
func _hold(item: String) -> void:
	holding = item
	if holding_node:
		holding_node.queue_free()
		holding_node = null
	if item != "":
		holding_node = _item_mesh(item)
		pet.add_child(holding_node)


# Where a thing is now: the spot it was left at, or its home.
func where(thing: String) -> String:
	return left.get(thing, THINGS.get(thing, ""))


# Picked up from wherever it was.
func take(thing: String) -> void:
	left.erase(thing)
	show_left()
	_hold(thing)


# Put down where she is (perched at a spot): left there, or home if that's its home.
func leave(spot: String) -> void:
	var thing := holding
	_hold("")
	if THINGS.has(thing) and spot != THINGS[thing] and pet.room.spot(spot).has("drop"):
		left[thing] = spot
	show_left()


# Things lying about where she left them (room.gd's drop point on each spot).
func show_left() -> void:
	for k in left_nodes.keys():
		if not left.has(k):
			left_nodes[k].queue_free()
			left_nodes.erase(k)
	for k in left:
		var d: Dictionary = pet.room.spot(left[k]) if pet.room else {}
		if not d.has("drop"):
			continue
		if not left_nodes.has(k):
			left_nodes[k] = _item_mesh(k)
			pet.room.add_child(left_nodes[k])
		var n: MeshInstance3D = left_nodes[k]
		n.position = d["drop"]
		n.rotation = Vector3(-PI / 2 if k in ["book", "phone"] else 0.0, 0.6, 0.0)    # books and phones lie flat


func _hold_frame() -> void:
	if not holding_node:
		return
	var skel: Skeleton3D = pet.skel
	var h := skel.find_bone("RightHand")
	if h >= 0:
		holding_node.global_position = skel.global_transform * skel.get_bone_global_pose(h).origin \
				+ Basis(Vector3.UP, pet.yaw) * Vector3(0, 0.02, 0.06)


func _item_mesh(item: String) -> MeshInstance3D:
	var m := MeshInstance3D.new()
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	match item:
		"book", "phone", "controller":
			var b := BoxMesh.new()
			b.size = {"book": Vector3(0.15, 0.2, 0.03), "phone": Vector3(0.07, 0.14, 0.01),
					"controller": Vector3(0.15, 0.04, 0.09)}[item]
			m.mesh = b
			mat.albedo_color = {"book": Color(0.25, 0.35, 0.6), "phone": Color(0.1, 0.1, 0.12),
					"controller": Color(0.15, 0.15, 0.18)}[item]
		"mug":
			var c := CylinderMesh.new()
			c.top_radius = 0.042; c.bottom_radius = 0.042; c.height = 0.1
			m.mesh = c
			mat.albedo_color = Color(0.62, 0.1, 0.12)
		"bowl":
			var c := CylinderMesh.new()
			c.top_radius = 0.07; c.bottom_radius = 0.04; c.height = 0.06
			m.mesh = c
			mat.albedo_color = Color(0.95, 0.93, 0.88)
		"can":
			var c := CylinderMesh.new()
			c.top_radius = 0.07; c.bottom_radius = 0.07; c.height = 0.16
			m.mesh = c
			mat.albedo_color = Color(0.25, 0.5, 0.52)
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
