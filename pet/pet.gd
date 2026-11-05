extends Node3D
# Aries's body: she lives on the whole desktop. She walks along the bottom of
# the screen and the tops of the widgets, sits on their edges, dances when
# music plays, turns to watch the app she's working in, shapes her mouth to
# the vowels she's saying, and falls asleep when nothing has happened for a
# while. You can pick her up and drop her anywhere. She never decides what to
# do for you; the core does that. This is just her being around.
#
# The window covers the ultrawide but only her body takes clicks; it's
# transparent everywhere else. Rendering is cheap: one character, the mobile
# renderer, 30 fps while she moves and 15 at rest.

const PORT := 47120                       # the core's read-only localhost port
const MODEL := "res://models/aries.vrm"
const CLIPS := ["res://assets/anims/ual1.glb", "res://assets/anims/ual2.glb"]
var PPM := 300.0                          # screen pixels per metre (Avatar: size); she's ~470 px tall at 300
const WALK_SPEED := 0.55                  # metres per second
const GRAVITY := 9.0
const SIT_DROP := 0.47                    # seat height in the sitting clips
var SLEEP_AFTER := 480.0                  # seconds of nothing before she dozes (Avatar: sleep after)
const MAX_THROW := 14.0                   # m/s, so a flick can't send her into orbit
const HARD_LANDING := 5.5                 # m/s down: lands flat and dizzy instead of on her feet
var FPS_BUSY := 30                        # Avatar: frame rate cap; idle runs at half
var FPS_IDLE := 15
# What she may do (Avatar settings). Everything on unless he turns it off.
var allow := {"wander": true, "sit_on_widgets": true, "walk_off_edges": true, "dance_to_music": true,
	"nap": true, "seek_cursor": true, "react_to_work": true, "lip_sync": true}
var shown := true                          # Desktop: her body
var settings_mtime := 0
var settings_check := 0.0

const FACE := {   # VRoid face shapes
	"blink": "Fcl_EYE_Close", "joy": "Fcl_ALL_Joy", "sorrow": "Fcl_ALL_Sorrow",
	"angry": "Fcl_ALL_Angry", "surprised": "Fcl_ALL_Surprised", "fun": "Fcl_ALL_Fun",
	"a": "Fcl_MTH_A", "i": "Fcl_MTH_I", "u": "Fcl_MTH_U", "e": "Fcl_MTH_E", "o": "Fcl_MTH_O",
}
# Her voice's emotion marks (Cartesia's names) onto her face.
# She has only five faces (joy, sorrow, angry, surprised, fun), so each of the
# voice's ~60 emotion tags goes to the nearest of them.
const EMOTION_FACE := {
	"happy": "joy", "excited": "joy", "enthusiastic": "joy", "elated": "joy", "euphoric": "joy",
	"triumphant": "joy", "grateful": "joy", "affectionate": "joy", "proud": "joy", "confident": "joy",
	"flirtatious": "fun", "content": "fun", "peaceful": "fun", "serene": "fun", "calm": "fun",
	"sarcastic": "fun", "ironic": "fun", "mysterious": "fun", "nostalgic": "fun", "trust": "fun",
	"determined": "fun", "sympathetic": "fun",
	"amazed": "surprised", "surprised": "surprised", "curious": "surprised", "anticipation": "surprised",
	"confused": "surprised", "alarmed": "surprised", "panicked": "surprised", "scared": "surprised",
	"anxious": "surprised", "threatened": "surprised", "hesitant": "surprised", "insecure": "surprised",
	"angry": "angry", "mad": "angry", "outraged": "angry", "frustrated": "angry", "agitated": "angry",
	"disgusted": "angry", "contempt": "angry", "envious": "angry", "skeptical": "angry",
	"sad": "sorrow", "dejected": "sorrow", "melancholic": "sorrow", "disappointed": "sorrow",
	"hurt": "sorrow", "guilty": "sorrow", "rejected": "sorrow", "apologetic": "sorrow", "wistful": "sorrow",
	"resigned": "sorrow", "tired": "sorrow", "bored": "sorrow", "distant": "sorrow", "contemplative": "sorrow",
}
# Her avatar tool's looks (adapters/avatar.py) onto the same five.
# MMD-style English face shapes (the Jane Doe model): each face is a blend.
# Besides the five moods and the mouth, these models have accents the VRoid
# face lacks, so her looks and voice emotions get their own faces here.
const MMD_FACE := {
	"blink": {"Eye_Closed": 1.0},
	"joy": {"Eye_Joyful": 1.0, "Mouth_Smile": 0.8, "Eyebrow_Up": 0.3},
	"sorrow": {"Eyebrow_Sad": 1.0, "Eye_Inner_Up": 0.5, "Mouth_Sad": 0.8},
	"angry": {"Eyebrow_Angry": 1.0, "Eye_Sharp": 0.7, "Mouth_Narrow": 0.4},
	"surprised": {"Eyebrow_Surprised": 1.0, "Eye_Surprised": 1.0, "Pupil_Small": 0.5, "Mouth_O": 0.4},
	"fun": {"Eye_Calm": 0.35, "Mouth_Cat": 0.6},
	"hearts": {"Pupil_Heart": 1.0, "Mouth_Smile": 0.6, "Blush": 0.6},
	"blush": {"Blush": 1.0, "Eye_Calm": 0.3, "Mouth_Smile": 0.4, "Eyebrow_Sad": 0.2},
	"smirk": {"Mouth_Smile.L": 1.0, "Mouth_Turn.L": 0.5, "Eye_Sharp": 0.4, "Eyebrow_Up": 0.3},
	"tears": {"Tear": 1.0, "Tear2": 1.0, "Eyebrow_Sad": 1.0, "Mouth_Sad": 0.8, "Eye_Inner_Up": 0.5},
	"gloom": {"Pale": 1.0, "Eyebrow_Sad": 0.6, "Eye_Bored": 0.6, "Pupil_Small": 0.4},
	"sleepy": {"Eye_Closed": 0.55, "Eyebrow_Down": 0.3, "Mouth_NN": 0.3},
	"thoughtful": {"Eye_Calm": 0.5, "Eyebrow_Close": 0.4, "Mouth_Narrow": 0.3, "Mouth_Move_Left": 0.3},
	"bored": {"Eye_Bored": 1.0, "Mouth_NN": 0.4},
	"dizzy": {"Pupil_HL_Off": 1.0, "Pupil_Small": 0.7, "Eye_Surprised": 0.6, "Eyebrow_Sad": 0.5, "Sweat1": 1.0,
			"Sweat2": 1.0, "Mouth_Wide": 0.4},
	"stars": {"Eye_Joyful": 0.5, "Pupil_Large": 0.6, "Mouth_Joyful": 0.8},
	"sweat": {"Sweat1": 1.0, "Eyebrow_Sad": 0.4, "Mouth_Narrow": 0.2},
	"a": {"Mouth_A": 1.0}, "i": {"Mouth_I": 1.0}, "u": {"Mouth_U": 1.0}, "e": {"Mouth_E": 1.0}, "o": {"Mouth_O": 1.0},
}
const MMD_LOOK := {"stars": "stars", "hearts": "hearts", "blush": "blush", "smirk": "smirk", "tears": "tears",
		"gloom": "gloom", "sleepy": "sleepy", "thoughtful": "thoughtful", "eyeroll": "bored", "dizzy": "dizzy"}
const MMD_EMOTION := {"affectionate": "hearts", "flirtatious": "smirk", "embarrassed": "blush", "shy": "blush",
		"sarcastic": "smirk", "ironic": "smirk", "bored": "bored", "tired": "sleepy", "contemplative": "thoughtful",
		"anxious": "sweat", "nervous": "sweat", "confused": "dizzy", "euphoric": "stars", "excited": "stars",
		"hurt": "tears", "melancholic": "gloom", "dejected": "gloom"}
const MOUTH_KEYS := ["blink", "a", "i", "u", "e", "o"]
const LOOK_FACE := {
	"smile": "joy", "stars": "joy", "hearts": "joy", "blush": "fun", "soft": "fun", "smirk": "fun",
	"angry": "angry", "tears": "sorrow", "gloom": "sorrow", "sleepy": "sorrow", "thoughtful": "sorrow",
	"eyeroll": "angry", "wide": "surprised", "dizzy": "surprised", "blood": "sorrow",
}
const BODY_FILE := "/.local/share/ariadne2/pet/body.json"

var tcp := StreamPeerTCP.new()
# The pointer anywhere on screen, relayed by the Live2D host from KWin
# (ariadne2/pet2d kwin_gaze.js): her window only hears it over herself.
const GAZE_UDP := 47121
var gaze_in := PacketPeerUDP.new()
var cursor := Vector2.ZERO
var cursor_at := -99.0
var cursor_dx := 0.0                       # the pointer's last sideways move, for wiggles
var wiggles: Array[float] = []             # when it doubled back near her
var noticed_at := -99.0
var clicks: Array[float] = []
var inbox := ""
var retry_in := 0.0
var said_hello := false

var body: Node3D
var skel: Skeleton3D
var ap: AnimationPlayer
var face := {}                            # key -> [[mesh, index, weight], ...]
var face_slots := {}                      # [mesh, index] -> this frame's summed weight
var body_path := ""                       # the model she's wearing (res://models/...)
var outfit := {"jacket": true, "weapon": false}   # Avatar settings: jacket on, weapon in hand
var weapon: Node3D
var fill: WorldEnvironment                # ambient light for GLB bodies (_toonify)
var clip_lib: AnimationLibrary            # the humanoid clips, shared by every body
var bones := {}
var cam: Camera3D
var screen := Vector2(3440, 1366)

# Where she is (metres, origin bottom-left of the window) and what she's doing.
var pos := Vector2(3.0, 0.0)
# The room (docs/PET_AI_PLAN.md): the desk floor runs back from the screen
# into the room, room_depth metres (Avatar: room depth, in feet). depth is how
# far back she is, 0 at the front plane where the widgets' ledges are, down
# to -room_depth. target_z is where she's headed in it.
var depth := 0.0
var target_z := 0.0
var jump_dz := 0.0                         # forward speed of a jump onto a ledge
var room_depth := 2.44
const CAM_DIST := 5.0                      # metres from the front plane: how strongly the room recedes
var shadow: MeshInstance3D
var vel := Vector2.ZERO
var floor_y := 0.0
var floor_span := Vector2(0, 11.4)        # x range of the surface she's on
var state := "idle"                        # idle wander sit dance sleep fall held react
var state_until := 0.0
var target_x := 0.0
var yaw := 0.0
var yaw_target := 0.0
var clip := ""
var floors := []                           # [y, x0, x1] in metres
var layout_mtime := 0
var layout_check := 0.0

var t := 0.0
var last_activity := 0.0
var next_blink := 2.0
var blink := 0.0
var moods := {"joy": 0.0, "sorrow": 0.0, "angry": 0.0, "surprised": 0.0, "fun": 0.1}
var mood_target := {}
var mood_until := 0.0
var look := Vector2.ZERO
var look_target := Vector2.ZERO
var look_until := 0.0
var spotify_playing := false
var last_song := ""
var on_name := "floor"                     # the widget she's standing on, for her avatar tool
var told_in := 1.0
var widget_x := {}                         # widget -> centre x (m), from the layout

# Speech: sentences queued with their length; vowels stepped through in time.
var speech := []                           # [{text, seconds, emotion}]
var speech_at := 0.0
var speech_on: Dictionary = {}
var level := 0.0
var speaking := false
var mouth := {"a": 0.0, "i": 0.0, "u": 0.0, "e": 0.0, "o": 0.0}

var roll := 0.0                           # her tilt while flying or dangling
var spin := 0.0
var held_vel := Vector2.ZERO
var slab: Node3D                           # the glowing 'window' she holds while working
var slab_widget := ""
var slab_sending := false
var slab_mat: StandardMaterial3D
var slab_label: Label3D
var carry_pose := {}                       # arm bones -> rotation, sampled from Walk_Carry
var crumbs: CPUParticles3D
var life                                   # life.gd: needs, items, dropped files
var brain                                  # brain.gd: what she does with her time
var room                                   # room.gd: her furniture
var places                                 # places.gd: the ways she can be at it (states.json)
var play                                   # play.gd: her interactions (play.json)
var pressing := false                      # his button down on her
var press_at := 0.0
var shakes := 0                            # back-and-forths while he dangles her
var brain_quiet := false
var pstate := ""                           # the one she's in (Bed_SitEdge ...), "" on her feet
var furniture := false                     # Avatar setting (off: her room is an empty stage)
var in_front := false                      # Avatar setting: drawn over the widgets, not behind them
var lift := 0.0                            # raised onto furniture (a cushion, the bed), metres
var perched := ""                          # the furniture spot her body's on, or ""
var perch := {}                            # moving onto or off it: from, to (x, lift, depth), t0, dur, yaw
var drag_from := Vector2.ZERO
var drag_moved := false
# Picked up by where he clicked: the bone under the pointer and the point on it
# (in its own space), the arm or leg that point is on (pulled up over her as she
# hangs from it), and a pendulum swing about it.
var grab_bone := -1
var grab_local := Vector3.ZERO
var grab_b := Vector3(0, 1.3, 0)            # that point, in her body's space
var grab_chain: Array = []                 # [bone, child] pairs aimed up
var grab_at := Vector2.ZERO                # the pointer, while he holds her
var grab_prev := Vector2.ZERO
var grab_k := 0.0                          # 0..1, eases the limb up
var held_w := 0.0                          # swing speed, rad/s
var last_rect := Rect2()
var snapshot_path := OS.get_environment("PET_SNAPSHOT")


func _ready() -> void:
	get_viewport().transparent_bg = true
	get_window().title = "ariadne2-pet"      # KWin finds her by this (desk/kwin_layer.js)
	_cover_ultrawide()
	# PET_MODEL picks the 3D body for a test run (PET_SNAPSHOT); otherwise
	# the Avatar "Model" setting does (_read_settings), Aries until it's read.
	var forced := OS.get_environment("PET_MODEL")
	var dressed := OS.get_environment("PET_OUTFIT")          # a test shot's outfit: "nojacket,weapon"
	if dressed != "":
		outfit = {"jacket": not dressed.contains("nojacket"), "weapon": dressed.contains("weapon")}
	_load_body(forced if forced != "" else MODEL)
	for k in moods:
		mood_target[k] = moods[k]
	_make_slab()
	_camera()
	life = load("res://life.gd").new()
	add_child(life)
	life.setup(self)
	brain = load("res://brain.gd").new(self)
	room = load("res://room.gd").new()
	add_child(room)
	room.setup(self)
	room.visible = furniture                  # off unless his Avatar setting turns it on
	places = load("res://places.gd").new(self)
	play = load("res://play.gd").new()
	add_child(play)
	play.setup(self)
	_read_layout()
	pos = Vector2(screen.x / PPM * 0.3, 0.0)
	_land()
	_play("Idle")
	if snapshot_path != "":
		_snapshot.call_deferred()
	else:
		gaze_in.bind(GAZE_UDP, "127.0.0.1")
		_connect()


# --- which body ---------------------------------------------------------------
# A 3D model in models/: aries.vrm, or a GLB imported with the humanoid bone
# map (models/jane.glb + jane_bonemap.tres; docs/JANE_3D_PLAN.md). The Avatar
# "Model" setting names it ("aries", or "3d:<file stem>"); a change swaps
# bodies while she runs.
func _model_path(setting: String) -> String:
	if setting == "aries":
		return MODEL
	if setting.begins_with("3d:"):
		return "res://models/%s.glb" % setting.substr(3)
	return ""


func _load_body(path: String) -> void:
	if body:
		body.free()                        # its AnimationPlayer goes with it
	body = (load(path) as PackedScene).instantiate()
	add_child(body)
	body_path = path
	skel = _find(body, "Skeleton3D")
	# MMD-style bodies tuck the skin in under clothes with "Shrink_for..." shapes.
	for m in body.find_children("*", "MeshInstance3D", true, false):
		for i in (m as MeshInstance3D).mesh.get_blend_shape_count() if (m as MeshInstance3D).mesh else 0:
			if String((m as MeshInstance3D).mesh.get_blend_shape_name(i)).begins_with("Shrink_for"):
				(m as MeshInstance3D).set_blend_shape_value(i, 1.0)
	# Which face set: MMD-style names if it has them, else VRoid's. Each key ->
	# [[mesh, index, weight], ...]; every slot is written every frame (_face_apply).
	var mmd := not _find_shapes(body, "Eye_Joyful").is_empty()
	var map: Dictionary = MMD_FACE if mmd else FACE
	face = {}
	face_slots = {}
	for key in map:
		var blend: Dictionary = map[key] if map[key] is Dictionary else {map[key]: 1.0}
		face[key] = []
		for shape in blend:
			for pair in _find_shapes(body, shape):
				face[key].append([pair[0], pair[1], blend[shape]])
				face_slots[[pair[0], pair[1]]] = 0.0
		if key not in MOUTH_KEYS and not moods.has(key):
			moods[key] = 0.0
			mood_target[key] = 0.0
	bones = {}
	for b in ["Neck", "Head", "Hips"]:
		var i := skel.find_bone(b)
		if i >= 0:
			bones[b] = i
	_load_clips()
	_measure_legs()
	carry_pose = {}
	_sample_carry_pose()
	clip = ""
	body.visible = shown
	# A VRM brings its own toon shader (MToon); a GLB body gets one here, and a
	# flat fill light so its shade side isn't black.
	var glb := path.ends_with(".glb")
	if glb:
		_toonify(body)
	_add_jiggle()
	if fill:
		fill.environment.ambient_light_energy = TOON_FILL if glb else 0.0
	weapon = null                              # went with the old body
	_dress()


