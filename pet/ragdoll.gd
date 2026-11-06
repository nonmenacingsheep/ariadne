extends Node
# Her ragdoll: physical bones on her skeleton while he holds her and while she
# tumbles after he lets go (docs/PET_RAGDOLL_PLAN.md). Pinned at the point he
# grabbed; a loose flail pulls on every limb but the one he has her by. Let go,
# she flails till she hits something, goes limp, settles, and pet.gd picks a
# get-up for the way she landed (lie(): back, front, side, sit).

var pet
var skel: Skeleton3D
var sim: PhysicalBoneSimulator3D
var rigid: Rigid
var parts := {}            # bone -> PhysicalBone3D
var row := {}              # bone -> its PARTS row
var up_part := {}          # bone -> the part it hangs from ("" for her hips)
var rel0 := {}             # bone -> its basis in its parent part when the ragdoll began
var wiggle := {}           # bone -> [axis1, axis2, phase1, phase2, rate]
var reach := {}            # bone -> its length, for its moment of inertia
var env: Node3D            # floor, walls, glass, widget ledges
var anchor: StaticBody3D
var pin: PinJoint3D
var pins: Array = []       # [anchor, joint, limb] she was left hanging from (pin mode): fixed in place
const MAX_PINS := 4
var target := Vector3.ZERO # where the anchor goes: the point under his pointer
var anchor_v := Vector3.ZERO  # how fast his hand is moving her, m/s
var on := false
var held := false
var limp: Array = []       # the limb he holds: no flail
var flail := 0.0
var t := 0.0
var since_drop := 0.0
var still_for := 0.0
var landed := false
var impact := 0.0
var exceptions: Array = []
var fwd_in_hips := Vector3.BACK
var up_in_hips := Vector3.UP
var last_speed := {}
var fading := 0.0          # seconds left of handing her back to her clips
var fade_len := 0.0

# bone, end ("Bone", "+len" past the joint along the bone, "*legs" between her
# thighs), radius, mass, joint (none / cone swing,twist / hinge lo,hi degrees), flail amplitude
const PARTS := [
	["Hips", "*legs", 0.12, 6.0, "none", 0, 0, 0.0],
	["Spine", "Chest", 0.1, 4.0, "cone", 20, 15, 0.15],
	["Chest", "Neck", 0.1, 6.0, "cone", 20, 15, 0.15],
	["Head", "+0.2", 0.095, 3.5, "cone", 40, 40, 0.35],
	["LeftUpperArm", "LeftLowerArm", 0.045, 3.0, "cone", 85, 40, 1.0],
	["LeftLowerArm", "LeftHand", 0.04, 2.5, "elbow", -5, 140, 0.8],
	["LeftHand", "+0.09", 0.035, 2.0, "cone", 50, 20, 0.5],
	["RightUpperArm", "RightLowerArm", 0.045, 3.0, "cone", 85, 40, 1.0],
	["RightLowerArm", "RightHand", 0.04, 2.5, "elbow", -5, 140, 0.8],
	["RightHand", "+0.09", 0.035, 2.0, "cone", 50, 20, 0.5],
	["LeftUpperLeg", "LeftLowerLeg", 0.062, 5.0, "cone", 60, 25, 0.7],
	["LeftLowerLeg", "LeftFoot", 0.05, 3.5, "knee", -5, 140, 0.9],
	["LeftFoot", "LeftToes", 0.04, 2.0, "cone", 30, 10, 0.3],
	["RightUpperLeg", "RightLowerLeg", 0.062, 5.0, "cone", 60, 25, 0.7],
	["RightLowerLeg", "RightFoot", 0.05, 3.5, "knee", -5, 140, 0.9],
	["RightFoot", "RightToes", 0.04, 2.0, "cone", 30, 10, 0.3]]
