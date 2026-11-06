extends Node3D
# Little things that make an episode happen (docs/PET_EPISODES_PLAN.md, part 3):
# small, natural, short-lived, and gone after. A ladybug in the corner she
# crouches over; it crawls about, runs at her, climbs onto her finger, flies
# off. Built from a few shapes and toon-shaded like her (pet._toonify), at a
# cartoon size: a real 1 cm ladybug would be three pixels on his screen.
#
# One at a time. pet.gd and brain.gd drive it with do(): "crawl" (to a point),
# "wander", "flee" (away from her), "fly_off", "hand" (onto her hand, riding
# it), "hop_at" (a hop at her face, then down and away).

var pet
var thing: Node3D                          # what's out now, or null
var kind := ""
var act := "wander"
var goal := Vector3.ZERO                   # where it's crawling to
var vel := Vector3.ZERO                    # flying, hopping
var born := 0.0
var t := 0.0
var legs: Array = []                       # leg pivots, for the scuttle
var wings: Array = []                      # wing cases and wings, for flying
var size := 1.0                            # its scale, eased in on appearing and out on going
var going := false

const SCALE := 1.0
const CRAWL := 0.18                        # m/s on the floor (cartoon-fast)
const LIFE := 60.0                         # seconds before it wanders off whatever happens


func setup(owner) -> void:
	pet = owner


func is_out() -> bool:
	return thing != null and not going


func where() -> Vector3:
	return thing.global_position if thing else Vector3.ZERO


# A new one at `at` (world, on the floor).
func spawn(k: String, at: Vector3) -> void:
	clear()
	kind = k
	match k:
		_:
			thing = _ladybug()
	add_child(thing)
	pet._toonify(thing)
	thing.global_position = at
	thing.rotation.y = randf() * TAU
	born = t
	size = 0.01
	going = false
	act = "still"
	goal = at


func clear() -> void:
	if thing:
		thing.queue_free()
	thing = null
	legs.clear()
	wings.clear()


func do(action: String, at := Vector3.ZERO) -> void:
	if thing == null:
		return
	act = action
	match action:
		"crawl":
			goal = Vector3(at.x, 0.0, at.z)
		"wander":
			goal = _near(thing.global_position, 0.25)
		"flee":
			var away := thing.global_position - _her()
			away.y = 0.0
			goal = thing.global_position + away.normalized() * 1.6
		"fly_off":
			vel = Vector3(randf_range(-0.4, 0.4), 0.9, randf_range(-0.3, 0.1))
		"hop_at":
			# Up at her face from the floor: a hop that falls short, then away.
			var face := _her() + Vector3(0, 0.55, 0)
			var d := face - thing.global_position
			vel = Vector3(d.x, 0.0, d.z) * 1.6 + Vector3(0, 2.6, 0)


func _process(delta: float) -> void:
	t += delta
	if thing == null:
		return
	size = move_toward(size, 0.0 if going else 1.0, delta * 3.0)
	thing.scale = Vector3.ONE * SCALE * maxf(size, 0.01)
	if going and size <= 0.0:
		clear()
		return
	var p := thing.global_position
	var moving := false
	var flying := false
	match act:
		"crawl", "wander", "flee":
			var d := goal - p
			d.y = 0.0
			if d.length() > 0.02:
				var step := minf(d.length(), CRAWL * (1.8 if act == "flee" else 1.0) * delta)
				p += d.normalized() * step
				thing.rotation.y = lerp_angle(thing.rotation.y, atan2(d.x, d.z), clampf(delta * 8.0, 0.0, 1.0))
				moving = true
			elif act == "wander":
				goal = _near(p, 0.25)
			elif act == "flee":
				going = true
		"fly_off":
			vel += Vector3(randf_range(-0.6, 0.6), 0.1, 0.0) * delta
			p += vel * delta
			flying = true
			if p.y > 2.2:
				going = true
		"hop_at":
			vel.y -= 9.8 * delta
			p += vel * delta
			flying = vel.y > 0.0
			if p.y <= 0.0 and vel.y < 0.0:
				p.y = 0.0
				do("flee")
		"hand":
			var h: Vector3 = pet.hand_point("Right")
			p = p.lerp(h, clampf(delta * 10.0, 0.0, 1.0))
	if not act in ["fly_off", "hop_at", "hand"]:
		p.y = 0.0
	thing.global_position = p
	# Legs scuttle when it walks; wings open when it flies.
	for i in legs.size():
		(legs[i] as Node3D).rotation.x = (sin(t * 28.0 + i * 2.1) * 0.5) if moving else 0.0
	for w in wings:
		var side: float = (w as Node3D).get_meta("side")
		var open := 1.0 if flying else 0.0
		(w as Node3D).rotation.z = lerpf((w as Node3D).rotation.z, side * open * 0.9, clampf(delta * 12.0, 0.0, 1.0))
		if (w as Node3D).has_meta("flap") and flying:
			(w as Node3D).rotation.x = sin(t * 60.0) * 0.4
	if t - born > LIFE and not going:
		do("flee")