# Jacket and weapon (Avatar settings), for bodies that have them. Without
# the jacket, the top it was squeezing ("Shrink_forJacket") fills out again.
# The weapon is <model>_weapon.glb (pet/import/jane_export.py), gripped in
# her right hand.
var WEAPON_GRIP := Transform3D(Basis.from_euler(Vector3(0, 0, -PI / 2)), Vector3(0.0, 0.07, 0.02))
func _dress() -> void:
	if not body:
		return
	var jacket: Node = body.find_child("Jacket", true, false)
	if jacket:
		jacket.visible = outfit["jacket"]
	for m in body.find_children("*", "MeshInstance3D", true, false):
		var idx := (m as MeshInstance3D).find_blend_shape_by_name("Shrink_forJacket")
		if idx >= 0:
			(m as MeshInstance3D).set_blend_shape_value(idx, 1.0 if outfit["jacket"] else 0.0)
	var wpath := body_path.replace(".glb", "_weapon.glb")
	if outfit["weapon"] and weapon == null and body_path.ends_with(".glb") and ResourceLoader.exists(wpath) \
			and skel and skel.find_bone("RightHand") >= 0:
		var hold := BoneAttachment3D.new()
		hold.bone_name = "RightHand"
		skel.add_child(hold)
		weapon = (load(wpath) as PackedScene).instantiate()
		weapon.transform = WEAPON_GRIP
		hold.add_child(weapon)
		_toonify(weapon)
	elif not outfit["weapon"] and weapon != null:
		weapon.get_parent().queue_free()
		weapon = null


# --- secondary motion ----------------------------------------------------------
# Spring bones (Godot's SpringBoneSimulator3D) on whatever of these chains the
# model has: [root, end, stiffness, drag, gravity, radius]. root == end is a
# single bone, extended. Missing bones are skipped, so any rig works.
const JIGGLE := [
	["Tail_0", "Tail_7", 0.35, 0.22, 0.55, 0.045],           # the dragon: loose and heavy, lies on the floor and drags
	["Hair_Ponytail_1", "Hair_Ponytail_5", 0.7, 0.35, 0.35, 0.02],
	["Hair_Ponytail_B_1", "Hair_Ponytail_B_2", 0.8, 0.4, 0.35, 0.015],
	["Hair_Ponytail_C_1", "Hair_Ponytail_C_4", 0.7, 0.35, 0.35, 0.015],
	["Hair_Back_C_1.L", "Hair_Back_C_2.L", 0.9, 0.45, 0.3, 0.015], ["Hair_Back_C_1.R", "Hair_Back_C_2.R", 0.9, 0.45, 0.3, 0.015],
	["Hair_Back_E_1.L", "Hair_Back_E_2.L", 0.9, 0.45, 0.3, 0.015], ["Hair_Back_E_1.R", "Hair_Back_E_2.R", 0.9, 0.45, 0.3, 0.015],
	["Hair_Side_1.L", "Hair_Side_2.L", 1.0, 0.45, 0.25, 0.015], ["Hair_Side_1.R", "Hair_Side_2.R", 1.0, 0.45, 0.25, 0.015],
	["Hair_Bangs_Side_1.L", "Hair_Bangs_Side_2.L", 1.4, 0.5, 0.15, 0.01], ["Hair_Bangs_Side_1.R", "Hair_Bangs_Side_2.R", 1.4, 0.5, 0.15, 0.01],
	["Hair_Back_A.C", "Hair_Back_A.C", 1.2, 0.45, 0.2, 0.015], ["Hair_Back_B.L", "Hair_Back_B.L", 1.2, 0.45, 0.2, 0.015],
	["Hair_Back_B.R", "Hair_Back_B.R", 1.2, 0.45, 0.2, 0.015], ["Hair_Back_D.L", "Hair_Back_D.L", 1.2, 0.45, 0.2, 0.015],
	["Hair_Back_D.R", "Hair_Back_D.R", 1.2, 0.45, 0.2, 0.015], ["Hair_Back_F.L", "Hair_Back_F.L", 1.2, 0.45, 0.2, 0.015],
	["Hair_Back_F.R", "Hair_Back_F.R", 1.2, 0.45, 0.2, 0.015],
	["Ear.L", "Ear.L", 0.8, 0.22, 0.04, 0.01], ["Ear.R", "Ear.R", 0.8, 0.22, 0.04, 0.01],     # soft: they wobble after a flick
	["Breast_1.L", "Breast_2.L", 4.0, 0.55, 0.0, 0.03], ["Breast_1.R", "Breast_2.R", 4.0, 0.55, 0.0, 0.03],
	["Butt.L", "Butt.L", 4.0, 0.55, 0.0, 0.03], ["Butt.R", "Butt.R", 4.0, 0.55, 0.0, 0.03],      # firm: a bounce, not a swing
	["JacketBelt_1.L", "JacketBelt_3.L", 0.6, 0.4, 0.6, 0.01], ["JacketBelt_1.R", "JacketBelt_3.R", 0.6, 0.4, 0.6, 0.01],
	["Necktie_1", "Necktie_3", 0.8, 0.4, 0.5, 0.012],
	["WaistBag", "WaistBag_Zipper", 1.2, 0.4, 0.5, 0.02],
	["Shoe_A_1.L", "Shoe_A_2.L", 0.7, 0.4, 0.7, 0.008], ["Shoe_A_1.R", "Shoe_A_2.R", 0.7, 0.4, 0.7, 0.008],
	["Shoe_B_1.L", "Shoe_B_2.L", 0.7, 0.4, 0.7, 0.008], ["Shoe_B_1.R", "Shoe_B_2.R", 0.7, 0.4, 0.7, 0.008],
]
# What hair and tail bump against, so they never pass through her: [humanoid
# bone, radius m, capsule along the bone to its child (true) or a ball].
const JIGGLE_COLLIDE := [["Head", 0.1, false], ["Neck", 0.055, true], ["UpperChest", 0.12, false],
		["Chest", 0.12, false], ["Spine", 0.11, false], ["Hips", 0.13, false],
		["LeftShoulder", 0.05, true], ["RightShoulder", 0.05, true],
		["LeftUpperArm", 0.045, true], ["RightUpperArm", 0.045, true],
		["LeftLowerArm", 0.04, true], ["RightLowerArm", 0.04, true], ["LeftHand", 0.04, false], ["RightHand", 0.04, false],
		["LeftUpperLeg", 0.075, true], ["RightUpperLeg", 0.075, true],
		# her boots: fat shins, and the feet as capsules out to the toes
		["LeftLowerLeg", 0.08, true], ["RightLowerLeg", 0.08, true], ["LeftFoot", 0.075, true], ["RightFoot", 0.075, true],
		["LeftToes", 0.06, false], ["RightToes", 0.06, false]]
var tail_x := 0.0
var tail_feet := 9.0
var tail_low: Array = []                   # a test run's lowest tail and hair joints, after the springs
var floor_plane: SpringBoneCollisionPlane3D   # the ground under her, for her tail (and her hair, lying down)
var jiggle: SpringBoneSimulator3D
var jiggle_at := Vector3.ZERO              # where her body was last frame: a jump is a teleport
var tail_bones: Array[int] = []
var tail_chain := -1                       # the tail's spring setting (its gravity drops while it's up)
var tail_up := 0.0                         # 0 lying on the floor, 1 raised
# Each segment's bend when raised (radians, + is up: a turn about her right
# side bends the tail down for minus, up for plus): up and back, tip curling over.
const TAIL_UP := [0.7, 0.35, 0.15, 0.0, -0.1, -0.15, -0.2, -0.2]
# The second spring: raising (about 0.4 Hz, a ~10% overshoot) and her body's
# motion swinging it (about 1.2 Hz, bouncier), spread down the tail by SWING_FALL.
const TAIL_K_UP := 6.0                     # about a second to rise, a small overshoot
const TAIL_C_UP := 2.6
const TAIL_K_SWING := 55.0
const TAIL_C_SWING := 4.0
const SWING_FALL := [1.0, 0.75, 0.55, 0.4, 0.3, 0.2, 0.15, 0.1]
var tail_up_v := 0.0
var wrap_k := 0.0                          # 1 wrapped round to her side (sitting, lying)
var tail_swing := Vector2.ZERO             # (sideways, down) radians, from her body's motion
var tail_swing_v := Vector2.ZERO
var tail_body_was := Vector3.ZERO
var ear_bones: Array = []                  # [bone, rest rotation] left, right
var ear_flick_at := [-9.0, -9.0]
var ear_next := [3.0, 5.0]
var walk_mix := 0.0                        # how much her stride (not the idle sway) is swinging her tail
var walk_wag := 0.0                        # +1 left foot ahead, -1 right foot ahead
var feet_were := 0.0
const WAG_SIDE := -1.0                     # away from the leading foot (measured: tail vs feet correlate -0.55; her pelvis alone gives +0.6)
var tail_rest: Array[Quaternion] = []


func _add_jiggle() -> void:
	var have := func(b: String) -> bool: return skel.find_bone(b) >= 0
	var chains := JIGGLE.filter(func(c): return have.call(c[0]) and have.call(c[1]))
	jiggle = null
	tail_bones.clear()
	tail_rest.clear()
	if chains.is_empty():
		return
	var sim := SpringBoneSimulator3D.new()
	jiggle = sim
	sim.name = "Jiggle"
	skel.add_child(sim)
	sim.set_setting_count(chains.size())
	for i in chains.size():
		var c: Array = chains[i]
		sim.set_root_bone_name(i, c[0])
		sim.set_end_bone_name(i, c[1])
		sim.set_extend_end_bone(i, true)
		sim.set_end_bone_length(i, 0.05)
		sim.set_stiffness(i, c[2])
		sim.set_drag(i, c[3])
		sim.set_gravity(i, c[4])
		sim.set_radius(i, c[5])
	for c in JIGGLE_COLLIDE:
		if not have.call(c[0]):
			continue
		var b := skel.find_bone(c[0])
		var kids := skel.get_bone_children(b)
		if c[2] and not kids.is_empty():
			# A capsule from this joint to the next, however the bone points.
			var along: Vector3 = skel.get_bone_rest(kids[0]).origin
			var cap := SpringBoneCollisionCapsule3D.new()
			cap.bone_name = c[0]
			cap.radius = c[1]
			cap.height = along.length() + 2.0 * float(c[1])
			cap.position_offset = along / 2.0
			cap.rotation_offset = Quaternion(Vector3.UP, along.normalized())
			sim.add_child(cap)
		else:
			var col := SpringBoneCollisionSphere3D.new()
			col.bone_name = c[0]
			col.radius = c[1]
			sim.add_child(col)
	floor_plane = SpringBoneCollisionPlane3D.new()
	sim.add_child(floor_plane)
	# Only hair and tail bump into her; a chain that sits on the body (chest,
	# hips, belts) would be pushed out by the very sphere it rests on.
	for i in chains.size():
		var root: String = chains[i][0]
		sim.set_enable_all_child_collisions(i, root.begins_with("Hair") or root.begins_with("Tail"))
	tail_chain = -1
	for i in chains.size():
		if chains[i][0] == "Tail_0":
			tail_chain = i
	ear_bones.clear()
	for e in ["Ear.L", "Ear.R"]:
		var eb := skel.find_bone(e)
		if eb >= 0:
			ear_bones.append([eb, skel.get_bone_rest(eb).basis.get_rotation_quaternion()])
	for i in 8:
		var b := skel.find_bone("Tail_%d" % i)
		if b < 0:
			break
		tail_bones.append(b)
		tail_rest.append(skel.get_bone_rest(b).basis.get_rotation_quaternion())


# The dragon tail: each frame its segments are given a lazy S-curl and the
# root a slow sway; the springs (low drag) make every segment trail the one
# before it, so the sway travels down the tail as a wave. Livelier when she's
# busy or happy, a slow drift when she sleeps.
func _tail_frame() -> void:
	# Teleported (placed on a widget, dropped in by a test shot)? The springs
	# start from rest instead of flinging everything across the screen.
	if jiggle and body.global_position.distance_to(jiggle_at) > 0.5:
		jiggle.reset()
	if body:
		jiggle_at = body.global_position
	if floor_plane:
		# The ground she's on (the room's floor, the bed, the cushion); on a
		# widget's edge there's nothing below, so her tail hangs free.
		var ground := pos.y + lift if floor_y < 0.01 and state not in ["held", "fall"] else -100.0
		if state in ["held", "fall"]:
			ground = 0.0                       # dangling or flying: only the room's floor
		floor_plane.global_transform = Transform3D(Basis.IDENTITY, Vector3(body.global_position.x, ground, body.global_position.z))
	var happy := clampf((_feeling("joy") - 0.3) / 1.2, 0.0, 1.0) if state != "sleep" else 0.0
	_ear_frame(happy)
	if tail_bones.is_empty():
		return
	var pace := 0.6 if state == "sleep" else (1.8 if state in ["dance", "held", "fall", "react"] else 1.0)
	# Happy, it swishes wider and quicker.
	var amp := 0.35 + 0.5 * happy
	var speed := 1.3 + 1.8 * happy
	# Walking, its root swings to the side away from the leg stepping forward
	# (left foot ahead, tail to her right), in time with her stride.
	var walking := state in ["wander", "stopping"] and (gait_velocity.has(variant) or variant.begins_with("stop_"))
	walk_mix = lerpf(walk_mix, 1.0 if walking else 0.0, 0.12)
	var ahead := 0.0
	if walking and leg_length > 0.1:
		var inv := body.global_transform.affine_inverse()
		var lf := inv * (skel.global_transform * skel.get_bone_global_pose(skel.find_bone("LeftFoot")).origin)
		var rf := inv * (skel.global_transform * skel.get_bone_global_pose(skel.find_bone("RightFoot")).origin)
		ahead = clampf((lf.z - rf.z) / (leg_length * 0.5), -1.0, 1.0)
	# Led a little (where her feet are heading): the springy tail lags its root.
	var lead := clampf(ahead + (ahead - feet_were) * 3.0, -1.2, 1.2) if walking else 0.0
	feet_were = ahead
	walk_wag = lerpf(walk_wag, lead, 0.35)
	# Up while she's doing anything (walking, playing, dancing, reacting): it
	# arcs up off the floor, light. Idling, resting or asleep it eases down
	# and lies heavy along the ground, the floor plane under it.
	var relaxed := state in ["idle", "rest", "sleep", "sit"] and not speaking
	var dt := clampf(get_process_delta_time(), 0.001, 0.1)
	# A second spring under the springy bones: underdamped, so it overshoots.
	# Up it springs and bounces, down it flops; and her body's own motion
	# (setting off, stopping, turning, a jump) throws it, and it rebounds.
	tail_up_v += ((0.0 if relaxed else 1.0) - tail_up) * TAIL_K_UP * dt - tail_up_v * TAIL_C_UP * dt
	tail_up = clampf(tail_up + tail_up_v * dt, -0.1, 1.3)
	var moved := body.global_position - tail_body_was
	tail_body_was = body.global_position
	if moved.length() > 0.5:
		moved = Vector3.ZERO                   # a teleport, not motion
	var v := body.global_transform.basis.inverse() * (moved / dt)
	var goal := Vector2(clampf(-v.x * 0.5, -0.7, 0.7), clampf(-v.z * 0.35 - v.y * 0.25, -0.6, 0.6))
	tail_swing_v += (goal - tail_swing) * TAIL_K_SWING * dt - tail_swing_v * TAIL_C_SWING * dt
	tail_swing += tail_swing_v * dt
	var up_k := clampf(tail_up, 0.0, 1.0)
	wrap_k = lerpf(wrap_k, 1.0 if state in ["rest", "sit", "sleep"] else 0.0, 0.03)
	if jiggle and tail_chain >= 0:
		jiggle.set_gravity(tail_chain, lerpf(0.55, 0.08, up_k))
		jiggle.set_stiffness(tail_chain, lerpf(0.42, 0.6, up_k))       # held up loosely: its own springs keep moving
	var lift_k := 0.25 if state in ["sit", "sleep", "rest"] else 1.0
	for i in tail_bones.size():
		# (lying, a slight downward bend: it rests on the floor)
		# (the root angled back a little first, so it meets the floor clear of her heels)
		var down := (0.12 + 0.05 * sin(t * 0.7 * pace - i * 0.9)) * lift_k * (1.0 if i < 3 else 0.35) \
				+ float([-0.3, -0.12, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0][mini(i, 7)])
		var up: float = TAIL_UP[mini(i, TAIL_UP.size() - 1)] + 0.07 * sin(t * 0.9 * pace - i * 0.9)   # up and back, tip curling over
		var curl: float = lerpf(down, -up, tail_up) + tail_swing.y * SWING_FALL[mini(i, 7)]
		var side := (amp if i == 0 else 0.05 + 0.05 * happy) * sin(t * speed * pace - i * 0.6)
		if i < 3:
			# strong enough to beat her pelvis's own twist, which carries the root toward the stepping leg
			side = lerpf(side, WAG_SIDE * walk_wag * (0.8 + 0.3 * happy) * [1.0, 0.6, 0.35][i], walk_mix)
		side += tail_swing.x * float(SWING_FALL[mini(i, 7)])
		# Sitting or lying down it wraps round to her side, like a cat's, not
		# under her legs where her feet would press it into the floor.
		side += wrap_k * (1.0 - clampf(tail_up, 0.0, 1.0)) * float(SWING_FALL[mini(i, 7)]) * 0.9
		var q := Quaternion(Vector3.RIGHT, -curl) * Quaternion(Vector3.FORWARD, side)
		skel.set_bone_pose_rotation(tail_bones[i], tail_rest[i] * q)


