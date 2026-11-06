extends SkeletonModifier3D
# Her arms against her breasts, softly. A hard collision (the spring bones')
# shoved a breast clear of an arm in one frame: they slammed apart. Here each
# breast has a soft zone round it; an arm inside it is a push, and the breast
# eases aside on a damped spring (no overshoot), flattening along the push and
# (jacket off) filling out across it, the way flesh gives under a forearm.
#
# Runs after the spring bones, on top of their swing.

var sides: Array = []          # [Breast_1, Breast_2, turn [angle, rate], squash [amount, rate], the way it was last pushed]
var arms: Array = []           # [bone, its child (-1: the hand, out past its joint), radius]
var firm := false              # jacket on: it holds them in (no filling out)
var most_in := 0.0             # a test run's deepest press this frame, metres

const ZONE := 0.055            # metres round the breast an arm starts to press
const TIP := 0.05              # the end past Breast_2 (its spring chain's extended end)
const MOST := 0.07             # how far aside, at most (metres at the tip)
const TURN_W := 15.0           # rad/s: eases in over ~0.2 s
const TURN_Z := 0.9            # damping: barely any overshoot
const FLAT := 0.3              # how much a full press flattens it
const FILL := 0.4              # of that, how much it fills out across (jacket off)


func setup(sk: Skeleton3D) -> void:
	sides.clear()
	arms.clear()
	for s in ["L", "R"]:
		var b1 := sk.find_bone("Breast_1." + s)
		var b2 := sk.find_bone("Breast_2." + s)
		if b1 >= 0 and b2 >= 0:
			sides.append([b1, b2, [Vector3.ZERO, Vector3.ZERO], [0.0, 0.0], Vector3.UP])
	for a in [["UpperArm", "LowerArm", 0.05], ["LowerArm", "Hand", 0.045], ["Hand", "", 0.045]]:
		for side in ["Left", "Right"]:
			var b := sk.find_bone(side + a[0])
			if b >= 0:
				arms.append([b, sk.find_bone(side + a[1]) if a[1] != "" else -1, a[2]])


func _process_modification_with_delta(delta: float) -> void:
	var sk := get_skeleton()
	if sk == null or sides.is_empty() or delta <= 0.0:
		return
	delta = minf(delta, 1.0 / 30.0)
	var xf := sk.global_transform
	var to_skel := xf.basis.orthonormalized().inverse()
	# The arms as capsules, in the world.
	var segs: Array = []
	for a in arms:
		var p0: Vector3 = xf * sk.get_bone_global_pose(a[0]).origin
		var p1: Vector3
		if a[1] >= 0:
			p1 = xf * sk.get_bone_global_pose(a[1]).origin
		else:                                   # the hand: out past the wrist
			var up: Vector3 = xf * sk.get_bone_global_pose(sk.get_bone_parent(a[0])).origin
			p1 = p0 + (p0 - up).normalized() * 0.08
		segs.append([p0, p1, a[2]])
	most_in = 0.0
	for s in sides:
		var j1: Vector3 = xf * sk.get_bone_global_pose(s[0]).origin
		var j2: Vector3 = xf * sk.get_bone_global_pose(s[1]).origin
		var tip := j2 + (j2 - j1).normalized() * TIP
		# The deepest any arm is into her soft zone, and which way it pushes.
		var push := Vector3.ZERO
		var depth := 0.0
		for p in [j2, (j2 + tip) * 0.5, tip]:
			for g in segs:
				var q := Geometry3D.get_closest_point_to_segment(p, g[0], g[1])
				var into: float = ZONE + float(g[2]) - p.distance_to(q)
				if into > depth:
					depth = into
					push = (p - q).normalized() * into
		most_in = maxf(most_in, depth)
		push = push.limit_length(MOST * (0.5 if firm else 1.0))     # the jacket holds them close
		if push.length() > 1e-5:
			s[4] = push.normalized()
		var lever := tip - j1
		var goal := lever.cross(push) / maxf(lever.length_squared(), 1e-4)
		var turn: Array = s[2]
		turn[1] = (turn[1] as Vector3) + (TURN_W * TURN_W * (goal - (turn[0] as Vector3)) - 2.0 * TURN_Z * TURN_W * (turn[1] as Vector3)) * delta
		turn[0] = (turn[0] as Vector3) + (turn[1] as Vector3) * delta
		var sq: Array = s[3]
		var flat := clampf(depth / ZONE, 0.0, 1.0) * FLAT
		sq[1] = float(sq[1]) + (TURN_W * TURN_W * (flat - float(sq[0])) - 2.0 * TURN_Z * TURN_W * float(sq[1])) * delta
		sq[0] = clampf(float(sq[0]) + float(sq[1]) * delta, 0.0, FLAT)
		var ang: Vector3 = turn[0]
		var g1 := sk.get_bone_global_pose(s[0])
		var b := s[0] as int
		if ang.length() > 1e-4:
			var q := Quaternion(to_skel * ang.normalized(), ang.length())
			var turned := Transform3D(Basis(q) * g1.basis, g1.origin)
			var par := sk.get_bone_parent(b)
			var loc := turned if par < 0 else sk.get_bone_global_pose(par).affine_inverse() * turned
			sk.set_bone_pose_rotation(b, loc.basis.get_rotation_quaternion())
		# Flattened along the push (in the breast's own axes), filled out across it.
		var amount := float(sq[0])
		if amount > 0.002:                     # (easing back out, along the way it was pushed)
			var n := (sk.get_bone_global_pose(b).basis.orthonormalized().inverse() * (to_skel * (s[4] as Vector3))).abs()
			var scale := Vector3.ONE - n * amount
			if not firm:
				scale += (Vector3.ONE - n) * amount * FILL
			sk.set_bone_pose_scale(b, sk.get_bone_pose_scale(b) * scale)