# Physics only matters while she's a ragdoll (her joints need 120 Hz to hold
# under her weight); the rest of the time it ticks slowly, saving the CPU.
const RAG_TICKS := 120
const IDLE_TICKS := 30
const ENV_LAYER := 1
const BODY_LAYER := 4
# Which way each hinge bends at rest (she faces +Z in a T-pose): knees fold the
# shin back, elbows fold the forearm forward. Jolt counts a hinge's angle the
# other way round from that axis (measured: with +1 her knees bent forward).
const HINGE_SIGN := -1.0
# Her hips' cone leans forward: a leg swings far up in front, little behind.
const HIP_LEAN := 30.0


func build(p, sk: Skeleton3D) -> void:
	pet = p
	skel = sk
	sim = PhysicalBoneSimulator3D.new()
	sim.active = false
	skel.add_child(sim)
	skel.move_child(sim, 0)                # before the spring bones: tail and hair follow her
	rigid = Rigid.new()
	rigid.active = false
	skel.add_child(rigid)
	skel.move_child(rigid, 1)
	# Her pelvis, not her chest, tells how she lies: flat on her front whether
	# or not she's propped on her elbows.
	var hips_rest := skel.get_bone_global_rest(skel.find_bone("Hips")).basis
	fwd_in_hips = (hips_rest.inverse() * Vector3.BACK).normalized()     # she faces +Z at rest
	up_in_hips = (hips_rest.inverse() * Vector3.UP).normalized()
	var rest := {}
	for r in PARTS:
		var i := skel.find_bone(r[0])
		if i < 0:
			continue
		rest[r[0]] = skel.get_bone_global_rest(i)
	for r in PARTS:
		if not rest.has(r[0]):
			continue
		var g: Transform3D = rest[r[0]]
		var end_w: Vector3
		var e: String = r[1]
		if e == "*legs":
			end_w = (skel.get_bone_global_rest(skel.find_bone("LeftUpperLeg")).origin
					+ skel.get_bone_global_rest(skel.find_bone("RightUpperLeg")).origin) / 2.0
		elif e.begins_with("+"):
			end_w = g * Vector3(0, float(e.substr(1)), 0)
		else:
			end_w = skel.get_bone_global_rest(skel.find_bone(e)).origin
		var end_l := g.affine_inverse() * end_w
		var len := maxf(end_l.length(), 0.02)
		var dir := end_l / len
		var pb := PhysicalBone3D.new()
		pb.name = "rag_" + r[0]
		pb.bone_name = r[0]
		pb.mass = r[3]
		pb.friction = 0.8
		pb.bounce = 0.05
		pb.linear_damp = 0.15
		pb.angular_damp = 1.2
		pb.collision_layer = BODY_LAYER
		pb.collision_mask = ENV_LAYER | BODY_LAYER
		pb.body_offset = Transform3D(Basis(Quaternion(Vector3.UP, dir)), end_l * 0.5)
		var cs := CollisionShape3D.new()
		var cap := CapsuleShape3D.new()
		cap.radius = r[2]
		cap.height = maxf(len + r[2] * 0.6, r[2] * 2.0 + 0.01)
		cs.shape = cap
		pb.add_child(cs)
		# Its own place in the world: when pet.gd moves her frame under where she
		# lies (getting up), the ragdoll mustn't be carried round with it.
		pb.top_level = true
		sim.add_child(pb)
		pb.global_transform = skel.global_transform * g * pb.body_offset
		parts[r[0]] = pb
		row[r[0]] = r
		if r[0] != "Hips":
			rigid.ids.append(skel.find_bone(r[0]))
		reach[r[0]] = len
	# Joints, framed in the T-pose so the limits are a body's, not this moment's;
	# the legs lifted HIP_LEAN forward first, so that's the middle of their cone.
	for side in ["Left", "Right"]:
		if not parts.has(side + "UpperLeg"):
			continue
		var hip: Vector3 = joint(side + "UpperLeg")
		var lean := Transform3D(Basis(Vector3.RIGHT, deg_to_rad(-HIP_LEAN)), Vector3.ZERO)
		var about := Transform3D(Basis(), hip) * lean * Transform3D(Basis(), -hip)
		for b in [side + "UpperLeg", side + "LowerLeg", side + "Foot"]:
			if parts.has(b):
				(parts[b] as Node3D).global_transform = about * (parts[b] as Node3D).global_transform
	for b in parts:
		var r: Array = row[b]
		var pb: PhysicalBone3D = parts[b]
		var par := skel.get_bone_parent(skel.find_bone(b))
		up_part[b] = ""
		while par >= 0:
			if parts.has(skel.get_bone_name(par)):
				up_part[b] = skel.get_bone_name(par)
				break
			par = skel.get_bone_parent(par)
		var g: Transform3D = rest[b]
		var jb := Basis(Vector3.BACK, PI / 2.0)          # cone twist (X) along the bone (+Y)
		if r[4] in ["elbow", "knee"]:
			var side := 1.0 if b.begins_with("Left") else -1.0
			var bend: Vector3 = Vector3.RIGHT if r[4] == "knee" else Vector3.DOWN * side
			var z := (g.basis.inverse() * bend).normalized() * HINGE_SIGN
			var x := (Vector3.UP - z * z.dot(Vector3.UP)).normalized()
			jb = Basis(x, z.cross(x), z)
		pb.joint_offset = pb.body_offset.affine_inverse() * Transform3D(jb, Vector3.ZERO)
		match r[4]:
			"cone":
				pb.joint_type = PhysicalBone3D.JOINT_TYPE_CONE
				pb.set("joint_constraints/swing_span", float(r[5]))
				pb.set("joint_constraints/twist_span", float(r[6]))
				pb.set("joint_constraints/softness", 0.8)
			"elbow", "knee":
				pb.joint_type = PhysicalBone3D.JOINT_TYPE_HINGE
				pb.set("joint_constraints/angular_limit_enabled", true)
				pb.set("joint_constraints/angular_limit_lower", float(r[5]))
				pb.set("joint_constraints/angular_limit_upper", float(r[6]))
			_:
				pb.joint_type = PhysicalBone3D.JOINT_TYPE_NONE
		if up_part[b] != "":
			pb.add_collision_exception_with(parts[up_part[b]])
	# Neighbours that touch in any pose: shoulders against her chest, thighs against her hips.
	for pair in [["LeftUpperArm", "Chest"], ["RightUpperArm", "Chest"], ["LeftUpperArm", "Spine"],
			["RightUpperArm", "Spine"], ["LeftUpperLeg", "Spine"], ["RightUpperLeg", "Spine"], ["Head", "Spine"]]:
		if parts.has(pair[0]) and parts.has(pair[1]):
			(parts[pair[0]] as PhysicalBone3D).add_collision_exception_with(parts[pair[1]])
	for b in parts:
		var a1 := Vector3(randf_range(-1, 1), randf_range(-0.3, 0.3), randf_range(-1, 1)).normalized()
		var a2 := a1.cross(Vector3.UP).normalized()
		wiggle[b] = [a1, a2, randf() * TAU, randf() * TAU, randf_range(2.2, 3.8)]
	Engine.physics_ticks_per_second = IDLE_TICKS
	anchor = _new_anchor()
	env = Node3D.new()
	pet.add_child(env)