# Her ears flick: often when she's happy (now one, now both), once in a while
# otherwise. A quick perk upward and back (her ears point out to the sides:
# a turn about forward lifts the left tip for minus, the right for plus); the
# soft springs add the wobble after.
const EAR_FLICK := 0.6
func _ear_frame(happy: float) -> void:
	if ear_bones.size() < 2:
		return
	for e in 2:
		if t > ear_next[e] and state != "sleep":
			ear_flick_at[e] = t
			ear_next[e] = t + (randf_range(0.5, 2.0) / (0.5 + happy) if happy > 0.25 else randf_range(6.0, 15.0))
			if randf() < 0.35:                 # both together
				ear_flick_at[1 - e] = t
				ear_next[1 - e] = maxf(ear_next[1 - e], t + 0.5)
		var u: float = (t - float(ear_flick_at[e])) / 0.16
		var a := sin(PI * u) * EAR_FLICK * (0.6 + 0.4 * happy) if u >= 0.0 and u < 1.0 else 0.0
		skel.set_bone_pose_rotation(ear_bones[e][0], (ear_bones[e][1] as Quaternion) * Quaternion(Vector3.FORWARD, a * (-1.0 if e == 0 else 1.0)))


# Anime look for GLB bodies: two-tone lighting, a soft rim, no gloss, both
# sides of thin cloth drawn, and a thin dark outline (an inverted-hull pass).
const TOON_FILL := 0.35
const OUTLINE_M := 0.0016                   # outline thickness, metres
func _toonify(root: Node) -> void:
	for n in root.find_children("*", "MeshInstance3D", true, false):
		var mi := n as MeshInstance3D
		if not mi.mesh:
			continue
		for i in mi.mesh.get_surface_count():
			var src := mi.get_active_material(i) as StandardMaterial3D
			if src == null:
				continue
			var m := src.duplicate() as StandardMaterial3D
			m.diffuse_mode = BaseMaterial3D.DIFFUSE_TOON
			m.specular_mode = BaseMaterial3D.SPECULAR_DISABLED
			m.metallic = 0.0
			m.roughness = 1.0
			var skin := \
					String(src.resource_name).begins_with("Body") or String(src.resource_name).begins_with("Face")
			m.cull_mode = BaseMaterial3D.CULL_BACK if skin else BaseMaterial3D.CULL_DISABLED
			m.rim_enabled = not skin
			m.rim = 0.25
			m.rim_tint = 0.6
			var line := StandardMaterial3D.new()
			line.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
			line.albedo_color = Color(0.13, 0.09, 0.12)
			line.cull_mode = BaseMaterial3D.CULL_FRONT
			line.grow = true
			line.grow_amount = OUTLINE_M
			if m.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR:
				line.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
				line.alpha_scissor_threshold = m.alpha_scissor_threshold
				line.albedo_texture = m.albedo_texture
				line.albedo_color = Color(0.13, 0.09, 0.12, 1.0)
			m.next_pass = line
			mi.set_surface_override_material(i, m)


# --- window and camera ------------------------------------------------------
# Her window covers the biggest screen's usable area (KWin pins it there too,
# desk/kwin_layer.js). Any size: this once only did it for a 3000 px+
# ultrawide, so on an ordinary monitor she stood outside her own 420 px window.
func _cover_ultrawide() -> void:
	if snapshot_path != "":
		get_window().size = Vector2i(1500, 700)
		return
	var best := Rect2i()
	for s in DisplayServer.get_screen_count():
		var r := DisplayServer.screen_get_usable_rect(s)
		if r.size.x * r.size.y > best.size.x * best.size.y:
			best = r
	if best.size.x > 0:
		screen = Vector2(best.size)
		get_window().position = best.position
		get_window().size = best.size


# Perspective, looking straight into the room from CAM_DIST in front of the
# screen: the front plane (depth 0) shows at exactly PPM pixels a metre, as the
# flat camera had it, so ledges, clicks and the cursor line up; further back
# she's smaller.
func _frame_camera() -> void:
	if not cam:
		return
	var h := screen.y / PPM
	cam.projection = Camera3D.PROJECTION_PERSPECTIVE
	cam.keep_aspect = Camera3D.KEEP_HEIGHT
	cam.fov = rad_to_deg(2.0 * atan(h / 2.0 / CAM_DIST))
	cam.position = Vector3(screen.x / PPM / 2.0, h / 2.0, CAM_DIST)


# A soft round shadow on the floor under her, so the depth reads.
func _make_shadow() -> void:
	shadow = MeshInstance3D.new()
	var quad := QuadMesh.new()
	quad.size = Vector2(0.7, 0.45)
	quad.orientation = PlaneMesh.FACE_Y
	shadow.mesh = quad
	var img := Image.create(64, 64, false, Image.FORMAT_RGBA8)
	for y in 64:
		for x in 64:
			var r := Vector2(x - 31.5, y - 31.5).length() / 31.5
			img.set_pixel(x, y, Color(0, 0, 0, 0.45 * clampf(1.0 - r * r, 0.0, 1.0)))
	var mat := StandardMaterial3D.new()
	mat.albedo_texture = ImageTexture.create_from_image(img)
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	shadow.material_override = mat
	add_child(shadow)


func _camera() -> void:
	cam = Camera3D.new()
	cam.near = 0.05
	cam.far = 60.0
	add_child(cam)
	_frame_camera()
	_make_shadow()
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-30, 20, 0)
	light.light_energy = 1.1
	add_child(light)
	# Ambient fill, on only for bodies without their own toon shader (_load_body).
	fill = WorldEnvironment.new()
	fill.environment = Environment.new()
	fill.environment.background_mode = Environment.BG_CLEAR_COLOR
	fill.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	fill.environment.ambient_light_color = Color(1.0, 0.96, 0.98)
	fill.environment.ambient_light_energy = TOON_FILL if body_path.ends_with(".glb") else 0.0
	add_child(fill)


# --- the surfaces she can stand on ------------------------------------------
# The bottom of the screen, plus the top edge of every visible widget, read
# straight from the desk's saved layout.
func _read_layout() -> void:
	floors = [[0.0, 0.0, screen.x / PPM]]
	widget_x.clear()
	var path := OS.get_environment("HOME") + "/.config/ariadne2/layout.json"
	var f := FileAccess.open(path, FileAccess.READ)
	if not f:
		return
	layout_mtime = FileAccess.get_modified_time(path)
	var d = JSON.parse_string(f.get_as_text())
	var hidden := []
	var hf := FileAccess.open(OS.get_environment("HOME") + "/.config/ariadne2/hidden.json", FileAccess.READ)
	if hf:
		var h = JSON.parse_string(hf.get_as_text())
		if h is Array:
			hidden = h
	if not (d is Dictionary and d.get("widgets") is Dictionary):
		return
	for name in d["widgets"]:
		var r: Array = d["widgets"][name]
		if name in hidden or r.size() < 4:
			continue
		var x0 := float(r[0]) / PPM
		var x1 := float(r[0] + r[2]) / PPM
		widget_x[name] = (x0 + x1) / 2.0
	# The widgets are on the glass and she lives behind it (KWin stacks her
	# window under the desk's): they're not ledges in her room, she walks
	# around behind them.


func _land() -> void:
	# The highest surface at or below her feet that she's over.
	var best := [0.0, 0.0, screen.x / PPM, "floor"]
	for fl in floors:
		if pos.x >= fl[1] and pos.x <= fl[2] and fl[0] <= pos.y + 0.05 and fl[0] >= best[0] \
				and (fl[0] < 0.01 or depth > -0.25):     # widget ledges are at the front of the room
			best = fl
	on_name = str(best[3]) if best.size() > 3 else "floor"
	floor_y = best[0]
	floor_span = Vector2(best[1], best[2])


# --- the core ---------------------------------------------------------------
func _connect() -> void:
	tcp = StreamPeerTCP.new()
	said_hello = false
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
	if not said_hello:
		said_hello = true
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
		var msg = JSON.parse_string(inbox.substr(0, cut))
		inbox = inbox.substr(cut + 1)
		if msg is Dictionary:
			_on_message(msg)


func _on_message(msg: Dictionary) -> void:
	match str(msg.get("t", "")):
		"voice":
			speaking = bool(msg.get("speaking", false))
			level = float(msg.get("level", 0.0))
			_stir()
		"speak":
			speech.append({"text": str(msg.get("text", "")), "seconds": float(msg.get("seconds", 1.0)),
					"emotion": str(msg.get("emotion", ""))})
			_stir()
		"ears":
			if msg.get("listening", false):
				_stir()
				_attend()
				_feel("surprised", 0.5, 0.9)
				_face_front(2.0)
		"action":
			_stir()
			var phase := str(msg.get("phase", ""))
			var w := str(msg.get("widget", ""))
			if phase == "started" and allow["react_to_work"]:
				_watch(w, 3.0)
				_slab_show(w)
			elif phase == "done":
				_feel("joy", 0.8, 1.6)
				_slab_send()
				_react("Yes")
			elif phase == "failed":
				_feel("sorrow", 0.7, 2.4)
				_slab_crumble()
				if not play.run("wince"):
					_react("Idle_No")
		"flow":
			if msg.get("phase", "") == "fired":
				_watch(str(msg.get("widget", "")), 2.0)
		"body":
			_command(msg)
		"chat":
			_stir()
			if msg.get("role", "") == "you":
				_attend()
				if msg.get("done", false):
					life.bump("affection", 0.03)
		"state":
			if msg.get("widget", "") == "spotify" and msg.get("data") is Dictionary:
				var d: Dictionary = msg["data"]
				var was := spotify_playing
				spotify_playing = d.get("status", "") == "playing"
				var song := str(d.get("title", d.get("track", d.get("song", ""))))
				if state in FREE or state == "rest":
					if spotify_playing and not was:
						play.run("music_on")          # the music's on: she bobs along (and may dance)
					elif was and not spotify_playing:
						play.run("music_off")
					elif spotify_playing and song != last_song and last_song != "":
						play.run("new_song")
				last_song = song


# Her avatar tool (adapters/avatar.py): go somewhere, dance, stop, a face, sleep, wake.
func _command(msg: Dictionary) -> void:
	_stir()
	brain.drop()                               # his order (through her) comes before her plans
	if str(msg.get("cmd", "")) in ["go", "dance"]:
		_unperch_now()
	match str(msg.get("cmd", "")):
		"go":
			var tx := pos.x
			var ty := 0.0
			var widget := str(msg.get("widget", ""))
			if widget != "":
				if not widget_x.has(widget):
					return
				tx = widget_x[widget]                  # up behind it, at the glass
			elif msg.has("side"):
				var w := screen.x / PPM
				tx = {"left": w * 0.15, "right": w * 0.85, "center": w * 0.5}.get(str(msg["side"]), pos.x)
			elif msg.has("x"):
				tx = float(msg["x"]) / PPM
			tx = clampf(tx, 0.4, screen.x / PPM - 0.4)
			if floor_y < 0.01 and state != "fall":
				target_x = tx                          # walking along the floor
				target_z = -0.2 if widget != "" else depth
				_set_off(30.0)
			else:
				_jump(tx, ty)
		"dance":
			_set_state("dance", float(msg.get("seconds", 20)))
			_play("Dance", 0.4, 0.9)
		"stop":
			_set_state("idle", 2.0)
			_play("Idle", 0.3)
		"feel":
			_feel(_look_key(str(msg.get("look", ""))), 0.8, float(msg.get("seconds", 4)))
		"sleep":
			_set_state("sleep", 1e9)
			_settle_to_sleep()
		"wake":
			if state == "sleep":
				_wake()
		"do":                                  # her avatar tool: one of her interactions (play.json)
			play.run(str(msg.get("what", "")))
		"be":                                  # her avatar tool: a way to be at her furniture
			var st := str(msg.get("state", ""))
			if places.reachable(st):
				_set_state("idle", 0.0)
				brain.be(st, str(msg.get("holding", "")), float(msg.get("seconds", 60)))
				_choose()


# A jump that peaks a little above both ends and lands on (tx, ty): onto a
# widget's top, or down to the floor. The fall code does the landing.
func _jump(tx: float, ty: float) -> void:
	var peak := maxf(pos.y, ty) + 0.45
	var up := sqrt(2.0 * GRAVITY * maxf(0.2, peak - pos.y))
	var t_up := up / GRAVITY
	var t_down := sqrt(2.0 * maxf(0.05, peak - ty) / GRAVITY)
	vel = Vector2((tx - pos.x) / (t_up + t_down), up)
	# Up onto a ledge (they're at the front of the room): the jump carries her forward to it.
	jump_dz = (0.0 - depth) / (t_up + t_down) if ty > 0.01 else 0.0
	spin = 0.0
	_set_state("fall", 99.0)
	_play("Jump", 0.15)


# What her body is doing, for her (~/.local/share/ariadne2/pet/body.json), once a second.
func _tell(delta: float) -> void:
	told_in -= delta
	if told_in > 0.0 or snapshot_path != "":
		return
	told_in = 1.0
	var on := on_name if state not in ["fall", "held"] else "air"
	var mood := ""
	for k in mood_target:
		if mood_target[k] > 0.3 and t < mood_until:
			mood = k
	var data := {"kind": "3d", "model": "Aries", "x": pos.x * PPM, "y": screen.y - pos.y * PPM,
		"w": screen.x, "h": screen.y, "mode": state, "on": on, "look": mood,
		"dancing": state == "dance", "doing": play.current if state == "react" and play.current != "" else brain.doing, "at": perched,
		"plays": play.names(), "state": pstate, "states": _ways(),
		"holding": life.holding if life and life.holding in life.THINGS else "", "depth": snappedf(-depth / room_depth, 0.01), "asleep": state == "sleep", "ts": Time.get_unix_time_from_system(),
		"own": ["smile", "angry", "tears", "wide", "smirk"], "looks": LOOK_FACE.keys()}
	var f := FileAccess.open(OS.get_environment("HOME") + BODY_FILE, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(data))


# The place states she has clips for (for her avatar tool), worked out once.
var ways_cache: Array = []
func _ways() -> Array:
	if ways_cache.is_empty() and places and furniture:
		for s in places.table:
			if places.can(s) and room.has_spot(places.spot(s)):
				ways_cache.append(s)
	return ways_cache if furniture else []


func _stir() -> void:
	last_activity = t
	if state == "sleep":
		_wake()


# --- feelings and glances ---------------------------------------------------
func _feel(key: String, weight: float, seconds: float) -> void:
	for k in mood_target:
		mood_target[k] = 0.0
	mood_target[key] = weight
	mood_until = t + seconds


func _watch(widget: String, seconds: float) -> void:
	if not widget_x.has(widget):
		return
	var dx: float = widget_x[widget] - pos.x
	yaw_target = clampf(dx * 0.25, -1.1, 1.1)
	look_target = Vector2(signf(dx), 0.2)
	look_until = t + seconds


func _face_front(seconds: float) -> void:
	yaw_target = 0.0
	look_target = Vector2.ZERO
	look_until = t + seconds
	if state == "wander":
		_set_state("idle", seconds)
		_play("Idle")


func _react(clip_name: String) -> void:
	if state in ["idle", "wander", "dance"]:
		_set_state("react", 1.6)
		_play(clip_name, 0.2)


# --- animation --------------------------------------------------------------
func _load_clips() -> void:
	ap = AnimationPlayer.new()
	body.add_child(ap)
	ap.root_node = ap.get_path_to(body)    # clip tracks address %GeneralSkeleton in her scene
	ap.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
	if clip_lib == null:                   # read once; every body plays the same humanoid clips
		clip_lib = AnimationLibrary.new()
		var paths: Array = CLIPS.duplicate()
		# Kimodo clips (pet/import/: BVH -> GLB, soma_bonemap.tres), each played in place.
		for f in DirAccess.get_files_at(KIMODO_DIR):
			if f.ends_with(".glb"):
				paths.append(KIMODO_DIR + f)
		if OS.get_environment("PET_PREVIEW_GLB") != "":
			paths.append(OS.get_environment("PET_PREVIEW_GLB"))      # a new take from his ComfyUI board (pet/comfy)
		for path in paths:
			var src: Node = (load(path) as PackedScene).instantiate()
			var player := _find(src, "AnimationPlayer") as AnimationPlayer
			if player:
				for name in player.get_animation_list():
					if not clip_lib.has_animation(name):
						var anim := player.get_animation(name)
						if String(path).begins_with(KIMODO_DIR) or String(path) == OS.get_environment("PET_PREVIEW_GLB"):
							if String(name).begins_with("stop_"):
								stop_curve[name] = _travel_curve(anim)
							if GAIT_PREFIXES.any(func(px): return String(name).begins_with(px)):
								gait_velocity[name] = _ground_velocity(anim)
								anim = anim.duplicate(true)
								anim.loop_mode = Animation.LOOP_LINEAR
							anim = _in_place(anim, String(name).begins_with("stop_"))
						anim = _without_eyes(anim)
						clip_lib.add_animation(name, anim)
						_lying_heads(name, anim)
			src.free()
	ap.add_animation_library("", clip_lib)


