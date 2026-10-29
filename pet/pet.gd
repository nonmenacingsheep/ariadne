extends Node3D
# Aries's body. It reads the core's messages (her voice level, her actions,
# her ears) and turns them into a little life: breathing, blinking, a mouth
# that follows her voice, a glance toward the app she's working in, and a face
# for how it went. It never decides anything; the core does.
#
# Kept cheap on purpose: one small transparent window, the mobile renderer,
# 30 fps while something is happening and 15 at rest.

const PORT := 47120                       # the core's localhost port for the pet
const MODEL := "res://models/aries.vrm"
const FPS_BUSY := 30
const FPS_IDLE := 15

# VRoid's blend shape names first, then generic VRM names as a fallback.
const SHAPES := {
	"blink": ["Fcl_EYE_Close", "blink", "Blink"],
	"aa": ["Fcl_MTH_A", "aa", "A"],
	"happy": ["Fcl_ALL_Joy", "happy", "Joy"],
	"sad": ["Fcl_ALL_Sorrow", "sad", "Sorrow"],
	"angry": ["Fcl_ALL_Angry", "angry", "Angry"],
	"surprised": ["Fcl_ALL_Surprised", "surprised", "Surprised"],
	"relaxed": ["Fcl_ALL_Fun", "relaxed", "Fun"],
}
# Which way to glance for each app widget, from where she usually stands
# (x: + is her left on screen-right, y: + is up).
const GLANCE := {
	"spotify": Vector2(1, 0.3), "steam": Vector2(1, 0.0), "browser": Vector2(1, -0.2),
	"chat": Vector2(-1, 0.2), "claude": Vector2(-1, -0.3), "dolphin": Vector2(-0.3, -0.6),
	"flows": Vector2(0.3, -0.6), "system": Vector2(0.6, -0.6),
}

var tcp := StreamPeerTCP.new()
var inbox := ""
var retry_in := 0.0
var skel: Skeleton3D
var shapes := {}                          # key -> [[mesh, index], ...]
var bones := {}                           # name -> bone index
var t := 0.0
var next_blink := 2.0
var blink := 0.0
var mouth := 0.0
var level := 0.0
var speaking := false
var mood := {}                            # key -> current weight
var mood_target := {}
var mood_until := 0.0
var look := Vector2.ZERO
var look_target := Vector2.ZERO
var look_until := 0.0
var busy_until := 0.0
var snapshot_path := OS.get_environment("PET_SNAPSHOT")


const POS_FILE := "user://position.json"


func _ready() -> void:
	get_viewport().transparent_bg = true
	get_window().title = "ariadne2-pet"      # KWin finds her by this (desk/kwin_layer.js)
	_place()
	var body: Node = (load(MODEL) as PackedScene).instantiate()
	add_child(body)
	skel = _find_skeleton(body)
	for key in SHAPES:
		shapes[key] = _find_shapes(body, SHAPES[key])
		mood[key] = 0.0
		mood_target[key] = 0.0
	mood_target["relaxed"] = 0.12            # a resting half-smile
	for b in ["Spine", "Chest", "UpperChest", "Neck", "Head", "LeftUpperArm", "RightUpperArm",
			"LeftLowerArm", "RightLowerArm"]:
		var i := skel.find_bone(b) if skel else -1
		if i >= 0:
			bones[b] = i
	_frame_camera()
	if snapshot_path != "":
		_snapshot.call_deferred()
	else:
		_connect()


# --- the core ---------------------------------------------------------------
func _connect() -> void:
	tcp = StreamPeerTCP.new()
	if tcp.connect_to_host("127.0.0.1", PORT) != OK:
		retry_in = 2.0


func _poll_core(delta: float) -> void:
	if snapshot_path != "":
		return
	tcp.poll()
	var status := tcp.get_status()
	if status == StreamPeerTCP.STATUS_NONE or status == StreamPeerTCP.STATUS_ERROR:
		retry_in -= delta
		if retry_in <= 0.0:
			_connect()
			retry_in = 2.0
		return
	if status != StreamPeerTCP.STATUS_CONNECTED:
		return
	if inbox == "" and not has_meta("said_hello"):
		set_meta("said_hello", true)
		tcp.put_data(('{"t":"hello","v":1,"side":"desk","pid":%d}\n' % OS.get_process_id()).to_utf8_buffer())
	var n := tcp.get_available_bytes()
	if n <= 0:
		return
	var got := tcp.get_data(n)
	if got[0] != OK:
		return
	inbox += (got[1] as PackedByteArray).get_string_from_utf8()
	while inbox.contains("\n"):
		var cut := inbox.find("\n")
		var line := inbox.substr(0, cut)
		inbox = inbox.substr(cut + 1)
		var msg = JSON.parse_string(line)
		if msg is Dictionary:
			_on_message(msg)