func _new_anchor() -> StaticBody3D:
	var a := StaticBody3D.new()
	a.collision_layer = 0
	a.collision_mask = 0
	var dot := CollisionShape3D.new()
	dot.shape = SphereShape3D.new()
	(dot.shape as SphereShape3D).radius = 0.01
	a.add_child(dot)
	pet.add_child(a)
	return a


# The room she can land in: the floor, the screen's edges, the glass and the
# back wall, and the tops of his widgets near the glass. Called when they change.
func build_env(screen_m: Vector2, room_depth: float, floors: Array) -> void:
	if env == null:
		return
	for c in env.get_children():
		c.queue_free()
	var w := screen_m.x
	var h := screen_m.y
	_box(Vector3(w / 2.0, -0.5, -room_depth / 2.0), Vector3(w + 4.0, 1.0, room_depth + 4.0))       # floor
	_box(Vector3(-0.5, h / 2.0, -room_depth / 2.0), Vector3(1.0, h + 4.0, room_depth + 4.0))      # left
	_box(Vector3(w + 0.5, h / 2.0, -room_depth / 2.0), Vector3(1.0, h + 4.0, room_depth + 4.0))   # right
	_box(Vector3(w / 2.0, h + 0.5, -room_depth / 2.0), Vector3(w + 4.0, 1.0, room_depth + 4.0))   # ceiling
	_box(Vector3(w / 2.0, h / 2.0, 0.95), Vector3(w + 4.0, h + 4.0, 1.0))                         # the glass
	_box(Vector3(w / 2.0, h / 2.0, -room_depth - 0.8), Vector3(w + 4.0, h + 4.0, 1.0))             # back wall
	for fl in floors:
		if float(fl[0]) > 0.01:                                                                    # a widget's top edge
			var x0 := float(fl[1])
			var x1 := minf(float(fl[2]), w)
			_box(Vector3((x0 + x1) / 2.0, float(fl[0]) - 0.03, 0.1), Vector3(x1 - x0, 0.06, 0.7))