# The clips' source skeletons have no eyes, but the retarget gives every clip
# eye-bone tracks anyway, posed for some other face: they turned her irises
# into her head, leaving just the whites. Her eyes keep the model's own pose.
func _without_eyes(src: Animation) -> Animation:
	var drop := []
	for tr in src.get_track_count():
		var p := String(src.track_get_path(tr))
		if p.ends_with(":LeftEye") or p.ends_with(":RightEye") or p.ends_with(":Eyes"):
			drop.append(tr)
	if drop.is_empty():
		return src
	var anim := src.duplicate(true) as Animation
	for i in range(drop.size() - 1, -1, -1):
		anim.remove_track(drop[i])
	return anim


# Lying clips don't agree which way her head points (lying back from sitting
# puts it away from you, lying down from standing toward you), and a blend
# between two that disagree swings her through 180 degrees, feet up. So each
# clip that starts or ends lying gets a copy turned half round ("<name>@r"),
# and _play_variant plays whichever starts the way she's lying now.
var lie_head := {}                         # clip -> [start, end] head direction on the floor (x, z), or ZERO when not lying


func _lying_heads(name: String, anim: Animation) -> void:
	var hips := -1
	for tr in anim.get_track_count():
		if anim.track_get_type(tr) == Animation.TYPE_ROTATION_3D and String(anim.track_get_path(tr)).ends_with(":Hips"):
			hips = tr
	if hips < 0:
		return
	var ends := []
	for at in [0.0, anim.length]:
		var up := Basis(anim.rotation_track_interpolate(hips, at)) * Vector3.UP
		ends.append(Vector2(up.x, up.z).normalized() if up.y < 0.5 else Vector2.ZERO)
	if ends[0] == Vector2.ZERO and ends[1] == Vector2.ZERO:
		return
	lie_head[name] = ends
	var turned := anim.duplicate(true) as Animation
	var half := Quaternion(Vector3.UP, PI)
	for tr in turned.get_track_count():
		var path := String(turned.track_get_path(tr))
		if not (path.ends_with(":Hips") or path.ends_with(":Root")):
			continue
		for k in turned.track_get_key_count(tr):
			var v = turned.track_get_key_value(tr, k)
			if turned.track_get_type(tr) == Animation.TYPE_ROTATION_3D:
				turned.track_set_key_value(tr, k, half * (v as Quaternion))
			elif turned.track_get_type(tr) == Animation.TYPE_POSITION_3D:
				turned.track_set_key_value(tr, k, Vector3(-v.x, v.y, -v.z))
	clip_lib.add_animation(name + "@r", turned)
	lie_head[name + "@r"] = [-ends[0], -ends[1]]


# Locomotion loops (pet/import/kimodo_loop.py): each one's ground velocity,
# measured off its hips before the travel is taken out, in hip-heights per
# second, clip space (x her left, z forward). Her body moves her exactly that
# fast (times her hip height and the playback speed), so her feet stay planted.
const GAIT_PREFIXES := ["walk_", "stroll_", "strafe_", "walk_back_", "jog_", "carry_walk_"]
var gait_velocity := {}


# Stops (pet/import/kimodo_stop.py): how far she's travelled at each moment
# of the clip, hip-heights, along its direction of travel.
var stop_curve := {}
func _travel_curve(anim: Animation) -> Dictionary:
	for tr in anim.get_track_count():
		if anim.track_get_type(tr) == Animation.TYPE_POSITION_3D and String(anim.track_get_path(tr)).ends_with(":Hips"):
			var n := anim.track_get_key_count(tr)
			var a: Vector3 = anim.track_get_key_value(tr, 0)
			var b: Vector3 = anim.track_get_key_value(tr, n - 1)
			var along := Vector2(b.x - a.x, b.z - a.z).normalized()
			var times := PackedFloat32Array()
			var dist := PackedFloat32Array()
			var far := 0.0
			for k in n:
				var v: Vector3 = anim.track_get_key_value(tr, k)
				far = maxf(far, Vector2(v.x - a.x, v.z - a.z).dot(along))     # never backwards
				times.append(anim.track_get_key_time(tr, k))
				dist.append(far)
			return {"t": times, "d": dist}
	return {}


func _curve_at(c: Dictionary, time: float) -> float:
	var ts: PackedFloat32Array = c["t"]
	var ds: PackedFloat32Array = c["d"]
	var i := ts.bsearch(time)
	if i <= 0:
		return ds[0]
	if i >= ts.size():
		return ds[-1]
	return lerpf(ds[i - 1], ds[i], (time - ts[i - 1]) / maxf(ts[i] - ts[i - 1], 0.0001))


func _ground_velocity(anim: Animation) -> Vector2:
	for tr in anim.get_track_count():
		if anim.track_get_type(tr) == Animation.TYPE_POSITION_3D and String(anim.track_get_path(tr)).ends_with(":Hips"):
			var n := anim.track_get_key_count(tr)
			if n < 2:
				break
			var a: Vector3 = anim.track_get_key_value(tr, 0)
			var b: Vector3 = anim.track_get_key_value(tr, n - 1)
			var span := anim.track_get_key_time(tr, n - 1) - anim.track_get_key_time(tr, 0)
			# A loop's last key is one frame short of the cycle: travel per frame times the frames.
			var per := span / maxf(n - 1, 1)
			return Vector2(b.x - a.x, b.z - a.z) / maxf(span, 0.001) * (span / (span + per))
	return Vector2.ZERO


# Kimodo clips travel (a walk goes somewhere); her body moves her itself, so
# the hips' steady drift over the clip comes out, keeping its sway and bob.
const KIMODO_DIR := "res://assets/anims/kimodo/"
# exact: take out the travel as it happens (a stop slows down), not as a
# straight line, keeping only the sway across it; her body follows the curve.
func _in_place(src: Animation, exact := false) -> Animation:
	var anim := src.duplicate(true) as Animation
	for tr in anim.get_track_count():
		if anim.track_get_type(tr) != Animation.TYPE_POSITION_3D or not (String(anim.track_get_path(tr)).ends_with(":Hips") or String(anim.track_get_path(tr)).ends_with(":Root")):
			continue
		var n := anim.track_get_key_count(tr)
		if n < 2:
			continue
		var first: Vector3 = anim.track_get_key_value(tr, 0)
		var last: Vector3 = anim.track_get_key_value(tr, n - 1)
		if exact:
			var along := Vector2(last.x - first.x, last.z - first.z).normalized()
			var far := 0.0
			for k in n:
				var v: Vector3 = anim.track_get_key_value(tr, k)
				far = maxf(far, Vector2(v.x - first.x, v.z - first.z).dot(along))   # as _travel_curve has it
				anim.track_set_key_value(tr, k, Vector3(v.x - first.x - along.x * far, v.y, v.z - first.z - along.y * far))
			continue
		var t0 := anim.track_get_key_time(tr, 0)
		var span := maxf(anim.track_get_key_time(tr, n - 1) - t0, 0.001)
		for k in n:
			var f := (anim.track_get_key_time(tr, k) - t0) / span
			var v: Vector3 = anim.track_get_key_value(tr, k)
			var drift := first.lerp(last, f)
			anim.track_set_key_value(tr, k, Vector3(v.x - drift.x, v.y, v.z - drift.z))
	return anim


# GASP-style variety: a role ("Idle", "Sitting_Idle", ...) is a pool of clips,
# its base clip plus any generated ones whose names start with a listed
# prefix (assets/anims/kimodo, pet/import/kimodo_prompts.txt). Each entry's
# weight is a number or a feeling, read off her moods and needs, so a bored
# her picks bored idles. When a variant ends (or a looping one completes a
# cycle) another is picked, never the same one twice running.
const ROLES := {
	"Idle": [["Idle", 0.01], ["idle_calm_", 1.2], ["idle_happy_", "joy"], ["idle_bored_", "bored"],
			["idle_sad_", "sorrow"], ["idle_tired_", "tired"], ["stretch_", 0.25], ["yawn_", "tired"],
			["look_around_", 0.35], ["think_", 0.15]],
	"Idle_FoldArms": [["Idle_FoldArms", 0.01], ["fold_arms_", 1.0], ["think_", 0.8], ["shy_", "shy"]],
	"Idle_Talking": [["Idle_Talking", 0.01], ["talk_", 1.0]],
	"Sitting_Idle": [["Sitting_Idle", 0.01], ["sit_idle_", 1.5]],
	# Asleep on the floor: curled cross-legged, lying on her side or back.
	"Crouch_Idle": [["Crouch_Idle", 0.01], ["nap_", 1.5], ["lie_idle_", 1.0], ["floor_sit_", 0.5]],
	"Crouching": [["Crouch_Idle", 0.01], ["crouch_idle_", 1.0]],
	"Dance": [["Dance", 0.01], ["dance_", 1.5]],
	"Jump": [["Jump", 0.01], ["fall_", 1.0], ["jump_", 0.3]],
	"Held": [["Jump", 0.01], ["held_", 1.0]],
	"Jump_Land": [["Jump_Land", 0.01], ["land_", 1.0]],
	"Death01": [["Death01", 0.01], ["knocked_", 1.0]],
	"PickUp_Table": [["PickUp_Table", 0.01], ["pickup_", 1.0]],
	"LayToIdle": [["LayToIdle", 0.01], ["tr_lie_stand_", 1.0], ["get_up_", 1.0]],
	"Interact": [["Interact", 0.01], ["interact_", 1.0]],
	"Yes": [["Yes", 0.01], ["nod_", 1.0]],
	"Jog_Fwd": [["Jog_Fwd", 0.01], ["jog_", 1.0]],
	# Getting about: her walks (a cute bouncy one when she feels light), side
	# steps facing you, and backing up. The old stock walk only if none exist.
	"Walk": [["walk_1", 1.0], ["walk_2", 1.0], ["walk_3", 1.0], ["stroll_", 1.2], ["walk_cute_", "light"],
			["Walk", 0.01]],
	"Walk_Carry": [["carry_walk_", 1.0], ["Walk_Carry", 0.01]],
	"Strafe_Left": [["strafe_left_", 1.0], ["Walk", 0.01]],
	"Strafe_Right": [["strafe_right_", 1.0], ["Walk", 0.01]],
	"Walk_Back": [["walk_back_", 1.0], ["Walk", 0.01]],
	# The brain's activities (brain.gd): a look round, a stretch, sitting or lying on the floor, a cheer.
	"LookAround": [["look_around_", 1.0], ["Idle", 0.01]],
	"Stretch": [["stretch_", 1.0], ["yawn_", "tired"], ["Idle", 0.01]],
	"FloorSit": [["floor_sit_", 1.0], ["Crouch_Idle", 0.01]],
	"LieDown": [["lie_idle_", 1.0], ["Crouch_Idle", 0.01]],
	"Cheer": [["cheer_", 1.0], ["wave_", 0.5], ["Yes", 0.01]],
	"Shy": [["shy_", 1.0], ["Idle_FoldArms", 0.01]],
	# Her things to do (docs/PET_LIFE_PLAN.md): the ones at furniture are its
	# states now (states.json); watering the plant is still a role.
	"Water": [["water_plant_", 1.0], ["Interact", 0.01]],
}
# Today's stances with one of her things in hand (docs/PET_STATES_PLAN.md, phase 9).
const ROLE_ITEMS := {
	"Idle": {"phone": [["stand_phone_", 1.0], ["idle_calm_", 0.2]], "book": [["stand_read_", 1.0]],
			"mug": [["stand_sip_", 1.0], ["drink_", 1.0], ["idle_calm_", 0.3]]},
	"FloorSit": {"book": [["read_", 1.0]], "phone": [["phone_", 1.0]], "bowl": [["eat_", 1.0]],
			"mug": [["floor_sip_", 1.0], ["floor_sit_", 0.3]]},
	"LieDown": {"book": [["floor_front_read_", 1.0]], "phone": [["floor_front_phone_", 1.0]]},
}
const GAIT_PLAYBACK := 0.8                 # a touch slower than Kimodo's brisk takes; speed follows
# Played once and held at their end (a nod, being knocked over), not re-picked.
const ONE_SHOT := ["Jump_Land", "Death01", "PickUp_Table", "LayToIdle", "Interact", "Yes"]

# --- stances: every clip is standing, sitting on a ledge, sitting on the
# floor, lying, or crouching. Moving between two, the matching transition
# plays first (tr_<from>_<to>_*, sit_down_/sit_up_ for ledges), so she never
# pops from a nap to standing or from standing to a crouch.
const STANCE_PREFIXES := [["sit_idle_", "ledge"], ["Sitting_", "ledge"], ["nap_", "floor"], ["floor_sit_", "floor"],
		["lie_", "lie"], ["crouch_idle_", "crouch"], ["Crouch_Idle", "crouch"],
		["work_", "ledge"], ["game_", "ledge"], ["eat_", "floor"], ["read_", "floor"], ["phone_", "floor"],
		["meditate_", "floor"], ["sleep_bed_", "lie"]]
const TRANSITION_EXTRA := {"stand>ledge": "sit_down_", "ledge>stand": "sit_up_"}
var pending := ""                          # the clip waiting for a transition to finish


func _stance(name: String) -> String:
	if name.begins_with("tr_"):
		return name.split("_")[2]          # tr_<from>_<to>_N: where it ends up
	if name.begins_with("sit_down_"):
		return "ledge"
	if name.begins_with("sit_up_") or name == "Sitting_Exit" or name.begins_with("get_up_"):
		return "stand"
	for sp in STANCE_PREFIXES:
		if name.begins_with(sp[0]):
			return sp[1]
	return "stand"


# A clip that is itself a move between stances.
func _is_move(name: String) -> bool:
	if places and places.is_move(name):
		return true
	return name.begins_with("tr_") or name.begins_with("sit_down_") or name.begins_with("sit_up_") \
			or name.begins_with("get_up_") or name == "Sitting_Exit" or name == "LayToIdle"


func _transition(from: String, to: String) -> String:
	if from == to:
		return ""
	var tr := _variant_of("tr_%s_%s_" % [from, to])
	if tr == "" and TRANSITION_EXTRA.has(from + ">" + to):
		tr = _variant_of(TRANSITION_EXTRA[from + ">" + to])
	if tr == "" and from != "stand" and to != "stand":
		tr = _variant_of("tr_%s_stand_" % from)    # no direct move: stand up first, the next one follows
	return tr
var variant := ""                          # the clip actually playing for the role in `clip`
var variant_until := 0.0


func _feeling(f: String) -> float:
	var n: Dictionary = life.needs if life else {}
	match f:
		"joy": return 0.2 + 2.5 * float(moods.get("joy", 0.0)) + float(moods.get("stars", 0.0))
		"sorrow": return 0.05 + 2.5 * float(moods.get("sorrow", 0.0)) + maxf(0.0, 0.4 - float(n.get("affection", 0.6)))
		"bored": return maxf(0.0, 0.7 - float(n.get("fun", 0.6))) * 2.0 + float(moods.get("bored", 0.0))
		"tired": return maxf(0.0, 0.6 - float(n.get("energy", 0.8))) * 2.5 + float(moods.get("sleepy", 0.0))
		"shy": return 0.2 + 2.0 * float(moods.get("blush", 0.0))
		"angry": return 0.05 + 2.5 * float(moods.get("angry", 0.0))
		"lonely": return maxf(0.0, 0.6 - float(n.get("affection", 0.6))) * 2.5 + 0.05
		"hungry": return maxf(0.0, 0.6 - float(n.get("hunger", 0.7))) * 2.5 + 0.05
		"light": return 0.15 + 3.0 * float(moods.get("joy", 0.0)) + 2.0 * float(moods.get("stars", 0.0)) \
				+ 2.0 * float(moods.get("hearts", 0.0)) + maxf(0.0, float(n.get("energy", 0.8)) - 0.6) * 2.0
	return 0.0


func _variant(role: String) -> String:
	var entries: Array = ROLES.get(role, [])
	if role.begins_with("play:") and play:
		entries = play.entry(role.substr(5)).get("clips", [])     # an interaction's pool (play.json)
	var held: String = life.holding if life else ""
	if ROLE_ITEMS.has(role) and ROLE_ITEMS[role].has(held) \
			and (ROLE_ITEMS[role][held] as Array).any(func(e): return _variant_of(e[0]) != ""):
		entries = ROLE_ITEMS[role][held]       # a book or her phone in hand, standing or on the floor
	if places and places.has(role.get_slice(":", 0)):
		# A place state's idles (or what she does there with what she's holding);
		# "<state>:react" when he pokes or talks to her there.
		var s := role.get_slice(":", 0)
		entries = places.react(s) if role.ends_with(":react") else places.pool(s, life.holding if life else "")
	elif not ROLES.has(role) and not role.begins_with("play:"):
		return role if ap.has_animation(role) else ""
	var pool := []
	var weights := []
	for entry in entries:
		var w: float = entry[1] if (entry[1] is float or entry[1] is int) else _feeling(entry[1])
		if w <= 0.0:
			continue
		var names: Array = [entry[0]] if ap.has_animation(entry[0]) else []
		if entry[0].ends_with("_"):
			names = Array(ap.get_animation_list()).filter(func(a): return String(a).begins_with(entry[0]) and not String(a).contains("@"))
		for a in names:
			pool.append(a)
			weights.append(w / names.size())        # a prefix's weight is shared by its variants
	if pool.size() > 1 and variant in pool:
		weights[pool.find(variant)] = 0.0             # not the same one twice running
	var total := 0.0
	for w in weights:
		total += w
	if total <= 0.0:
		return pool[0] if pool.size() > 0 else ""
	var r := randf() * total
	for i in pool.size():
		r -= weights[i]
		if r <= 0.0:
			return pool[i]
	return pool[-1]