func _her() -> Vector3:
	return Vector3(pet.pos.x, 0.0, pet.depth)


func _near(p: Vector3, r: float) -> Vector3:
	var a := randf() * TAU
	return Vector3(p.x + cos(a) * r, 0.0, clampf(p.z + sin(a) * r, -pet.room_depth + 0.1, -0.05))


func _mat(c: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	return m


func _ball(r: float, c: Color, at: Vector3, half := false) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var s := SphereMesh.new()
	s.radius = r
	s.height = r * (1.0 if half else 2.0)
	s.is_hemisphere = half
	s.radial_segments = 20
	s.rings = 10
	mi.mesh = s
	mi.material_override = _mat(c)
	mi.position = at
	return mi


# A ladybug about 7 cm long: red shell in two wing cases with black spots, a
# black head with white cheek spots, six legs; the cases lift and the wings
# flap when it flies.
func _ladybug() -> Node3D:
	var root := Node3D.new()
	var red := Color(0.86, 0.12, 0.1)
	var black := Color(0.08, 0.07, 0.08)
	var body := _ball(0.03, black, Vector3(0, 0.012, 0))
	body.scale = Vector3(1.0, 0.45, 1.15)
	root.add_child(body)
	var head := _ball(0.016, black, Vector3(0, 0.014, 0.034))
	root.add_child(head)
	for sx in [-1.0, 1.0]:
		root.add_child(_ball(0.005, Color(0.95, 0.95, 0.92), Vector3(sx * 0.009, 0.02, 0.044)))
	legs.clear()
	wings.clear()
	for side in [-1.0, 1.0]:
		var case := Node3D.new()
		case.position = Vector3(side * 0.002, 0.016, 0.02)
		case.set_meta("side", side)
		var shell := _ball(0.032, red, Vector3(side * 0.014, 0.0, -0.022), true)
		shell.scale = Vector3(0.55, 0.75, 1.05)
		case.add_child(shell)
		for sp in [Vector3(0.012, 0.019, -0.01), Vector3(0.016, 0.014, -0.032), Vector3(0.006, 0.012, -0.045)]:
			case.add_child(_ball(0.0055, black, Vector3(side * sp.x, sp.y, sp.z)))
		root.add_child(case)
		wings.append(case)
		var wing := MeshInstance3D.new()
		var q := QuadMesh.new()
		q.size = Vector2(0.03, 0.05)
		wing.mesh = q
		var wm := _mat(Color(0.85, 0.85, 0.9, 0.45))
		wm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		wing.material_override = wm
		var flap := Node3D.new()
		flap.position = Vector3(side * 0.006, 0.02, 0.01)
		flap.set_meta("side", side * 1.4)
		flap.set_meta("flap", true)
		wing.position = Vector3(side * 0.015, 0.0, -0.02)
		wing.rotation.x = -PI / 2
		flap.add_child(wing)
		root.add_child(flap)
		wings.append(flap)
		for k in 3:
			var leg := Node3D.new()
			leg.position = Vector3(side * 0.02, 0.006, 0.018 - k * 0.018)
			var stick := MeshInstance3D.new()
			var c := CylinderMesh.new()
			c.top_radius = 0.0018
			c.bottom_radius = 0.0018
			c.height = 0.022
			stick.mesh = c
			stick.material_override = _mat(black)
			stick.position = Vector3(side * 0.008, -0.004, 0)
			stick.rotation.z = side * 1.1
			leg.add_child(stick)
			root.add_child(leg)
			legs.append(leg)
	return root