func _box(at: Vector3, size: Vector3) -> void:
	var sb := StaticBody3D.new()
	sb.collision_layer = ENV_LAYER
	sb.collision_mask = 0
	var cs := CollisionShape3D.new()
	var bx := BoxShape3D.new()
	bx.size = size
	cs.shape = bx
	sb.add_child(cs)
	sb.position = at
	env.add_child(sb)


# Picked up: every bone goes physical from the pose she's in, pinned at `at`
# (world) on `bone`. The limb that point is on hangs limp.
func start(bone: String, at: Vector3) -> void:
	if on:
		stop()                             # caught again while getting up
	Engine.physics_ticks_per_second = RAG_TICKS
	var b := _part_for(bone)
	sim.active = true
	rigid.active = true
	sim.influence = 1.0
	sim.physical_bones_start_simulation()
	# From the pose she's in this moment (the bodies otherwise start where they last were).
	for n in parts:
		var pb: PhysicalBone3D = parts[n]
		var xf := skel.global_transform * skel.get_bone_global_pose(skel.find_bone(n)) * pb.body_offset
		pb.global_transform = xf
		PhysicsServer3D.body_set_state(pb.get_rid(), PhysicsServer3D.BODY_STATE_TRANSFORM, xf)
		PhysicsServer3D.body_set_state(pb.get_rid(), PhysicsServer3D.BODY_STATE_LINEAR_VELOCITY, Vector3.ZERO)
		PhysicsServer3D.body_set_state(pb.get_rid(), PhysicsServer3D.BODY_STATE_ANGULAR_VELOCITY, Vector3.ZERO)
	on = true
	held = true
	landed = false
	impact = 0.0
	t = 0.0
	since_drop = 0.0
	still_for = 0.0
	flail = 1.0
	last_speed.clear()
	for p in parts:
		if up_part[p] != "":
			rel0[p] = ((parts[up_part[p]] as Node3D).global_basis.inverse() * (parts[p] as Node3D).global_basis).orthonormalized()
	limp = _limb(b)
	# Parts already touching each other in this pose pass through each other till she's let go of.
	exceptions.clear()
	var names := parts.keys()
	for i in names.size():
		for j in range(i + 1, names.size()):
			var a: PhysicalBone3D = parts[names[i]]
			var c: PhysicalBone3D = parts[names[j]]
			var gap := _seg_gap(names[i], names[j])
			if gap < (row[names[i]][2] + row[names[j]][2]) * 0.9:
				a.add_collision_exception_with(c)
				exceptions.append([a, c])
	_hold(b, at)