func _play(name: String, blend := 0.3, speed := 1.0) -> void:
	if pstate != "" and name in REACTIONS:
		name = pstate + ":react"               # in bed or at the desk: a wave from there, not up on her feet
	if clip == name and ap.is_playing():
		ap.speed_scale = speed
		return
	var pick := _variant(name)
	if pick == "":
		return
	clip = name
	_play_variant(pick, blend)
	ap.speed_scale = speed


func _play_variant(pick: String, blend: float) -> void:
	var want := clip.get_slice(":", 0) if _is_state_role(clip) else ""
	if not _is_move(pick) and (pstate != "" or want != ""):
		var hop := _state_hop(want)
		if hop != "":
			pending = pick
			pick = hop
		else:
			if pick == pending:
				pending = ""
			if pstate != want and want != "":      # no way there from here (not beside it): on her feet
				clip = "Idle"
				pick = _variant("Idle")
	else:
		var from := _stance(variant) if variant != "" else "stand"
		var tr := "" if _is_move(pick) else _transition(from, _stance(pick))
		if tr != "" and tr != pick and not variant.begins_with("tr_"):
			pending = pick
			pick = tr
		elif pick == pending:
			pending = ""
	# Lying: carry on the way her head points now (the half-turned copy if need be).
	var none := [Vector2.ZERO, Vector2.ZERO]
	var head_now: Vector2 = (lie_head.get(variant, none) as Array)[1]
	var head_next: Vector2 = (lie_head.get(pick, none) as Array)[0]
	if head_now != Vector2.ZERO and head_next != Vector2.ZERO and head_now.dot(head_next) < 0.0 \
			and ap.has_animation(pick + "@r"):
		pick += "@r"
	elif variant.ends_with("@r") and head_now == Vector2.ZERO:
		# Up off the floor from a half-turned clip she faces the other way:
		# her body turns with her instead, and the next clip starts square.
		yaw = wrapf(yaw + PI, -PI, PI)
		yaw_target = wrapf(yaw_target + PI, -PI, PI)
		if perch.has("yaw"):
			perch["yaw"] = wrapf(float(perch["yaw"]) + PI, -PI, PI)
		blend = 0.0
	variant = pick
	ap.play(pick, maxf(blend, _calm_blend(pick)))
	var a := ap.get_animation(pick)
	# A looping clip gets a cycle or three before a change; a one-shot plays out.
	variant_until = t + (a.length * randi_range(1, 3) if a.loop_mode != Animation.LOOP_NONE else a.length) - minf(0.4, a.length * 0.3)


# The least blend between two clips: unhurried, so a change of clip eases in
# instead of snapping. Quick only where it must be (a fall, being grabbed,
# landing); steps and stance moves a little quicker so her feet stay put.
const MIN_BLEND := 0.6
const QUICK := ["Jump", "fall_", "held_", "land_", "knocked_", "Death01", "Held"]
func _calm_blend(pick: String) -> float:
	if state in ["fall", "held", "knocked"] or QUICK.any(func(q): return pick.begins_with(q)):
		return 0.0
	if gait_velocity.has(pick) or pick.begins_with("stop_") or _is_move(pick):
		return 0.4
	return MIN_BLEND


# A one-shot transition into a role: sitting down onto a widget, getting up
# off the floor. The role's pool takes over when it ends (_vary).
func _play_via(first: String, role: String, blend := 0.3) -> void:
	if not ap.has_animation(first):
		_play(role, blend)
		return
	clip = role
	_play_variant(first, blend)
	ap.speed_scale = 1.0


# --- place states (places.gd, states.json) ----------------------------------------
# Reactions that, in a place state, become that state's own (a wave from the bed).
const REACTIONS := ["Idle_Talking", "Yes", "Interact", "Cheer", "Shy", "Stretch", "Idle_No", "Idle_FoldArms"]


func _is_state_role(role: String) -> bool:
	return places != null and places.has(role.get_slice(":", 0))


# One move toward the state she wants (want; "" = on her feet): the clip to
# play first, her body sliding to where that state has her, or "" when she's
# there. A move with no clip (asleep from lying back) happens at once.
func _state_hop(want: String) -> String:
	if pstate == "" and want != "" and _stance(variant) != "stand" and variant != "":
		var up := _transition(_stance(variant), "stand")      # off the floor first (today's stances)
		if up != "":
			return up
	for i in 4:                                # through any moves that have no clip
		if pstate == want:
			return ""
		var e: Dictionary = places.next_exit(pstate, want)
		if e.is_empty() and pstate != "":
			e = places.next_exit(pstate, "")   # another place: up on her feet first, the brain walks her
		if e.is_empty():
			return ""
		if pstate == "" and room:
			# Into a state only from beside it; otherwise she stays on her feet.
			var near: Vector2 = room.spot(places.spot(e["to"])).get("approach", Vector2(pos.x, depth))
			if near.distance_to(Vector2(pos.x, depth)) > 0.6:
				return ""
		var c: String = e["clip"]
		var pick := "" if c == "" else (c if ap.has_animation(c) else _variant_of(c))
		var dur := ap.get_animation(pick).length if pick != "" else 0.5
		_state_move(e["to"], dur, e["lift"] == "hips")
		if pick != "":
			return pick
		if pstate == want:
			return ""
	return ""


func _state_move(to: String, dur: float, hips: bool) -> void:
	pstate = to
	if to == "":
		_unperch(dur)
	else:
		_perch_on(places.spot(to), dur)
	if hips and not perch.is_empty():
		perch["hips"] = true


# Her hips' height over her feet, this frame (for lifting her as she lies back).
func _hips_y() -> float:
	var h := skel.find_bone("Hips")
	return (skel.global_transform * skel.get_bone_global_pose(h).origin).y - body.global_position.y if h >= 0 else 0.0


# Setting off toward target_x. A short hop sideways she side-steps, still
# facing you; one behind the way she faces, sometimes she backs up; a longer
# trip starts with a couple of side steps and turns into a straight walk.
var gait := "walk"                         # walk | strafe | back | lead (side steps, then turning to walk)
var gait_turn_at := 0.0
var gait_from := 0.0                      # when she set off: speed eases in with the clip's blend
func _set_off(seconds: float) -> void:
	_set_state("wander", seconds)
	gait_from = t
	if floor_y > 0.01:
		target_z = 0.0                         # on a ledge: along it
	var to := _to_target()
	var m := to.normalized()
	var ahead := m.dot(_facing())              # 1 = straight ahead, -1 = behind her
	var side := absf(m.dot(_left()))
	if to.length() < 0.9:
		gait = "back" if ahead < -0.5 and randf() < 0.6 else ("strafe" if side > 0.6 else "walk")
	elif side > 0.6 and randf() < 0.55:
		gait = "lead"
		gait_turn_at = t + randf_range(0.5, 0.9)
	else:
		gait = "walk"
	if gait != "walk":
		yaw_target = yaw                       # side steps and backing up keep the way she faces
	_gait_clip()


# Where she's headed, on the floor: (x, depth) from her.
func _to_target() -> Vector2:
	return Vector2(target_x - pos.x, target_z - depth)


# Which way she faces on the floor (x, depth) and her left. Yaw 0 faces you.
func _facing() -> Vector2:
	return Vector2(sin(yaw), cos(yaw))


func _left() -> Vector2:
	return Vector2(cos(yaw), -sin(yaw))


func _gait_clip() -> void:
	var m := _to_target().normalized()
	match gait:
		"strafe", "lead":
			_play("Strafe_Left" if m.dot(_left()) > 0.0 else "Strafe_Right", 0.3, GAIT_PLAYBACK)
		"back":
			_play("Walk_Back", 0.3, GAIT_PLAYBACK)
		_:
			# A bowl or a mug she carries in front of her in both hands.
			var carry: bool = life != null and life.holding in ["bowl", "mug"] and _variant_of("carry_walk_") != ""
			_play("Walk_Carry" if carry else "Walk", 0.35, GAIT_PLAYBACK)


# Stopping: walk, side-steps or backing up each end in their own stop clip,
# begun when the distance left is the clip's stopping distance and followed
# along its slowing curve, so she arrives on her feet instead of sliding.
var stop_name := ""
var stop_from := Vector2.ZERO
var stop_dir := Vector2.RIGHT
var stop_scale := 1.0
func _stop_clip(m: Vector2) -> String:
	match gait:
		"strafe", "lead":
			return _variant_of("stop_strafe_left_" if m.dot(_left()) > 0.0 else "stop_strafe_right_")
		"back":
			return _variant_of("stop_back_")
	return _variant_of("stop_walk_")


func _stop_length(stop: String) -> float:
	if not stop_curve.has(stop) or leg_length < 0.1:
		return 0.0
	return (stop_curve[stop]["d"] as PackedFloat32Array)[-1] * (leg_length / SOMA_LEG)


func _begin_stop(stop: String, m: Vector2) -> void:
	var length := _stop_length(stop)
	stop_name = stop
	stop_from = Vector2(pos.x, depth)
	stop_dir = m
	stop_scale = (_to_target().length() / length if length > 0.0 else 1.0) * (leg_length / SOMA_LEG)
	_set_state("stopping", 6.0)
	_play_via(stop, "Idle", 0.25)
	ap.speed_scale = GAIT_PLAYBACK


# How fast her body moves for the clip playing: its measured stride if it's
# a locomotion loop, else the old fixed pace.
# Stride is set by leg length, not hip height: the clips' source skeleton
# (Kimodo's SOMA) has hips at 1 m and 0.855 m from hip joint to ankle, and the
# velocity is in its hip-heights, so her legs over SOMA's give her pace.
# (Scaling by hip height left Jane 13% fast: her feet slid forward.)
const SOMA_LEG := 0.855
var leg_length := 0.0
func _gait_speed() -> float:
	# Easing in over the first 0.35 s, while the walk blends in from standing
	# (at full speed at once, her planted feet skated those first frames).
	var ease := smoothstep(0.0, 0.35, t - gait_from)
	if gait_velocity.has(variant) and leg_length > 0.1:
		return (gait_velocity[variant] as Vector2).length() * (leg_length / SOMA_LEG) * ap.speed_scale * ease
	return WALK_SPEED * _stride() * ease


# Nothing of her sinks into what she's on: Kimodo's lying and kneeling poses
# put her back or her shins about level with the floor, so her body is lifted
# until every bone's joint is at least its flesh's depth above the surface
# (the floor, the mattress, the cushion: whatever her lift stands her on).
const FLESH := {"Hips": 0.1, "Spine": 0.1, "Chest": 0.1, "UpperChest": 0.1, "Neck": 0.07, "Head": 0.1,
		"LeftUpperLeg": 0.07, "RightUpperLeg": 0.07, "LeftLowerLeg": 0.05, "RightLowerLeg": 0.05,
		"LeftFoot": 0.04, "RightFoot": 0.04, "LeftUpperArm": 0.045, "RightUpperArm": 0.045,
		"LeftLowerArm": 0.04, "RightLowerArm": 0.04, "LeftHand": 0.025, "RightHand": 0.025}
var flesh: Array = []                      # [bone index, depth] for this body
var ground_lift := 0.0


func _ground() -> float:
	if state in ["held", "fall"] or floor_y > 0.01 or flesh.is_empty():
		ground_lift = 0.0                      # dangling, flying, on a widget's edge: no floor under her
		return 0.0
	var origin := body.global_position.y
	var need := 0.0
	for f in flesh:
		var y: float = (skel.global_transform * skel.get_bone_global_pose(f[0]).origin).y - origin
		need = maxf(need, float(f[1]) - y)
	# up at once (no sinking), down gently (no drop when she sits up)
	ground_lift = need if need > ground_lift else lerpf(ground_lift, need, 0.15)
	return ground_lift


func _measure_legs() -> void:
	flesh.clear()
	for b in FLESH:
		var i := skel.find_bone(b)
		if i >= 0:
			flesh.append([i, FLESH[b] * (skel.motion_scale / 0.795 if skel.motion_scale > 0.1 else 1.0)])
	leg_length = 0.0
	var ids := ["LeftUpperLeg", "LeftLowerLeg", "LeftFoot"].map(func(b): return skel.find_bone(b))
	if ids.has(-1):
		return
	var p: Array = ids.map(func(i): return skel.get_bone_global_rest(i).origin)
	leg_length = (p[0] as Vector3).distance_to(p[1]) + (p[1] as Vector3).distance_to(p[2])


# Longer legs take longer strides: WALK_SPEED was set for Aries' (hips 0.795 m),
# so a taller body moves faster at the same step rate, or her feet slide.
func _stride() -> float:
	return skel.motion_scale / 0.795 if skel and skel.motion_scale > 0.1 else 1.0


# How far into the current clip (0-1).
func _progress() -> float:
	var len := ap.current_animation_length
	return clampf(ap.current_animation_position / len, 0.0, 1.0) if len > 0.0 else 1.0


# Falling asleep: on a widget she sits down first (unless already seated),
# on the floor she settles into a nap.
func _settle_to_sleep() -> void:
	if pstate != "":                           # in a place: dozing off there (in bed, lying back first)
		_play(places.sleep_state(pstate), 1.0, 0.6)
		return
	_play("Sitting_Idle" if floor_y > 0.01 else "Crouch_Idle", 1.0, 0.6)      # the stance move comes first


# Waking: from a floor nap she gets up (get_up_*), from a widget seat she
# just comes to.
func _wake() -> void:
	brain.drop()
	if pstate != "":                           # in bed: she comes to there (lying back), then the brain decides
		_set_state("rest", randf_range(3.0, 6.0))
		_play(places.wake_state(pstate), 0.6)
		return
	if perched != "":                          # out of bed: she gets up and steps off it
		_set_state("idle", 3.0)
		_play("Idle", 0.4)
		_unperch(maxf(0.8, variant_until - t))
		return
	# Getting up from wherever she was comes first (the stance moves); off
	# the floor, now and then she comes up through a crouch, stretching awake.
	if floor_y < 0.01 and randf() < 0.35 and _variant_of("crouch_idle_") != "":
		_set_state("idle", randf_range(1.5, 3.0))
		_play("Crouching", 0.4)
		return
	_set_state("idle", 3.0)
	_play("Idle", 0.4)


func _variant_of(prefix: String) -> String:
	var names := Array(ap.get_animation_list()).filter(func(a): return String(a).begins_with(prefix) and not String(a).contains("@"))
	return names.pick_random() if not names.is_empty() else ""


# Called each frame: a role whose variant has had its time moves on to another.
func _vary() -> void:
	if t < variant_until:
		return
	if pending != "":                          # a transition ended: on to what it led to
		var next := pending
		pending = ""
		_play_variant(next, 0.35)
		return
	if not (ROLES.has(clip) or _is_state_role(clip) or clip.begins_with("play:")) or clip in ONE_SHOT or clip.ends_with(":react"):
		return
	var pick := _variant(clip)
	if pick != "" and (pick != variant or ap.get_animation(pick).loop_mode == Animation.LOOP_NONE):
		_play_variant(pick, 0.6)                # a long blend: a swap, not a snap
	else:
		variant_until = t + 2.0


func _set_state(s: String, seconds: float) -> void:
	state = s
	state_until = t + seconds


# What she does next when she's free: the brain's next step (brain.gd).
func _choose() -> void:
	if brain_quiet:                            # a test run driving her itself
		_set_state("idle", 1.0)
		_play("Idle", 0.4)
		return
	brain.next()


func _nap() -> void:
	_set_state("sleep", 1e9)
	_settle_to_sleep()


# To bed: sitting on its edge, lying back, then asleep (places.gd finds the moves).
func _bed_sleep() -> void:
	_set_state("sleep", 1e9)
	_play("Bed_Sleep", 0.6)


