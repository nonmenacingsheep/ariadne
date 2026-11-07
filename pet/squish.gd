extends SkeletonModifier3D
# Her arms against her breasts, softly. A hard collision (the spring bones')
# shoved a breast clear of an arm in one frame: they slammed apart. Here each
# breast has a soft zone round it; an arm inside it is a push, and the breast
# eases aside on a damped spring (no overshoot), flattening along the push and
# (jacket off) filling out across it, the way flesh gives under a forearm.
#
# And their weight: the spring bones only turn each breast about where it
# meets her chest, so the tip swung and the rest stretched. Here the whole
# breast moves as a mass on a bouncy spring (bone position, not rotation),
# driven by how her chest accelerates (a step, a hop, a landing, a turn) and
# by gravity: tilted far from upright (lying down, bent over, upside down in
# his hand) they hang toward it, sliding along her chest and tipping over, so
# held upside down they fall toward her chin; lying back they flatten and
# spread. Clothes that hold her in (firm) make all of it quicker and smaller.
#
# Runs after the spring bones, on top of their swing.

var sides: Array = []          # [Breast_1, Breast_2, turn [angle, rate], squash [amount, rate], the way it was last pushed,
                               #  bounce [offset, rate (her chest's frame), last place, speed, acceleration (world, smoothed), gravity turn (world), flat]
var arms: Array = []           # [bone, its child (-1: the hand, out past its joint), radius]
var firm := false              # jacket on: it holds them in (no filling out)
var size := 1.0                # her build against Jane's (leg length): the zone and arms scale with it
var most_in := 0.0             # a test run's deepest press this frame, metres
var most_bounce := 0.0         # and the furthest either breast has bounced, metres
var last_tilt := Vector3.ZERO  # (a test run's readout: how far gravity is toward her head, into her chest, and in all)

# The bounce: about 2 Hz and lively (soft), 3 Hz and tighter (firm); how far at most.
# The bounce: Hz, damping, how far her moves throw them (m); how far gravity
# hangs them (m, fully upside down), how far they tip (rad), how much they flatten.
const SOFT := [2.0, 0.22, 0.025, 0.065, 0.95, 0.35]
const FIRM := [3.2, 0.4, 0.012, 0.025, 0.38, 0.12]
const PUSH := 0.6              # how much of her chest's acceleration they feel
const LEAN := [0.12, 0.45]     # gravity this far from upright (of 2) counts not at all .. fully: a lean while standing doesn't
const HEAD_FROM := 1.0         # toward her head: none till she is past level (of 2: lying is 1), all of it upside down

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
		if b1 < 0:                              # a one-bone breast (the Booth avatars: Breast_L)
			b1 = sk.find_bone("Breast_" + s)
			b2 = b1
		if b1 >= 0 and b2 >= 0:
			sides.append([b1, b2, [Vector3.ZERO, Vector3.ZERO], [0.0, 0.0], Vector3.UP,
					[Vector3.ZERO, Vector3.ZERO, Vector3.INF, Vector3.ZERO, Vector3.ZERO, Vector3.ZERO, 0.0]])
	# Forearms and hands: crossing her arms, hugging herself. (Not the upper arms:
	# hanging at her sides they sat in the zone the whole time on a slight build.)
	for a in [["LowerArm", "Hand", 0.045], ["Hand", "", 0.045]]:
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
		_bounce(sk, s, xf, to_skel, delta)
		var j1: Vector3 = xf * sk.get_bone_global_pose(s[0]).origin
		var j2: Vector3 = xf * sk.get_bone_global_pose(s[1]).origin
		if s[0] == s[1]:                        # one bone: along its own length
			j2 = j1 + (xf.basis * sk.get_bone_global_pose(s[0]).basis.y).normalized() * TIP
		var tip := j2 + (j2 - j1).normalized() * TIP
		# The deepest any arm is into her soft zone, and which way it pushes.
		var push := Vector3.ZERO
		var depth := 0.0
		for p in [j2, (j2 + tip) * 0.5, tip]:
			for g in segs:
				var q := Geometry3D.get_closest_point_to_segment(p, g[0], g[1])
				var into: float = (ZONE + float(g[2])) * size - p.distance_to(q)
				if into > depth:
					depth = into
					push = (p - q).normalized() * into
		most_in = maxf(most_in, depth)
		push = push.limit_length(MOST * size * (0.5 if firm else 1.0))     # the jacket holds them close
		if push.length() > 1e-5:
			s[4] = push.normalized()
		var lever := tip - j1
		var goal := lever.cross(push) / maxf(lever.length_squared(), 1e-4) + (s[5][5] as Vector3)
		var turn: Array = s[2]
		turn[1] = (turn[1] as Vector3) + (TURN_W * TURN_W * (goal - (turn[0] as Vector3)) - 2.0 * TURN_Z * TURN_W * (turn[1] as Vector3)) * delta
		turn[0] = (turn[0] as Vector3) + (turn[1] as Vector3) * delta
		var sq: Array = s[3]
		var flat := maxf(clampf(depth / (ZONE * size), 0.0, 1.0) * FLAT, float(s[5][6]))
		if depth <= 0.0 and float(s[5][6]) > 0.002:
			# (lying back: flattened toward her chest, along the bone's own way out of
			# it, its y as in _bounce; z flattened them sideways and they stood up tall)
			s[4] = (xf.basis * sk.get_bone_global_pose(s[0]).basis.y).normalized()
		sq[1] = float(sq[1]) + (TURN_W * TURN_W * (flat - float(sq[0])) - 2.0 * TURN_Z * TURN_W * float(sq[1])) * delta
		sq[0] = clampf(float(sq[0]) + float(sq[1]) * delta, 0.0, maxf(FLAT, float(s[5][6])))      # (lying back can flatten past an arm's press)
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