func _on_message(msg: Dictionary) -> void:
	match msg.get("t", ""):
		"voice":
			speaking = bool(msg.get("speaking", false))
			level = float(msg.get("level", 0.0))
			busy_until = t + 1.0
		"ears":
			if msg.get("listening", false):
				_feel("surprised", 0.55, 0.9)
				_glance(Vector2.ZERO, 1.5)
		"action":
			var phase := str(msg.get("phase", ""))
			if phase == "started":
				_glance(GLANCE.get(str(msg.get("widget", "")), Vector2(0.6, 0)), 2.5)
			elif phase == "done":
				_feel("happy", 0.8, 1.4)
			elif phase == "failed":
				_feel("sad", 0.7, 2.2)
		"flow":
			if msg.get("phase", "") == "fired":
				_glance(GLANCE.get(str(msg.get("widget", "")), Vector2(0.4, 0.2)), 1.5)


func _feel(key: String, weight: float, seconds: float) -> void:
	for k in mood_target:
		mood_target[k] = 0.0
	mood_target[key] = weight
	mood_until = t + seconds
	busy_until = t + seconds + 0.5


func _glance(at: Vector2, seconds: float) -> void:
	look_target = at
	look_until = t + seconds
	busy_until = max(busy_until, t + seconds)


# --- every frame ------------------------------------------------------------
func _process(delta: float) -> void:
	t += delta
	_poll_core(delta)
	Engine.max_fps = FPS_BUSY if t < busy_until else FPS_IDLE

	# Blink every few seconds, quickly.
	if t >= next_blink:
		blink = 1.0
		next_blink = t + randf_range(2.2, 5.5)
	blink = max(0.0, blink - delta * 9.0)

	# Mouth follows her voice level, a little smoothed so it doesn't buzz.
	var want := clampf(level * 4.0, 0.0, 1.0) if speaking else 0.0
	mouth = lerpf(mouth, want, clampf(delta * 18.0, 0.0, 1.0))

	# Moods ease in and back out to the resting half-smile.
	if t > mood_until:
		for k in mood_target:
			mood_target[k] = 0.12 if k == "relaxed" else 0.0
	for k in mood:
		mood[k] = lerpf(mood[k], mood_target[k], clampf(delta * 6.0, 0.0, 1.0))

	if t > look_until:
		look_target = Vector2(sin(t * 0.21) * 0.25, sin(t * 0.13) * 0.1)   # idle wander
	look = look.lerp(look_target, clampf(delta * 4.0, 0.0, 1.0))

	_set_shape("blink", clampf(blink * 1.6, 0.0, 1.0) * (1.0 - mood["happy"]))
	_set_shape("aa", mouth)
	for k in ["happy", "sad", "angry", "surprised", "relaxed"]:
		_set_shape(k, mood[k])
	_pose()


func _pose() -> void:
	if not skel:
		return
	var breath := sin(t * 1.6)
	# Arms down from VRoid's T-pose, with a slight breathing lift.
	_turn("LeftUpperArm", Vector3(0, 0, 1), -1.3 + breath * 0.012)
	_turn("RightUpperArm", Vector3(0, 0, 1), 1.3 - breath * 0.012)
	_turn("LeftLowerArm", Vector3(0, 1, 0), 0.25)
	_turn("RightLowerArm", Vector3(0, 1, 0), -0.25)
	_turn("Chest", Vector3(1, 0, 0), breath * 0.018)
	_turn("Spine", Vector3(0, 0, 1), sin(t * 0.5) * 0.015)
	# Head and neck share the glance.
	_turn_xy("Neck", look * 0.4)
	_turn_xy("Head", look * 0.6)