# --- every frame ------------------------------------------------------------
# His settings (~/.config/ariadne2/settings.json): the avatar section and
# whether her body is shown. Re-read when the file changes.
func _read_settings() -> void:
	var path := OS.get_environment("HOME") + "/.config/ariadne2/settings.json"
	var m := FileAccess.get_modified_time(path)
	if m == settings_mtime:
		return
	settings_mtime = m
	var f := FileAccess.open(path, FileAccess.READ)
	if not f:
		return
	var d = JSON.parse_string(f.get_as_text())
	if not d is Dictionary:
		return
	var av: Dictionary = d.get("avatar", {}) if d.get("avatar") is Dictionary else {}
	var desk: Dictionary = d.get("desktop", {}) if d.get("desktop") is Dictionary else {}
	for k in allow:
		if av.has(k):
			allow[k] = bool(av[k])
	for need in ["energy", "fun", "affection", "hunger"]:
		if av.has(need + "_drain"):
			life.rates[need] = clampf(float(av[need + "_drain"]), 0.25, 4.0)
	if av.has("fps_cap"):
		FPS_BUSY = clampi(int(av["fps_cap"]), 10, 60)
		FPS_IDLE = maxi(10, FPS_BUSY / 2)
	if av.has("sleep_after"):
		SLEEP_AFTER = clampf(float(av["sleep_after"]), 1, 120) * 60.0
	if av.has("in_front") and bool(av["in_front"]) != in_front:
		in_front = bool(av["in_front"])
		# KWin stacks her by her window's title (desk/kwin_layer.js): under the
		# desk's widgets as "ariadne2-pet", over them as "ariadne2-pet-front".
		get_window().title = "ariadne2-pet-front" if in_front else "ariadne2-pet"
	if av.has("furniture") and bool(av["furniture"]) != furniture:
		furniture = bool(av["furniture"])
		if room:
			room.visible = furniture
			if not furniture:
				_unperch_now()
	if av.has("room_depth"):
		room_depth = clampf(float(av["room_depth"]), 5.0, 10.0) * 0.3048
		depth = clampf(depth, -room_depth, 0.0)
		if room:
			room.arrange()
	if av.has("size") and absf(float(av["size"]) - PPM) > 0.5:
		PPM = clampf(float(av["size"]), 200, 840)
		screen = Vector2.ZERO                 # forces the camera to re-fit
	# Hidden while she wears another body (a Live2D model: ariadne2/pet2d).
	var want_path := _model_path(str(av.get("model", "aries")))
	if OS.get_environment("PET_MODEL") == "" and want_path != "" and want_path != body_path \
			and ResourceLoader.exists(want_path):
		_load_body(want_path)
		_play("Idle")
	outfit = {"jacket": bool(av.get("jacket", true)), "weapon": bool(av.get("weapon", false))}
	_dress()
	var want_shown: bool = bool(desk.get("body", true)) and want_path != ""
	if want_shown != shown:
		shown = want_shown
		body.visible = shown
		if not shown:
			DisplayServer.window_set_mouse_passthrough(PackedVector2Array([Vector2.ZERO, Vector2(1, 0), Vector2(1, 1)]))
			last_rect = Rect2()


# The window's real size arrives a frame or two after asking for it; the
# camera keeps one metre = PPM pixels whatever size it ends up.
func _sync_screen() -> void:
	var v := get_viewport().get_visible_rect().size
	if v != screen and v.x > 0:
		screen = v
		_frame_camera()
		if room:
			room.arrange()
		_read_layout()
		_land()
		pos.x = clampf(pos.x, 0.4, maxf(0.4, screen.x / PPM - 0.4))   # a smaller screen than assumed: keep her on it


func _process(delta: float) -> void:
	t += delta
	_sync_screen()
	_poll_core(delta)
	layout_check -= delta
	if layout_check <= 0.0 and snapshot_path == "":   # pick up layout changes every few seconds
		layout_check = 4.0
		var path := OS.get_environment("HOME") + "/.config/ariadne2/layout.json"
		if FileAccess.get_modified_time(path) != layout_mtime:
			var before := layout_mtime
			_read_layout()
			_land()
			if before != 0 and state in FREE:
				play.run("startle")               # a widget moved on the glass: she jumps

	settings_check -= delta
	if settings_check <= 0.0 and snapshot_path == "":
		settings_check = 3.0
		_read_settings()
	if not shown:
		Engine.max_fps = 5                  # still reading settings, so she can come back
		return
	_think(delta)
	_perch_frame()
	_move(delta)
	_vary()
	ap.advance(delta)                       # clips first, then her arms, head and face on top
	_tail_frame()
	_carry_frame(delta)
	_head()
	_held_frame(delta)
	play.emote_frame()
	_face_frame(delta)
	_place_body()
	_update_click_area()
	_tell(delta)
	var busy: bool = state in ["wander", "fall", "held", "react", "dance", "knocked"] or speaking or t < mood_until or (slab and slab.visible)
	Engine.max_fps = FPS_BUSY if busy else FPS_IDLE


func _think(_delta: float) -> void:
	if state in ["fall", "held"] or (state == "knocked" and t < state_until):
		return
	if allow["nap"] and state != "sleep" and t - last_activity > SLEEP_AFTER and state in ["idle", "sit", "rest"]:
		_set_state("sleep", 1e9)
		_settle_to_sleep()
		return
	if speaking and state in ["rest", "sit"]:
		yaw_target = 0.0                       # seated, she turns to him to talk
	if speaking and state in ["idle", "wander"] and not (state == "wander" and brain.doing == "attend"):
		if state == "wander":
			_set_state("idle", 2.0)
		_play("Idle_Talking", 0.3)
		yaw_target = 0.0
		return
	if t > state_until and state != "sleep":
		if state == "sit":
			_play("Idle", 0.3)                    # sitting up off the ledge comes first
			_set_state("idle", 1.2)
			return
		_choose()


func _move(delta: float) -> void:
	match state:
		"wander":
			if t < brain.follow_until:
				target_x = clampf(brain._cursor_x(), 0.6, screen.x / PPM - 0.6)   # his pointer moves; so does she
			var to := _to_target()
			var m := to.normalized() if to.length() > 0.001 else Vector2.ZERO
			var dir := signf(m.x)
			if gait == "lead" and t > gait_turn_at:
				gait = "walk"                      # done side-stepping: turn and walk straight
				_gait_clip()
			# Close enough that the stop's own slowing carries her the rest of the way.
			var stop := _stop_clip(m)
			if stop != "" and to.length() <= _stop_length(stop):
				_begin_stop(stop, m)
				return
			var step := _gait_speed() * delta
			pos.x += m.x * step
			depth = clampf(depth + m.y * step, -room_depth, 0.0)
			if gait == "walk":
				yaw_target = atan2(m.x, m.y)       # facing where she's going (strafing and backing keep it)
			if to.length() < 0.05:
				_set_state("idle", _pause())
				_play("Idle", 0.3)
				yaw_target = 0.0
			elif (pos.x < floor_span.x or pos.x > floor_span.y) and not allow["walk_off_edges"]:
				pos.x = clampf(pos.x, floor_span.x, floor_span.y)   # stays on her widget
				_set_state("idle", 2.0)
				_play("Idle", 0.3)
			elif pos.x < floor_span.x or pos.x > floor_span.y:
				# Walked off the edge of a widget: down she goes.
				_set_state("fall", 99.0)
				vel = Vector2(dir * _gait_speed(), 0.0)
				_play("Jump", 0.15)
		"stopping":
			var c: Dictionary = stop_curve.get(variant, {})
			if variant == stop_name and not c.is_empty():
				var at := stop_from + stop_dir * _curve_at(c, ap.current_animation_position) * stop_scale
				pos.x = at.x
				depth = at.y
			else:                                  # stopped: the idle took over
				_set_state("idle", _pause())
				yaw_target = 0.0
		"fall":
			var before := pos.y
			vel.y -= GRAVITY * delta
			pos += vel * delta
			depth = clampf(depth + jump_dz * delta, -room_depth, 0.0)
			roll += spin * delta
			# Screen edges are walls and a ceiling: she bounces off them.
			var right := screen.x / PPM - 0.3
			if pos.x < 0.3 or pos.x > right:
				pos.x = clampf(pos.x, 0.3, right)
				vel.x *= -0.55
				spin *= -0.6
				_feel("surprised", 0.6, 0.8)
			if pos.y + 1.6 > screen.y / PPM and vel.y > 0.0:
				vel.y = -absf(vel.y) * 0.4
			var landed := false
			for fl in floors:
				if pos.x >= fl[1] and pos.x <= fl[2] and pos.y <= fl[0] and before >= fl[0] - 0.02 \
						and (fl[0] < 0.01 or depth > -0.25):
					pos.y = fl[0]
					landed = true
			if pos.y <= 0.0:
				pos.y = 0.0
				landed = true
			if landed:
				jump_dz = 0.0
				var impact := -vel.y
				vel = Vector2.ZERO
				spin = 0.0
				_land()
				play.landed(impact > HARD_LANDING or absf(wrapf(roll, -PI, PI)) > 1.2)
				if impact > HARD_LANDING or absf(wrapf(roll, -PI, PI)) > 1.2:
					# Flat on her back, dizzy for a moment, then back up.
					roll = 0.0
					_set_state("knocked", 3.2)
					_play("Death01", 0.08)
					_feel("sorrow", 0.5, 3.0)
				else:
					roll = 0.0
					_set_state("react", 0.6)
					_play("Jump_Land", 0.1)
		"held":
			depth = lerpf(depth, 0.0, clampf(delta * 8.0, 0.0, 1.0))   # picked up: pulled to the front
		"knocked":
			pos.y = floor_y
			if t > state_until - 1.4 and clip != "LayToIdle":
				_play("LayToIdle", 0.25)
		_:
			pos.y = floor_y
	if state not in ["fall", "held"]:
		roll = lerpf(roll, 0.0, clampf(delta * 8.0, 0.0, 1.0))
	pos.x = clampf(pos.x, 0.3, screen.x / PPM - 0.3)
	if perched != "":
		yaw_target = float(perch.get("yaw", yaw_target))   # at the desk, in bed: facing the way it faces
	elif t > look_until and state not in ["wander", "stopping"]:
		yaw_target = sin(t * 0.17) * 0.25
	yaw = lerp_angle(yaw, yaw_target, clampf(delta * 5.0, 0.0, 1.0))


# --- reacting to him (docs/PET_AI_PLAN.md, phase 4) ---------------------------
const FREE := ["idle", "wander", "stopping", "rest", "dance"]

# He's talking to her (typing to her or speaking): she comes to the front and faces him.
func _attend() -> void:
	if pstate != "" and state in ["rest", "work", "workout", "idle"]:
		brain.attend()                         # where she is: sitting up in bed, turning in her chair
		_choose()
	elif state in FREE:
		brain.attend()
		_choose()


# A wiggle of his pointer near her: she notices, and comes over to it.
func _noticed() -> void:
	if state == "sleep" or not allow["seek_cursor"]:
		return
	_stir()
	_feel("joy", 0.6, 2.0)
	if state in FREE and floor_y < 0.01:
		brain.come_to_cursor()
		_choose()


# Clicked: how she takes it depends on how she feels; poked over and over, she's had enough.
func _clicked(part := "") -> void:
	clicks = clicks.filter(func(c): return t - c < 4.0)
	clicks.append(t)
	if clicks.size() >= 4 and play.run("huff"):     # poked over and over: she's had enough
		return
	if play.clicked(part):                    # her head, face, hand, middle, feet (play.gd)
		return
	brain.drop()
	life.bump("affection", 0.06 if clicks.size() < 3 else 0.0)
	_set_state("react", 2.0)
	_face_front(2.4)
	if clicks.size() >= 4:
		_feel("angry", 0.6, 2.0)
		_play("Idle_No", 0.2)
	elif _feeling("tired") > 0.9:
		_play("Stretch", 0.3)                  # half awake: a stretch and a yawn
	elif _feeling("shy") > 0.7:
		_feel(_look_key("blush"), 0.8, 2.2)
		_play("Shy", 0.3)
	elif _feeling("sorrow") > 0.6:
		_feel("joy", 0.5, 2.0)                 # cheered up a little
		_play("Yes", 0.3, 0.8)
	elif _feeling("light") > 0.9 or randf() < 0.2:
		_feel("joy", 0.9, 2.0)
		_play("Cheer", 0.2)
	else:
		_feel("joy", 0.7, 1.5)
		_play("Yes" if randf() < 0.6 else "Interact", 0.2)


# --- furniture -----------------------------------------------------------------
# Onto a piece of furniture: her body slides from where she stood to its spot
# (and up onto the cushion or the bed) while the sitting or lying-down move
# plays, and back off it while she gets up.
func _perch_on(name: String, dur: float) -> void:
	var s: Dictionary = room.spot(name)
	if s.is_empty():
		return
	perched = name
	perch = {"from": Vector3(pos.x, lift, depth), "to": s["at"], "t0": t, "dur": dur, "yaw": s["yaw"]}
	yaw_target = s["yaw"]


func _unperch(dur: float) -> void:
	if perched == "":
		return
	var s: Dictionary = room.spot(perched)
	var back: Vector2 = s.get("approach", Vector2(pos.x, depth))
	perch = {"from": Vector3(pos.x, lift, depth), "to": Vector3(back.x, 0.0, back.y), "t0": t, "dur": dur,
			"yaw": perch.get("yaw", yaw), "off": true}


# Off it at once (picked up, sent somewhere): no sliding.
func _unperch_now() -> void:
	pstate = ""
	perched = ""
	perch = {}
	lift = 0.0


func _perch_frame() -> void:
	if perch.is_empty() or not perch.has("t0"):
		return
	var u := clampf((t - float(perch["t0"])) / maxf(0.05, float(perch["dur"])), 0.0, 1.0)
	var k := smoothstep(0.0, 1.0, u)
	var p: Vector3 = (perch["from"] as Vector3).lerp(perch["to"], k)
	pos.x = p.x
	lift = p.y
	depth = p.z
	if perch.has("hips"):
		# Lying back onto the bed (or sitting up off it): her hips stay on the
		# mattress, so she rises as the clip lowers them, and settles at the end.
		var a: float = (perch["from"] as Vector3).y
		var b: float = (perch["to"] as Vector3).y
		if not perch.has("h0"):
			perch["h0"] = _hips_y()
		var follow := clampf(a + float(perch["h0"]) - _hips_y(), minf(a, b), maxf(a, b))
		lift = lerpf(follow, b, smoothstep(0.75, 1.0, u))
	if k >= 1.0:
		perch.erase("t0")                       # there; keep the facing
		if perch.has("off"):
			perched = ""
			perch = {}


# Arrived: a moment's pause, short when her plan has more to do there.
func _pause() -> float:
	return 0.8 if brain.plan_left() else randf_range(4, 9)


func _place_body() -> void:
	# Seated on a widget, her body drops by the seat height; sitting down and
	# getting up, it follows the clip's hips so she lowers onto the edge and
	# rises off it instead of popping.
	var sit := 0.0
	if floor_y > 0.01 and (_stance(variant) == "ledge" or variant.begins_with("sit_up_") or variant == "Sitting_Exit"):
		sit = 1.0
		if variant.begins_with("sit_down_"):
			sit = smoothstep(0.38, 0.72, _progress())
		elif variant.begins_with("sit_up_") or variant == "Sitting_Exit":
			sit = 1.0 - smoothstep(0.15, 0.75, _progress())
	# SIT_DROP was measured on Aries (hips 0.795 m); a taller body sits lower.
	var drop := SIT_DROP * (skel.motion_scale / 0.795 if skel and skel.motion_scale > 0.1 else 1.0)
	body.position = Vector3(pos.x, pos.y + lift - drop * sit + _ground(), depth)
	if shadow:
		# On the room's floor only (a ledge is a thin edge); fainter the higher she's up.
		shadow.visible = shown and floor_y < 0.01 and pos.y < 2.0
		shadow.position = Vector3(pos.x, 0.004, depth)
		shadow.scale = Vector3.ONE * (1.0 - clampf(pos.y / 2.5, 0.0, 0.6))
	# Roll about the point she's held by (her upper chest), not her feet.
	var pivot := Vector3(0, 1.3, 0)
	var spin := _chair_spin()
	body.rotation = Vector3(0, yaw + spin, 0.0)
	if state in ["held", "fall"]:              # rolled on the screen, whichever way she faces
		body.basis = Basis(Vector3.BACK, roll) * Basis(Vector3.UP, yaw + spin)
	if spin != 0.0:                            # round the chair's centre, not her feet
		var c: Vector3 = (room.items["chair"] as Node3D).position
		var off := body.position - Vector3(c.x, body.position.y, c.z)
		body.position = Vector3(c.x, body.position.y, c.z) + off.rotated(Vector3.UP, spin)
	if state == "held":
		# The point he grabbed sits under the pointer; she hangs from it.
		var off: Vector3 = body.basis * grab_b
		var hit = Plane(Vector3.BACK, depth + off.z).intersects_ray(cam.project_ray_origin(grab_at), cam.project_ray_normal(grab_at))
		if hit != null:
			body.position = (hit as Vector3) - off
		# Where her feet would be for the fall's pivot, so letting go doesn't jump.
		var p := body.position - Vector3(0, lift, 0) - (pivot - pivot.rotated(Vector3.BACK, roll))
		pos = Vector2(p.x, p.y)
	elif state == "fall":
		body.position += pivot - pivot.rotated(Vector3.BACK, roll)


# Spinning round on the desk chair (desk_spin_ clips lift her feet): she and
# the chair turn a full circle over the clip.
func _chair_spin() -> float:
	var a := 0.0
	if variant.begins_with("desk_spin_") and pstate.begins_with("Desk_"):
		a = TAU * smoothstep(0.15, 0.85, _progress())
	if room and room.items.has("chair"):
		(room.items["chair"] as Node3D).rotation.y = a
	return a


