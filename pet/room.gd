extends Node3D
# Her furniture (docs/PET_LIFE_PLAN.md): models/props.glb (pet/import/
# props_build.py) placed around the back and sides of her room behind the
# screen, so the front stays clear for her. Each piece has a spot she uses it
# from: where she walks to (approach), where her body ends up (at: x, how
# high she's lifted, depth) and which way she faces. brain.gd routes her
# round the pieces (blockers) and picks activities that use them.

const PROPS := "res://models/props.glb"
const FUTON_TOP := 0.14                    # props_build.py FUTON
const CUSHION_TOP := 0.05
const MARGIN := 0.22                       # how close she walks past furniture

var pet
var items := {}                            # piece -> Node3D
var spots := {}                            # name -> {approach: Vector2, at: Vector3, yaw: float}
var blockers: Array[Rect2] = []            # floor footprints (x, depth) she walks round
var arranged_for := Vector3.ZERO           # (room width, depth, PPM) it was laid out for


func setup(owner) -> void:
	pet = owner
	if not ResourceLoader.exists(PROPS):
		return
	var root: Node3D = (load(PROPS) as PackedScene).instantiate()
	add_child(root)
	for c in root.get_children():
		items[str(c.name)] = c
	pet._toonify(root)
	# The monitor's screen glows (it's lit when the room is).
	for n in root.find_children("*", "MeshInstance3D", true, false):
		var mi := n as MeshInstance3D
		for i in mi.mesh.get_surface_count():
			var m := mi.get_active_material(i) as StandardMaterial3D
			if m and String(m.resource_name) == "screen":
				m.emission_enabled = true
				m.emission = Color(0.3, 0.55, 0.9)
				m.emission_energy_multiplier = 0.9
	arrange()


func has(piece: String) -> bool:
	return visible and items.has(piece)


func spot(name: String) -> Dictionary:
	return spots.get(name, {}) if visible else {}


# Lay the room out for its size: called again when the screen or the room depth changes.
func arrange() -> void:
	var w: float = pet.screen.x / pet.PPM
	var rd: float = pet.room_depth
	var key := Vector3(w, rd, pet.PPM)
	if key == arranged_for or items.is_empty():
		return
	arranged_for = key
	blockers.clear()
	spots.clear()
	var back := -rd
	# Bed along the back wall on the left, head to the left.
	var f := _place("futon", Vector2(1.5, back + 0.62), PI / 2, Vector2(2.0, 1.0))
	spots["futon"] = {"approach": f + Vector2(-0.3, 0.85), "at": Vector3(f.x - 0.45, FUTON_TOP, f.y), "yaw": -PI / 2}
	# Workout mat across the room, left of centre, halfway back.
	var m := _place("mat", Vector2(3.3, -rd * 0.4), PI / 2, Vector2.ZERO)
	spots["mat"] = {"approach": m, "at": Vector3(m.x, 0.0, m.y), "yaw": 0.0}
	# Low table on a rug with a cushion behind it: she sits facing out at you to eat and read.
	_place("rug", Vector2(w * 0.42, -rd * 0.55), 0.0, Vector2.ZERO)
	var lt := _place("low_table", Vector2(w * 0.42, -rd * 0.5), 0.0, Vector2(0.8, 0.5))
	var cu := _place("cushion", Vector2(lt.x, lt.y - 0.48), 0.0, Vector2(0.5, 0.5))
	blockers[-1] = blockers[-1].merge(blockers[-2])            # table and cushion as one
	blockers.remove_at(blockers.size() - 2)
	spots["cushion"] = {"approach": Vector2(cu.x - 0.75, cu.y), "at": Vector3(cu.x, CUSHION_TOP, cu.y), "yaw": 0.0}
	# Bookshelf and kitchenette along the back wall.
	var sh := _place("shelf", Vector2(w * 0.55, back + 0.17), 0.0, Vector2(0.8, 0.3))
	spots["shelf"] = {"approach": sh + Vector2(0, 0.6), "at": Vector3(sh.x, 0, sh.y + 0.6), "yaw": PI}
	var k := _place("kitchen", Vector2(w * 0.68, back + 0.32), 0.0, Vector2(1.24, 0.64))
	spots["kitchen"] = {"approach": k + Vector2(0.2, 0.68), "at": Vector3(k.x + 0.2, 0, k.y + 0.68), "yaw": PI}
	# Desk on the right, its chair in front: she works with her back to you.
	var d := _place("desk", Vector2(w - 2.3, back + 0.33), 0.0, Vector2(1.2, 0.6))
	var ch := _place("chair", Vector2(d.x, d.y + 0.58), 0.0, Vector2(0.5, 0.5))
	blockers[-1] = blockers[-1].merge(blockers[-2])
	blockers.remove_at(blockers.size() - 2)
	spots["desk"] = {"approach": Vector2(ch.x + 0.62, ch.y + 0.25), "at": Vector3(ch.x + 0.06, 0, ch.y - 0.12), "yaw": PI}
	# A plant in the corner by the desk, its watering can beside it.
	var p := _place("plant", Vector2(w - 0.75, back + 0.3), 0.0, Vector2(0.4, 0.4))
	spots["plant"] = {"approach": p + Vector2(-0.1, 0.62), "at": Vector3(p.x - 0.1, 0, p.y + 0.62), "yaw": PI}
	var c := _place("watering_can", Vector2(w - 1.15, back + 0.22), 0.0, Vector2.ZERO)
	spots["can"] = {"approach": c + Vector2(0, 0.5), "at": Vector3(c.x, 0, c.y + 0.5), "yaw": PI}


# Puts a piece at (x, depth), turned by yaw, and blocks its footprint (size, before turning).
func _place(piece: String, at: Vector2, yaw: float, size: Vector2) -> Vector2:
	if items.has(piece):
		var n: Node3D = items[piece]
		n.position = Vector3(at.x, 0.0, at.y)
		n.rotation = Vector3(0, yaw, 0)
	if size != Vector2.ZERO:
		var s := Vector2(size.y, size.x) if absf(sin(yaw)) > 0.7 else size
		blockers.append(Rect2(at - s / 2.0, s).grow(MARGIN))
	return at


func blocked(p: Vector2) -> bool:
	if not visible:
		return false
	for r in blockers:
		if r.has_point(p):
			return true
	return false


# Straight there, or round the front of whatever's in the way.
func route(from: Vector2, to: Vector2) -> Array[Vector2]:
	if not visible or not _crosses(from, to):
		return [to]
	var front := -1e9
	for r in blockers:
		if _crosses_rect(from, to, r):
			front = maxf(front, r.end.y + 0.1)
	front = minf(front, -0.15)
	var out: Array[Vector2] = []
	if from.y < front - 0.05:
		out.append(Vector2(from.x, front))
	out.append(Vector2(to.x, front))
	out.append(to)
	return out


func _crosses(a: Vector2, b: Vector2) -> bool:
	for r in blockers:
		if _crosses_rect(a, b, r):
			return true
	return false


func _crosses_rect(a: Vector2, b: Vector2, r: Rect2) -> bool:
	var n := int(ceil(a.distance_to(b) / 0.08))
	for i in range(1, n):                      # the ends are spots next to furniture: not checked
		if r.has_point(a.lerp(b, float(i) / n)):
			return true
	return false