# Caught by another point while she hangs from pins: the pins stay, and this
# one follows his pointer.
func grab_more(bone: String, at: Vector3) -> void:
	var b := _part_for(bone)
	held = true
	landed = false
	impact = 0.0
	since_drop = 0.0
	still_for = 0.0
	if pin:                                # (a hold still on: caught twice in one press)
		pin.queue_free()
		pin = null
	flail = maxf(flail, 0.7)
	limp = _limb(b)
	for p in pins:
		limp.append_array(p[2])
	# (`at` is on her physical part: pet.gd's _bone_xf. Read from her skeleton it
	# was the "Held" clip's pose, up to a metre off, and the pin yanked her over.)
	if OS.get_environment("PET_SNAPSHOT_SEQ").begins_with("pin:"):
		var pb: PhysicalBone3D = parts[b]
		print("GRIP %s %.3f m from the part" % [b, at.distance_to(pb.global_position)])
	_hold(b, at)


func _hold(b: String, at: Vector3) -> void:
	anchor.global_position = at
	anchor_v = Vector3.ZERO
	target = at
	pin = PinJoint3D.new()
	pet.add_child(pin)
	pin.global_position = at
	pin.node_a = pin.get_path_to(anchor)
	pin.node_b = pin.get_path_to(parts[b])
	pin.set_meta("limb", _limb(b))


# Let go in pin mode: the point he held stays where it is, and she hangs from it.
func pin_here() -> void:
	if pin == null:
		return
	pins.append([anchor, pin, pin.get_meta("limb")])
	pin = null
	anchor = _new_anchor()
	anchor_v = Vector3.ZERO
	while pins.size() > MAX_PINS:            # the oldest lets go
		var old: Array = pins.pop_front()
		(old[1] as Node).queue_free()
		(old[0] as Node).queue_free()


func unpin_all() -> void:
	for p in pins:
		(p[1] as Node).queue_free()
		(p[0] as Node).queue_free()
	pins.clear()


func let_go() -> void:
	held = false
	since_drop = 0.0
	# The anchor is moved by hand, not by the physics, so her parts only follow
	# it and carry little speed of their own: give them his hand's, so a flick
	# throws her (each part keeps a little of its own swing).
	for b in parts:
		var rid: RID = (parts[b] as PhysicalBone3D).get_rid()
		var v := PhysicsServer3D.body_get_state(rid, PhysicsServer3D.BODY_STATE_LINEAR_VELOCITY) as Vector3
		PhysicsServer3D.body_set_state(rid, PhysicsServer3D.BODY_STATE_LINEAR_VELOCITY, v.lerp(anchor_v, 0.85))
	if OS.get_environment("PET_SNAPSHOT_SEQ").begins_with("grab:"):
		print("THROW anchor_v %s" % anchor_v)
	if pin:
		pin.queue_free()
		pin = null
	unpin_all()


# Poked while she lies in a heap: that part is shoved (an impulse at the point, world).
func shove(bone: String, at: Vector3, impulse: Vector3) -> void:
	var pb: PhysicalBone3D = parts[_part_for(bone)]
	PhysicsServer3D.body_apply_impulse(pb.get_rid(), impulse * float(row[_part_for(bone)][3]) * 0.4, at - pb.global_position)
	still_for = 0.0


# Up she gets: the ragdoll's pose fades into the get-up clip's over `secs`, then stops.
func ease_out(secs: float) -> void:
	fade_len = secs
	fading = secs
	flail = 0.0


# Which way is up, in her pelvis's own frame.
func hips_up() -> Vector3:
	return _hips_bone().inverse() * Vector3.UP


func fwd_now() -> Vector3:
	return _hips_bone() * fwd_in_hips