func _head() -> void:
	while gaze_in.get_available_packet_count() > 0:
		var xy := gaze_in.get_packet().get_string_from_ascii().split(" ")
		if xy.size() == 2:
			var c := Vector2(float(xy[0]), float(xy[1]))
			if c.distance_to(cursor) > 2.0:
				cursor_at = t
			var dx := c.x - cursor.x
			if absf(dx) > 6.0:
				if cursor_dx != 0.0 and signf(dx) != signf(cursor_dx) and cam \
						and c.distance_to(cam.unproject_position(Vector3(pos.x, pos.y + 1.0, depth))) < PPM * 1.3:
					wiggles.append(t)
				cursor_dx = dx
			cursor = c
	wiggles = wiggles.filter(func(w): return t - w < 1.2)
	if wiggles.size() >= 4 and t - noticed_at > 8.0:
		wiggles.clear()
		noticed_at = t
		play.wiggled()                         # a wave back, or over she comes
	if t - cursor_at < 2.5 and state != "sleep" and cam and bones.has("Head"):
		# Toward the pointer, from where her head is on screen; held a moment after it stops.
		var head := skel.global_transform * skel.get_bone_global_pose(bones["Head"]).origin
		var d := cursor - cam.unproject_position(head)
		look_target = Vector2(clampf(d.x / (PPM * 1.5), -1.0, 1.0), clampf(-d.y / (PPM * 1.0), -0.8, 0.8))
	elif t > look_until:
		look_target = Vector2(sin(t * 0.21) * 0.3, sin(t * 0.13) * 0.12)
	look = look.lerp(look_target, 0.12)
	_turn_head("Neck", look * 0.35)
	_turn_head("Head", look * 0.55)


# Turn a bone on top of whatever the clip did this frame, in her own space.
func _turn_head(bone: String, v: Vector2) -> void:
	if not bones.has(bone):
		return
	var i: int = bones[bone]
	var parent := skel.get_bone_parent(i)
	var parent_g := skel.get_bone_global_pose(parent).basis if parent >= 0 else Basis()
	var g := skel.get_bone_global_pose(i).basis
	var turned := Basis(Vector3.UP, v.x * 0.5) * Basis(Vector3.RIGHT, -v.y * 0.35) * g
	skel.set_bone_pose_rotation(i, (parent_g.inverse() * turned).get_rotation_quaternion())


# --- her face ---------------------------------------------------------------
func _face_frame(delta: float) -> void:
	if t >= next_blink:
		blink = 1.0
		next_blink = t + randf_range(2.2, 5.5)
	blink = maxf(0.0, blink - delta * 9.0)
	var eyes := 1.0 if state == "sleep" else clampf(blink * 1.6, 0.0, 1.0)

	if t > mood_until:
		for k in mood_target:
			mood_target[k] = 0.1 if k == "fun" else 0.0
	for k in moods:
		moods[k] = lerpf(moods[k], mood_target[k], clampf(delta * 6.0, 0.0, 1.0))

	_speech_frame(delta)
	_shape("blink", eyes * (1.0 - moods["joy"]))
	for k in moods:
		_shape(k, moods[k])
	for v in mouth:
		_shape(v, mouth[v] if allow["lip_sync"] else 0.0)
	_face_apply()


# a i u e o: step through the vowels of the sentence she's saying, at the
# pace the sentence actually lasts, opened as wide as her voice is loud.
func _speech_frame(delta: float) -> void:
	if speech_on.is_empty() and not speech.is_empty():
		speech_on = speech.pop_front()
		speech_at = 0.0
		var em: String = speech_on.get("emotion", "")
		if _emotion_key(em) != "":
			_feel(_emotion_key(em), 0.6, float(speech_on["seconds"]) + 0.5)
	var want := {"a": 0.0, "i": 0.0, "u": 0.0, "e": 0.0, "o": 0.0}
	if not speech_on.is_empty():
		speech_at += delta
		var text: String = str(speech_on["text"]).to_lower()
		var seconds: float = maxf(0.3, float(speech_on["seconds"]))
		if speech_at >= seconds:
			speech_on = {}
		elif text.length() > 0:
			var c := text[clampi(int(speech_at / seconds * text.length()), 0, text.length() - 1)]
			var open := clampf(level * 4.5, 0.25, 1.0) if speaking else 0.6
			match c:
				"a": want["a"] = open
				"i", "y": want["i"] = open * 0.8
				"u", "w": want["u"] = open * 0.8
				"e": want["e"] = open * 0.85
				"o": want["o"] = open
				" ", ",", ".", "!", "?", "m", "b", "p": pass         # lips together
				_: want["a"] = open * 0.3                           # other consonants: barely open
	for v in mouth:
		mouth[v] = lerpf(mouth[v], want[v], clampf(delta * 22.0, 0.0, 1.0))


func _shape(key: String, w: float) -> void:
	for e in face.get(key, []):
		var slot := [e[0], e[1]]
		face_slots[slot] = face_slots.get(slot, 0.0) + w * float(e[2])


# Faces add up (blinking and a sleepy face share the lids), then each shape
# is set once, clamped, and its tally cleared for the next frame.
func _face_apply() -> void:
	for slot in face_slots:
		(slot[0] as MeshInstance3D).set_blend_shape_value(slot[1], clampf(face_slots[slot], 0.0, 1.0))
		face_slots[slot] = 0.0


# Her look ("hearts") or voice emotion ("affectionate") -> a face key, using
# the richer MMD faces when this body has them.
func _look_key(look: String) -> String:
	if MMD_LOOK.has(look) and face.has(MMD_LOOK[look]):
		return MMD_LOOK[look]
	return LOOK_FACE.get(look, "joy")


func _emotion_key(em: String) -> String:
	if MMD_EMOTION.has(em) and face.has(MMD_EMOTION[em]):
		return MMD_EMOTION[em]
	return EMOTION_FACE.get(em, "")


# --- picking her up -----------------------------------------------------------
func _update_click_area() -> void:
	if snapshot_path != "":
		return
	if state in ["held", "fall"] and skel:
		var box := Rect2(cam.unproject_position(body.global_position), Vector2.ZERO)
		for b in ["Head", "LeftHand", "RightHand", "LeftFoot", "RightFoot", "Hips"]:
			if skel.find_bone(b) >= 0:
				box = box.expand(cam.unproject_position(skel.global_transform * skel.get_bone_global_pose(skel.find_bone(b)).origin))
		_set_click_rect(box.grow(36))
		return
	var sitting := clip.begins_with("Sitting") and floor_y > 0.01
	var feet := cam.unproject_position(Vector3(pos.x, pos.y - (SIT_DROP if sitting else 0.0), depth))
	var head := cam.unproject_position(Vector3(pos.x, pos.y + 1.62, depth))
	var wide := (feet.y - head.y) * 0.3                  # narrower further back
	_set_click_rect(Rect2(Vector2(feet.x - wide / 2.0, head.y - 10), Vector2(wide, feet.y - head.y + 20)))


func _set_click_rect(r: Rect2) -> void:
	if r.position.distance_to(last_rect.position) < 3 and r.size.distance_to(last_rect.size) < 3:
		return
	last_rect = r
	DisplayServer.window_set_mouse_passthrough(PackedVector2Array([
		r.position, r.position + Vector2(r.size.x, 0), r.end, r.position + Vector2(0, r.size.y)]))


func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN] \
			and event.pressed:
		_stir()
		play.run("twirl")                     # scrolled over her: round she goes
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			drag_from = event.position
			drag_moved = false
			held_vel = Vector2.ZERO
			shakes = 0
			_stir()
			if event.double_click:
				pressing = false
				play.run("joy_jump")
				return
			# Picked up once he drags; held still, it's a hug (play.gd).
			pressing = true
			press_at = t
			play.press_part = play.part_at(event.position)
			_pick_grab(event.position)
		else:
			pressing = false
			if play.holding_still:
				play.let_go()
			elif drag_moved:
				if shakes >= 6:
					play.after_landing = "shaken"
				# Let go: she keeps the speed you threw her with, and spins with it.
				_set_state("fall", 99.0)
				vel = held_vel.limit_length(MAX_THROW)
				spin = clampf(held_w - vel.x * 1.6, -9.0, 9.0)
				_play("Jump", 0.15)
				if vel.length() > 4.0:
					_feel("surprised", 0.8, 1.2)
			elif state != "held":              # a click, not a drag
				_clicked(play.press_part)
	elif event is InputEventMouseMotion and pressing:
		if event.position.distance_to(drag_from) > 4 and not drag_moved and not play.holding_still:
			drag_moved = true
			brain.drop()
			_unperch_now()
			_set_state("held", 1e9)
			_feel("surprised", 0.4, 1.0)
			_play("Held", 0.15)               # dangling while held
			grab_prev = drag_from
			grab_k = 0.0
			held_w = 0.0
			roll = 0.0
		if state != "held":
			return
		var v: Vector2 = event.velocity / PPM
		if absf(v.x) > 2.0 and signf(v.x) != signf(held_vel.x) and held_vel.x != 0.0:
			shakes += 1                        # shaken side to side
		grab_at = event.position


# Which bit of her is under the pointer: the nearest bone on screen, and the
# exact point on it, kept in that bone's space so it moves with her.
const GRAB_SEGS := [["Hips", "Spine"], ["Spine", "Chest"], ["Chest", "UpperChest"], ["UpperChest", "Neck"],
		["Neck", "Head"], ["Head", ""],
		["LeftUpperArm", "LeftLowerArm"], ["LeftLowerArm", "LeftHand"], ["LeftHand", ""],
		["RightUpperArm", "RightLowerArm"], ["RightLowerArm", "RightHand"], ["RightHand", ""],
		["LeftUpperLeg", "LeftLowerLeg"], ["LeftLowerLeg", "LeftFoot"], ["LeftFoot", "LeftToes"],
		["RightUpperLeg", "RightLowerLeg"], ["RightLowerLeg", "RightFoot"], ["RightFoot", "RightToes"]]
func _pick_grab(p: Vector2) -> void:
	grab_bone = -1
	grab_chain = []
	grab_at = p
	if skel == null or cam == null:
		return
	var best := INF
	var at := Vector3.ZERO
	var seg: Array = []
	for s in GRAB_SEGS:
		var ia := skel.find_bone(s[0])
		if ia < 0:
			continue
		var a := skel.global_transform * skel.get_bone_global_pose(ia).origin
		var b: Vector3
		if s[1] != "" and skel.find_bone(s[1]) >= 0:
			b = skel.global_transform * skel.get_bone_global_pose(skel.find_bone(s[1])).origin
		else:                                  # the top of her head, her fingers: past the joint
			var pa := skel.global_transform * skel.get_bone_global_pose(skel.get_bone_parent(ia)).origin
			b = a + (a - pa) * (1.4 if s[0] == "Head" else 0.6)
		var sa := cam.unproject_position(a)
		var sb := cam.unproject_position(b)
		var q := Geometry2D.get_closest_point_to_segment(p, sa, sb)
		var d := p.distance_to(q)
		if d < best:
			best = d
			var u := clampf((q - sa).dot(sb - sa) / maxf((sb - sa).length_squared(), 1e-6), 0.0, 1.0)
			at = a.lerp(b, u)
			grab_bone = ia
			seg = s
	if grab_bone < 0:
		return
	# The point under the pointer itself, at that bone's depth.
	var hit = Plane(Vector3.BACK, at.z).intersects_ray(cam.project_ray_origin(p), cam.project_ray_normal(p))
	if hit != null:
		at = hit
	grab_local = (skel.global_transform * skel.get_bone_global_pose(grab_bone)).affine_inverse() * at
	# Held by an arm or a leg: that limb goes up over her, straight, as she hangs from it.
	var side := "Left" if (seg[0] as String).begins_with("Left") else "Right"
	if (seg[0] as String).contains("Arm") or (seg[0] as String).contains("Hand"):
		grab_chain = [[side + "UpperArm", side + "LowerArm"], [side + "LowerArm", side + "Hand"]]
	elif (seg[0] as String).contains("Leg") or (seg[0] as String).contains("Foot"):
		grab_chain = [[side + "UpperLeg", side + "LowerLeg"], [side + "LowerLeg", side + "Foot"]]


# Held: the limb he has her by is pulled up toward his pointer, and she swings
# under the point he grabbed like a pendulum, pushed by how he moves it.
func _held_frame(delta: float) -> void:
	if state != "held" or grab_bone < 0 or delta <= 0.0:
		grab_b = Vector3(0, 1.3, 0)
		return
	grab_k = move_toward(grab_k, 1.0, delta / 0.35)
	var up := (skel.global_transform.basis.inverse() * Vector3.UP).normalized()
	for c in grab_chain:
		var i := skel.find_bone(c[0])
		var j := skel.find_bone(c[1])
		if i < 0 or j < 0:
			continue
		var g := skel.get_bone_global_pose(i)
		var cur := (skel.get_bone_global_pose(j).origin - g.origin).normalized()
		var want := cur.slerp(up, smoothstep(0.0, 1.0, grab_k) * 0.95)
		var turned := Basis(Quaternion(cur, want)) * g.basis
		var parent := skel.get_bone_parent(i)
		var parent_g := skel.get_bone_global_pose(parent).basis if parent >= 0 else Basis()
		skel.set_bone_pose_rotation(i, (parent_g.inverse() * turned).get_rotation_quaternion())
	var inv := body.global_transform.affine_inverse()
	grab_b = inv * (skel.global_transform * skel.get_bone_global_pose(grab_bone) * grab_local)
	var hips := inv * (skel.global_transform * skel.get_bone_global_pose(skel.find_bone("Hips")).origin)
	var chest := inv * (skel.global_transform * skel.get_bone_global_pose(skel.find_bone("Spine")).origin)
	# His pointer's speed and push, in metres (screen y is down).
	var v := (grab_at - grab_prev) / delta / PPM
	v.y = -v.y
	grab_prev = grab_at
	var before := held_vel
	held_vel = held_vel.lerp(v, clampf(delta * 14.0, 0.0, 1.0))
	var acc := (held_vel - before) / delta
	# Her weight (between hips and belly) hangs below the grab point at rest.
	var d := Basis(Vector3.UP, yaw) * ((hips + chest) / 2.0 - grab_b)
	var arm := maxf(Vector2(d.x, d.y).length(), 0.3)
	var rest := -PI / 2.0 - atan2(d.y, d.x)
	var e := wrapf(roll - rest, -PI, PI)
	if absf(e) > 2.9 and absf(held_w) < 0.6:
		e = 2.9 * signf(e + 0.001)             # balanced upside down: tips one way
	var grav := maxf(GRAVITY + clampf(acc.y, -20.0, 20.0) * 0.5, 2.0)
	var push := clampf(acc.x, -40.0, 40.0) * 0.6
	# Gravity eases in as the limb comes up, so a hand at her side doesn't fling her sideways first.
	grav *= 0.25 + 0.75 * grab_k * grab_k
	held_w += (-(grav / arm) * sin(e) - (push / arm) * cos(e) - 2.6 * held_w) * delta
	held_w = clampf(held_w, -12.0, 12.0)
	roll += held_w * delta


# --- the window slab ---------------------------------------------------------
# While she works in an app she holds a small glowing slab of it, like the
# desk's widgets. When it works the slab flies off toward that widget; when it
# fails it crumbles in her hands.
func _make_slab() -> void:
	slab = Node3D.new()
	add_child(slab)
	var glass := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = Vector3(0.38, 0.25, 0.025)
	glass.mesh = box
	slab_mat = StandardMaterial3D.new()
	slab_mat.albedo_color = Color(0.07, 0.05, 0.14, 0.82)
	slab_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	slab_mat.emission_enabled = true
	slab_mat.emission = Color(1.0, 0.16, 0.24)
	slab_mat.emission_energy_multiplier = 0.35
	slab_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	glass.material_override = slab_mat
	slab.add_child(glass)
	var rim := MeshInstance3D.new()
	var rbox := BoxMesh.new()
	rbox.size = Vector3(0.40, 0.27, 0.012)
	rim.mesh = rbox
	var rmat := StandardMaterial3D.new()
	rmat.albedo_color = Color(1.0, 0.16, 0.24)
	rmat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	rim.material_override = rmat
	rim.position.z = -0.012
	slab.add_child(rim)
	slab_label = Label3D.new()
	slab_label.pixel_size = 0.0016
	slab_label.font_size = 52
	slab_label.outline_size = 8
	slab_label.outline_modulate = Color(0.1, 0, 0.05)
	slab_label.modulate = Color(1.0, 0.95, 0.96)
	slab_label.position.z = 0.016
	slab.add_child(slab_label)
	crumbs = CPUParticles3D.new()
	crumbs.emitting = false
	crumbs.one_shot = true
	crumbs.amount = 70
	crumbs.lifetime = 1.3
	crumbs.explosiveness = 0.9
	crumbs.direction = Vector3(0, 1, 0.3)
	crumbs.spread = 70.0
	crumbs.initial_velocity_min = 0.6
	crumbs.initial_velocity_max = 1.8
	crumbs.gravity = Vector3(0, -6, 0)
	var shard := BoxMesh.new()
	shard.size = Vector3(0.035, 0.035, 0.01)
	var smat := StandardMaterial3D.new()
	smat.albedo_color = Color(1.0, 0.3, 0.4)
	smat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	shard.material = smat
	crumbs.mesh = shard
	add_child(crumbs)
	slab.visible = false


func _slab_show(widget: String) -> void:
	if state in ["held", "fall", "knocked", "sleep"]:
		return
	slab_widget = widget
	slab_sending = false
	slab_label.text = widget.to_upper()
	slab.scale = Vector3.ONE * 0.2
	slab.visible = true
	create_tween().tween_property(slab, "scale", Vector3.ONE, 0.25).set_trans(Tween.TRANS_BACK)