func _bounce(sk: Skeleton3D, s: Array, xf: Transform3D, to_skel: Basis, delta: float) -> void:
	var b := s[0] as int
	var par := sk.get_bone_parent(b)
	if par < 0:
		return
	var st: Array = s[5]
	var g := sk.get_bone_global_pose(b)
	var p: Vector3 = xf * g.origin
	if st[2] == Vector3.INF or p.distance_to(st[2]) > 0.5:     # first frame, or she was put somewhere
		st[2] = p
		st[3] = Vector3.ZERO
		st[4] = Vector3.ZERO
	# Her clips are keyed at 30 fps and drawn at 60: the speed steps every other
	# frame, and its raw change was all spikes. Smoothed over a few hundredths of
	# a second, what's left is her real moves.
	var vel: Vector3 = (st[3] as Vector3).lerp((p - (st[2] as Vector3)) / delta, 1.0 - exp(-delta / 0.04))
	var acc: Vector3 = (vel - (st[3] as Vector3)) / delta
	st[4] = (st[4] as Vector3).lerp(acc, 1.0 - exp(-delta / 0.05))
	st[2] = p
	st[3] = vel
	# Gravity in her chest's frame, against upright (the rig's rest: standing
	# straight); small leans don't count, lying down and upside down do.
	var chest := (xf.basis * sk.get_bone_global_pose(par).basis).orthonormalized()
	var upright := (xf.basis * sk.get_bone_global_rest(par).basis).orthonormalized()
	var g_now: Vector3 = chest.inverse() * Vector3.DOWN
	var g_up: Vector3 = upright.inverse() * Vector3.DOWN
	var off := g_now - g_up                                   # 0 upright .. 2 upside down
	var how := smoothstep(LEAN[0], LEAN[1], off.length())
	# Toward her head is only gravity's doing once she's well past lying flat:
	# on her back or side, losing the pull to her feet lifts them a little, not
	# the half of upside down that a straight share gave (they rose to her chin
	# lying down, as if pushed). Sideways and into her chest stay as they are.
	var headward := -g_up.normalized()
	var along := off.dot(headward)                            # 0 upright, 1 lying, 2 upside down
	off += headward * along * (smoothstep(HEAD_FROM, 2.0, along) - 1.0)
	var g_eff := (g_up + off).normalized()
	last_tilt = Vector3(along, maxf(0.0, -g_now.dot((chest.inverse() * (xf.basis * g.basis.y)).normalized())), (g_now - g_up).length())
	var spec: Array = FIRM if firm else SOFT
	# Where they hang: along her chest, never into it (her forward is the
	# breast bone's own way out of her chest, in the chest's frame).
	var out: Vector3 = (chest.inverse() * (xf.basis * g.basis.y)).normalized()
	var hang := off * how * 0.5 * float(spec[3])
	if hang.dot(out) < 0.0:
		hang -= out * hang.dot(out)
	# Tipped toward it: the turn from upright's hang to now's (world), and
	# flattened when gravity presses them back into her (lying on her back).
	var tip_turn := (out.cross(g_eff) - out.cross(g_up)) * how * float(spec[4])
	st[5] = (xf.basis * sk.get_bone_global_pose(par).basis).orthonormalized() * tip_turn.limit_length(float(spec[4]))
	st[6] = maxf(0.0, -g_now.dot(out)) * how * float(spec[5])
	# The spring: toward that hang, thrown about by her moves.
	var push := chest.inverse() * -(st[4] as Vector3) * PUSH
	var w: float = TAU * float(spec[0])
	var o: Vector3 = st[0]
	var v: Vector3 = st[1]
	v += (push + w * w * (hang - o) - 2.0 * float(spec[1]) * w * v) * delta
	o = (o + v * delta)
	o = hang + (o - hang).limit_length(float(spec[2]))
	st[0] = o
	st[1] = v
	most_bounce = maxf(most_bounce, o.length())
	# Moved as a whole: its place in the skeleton, shifted by the offset in her chest's frame.
	var moved := g.origin + to_skel * (chest * o)
	sk.set_bone_pose_position(b, (sk.get_bone_global_pose(par).affine_inverse() * moved))