# Her hips bone's turn in the world, from its physical part.
func _hips_bone() -> Basis:
	var pb: PhysicalBone3D = parts["Hips"]
	return pb.global_basis * pb.body_offset.basis.inverse()


func stop() -> void:
	fading = 0.0
	sim.influence = 1.0
	on = false
	held = false
	if pin:
		pin.queue_free()
		pin = null
	unpin_all()
	for e in exceptions:
		if is_instance_valid(e[0]) and is_instance_valid(e[1]):
			(e[0] as PhysicalBone3D).remove_collision_exception_with(e[1])
	exceptions.clear()
	sim.physical_bones_stop_simulation()
	sim.active = false
	rigid.active = false
	Engine.physics_ticks_per_second = IDLE_TICKS


# Where a part is, in the world (its middle).
func at(bone: String) -> Vector3:
	return (parts[bone] as Node3D).global_position if parts.has(bone) else pet.body.global_position


# The joint end of a part (where the bone starts), in the world.
func joint(bone: String) -> Vector3:
	var pb: PhysicalBone3D = parts[bone]
	return pb.global_transform * pb.body_offset.affine_inverse().origin


# How she's lying: "back", "front", "side" or "sit".
func lie() -> String:
	return lie_of(_hips_bone())


# The same for any turn of her hips bone (a get-up clip's first frame, say).
func lie_of(hips: Basis) -> String:
	var up := hips * up_in_hips
	var fwd := hips * fwd_in_hips
	if up.y > 0.55:
		return "sit"
	if fwd.y > 0.45:
		return "back"
	if fwd.y < -0.45:
		return "front"
	return "side"


func _part_for(bone: String) -> String:
	var i := skel.find_bone(bone)
	while i >= 0:
		if parts.has(skel.get_bone_name(i)):
			return skel.get_bone_name(i)
		i = skel.get_bone_parent(i)
	return "Hips"


# The limb a part is on, from it up to her torso.
func _limb(b: String) -> Array:
	var out := [b]
	var p: String = up_part.get(b, "")
	while p != "" and p not in ["Hips", "Spine", "Chest"] and b not in ["Hips", "Spine", "Chest", "Head"]:
		out.append(p)
		p = up_part.get(p, "")
	return out


func _seg_gap(a: String, b: String) -> float:
	var pa: PhysicalBone3D = parts[a]
	var pb: PhysicalBone3D = parts[b]
	var ha: Vector3 = pa.global_basis.y.normalized() * float(reach[a]) * 0.5
	var hb: Vector3 = pb.global_basis.y.normalized() * float(reach[b]) * 0.5
	var c := Geometry3D.get_closest_points_between_segments(pa.global_position - ha, pa.global_position + ha,
			pb.global_position - hb, pb.global_position + hb)
	return c[0].distance_to(c[1])