func _slab_send() -> void:
	if not slab.visible:
		return
	slab_sending = true
	var dx: float = (widget_x.get(slab_widget, pos.x + 2.0) - pos.x)
	var tw := create_tween().set_parallel(true)
	tw.tween_property(slab, "position", slab.position + Vector3(clampf(dx, -4, 4), 1.2, 0), 0.5).set_trans(Tween.TRANS_QUAD)
	tw.tween_property(slab, "scale", Vector3.ONE * 0.05, 0.5)
	tw.chain().tween_callback(func(): slab.visible = false)


func _slab_crumble() -> void:
	if not slab.visible:
		return
	crumbs.position = slab.global_position
	crumbs.restart()
	slab.visible = false


# Arms out in front, as if carrying, laid over whatever clip is playing.
func _sample_carry_pose() -> void:
	var carry := _variant_of("carry_walk_")
	if carry == "":
		carry = "Walk_Carry"
	if not ap.has_animation(carry):
		return
	ap.play(carry)
	ap.seek(0.0, true)
	for b in ["LeftShoulder", "RightShoulder", "LeftUpperArm", "RightUpperArm", "LeftLowerArm",
			"RightLowerArm", "LeftHand", "RightHand"]:
		var i := skel.find_bone(b)
		if i >= 0:
			carry_pose[i] = skel.get_bone_pose_rotation(i)
	ap.stop()


func _carry_frame(delta: float) -> void:
	if not slab.visible:
		return
	if state not in ["held", "fall", "knocked"]:
		for i in carry_pose:
			skel.set_bone_pose_rotation(i, carry_pose[i])
	var l := skel.find_bone("LeftHand")
	var r := skel.find_bone("RightHand")
	if l >= 0 and r >= 0 and not slab_sending:
		var hands := (skel.global_transform * skel.get_bone_global_pose(l).origin
				+ skel.global_transform * skel.get_bone_global_pose(r).origin) / 2.0
		slab.position = hands + Vector3(0, 0.12, 0.06)
	slab.rotation = Vector3(-0.15, 0, 0)
	# The holographic sheen: the slab's glow cycles while she works.
	slab_mat.emission = Color.from_hsv(fmod(t * 0.35, 1.0), 0.75, 1.0)
	slab_mat.emission_energy_multiplier = 0.35 + 0.25 * sin(t * 6.0)


# --- setup helpers ----------------------------------------------------------
func _find(n: Node, cls: String) -> Node:
	if n.is_class(cls):
		return n
	for c in n.get_children():
		var f := _find(c, cls)
		if f:
			return f
	return null


func _find_shapes(n: Node, shape: String) -> Array:
	var found := []
	if n is MeshInstance3D and n.mesh:
		var idx: int = n.find_blend_shape_by_name(shape)
		if idx >= 0:
			found.append([n, idx])
	for c in n.get_children():
		found.append_array(_find_shapes(c, shape))
	return found


# PET_SNAPSHOT_SEQ=sit|wake|walk|strafe|back|lead: film one behaviour over time, a frame every
# 0.4 s (path_seq_00.png ...), with the body running as it does live.
func _snapshot_seq(what: String) -> void:
	for i in 3:
		await get_tree().process_frame
	_sync_screen()
	var on_widget := what == "sit"
	pos = Vector2(screen.x / PPM / 2.0, 0.9 if on_widget else 0.0)
	floor_y = pos.y
	floor_span = Vector2(0.0, 99.0)
	yaw = 0.0
	if OS.get_environment("PET_TIME_SCALE") != "":
		Engine.time_scale = float(OS.get_environment("PET_TIME_SCALE"))
	if what.begins_with("clip:"):                # one clip, from standing
		_set_state("workout", 99.0)
		await get_tree().create_timer(0.3).timeout
		_play_variant(what.substr(5), 0.3)
		variant_until = 1e9
	if what.begins_with("state:"):               # place states in turn (states.json), from beside the first
		var chain := what.substr(6).split(",")
		var by: Vector2 = room.spot(places.spot(chain[0])).get("approach", Vector2(pos.x, -0.4))
		pos.x = by.x
		depth = by.y
		_set_state("rest", 1e9)
		if OS.get_environment("PET_HOLD") != "":
			life._hold(OS.get_environment("PET_HOLD"))
		var hold := float(OS.get_environment("PET_SEQ_HOLD")) if OS.get_environment("PET_SEQ_HOLD") != "" else 6.0
		for i in chain.size():
			get_tree().create_timer(0.3 + hold * i).timeout.connect(_play.bind(chain[i], 0.4))
		if OS.get_environment("PET_SEQ_TALK") != "":      # he talks to her that many seconds in
			get_tree().create_timer(float(OS.get_environment("PET_SEQ_TALK"))).timeout.connect(_attend)
	if what.begins_with("film:"):                # one clip, filmed frame by frame for his ComfyUI board
		var name := what.substr(5)
		depth = -0.4
		brain_quiet = true
		yaw = {"side": PI / 2, "three-quarter": 0.6}.get(OS.get_environment("PET_FILM_VIEW"), 0.0)
		yaw_target = yaw
		look_until = 1e9
		_set_state("workout", 1e9)
		await get_tree().create_timer(0.4).timeout
		if not ap.has_animation(name):
			print("FILM no clip ", name)
			get_tree().quit()
			return
		_play_variant(name, 0.0)
		variant_until = 1e9
		ground_lift = 0.0                      # not the last pose's lift: she starts on the floor
		var fps := 15.0
		var n := int(ap.get_animation(name).length * fps)
		for k in n:
			await get_tree().create_timer(1.0 / fps).timeout
			await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png(snapshot_path.replace(".png", "_film_%03d.png" % k))
		print("FILM done ", n)
		get_tree().quit()
		return
	if what.begins_with("play:"):                # one interaction (play.json), near the glass
		depth = -0.3
		_set_state("idle", 1.0)
		get_tree().create_timer(0.5).timeout.connect(func(): play.run(what.substr(5)))
	if what == "playall":                       # every interaction in turn: a frame from each, heights logged
		Engine.time_scale = float(OS.get_environment("PET_TIME_SCALE")) if OS.get_environment("PET_TIME_SCALE") != "" else 3.0
		brain_quiet = true
		var only := OS.get_environment("PET_PLAY_ONLY")
		for n in play.names():
			if only != "" and not String(n).begins_with(only):
				continue
			pos.x = screen.x / PPM / 2.0
			depth = -0.3
			yaw = 0.0
			_set_state("idle", 99.0)
			play.cool_until.clear()
			brain.plan.clear()
			if not play.run(n, true):
				print("PLAYALL %s did-not-run" % n)
				continue
			var secs := ap.get_animation(variant).length
			var lo := 9.0
			var hi := -9.0
			var hd_lo := 9.0
			for k in 6:
				await get_tree().create_timer(secs / 7.0).timeout
				var hd := skel.global_transform * skel.get_bone_global_pose(skel.find_bone("Head")).origin
				var hp := skel.global_transform * skel.get_bone_global_pose(skel.find_bone("Hips")).origin
				lo = minf(lo, hp.y)
				hi = maxf(hi, hp.y)
				hd_lo = minf(hd_lo, hd.y - hp.y)
				if k == 2:
					await RenderingServer.frame_post_draw
					get_viewport().get_texture().get_image().save_png(snapshot_path.replace(".png", "_all_%s.png" % n))
			print("PLAYALL %s %s hips %.2f-%.2f head-over-hips min %.2f" % [n, variant, lo, hi, hd_lo])
			await get_tree().create_timer(secs / 7.0 + 0.3).timeout
		get_tree().quit()
		return
	if what.begins_with("gesture:"):             # his pointer doing something at her (play.gd reads it)
		depth = -0.3
		_set_state("idle", 99.0)
		play.test = true
		_gesture(what.substr(8))
	if what.begins_with("grab:"):                # picked up by a bone, lifted, swung, held still
		depth = -0.3
		_set_state("idle", 99.0)
		_grab_test(what.substr(5))
	if what.begins_with("do:"):                  # one activity of hers, from the middle of the room
		depth = -0.4
		var act := what.substr(3)
		brain.doing = act
		brain.plan = brain._plan(act, false)
		_set_state("idle", 0.2)
	match what:
		"sit":
			_set_state("sit", 99.0)
			_play("Sitting_Idle", 0.4)
		"wake":
			_set_state("sleep", 1e9)
			_play("Crouch_Idle", 0.0, 0.6)
			await get_tree().create_timer(0.5).timeout
			_wake()
		"brain":                                   # her own choices, sped up (PET_TIME_SCALE)
			Engine.time_scale = float(OS.get_environment("PET_TIME_SCALE")) if OS.get_environment("PET_TIME_SCALE") != "" else 1.0
			_set_state("idle", 0.5)
		"liedown":                                 # lies down on the floor, then gets up again (side on)
			yaw = PI / 2
			yaw_target = yaw
			look_until = 1e9
			_set_state("rest", 99.0)
			_play("LieDown", 0.4)
			await get_tree().create_timer(5.5).timeout
			_set_state("idle", 99.0)
			_play("Idle", 0.4)
		"attend", "follow":                        # he talks to her / wiggles his pointer, she's at the back
			depth = -room_depth * 0.8
			yaw = 2.6
			_set_state("idle", 99.0)
			await get_tree().create_timer(0.3).timeout
			if what == "attend":
				_attend()
			else:
				cursor_at = t
				cursor = Vector2(screen.x * 0.75, screen.y * 0.7)
				_noticed()
		"deep":
			target_x = pos.x + 2.5
			target_z = -room_depth                 # into the back of the room
			_set_off(99.0)
			gait = "walk"
			_gait_clip()
		"walk", "strafe", "back", "lead":
			target_x = pos.x + (0.7 if what in ["strafe", "back"] else 3.0)
			target_z = depth
			if what == "back":
				yaw = -1.2                         # facing left, backing to the right
			_set_off(99.0)
			gait = what
			gait_turn_at = t + 0.8
			_gait_clip()
	if OS.get_environment("PET_SEQ_HEAD") != "":
		tail_low = [9.0, 9.0]
		skel.skeleton_updated.connect(func():
			for b in skel.get_bone_count():
				var nm := skel.get_bone_name(b)
				if nm.begins_with("Tail"):                # nearest any tail joint gets to her shins and feet
					var tp := skel.global_transform * skel.get_bone_global_pose(b).origin
					for fb in ["LeftFoot", "RightFoot", "LeftToes", "RightToes"]:
						var fi := skel.find_bone(fb)
						if fi >= 0:
							var fp := skel.global_transform * skel.get_bone_global_pose(fi).origin
							var pp := skel.global_transform * skel.get_bone_global_pose(skel.get_bone_parent(fi)).origin
							tail_feet = minf(tail_feet, tp.distance_to(Geometry3D.get_closest_point_to_segment(tp, pp, fp)))
				if nm == "Tail_3":                   # sideways from her hips, in her own frame
					var inv := body.global_transform.affine_inverse()
					tail_x = (inv * (skel.global_transform * skel.get_bone_global_pose(b).origin)).x \
							- (inv * (skel.global_transform * skel.get_bone_global_pose(skel.find_bone("Hips")).origin)).x
				var k := 0 if nm.begins_with("Tail") else (1 if nm.begins_with("Hair") else -1)
				if k >= 0:
					tail_low[k] = minf(tail_low[k], (skel.global_transform * skel.get_bone_global_pose(b).origin).y))
	var dt := float(OS.get_environment("PET_SEQ_DT")) if OS.get_environment("PET_SEQ_DT") != "" else 0.4
	var feet := OS.get_environment("PET_SEQ_FEET") != ""      # log where her feet are, for slide checks
	for i in 14:
		await get_tree().create_timer(dt).timeout
		await RenderingServer.frame_post_draw
		if OS.get_environment("PET_SEQ_HEAD") != "":      # head and hips heights: catches her upside down
			var hd := skel.global_transform * skel.get_bone_global_pose(skel.find_bone("Head")).origin
			var hp := skel.global_transform * skel.get_bone_global_pose(skel.find_bone("Hips")).origin
			print("HEAD %d head(%.2f %.2f %.2f) hips(%.2f %.2f %.2f) %s %s" % [i, hd.x, hd.y, hd.z, hp.x, hp.y, hp.z, state, variant])
			if not tail_low.is_empty():              # her tail and hair after the springs: on the floor, never under it
				print("TAIL %d lowest tail %.3f hair %.3f (floor %.2f) tip_x %.2f ahead %.2f up %.2f feet %.3f" % [i, tail_low[0], tail_low[1], pos.y + lift, tail_x, walk_wag, tail_up, tail_feet])
				tail_feet = 9.0
				tail_low = [9.0, 9.0]
		if feet:
			for b in ["LeftToes", "RightToes"]:
				var g := skel.global_transform * skel.get_bone_global_pose(skel.find_bone(b)).origin
				print("FOOT %d %s %.3f %.3f %s %s %.2f" % [i, b, g.x, g.y, state, variant, pos.x])
		get_viewport().get_texture().get_image().save_png(snapshot_path.replace(".png", "_seq_%02d.png" % i))
	get_tree().quit()


# A test run's hand picking her up by one bone: press on it, lift, swing side
# to side, hold still. Logs how far the grabbed point is from the pointer.
func _grab_test(bone: String) -> void:
	await get_tree().create_timer(0.6).timeout
	var p := cam.unproject_position(skel.global_transform * skel.get_bone_global_pose(skel.find_bone(bone)).origin)
	var e := InputEventMouseButton.new()
	e.button_index = MOUSE_BUTTON_LEFT
	e.pressed = true
	e.position = p
	_input(e)
	for i in 150:
		var at := p + Vector2(0, -minf(i, 30) * 8.0)
		if i >= 50 and i < 110:
			at.x += sin((i - 50) * 0.2) * 160.0
		var m := InputEventMouseMotion.new()
		m.position = at
		m.velocity = (at - grab_at) * 30.0
		_input(m)
		await get_tree().process_frame
		if i % 10 == 0 and state == "held":
			var gp := cam.unproject_position(skel.global_transform * skel.get_bone_global_pose(grab_bone) * grab_local)
			print("GRAB %d %s roll %.2f gap %.1f px" % [i, bone, roll, gp.distance_to(grab_at)])


# A test run's pointer: stroking her head, tickling her, circling her, held still, clicks on her parts.
func _gesture(g: String) -> void:
	await get_tree().create_timer(0.6).timeout
	var head := cam.unproject_position(skel.global_transform * skel.get_bone_global_pose(skel.find_bone("Head")).origin)
	var belly := cam.unproject_position(skel.global_transform * skel.get_bone_global_pose(skel.find_bone("Spine")).origin)
	var r := (head - belly).length()
	if g.begins_with("click:"):
		_clicked(g.substr(6))
		return
	for i in 240:
		var a := i * 0.35
		match g:
			"pat": cursor = head + Vector2(sin(a) * r * 0.3, -r * 0.35 + cos(a * 2.0) * 4.0)
			"tickle": cursor = belly + Vector2(sin(a * 4.0) * r * 0.25, 0.0)
			"circle": cursor = belly + Vector2(cos(a * 0.5), sin(a * 0.5)) * r * 2.2
			"still": cursor = belly + Vector2(r * 0.9, -r * 0.2) if i == 0 else cursor
			"away": cursor_at = t - 700.0 if i == 2 else cursor_at
		if g != "still" and g != "away":
			cursor_at = t
		elif i == 0:
			cursor_at = t
		if g == "away" and i == 120:
			cursor = cursor + Vector2(40, 0)
			cursor_at = t                      # he's back
		await get_tree().process_frame


# PET_SNAPSHOT=path: render her in a few clips, one image each, then quit.
func _snapshot() -> void:
	floors.append([0.9, 0.0, 99.0])
	if OS.get_environment("PET_SNAPSHOT_SEQ") != "":
		await _snapshot_seq(OS.get_environment("PET_SNAPSHOT_SEQ"))
		return
	var shots := [["Idle", 0.0, 0.0, "idle"], ["Walk", 1.2, 0.0, "walk"], ["Sitting_Idle", 0.0, 0.9, "sit"],
			["Dance", 0.0, 0.0, "dance"], ["Idle_Talking", 0.0, 0.0, "talk"], ["Idle", 0.0, 0.0, "slab"],
			["Jump", 0.0, 0.6, "thrown"]]
	for i in 3:
		await get_tree().process_frame
	_sync_screen()
	for s in shots:
		pos = Vector2(screen.x / PPM / 2.0, s[2])
		floor_y = s[2]
		yaw = s[1]
		clip = ""
		_play(s[0], 0.0)
		ap.advance(0.7)
		state = "fall" if s[3] == "thrown" else "idle"
		roll = 0.9 if s[3] == "thrown" else 0.0
		if s[3] == "slab":
			_slab_show("spotify")
			slab.scale = Vector3.ONE
		else:
			slab.visible = false
		_carry_frame(0.016)
		_head()
		mouth["a"] = 0.8 if s[3] == "talk" else 0.0
		for v in mouth:
			_shape(v, mouth[v])
		_face_apply()
		_place_body()
		await get_tree().process_frame
		await get_tree().process_frame
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(snapshot_path.replace(".png", "_" + s[3] + ".png"))
	get_tree().quit()
