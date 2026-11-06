extends SkeletonModifier3D
# Poke mode: his pointer presses on her. The point he pressed is held on its
# bone; a finger there pushes into the screen (and sideways, if he drags), and
# every joint from that bone up to her hips turns by the twist that push puts
# on it, on a spring back to her pose: a poke to her shoulder turns her chest
# away, one to her forehead tips her head back, her hand swings. Her hips lean
# from her feet. Let go, each joint springs back with a little wobble.
#
# Runs after her clips, before the spring bones, so hair and chest follow.

var pet
var bone := -1                 # the bone he's pressing, -1 when he isn't
var local := Vector3.ZERO      # the point on it, in its own space
var target := Vector3.ZERO     # where the finger is (world): the pointer's ray, pressed in
var press := 0.0               # how far in, metres (ramps up while held)
var springs := {}              # bone -> [angle (world rotation vector), its rate]
var kick := false              # first frame of a press: a jolt as well as a push

# How far each joint gives to the twist on it (radians per m² of lever × push),
# how fast it springs back (rad/s), by the bone's name.
const GIVE := {"Head": 2.0, "Neck": 1.0, "UpperChest": 0.5, "Chest": 0.5, "Spine": 0.4,
		"Shoulder": 0.6, "UpperArm": 1.6, "LowerArm": 1.6, "Hand": 2.0,
		"UpperLeg": 0.25, "LowerLeg": 0.1, "Hips": 0.03}
const RATE := {"Head": 13.0, "Neck": 11.0, "Hand": 14.0, "LowerArm": 12.0, "UpperArm": 10.0,
		"Shoulder": 9.0, "Hips": 5.0, "UpperLeg": 7.0, "LowerLeg": 8.0}
const GAIN := 12.0
const DAMP := 0.4              # under 1: a wobble back, not a slow ooze
const MOST := 0.6              # radians any joint turns, at most
const DEPTH := 0.08            # how far a press goes in, metres
const SIDE := 0.1              # how far a drag pushes sideways


func _kind(name: String) -> String:
	for k in GIVE:
		if name.ends_with(k):
			return k
	return ""


# He pressed `b` at `at` (world).
func start(b: int, at: Vector3) -> void:
	var sk := get_skeleton()
	bone = b
	local = (sk.global_transform * sk.get_bone_global_pose(b)).affine_inverse() * at
	target = at
	press = 0.0
	kick = true


func stop() -> void:
	bone = -1


func busy() -> bool:
	if bone >= 0:
		return true
	for s in springs.values():
		if (s[0] as Vector3).length() > 0.002 or (s[1] as Vector3).length() > 0.02:
			return true
	return false


func _process_modification_with_delta(delta: float) -> void:
	var sk := get_skeleton()
	if sk == null or delta <= 0.0:
		return
	delta = minf(delta, 1.0 / 30.0)
	var xf := sk.global_transform
	# The joints from the pressed bone up to her hips, and what each should turn by.
	var want := {}
	if bone >= 0:
		press = move_toward(press, DEPTH, delta * DEPTH / 0.12)
		var contact: Vector3 = xf * sk.get_bone_global_pose(bone) * local
		var side := target - contact
		side.z = 0.0
		var push := Vector3.FORWARD * press + side.limit_length(SIDE)
		var b := bone
		while b >= 0:
			var k := _kind(sk.get_bone_name(b))
			if k != "":
				var g: Transform3D = xf * sk.get_bone_global_pose(b)
				var pivot: Vector3 = g.origin
				if k == "Hips":
					pivot = Vector3(g.origin.x, xf.origin.y, g.origin.z)       # she leans from her feet
				want[b] = ((contact - pivot).cross(push) * GAIN * float(GIVE[k])).limit_length(MOST)
			if k == "Hips":
				break
			b = sk.get_bone_parent(b)
	for b in want:
		if not springs.has(b):
			springs[b] = [Vector3.ZERO, Vector3.ZERO]
	# Each joint on its spring toward what it should turn by (nothing, once he lets go).
	var order: Array = springs.keys()
	order.sort()                               # parents before children (bone order)
	for b in order:
		var k := _kind(sk.get_bone_name(b))
		var w: float = RATE.get(k, 9.0)
		var s: Array = springs[b]
		var goal: Vector3 = want.get(b, Vector3.ZERO)
		if kick and want.has(b):
			s[1] = (s[1] as Vector3) + goal * w * 0.8     # the jab itself
		s[1] = (s[1] as Vector3) + (w * w * (goal - (s[0] as Vector3)) - 2.0 * DAMP * w * (s[1] as Vector3)) * delta
		s[0] = ((s[0] as Vector3) + (s[1] as Vector3) * delta).limit_length(MOST)
	kick = false
	# Turn each joint (parents first, so the children carry their turn too).
	var to_skel := xf.basis.orthonormalized().inverse()
	for b in order:
		var ang: Vector3 = springs[b][0]
		if ang.length() < 1e-4:
			continue
		var q := Quaternion(to_skel * ang.normalized(), ang.length())      # in the skeleton's space
		var g := sk.get_bone_global_pose(b)
		var turned := Transform3D(Basis(q) * g.basis, g.origin)
		if _kind(sk.get_bone_name(b)) == "Hips":
			var pivot := Vector3(g.origin.x, 0.0, g.origin.z)
			turned.origin = pivot + q * (g.origin - pivot)
		var p := sk.get_bone_parent(b)
		var loc := turned if p < 0 else sk.get_bone_global_pose(p).affine_inverse() * turned
		sk.set_bone_pose_rotation(b, loc.basis.get_rotation_quaternion())
		sk.set_bone_pose_position(b, loc.origin)
	# Done springing back: forget it.
	if bone < 0:
		for b in order:
			if (springs[b][0] as Vector3).length() < 1e-4 and (springs[b][1] as Vector3).length() < 1e-3:
				springs.erase(b)