func _physics_process(delta: float) -> void:
	if not on:
		return
	t += delta
	if fading > 0.0:
		fading -= delta
		sim.influence = smoothstep(0.0, 1.0, maxf(fading, 0.0) / fade_len)
		if fading <= 0.0:
			stop()
		return
	if held:
		# Toward his pointer, no faster than a hand can yank her (a flick won't tear her apart).
		var step := ((target - anchor.global_position) * clampf(delta * 30.0, 0.0, 1.0)).limit_length(30.0 * delta)
		anchor.global_position += step
		anchor_v = anchor_v.lerp(step / delta, clampf(delta * 20.0, 0.0, 1.0))
		# Flailing hard when first grabbed, tiring to a wriggle after a few seconds.
		var tired := 0.6 if pin != null else (0.25 if t > 6.0 else 0.6)    # left hanging: wriggles, then mostly hangs
		flail = lerpf(flail, tired if t > 2.5 else 1.0, clampf(delta * 1.5, 0.0, 1.0))
	else:
		since_drop += delta
		# A last flail through the air, limp by the time she's down.
		flail = move_toward(flail, 0.0, delta * (4.0 if landed else 1.6))
	var fastest := 0.0
	var spin := 0.0
	for b in parts:
		var pb: PhysicalBone3D = parts[b]
		var v := PhysicsServer3D.body_get_state(pb.get_rid(), PhysicsServer3D.BODY_STATE_LINEAR_VELOCITY) as Vector3
		var w := PhysicsServer3D.body_get_state(pb.get_rid(), PhysicsServer3D.BODY_STATE_ANGULAR_VELOCITY) as Vector3
		fastest = maxf(fastest, v.length())
		spin = maxf(spin, w.length())
		# A sudden loss of speed: she hit the floor, a wall or a widget.
		if not held and last_speed.has(b) and float(last_speed[b]) - v.length() > 1.6 * 60.0 * delta:
			impact = maxf(impact, float(last_speed[b]))
			if since_drop > 0.05:
				landed = true
		last_speed[b] = v.length()
		var up: String = up_part[b]
		if up == "" or not rel0.has(b):
			continue
		_drive(b, pb, parts[up], w, delta)
	if not held:
		still_for = still_for + delta if fastest < 0.3 and spin < 1.5 else 0.0


# Her muscles: a soft spring from each part toward its flailing target in the
# part above it, pushing back on that part too. Low and damped: a loose pull,
# so gravity and his hand still win.
func _drive(b: String, pb: PhysicalBone3D, par: PhysicalBone3D, w: Vector3, _delta: float) -> void:
	var r: Array = row[b]
	var k_flail: float = 0.0 if b in limp else flail * float(r[7])
	var wg: Array = wiggle[b]
	var target_rel: Basis = rel0[b] * Basis(wg[0], k_flail * 1.1 * sin(t * float(wg[4]) + float(wg[2]))) \
			* Basis(wg[1], k_flail * 0.7 * sin(t * float(wg[4]) * 1.37 + float(wg[3])))
	var want := par.global_basis.orthonormalized() * target_rel
	var q := (want * pb.global_basis.orthonormalized().inverse()).get_rotation_quaternion()
	var ang := q.get_angle()
	if ang > PI:
		ang -= TAU
	var axis := q.get_axis() if ang != 0.0 else Vector3.ZERO
	var wp := PhysicsServer3D.body_get_state(par.get_rid(), PhysicsServer3D.BODY_STATE_ANGULAR_VELOCITY) as Vector3
	# Strong enough to swing a leg against gravity while flailing, near nothing
	# when limp (a little tone so she isn't string).
	var k := 6.0 + 240.0 * k_flail if b not in limp else 0.5
	var d := 2.0 * sqrt(k) * 0.7
	# Turning a part against the one above it: their reduced inertia, so a light
	# part (her hips under two heavy legs) isn't kicked harder than it can take.
	var ic := _inertia(b)
	var ip := _inertia(up_part[b])
	var inertia := ic * ip / (ic + ip)
	var tq := (axis * ang * k - (w - wp) * d) * inertia
	PhysicsServer3D.body_apply_torque(pb.get_rid(), tq)
	PhysicsServer3D.body_apply_torque(par.get_rid(), -tq)


func _inertia(b: String) -> float:
	var r: Array = row[b]
	var l: float = reach[b]
	return float(r[3]) * (l * l / 3.0 + float(r[2]) * float(r[2]) / 2.0)


# After the physics: each part keeps its bone's own length (its rest offset
# from its parent), so her joints can't drift apart under her weight and
# stretch her; only how they turn comes from the physics.
class Rigid extends SkeletonModifier3D:
	var ids: Array[int] = []

	func _process_modification_with_delta(_delta: float) -> void:
		var sk := get_skeleton()
		if sk == null:
			return
		for i in ids:
			sk.set_bone_pose_position(i, sk.get_bone_rest(i).origin)