# Rotate a bone about an axis given in the model's space, on top of its rest
# pose. Working from the rest pose keeps it independent of how the importer
# oriented each bone.
func _turn(bone: String, axis: Vector3, angle: float) -> void:
	if not bones.has(bone):
		return
	var i: int = bones[bone]
	var parent := skel.get_bone_parent(i)
	var parent_rest := skel.get_bone_global_rest(parent).basis if parent >= 0 else Basis()
	var global_rest := skel.get_bone_global_rest(i).basis
	var turned := Basis(axis.normalized(), angle) * global_rest
	skel.set_bone_pose_rotation(i, (parent_rest.inverse() * turned).get_rotation_quaternion())


func _turn_xy(bone: String, v: Vector2) -> void:
	if not bones.has(bone):
		return
	var i: int = bones[bone]
	var parent := skel.get_bone_parent(i)
	var parent_rest := skel.get_bone_global_rest(parent).basis if parent >= 0 else Basis()
	var global_rest := skel.get_bone_global_rest(i).basis
	var turned := Basis(Vector3.UP, v.x * 0.5) * Basis(Vector3.RIGHT, -v.y * 0.35) * global_rest
	skel.set_bone_pose_rotation(i, (parent_rest.inverse() * turned).get_rotation_quaternion())


# --- where she stands -------------------------------------------------------
# Under X11 (XWayland) a window may place itself; she starts where she was
# left, or on the ultrawide's left-centre the first time.
func _place() -> void:
	if snapshot_path != "":
		return
	var pos := Vector2i(-1, -1)
	var f := FileAccess.open(POS_FILE, FileAccess.READ)
	if f:
		var d = JSON.parse_string(f.get_as_text())
		if d is Dictionary:
			pos = Vector2i(int(d.get("x", -1)), int(d.get("y", -1)))
	if pos.x < 0:
		for s in DisplayServer.get_screen_count():
			var r := DisplayServer.screen_get_usable_rect(s)
			if r.size.x >= 3000:                 # the ultrawide
				pos = r.position + Vector2i(790, r.size.y - 600 - 260)
	if pos.x >= 0:
		DisplayServer.window_set_position(pos)
	# Only her body takes clicks; the rest of the window lets them through.
	DisplayServer.window_set_mouse_passthrough(PackedVector2Array([
		Vector2(125, 10), Vector2(295, 10), Vector2(320, 300), Vector2(300, 600),
		Vector2(120, 600), Vector2(100, 300)]))


func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		DisplayServer.window_start_drag()       # drag her anywhere
		_save_position.call_deferred()


func _save_position() -> void:
	await get_tree().create_timer(0.6).timeout
	var p := DisplayServer.window_get_position()
	var f := FileAccess.open(POS_FILE, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify({"x": p.x, "y": p.y}))


# --- setup helpers ----------------------------------------------------------
func _find_skeleton(n: Node) -> Skeleton3D:
	if n is Skeleton3D:
		return n
	for c in n.get_children():
		var s := _find_skeleton(c)
		if s:
			return s
	return null


func _find_shapes(n: Node, names: Array) -> Array:
	var found := []
	if n is MeshInstance3D and n.mesh:
		for name in names:
			var idx: int = n.find_blend_shape_by_name(name)
			if idx >= 0:
				found.append([n, idx])
				break
	for c in n.get_children():
		found.append_array(_find_shapes(c, names))
	return found


func _set_shape(key: String, w: float) -> void:
	for pair in shapes.get(key, []):
		(pair[0] as MeshInstance3D).set_blend_shape_value(pair[1], w)


# Frame head to waist, from the front, whichever way the importer faced her.
func _frame_camera() -> void:
	var cam := Camera3D.new()
	cam.fov = 28.0
	add_child(cam)
	var head := Vector3(0, 1.4, 0)
	var hips := Vector3(0, 0.9, 0)
	if skel and bones.has("Head"):
		head = skel.global_transform * skel.get_bone_global_rest(bones["Head"]).origin
		var h := skel.find_bone("Hips")
		if h >= 0:
			hips = skel.global_transform * skel.get_bone_global_rest(h).origin
	var centre := head.lerp(hips, 0.5) + Vector3(0, 0.06, 0)
	var facing := 1.0 if OS.get_environment("PET_FLIP") == "" else -1.0
	cam.position = centre + Vector3(0, 0.05, 2.05 * facing)
	cam.look_at(centre, Vector3.UP)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-35, 25 if facing > 0 else 205, 0)
	add_child(light)


func _snapshot() -> void:
	for i in 8:
		_process(0.05)
		await get_tree().process_frame
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png(snapshot_path)
	get_tree().quit()
