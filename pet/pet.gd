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
	"angry": {"Eyebrow_Angry": 0.7, "Eyebrow_Furious": 1.0, "Eyebrow_Close": 0.6, "Eye_Sharp": 1.0, "Eye_Inner_Down": 0.6,
			"Eye_Tail_Up": 0.4, "Pupil_Small": 0.45, "Mouth_Sad": 0.85, "Mouth_Narrow": 0.35, "CheekPuff": 0.4},
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
	# Not moods: driven by her body (_face_frame): hands up by her eyes, flung
	# about, landed hard.
	"squint": {"Eye_Sharp": 0.5, "Eye_Closed": 0.4, "Eyebrow_Close": 0.5, "Eye_Inner_Down": 0.4, "Mouth_Narrow": 0.2},
	"flung": {"Eyebrow_Surprised": 1.0, "Eye_Surprised": 1.0, "Pupil_Small": 0.7, "Mouth_Wide": 0.5, "Mouth_O": 0.3},
	"wince": {"Eye_Closed": 0.75, "Eyebrow_Sad": 0.6, "Eye_Inner_Up": 0.4, "Mouth_Narrow": 0.5, "Mouth_Sad": 0.3},
	"sweat": {"Sweat1": 1.0, "Eyebrow_Sad": 0.4, "Mouth_Narrow": 0.2},
	"a": {"Mouth_A": 1.0}, "i": {"Mouth_I": 1.0}, "u": {"Mouth_U": 1.0}, "e": {"Mouth_E": 1.0}, "o": {"Mouth_O": 1.0},
}
# Booth avatars (Kuromoji, Shiromoji: pet/import/avatar_export.py) carry the
# standard MMD morphs by their Japanese names, and VRChat's mouth shapes.
# Eyes: まばたき blink, 笑い smiling, なごみ soft, はぅ >< , びっくり wide,
# じと目 half-lidded, ｷﾘｯ sharp, はぁと hearts, 星目 stars, 瞳小 small pupils,
# ハイライト消 dull. Brows: 真面目 serious, 困る troubled, にこり cheerful,
# 怒り angry, 上 raised, 下 lowered. Mouth: にやり smirk, にっこり smile, ワ
# wide, 口角上げ / 口角下げ corners up / down.
const BOOTH_FACE := {
	"blink": {"まばたき": 1.0},
	"joy": {"笑い": 0.8, "にっこり": 0.8, "にこり": 0.6},
	"sorrow": {"困る": 1.0, "口角下げ": 0.7},
	"angry": {"怒り": 1.0, "ｷﾘｯ": 0.6, "口角下げ": 0.7, "瞳小": 0.3},
	"surprised": {"びっくり": 1.0, "上": 0.8, "vrc.v_oh": 0.4, "瞳小": 0.4},
	"fun": {"なごみ": 0.5, "にやり": 0.4},
	"hearts": {"はぁと": 1.0, "にっこり": 0.6},
	"blush": {"なごみ": 0.4, "にっこり": 0.4, "困る": 0.3},
	"smirk": {"にやり": 1.0, "じと目": 0.3},
	"tears": {"困る": 1.0, "口角下げ": 0.8},
	"gloom": {"ハイライト消": 1.0, "困る": 0.6, "じと目": 0.5},
	"sleepy": {"まばたき": 0.55, "下": 0.3},
	"thoughtful": {"じと目": 0.3, "真面目": 0.5},
	"bored": {"じと目": 1.0},
	"dizzy": {"ハイライト消": 1.0, "瞳小": 0.7, "困る": 0.5, "ワ": 0.3},
	"stars": {"星目": 1.0, "ワ": 0.6},
	"squint": {"まばたき": 0.4, "じと目": 0.4, "真面目": 0.5},
	"flung": {"びっくり": 1.0, "瞳小": 0.7, "ワ": 0.6, "上": 1.0},
	"wince": {"はぅ": 1.0, "困る": 0.6},
	"sweat": {"困る": 0.4},
	"a": {"vrc.v_aa": 1.0}, "i": {"vrc.v_ih": 1.0}, "u": {"vrc.v_ou": 1.0}, "e": {"vrc.v_e": 1.0}, "o": {"vrc.v_oh": 1.0},
}
const MMD_LOOK := {"stars": "stars", "hearts": "hearts", "blush": "blush", "smirk": "smirk", "tears": "tears",
		"gloom": "gloom", "sleepy": "sleepy", "thoughtful": "thoughtful", "eyeroll": "bored", "dizzy": "dizzy"}
const MMD_EMOTION := {"affectionate": "hearts", "flirtatious": "smirk", "embarrassed": "blush", "shy": "blush",
		"sarcastic": "smirk", "ironic": "smirk", "bored": "bored", "tired": "sleepy", "contemplative": "thoughtful",
		"anxious": "sweat", "nervous": "sweat", "confused": "dizzy", "euphoric": "stars", "excited": "stars",
		"hurt": "tears", "melancholic": "gloom", "dejected": "gloom"}
const MOUTH_KEYS := ["blink", "a", "i", "u", "e", "o", "squint", "flung", "wince"]
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
var outfit := {"name": "", "weapon": false}   # Avatar settings: her outfit ("" its usual), weapon in hand
var outfits := {}                          # this body's outfits (models/<name>.json)
var outfit_firm := false                   # clothes that hold her chest in (a jacket, a sweater)
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
var blink_again := false                   # a double blink's second
var raw_shapes := {}                       # face shape name -> [[mesh, index]], for the living layer
var micro := ""                            # a passing micro-expression (_alive_face)
var micro_at := -9.0
var micro_len := 1.0
var micro_next := 4.0
var squint := 0.0
var flung := 0.0
var wince := 0.0
var pupil_big := 0.0
var mmd_face := false                      # the MMD face set (her own shapes by name for the living layer)
var face_test := ""                        # a test run (PET_SNAPSHOT_SEQ=faces) holds one face
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
var grab_at := Vector2.ZERO                # the pointer, while he holds her
var grab_prev := Vector2.ZERO
var grab_z := 0.0                          # depth of the point he holds, drawn to the glass
var ragdoll                                # ragdoll.gd: her physical bones while held and tumbling
var poke                                   # poke.gd: his pointer pressing on her (poke mode)
var things                                 # things.gd: a bug, a leaf... in one of her episodes
# How she walks this trip (docs/PET_EPISODES_PLAN.md): an episode asks for one
# (walk_style: tiptoeing up on a bug), else her mood picks one as she sets off.
var walk_style := ""
var trip_style := ""
var look_node: Node3D = null               # watching a thing (a bug crawling) till look_until
var look_spot := Vector3.INF               # or a point (the floor in front of her)
var poking := false
var asked_at := -1e9                       # when he last asked her something (chat or voice)
var saluted := true                        # her first step for it has been taken (with a salute, now and then)
var squish                                 # squish.gd: her arms pressing her breasts aside
var poke_z := 0.0                          # depth of the point he's pressing
# What a left click on her does, picked from her right-click menu: "play" (tap,
# hug, pick up and throw), "poke" (press on her) or "pin" (pick up, let go,
# she stays hanging there).
var mode := "play"
var menu: PopupMenu
const MODES := ["play", "poke", "pin"]
const MODE_FILE := "user://click_mode"
# While a game is in front she closes (exit GAME_EXIT, which bin/ariadne2 waits
# out), keeping where she was in PLACE_FILE for when she comes back.
var GAME_FLAG := OS.get_environment("XDG_RUNTIME_DIR").path_join("ariadne2-game") if OS.get_environment("XDG_RUNTIME_DIR") != "" else "/tmp/ariadne2-game"
const GAME_EXIT := 42
const PLACE_FILE := "user://place.json"
const RAGDOLL := ["held", "tumble"]
const DEPTH_STEP := 0.25                   # metres a wheel notch carries her, held
var last_rect := Rect2()
var snapshot_path := OS.get_environment("PET_SNAPSHOT")


func _ready() -> void:
	# A game in front (ariadne2/desk/game.py): stay closed; bin/ariadne2 starts
	# her again when it's gone.
	if snapshot_path == "" and FileAccess.file_exists(GAME_FLAG):
		set_process(false)
		set_physics_process(false)
		set_process_input(false)
		get_tree().quit(GAME_EXIT)
		return
	if FileAccess.file_exists(MODE_FILE):
		var m := FileAccess.get_file_as_string(MODE_FILE).strip_edges()
		if m in MODES:
			mode = m
	get_viewport().transparent_bg = true
	get_window().title = "ariadne2-pet"      # KWin finds her by this (desk/kwin_layer.js)
	_cover_ultrawide()
	# PET_MODEL picks the 3D body for a test run (PET_SNAPSHOT); otherwise
	# the Avatar "Model" setting does (_read_settings), Aries until it's read.
	var forced := OS.get_environment("PET_MODEL")
	var dressed := OS.get_environment("PET_OUTFIT")          # a test shot's outfit: "Swimsuit" or "No jacket,weapon"
	if dressed != "":
		outfit = {"name": dressed.get_slice(",", 0).replace("nojacket", "No jacket").replace("weapon", ""),
				"weapon": dressed.contains("weapon")}
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
	things = load("res://things.gd").new()
	add_child(things)
	things.setup(self)
	_read_layout()
	pos = Vector2(screen.x / PPM * 0.3, 0.0)
	if FileAccess.file_exists(PLACE_FILE):            # back after a game: where she was
		var was = JSON.parse_string(FileAccess.get_file_as_string(PLACE_FILE))
		DirAccess.remove_absolute(ProjectSettings.globalize_path(PLACE_FILE))
		if was is Dictionary and Time.get_unix_time_from_system() - float(was.get("at", 0)) < 86400.0:
			pos.x = clampf(float(was.get("x", pos.x)), 0.2, screen.x / PPM - 0.2)
			depth = clampf(float(was.get("depth", 0.0)), -room_depth, 0.0)
			yaw = float(was.get("yaw", 0.0))
			yaw_target = yaw
	_land()
	_play("Idle")
	if snapshot_path != "":
		_snapshot.call_deferred()
	else:
		gaze_in.bind(GAZE_UDP, "127.0.0.1")
		_connect()


# A game came to the front: note where she is, and close.
func _game_sleep() -> void:
	var f := FileAccess.open(PLACE_FILE, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify({"x": pos.x, "depth": depth, "yaw": yaw, "at": Time.get_unix_time_from_system()}))
		f.close()
	get_tree().quit(GAME_EXIT)


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
	var cfg := path.get_basename() + ".json"
	var got = JSON.parse_string(FileAccess.get_file_as_string(cfg)) if FileAccess.file_exists(cfg) else null
	outfits = got if got is Dictionary else {}
	# MMD-style bodies tuck the skin in under clothes with "Shrink_for..." shapes.
	for m in body.find_children("*", "MeshInstance3D", true, false):
		for i in (m as MeshInstance3D).mesh.get_blend_shape_count() if (m as MeshInstance3D).mesh else 0:
			if String((m as MeshInstance3D).mesh.get_blend_shape_name(i)).begins_with("Shrink_for"):
				(m as MeshInstance3D).set_blend_shape_value(i, 1.0)
	# Which face set: MMD-style names if it has them, else VRoid's. Each key ->
	# [[mesh, index, weight], ...]; every slot is written every frame (_face_apply).
	var mmd := not _find_shapes(body, "Eye_Joyful").is_empty()
	var booth := not mmd and not _find_shapes(body, "まばたき").is_empty()
	mmd_face = mmd
	var map: Dictionary = MMD_FACE if mmd else (BOOTH_FACE if booth else FACE)
	face = {}
	face_slots = {}
	raw_shapes = {}
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
	if squish:
		squish.size = leg_length / JANE_LEG if leg_length > 0.1 else 1.0
	carry_pose = {}
	_sample_carry_pose()
	clip = ""
	body.visible = shown
	# A VRM brings its own toon shader (MToon); a GLB body gets one here, and a
	# flat fill light so its shade side isn't black.
	var glb := path.ends_with(".glb")
	if glb:
		_toonify(body, float(outfits.get("tone", {}).get("albedo", 1.0)))
	_add_jiggle()
	_add_ragdoll()
	var tone: Dictionary = outfits.get("tone", {})
	if fill:
		fill.environment.ambient_light_energy = TOON_FILL * float(tone.get("fill", 1.0)) if glb else 0.0
	if sun:
		sun.light_energy = SUN * float(tone.get("light", 1.0))
	weapon = null                              # went with the old body
	_dress()


# Her outfit and weapon (Avatar settings), for bodies that have them. A body's
# outfits are models/<name>.json: each shows its meshes and hides every other
# outfit's, and sets blend shapes (Jane without her jacket: the top it was
# squeezing, "Shrink_forJacket", fills out again). An outfit he hasn't picked
# for this body (or "") is its default. The weapon is <model>_weapon.glb
# (pet/import/jane_export.py), gripped in her right hand.
var WEAPON_GRIP := Transform3D(Basis.from_euler(Vector3(0, 0, -PI / 2)), Vector3(0.0, 0.07, 0.02))
func _dress() -> void:
	if not body:
		return
	var all: Dictionary = outfits.get("outfits", {})
	var pick: String = outfit["name"] if all.has(outfit["name"]) else str(outfits.get("default", ""))
	var o: Dictionary = all.get(pick, {})
	var pieces := {}
	for k in all:
		for m in all[k].get("show", []):
			pieces[m] = true
	for m in pieces:
		var n := body.find_child(m, true, false)
		if n is Node3D:
			(n as Node3D).visible = m in o.get("show", [])
	for m in outfits.get("hide", []):
		var n := body.find_child(m, true, false)
		if n is Node3D:
			(n as Node3D).visible = false
	# Every outfit's shapes, then this one's: "Mesh/Shape" for one mesh (fit keys
	# share names like "Key 1" across pieces), "Shape" for any mesh that has it.
	var shapes: Dictionary = (outfits.get("shapes", {}) as Dictionary).duplicate()
	shapes.merge(o.get("shapes", {}), true)
	for m in body.find_children("*", "MeshInstance3D", true, false):
		for sh in shapes:
			var only_on := String(sh).get_slice("/", 0) if String(sh).contains("/") else ""
			if only_on != "" and only_on != String(m.name):
				continue
			var idx := (m as MeshInstance3D).find_blend_shape_by_name(String(sh).get_slice("/", 1) if only_on != "" else sh)
			if idx >= 0:
				(m as MeshInstance3D).set_blend_shape_value(idx, float(shapes[sh]))
	outfit_firm = bool(o.get("firm", false))
	var only := OS.get_environment("PET_ONLY")              # a test shot of just these meshes: "Visor_Cap,Body"
	if only != "":
		for m in body.find_children("*", "MeshInstance3D", true, false):
			(m as MeshInstance3D).visible = String(m.name) in only.split(",")
	_breast_feel()
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
	["Breast_1.L", "Breast_2.L", 2.6, 0.32, 0.35, 0.03], ["Breast_1.R", "Breast_2.R", 2.6, 0.32, 0.35, 0.03],   # soft; firm at her chest (_add_jiggle)
	["Butt.L", "Butt.L", 4.0, 0.55, 0.0, 0.03], ["Butt.R", "Butt.R", 4.0, 0.55, 0.0, 0.03],      # firm: a bounce, not a swing
	["JacketBelt_1.L", "JacketBelt_3.L", 0.6, 0.4, 0.6, 0.01], ["JacketBelt_1.R", "JacketBelt_3.R", 0.6, 0.4, 0.6, 0.01],
	["Necktie_1", "Necktie_3", 0.8, 0.4, 0.5, 0.012],
	["WaistBag", "WaistBag_Zipper", 1.2, 0.4, 0.5, 0.02],
	["Shoe_A_1.L", "Shoe_A_2.L", 0.7, 0.4, 0.7, 0.008], ["Shoe_A_1.R", "Shoe_A_2.R", 0.7, 0.4, 0.7, 0.008],
	["Shoe_B_1.L", "Shoe_B_2.L", 0.7, 0.4, 0.7, 0.008], ["Shoe_B_1.R", "Shoe_B_2.R", 0.7, 0.4, 0.7, 0.008],
	# Booth avatars (Kuromoji, Shiromoji): twin tails, back, side and top hair,
	# bangs, cat ears, a cat's tail (4 bones, else 3), earrings, a necklace.
	["Hair_Twintails_1_L", "Hair_Twintails_3_L", 0.6, 0.35, 0.4, 0.03], ["Hair_Twintails_1_R", "Hair_Twintails_3_R", 0.6, 0.35, 0.4, 0.03],
	["Hair_Back_1_1", "Hair_Back_1_2", 0.9, 0.4, 0.3, 0.02],
	["Hair_Back_2_1_L", "Hair_Back_2_2_L", 0.9, 0.4, 0.3, 0.018], ["Hair_Back_2_1_R", "Hair_Back_2_2_R", 0.9, 0.4, 0.3, 0.018],
	["Hair_Side_1_1_L", "Hair_Side_1_2_L", 1.0, 0.45, 0.25, 0.015], ["Hair_Side_1_1_R", "Hair_Side_1_2_R", 1.0, 0.45, 0.25, 0.015],
	["Hair_Side_2_1_L", "Hair_Side_2_2_L", 1.0, 0.45, 0.25, 0.015], ["Hair_Side_2_1_R", "Hair_Side_2_2_R", 1.0, 0.45, 0.25, 0.015],
	["Hair_Bang_1_1", "hair_bang_1_3", 1.4, 0.5, 0.15, 0.01],
	["Hair_Bang_2_1_L", "Hair_Bang_2_2_L", 1.4, 0.5, 0.15, 0.01], ["Hair_Bang_2_1_R", "Hair_Bang_2_2_R", 1.4, 0.5, 0.15, 0.01],
	["Hair_Top_1", "Hair_Top_2", 1.2, 0.45, 0.2, 0.015],
	["Kemomimi_L", "Kemomimi_L", 0.8, 0.22, 0.04, 0.01], ["Kemomimi_R", "Kemomimi_R", 0.8, 0.22, 0.04, 0.01],
	["Tail_1", "Tail_4", 0.6, 0.3, 0.35, 0.02], ["Tail_1", "Tail_3", 0.6, 0.3, 0.35, 0.02],
	["Earrings_1_L", "Earrings_2_L", 1.0, 0.3, 0.5, 0.008], ["Earrings_1_R", "Earrings_2_R", 1.0, 0.3, 0.5, 0.008],
	["Necklace_1", "Necklace_2", 0.9, 0.4, 0.6, 0.01],
	["Breast_L", "Breast_L", 3.6, 0.4, 0.15, 0.03], ["Breast_R", "Breast_R", 3.6, 0.4, 0.15, 0.03],
	["Butt_L", "Butt_L", 4.0, 0.55, 0.0, 0.03], ["Butt_R", "Butt_R", 4.0, 0.55, 0.0, 0.03],
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


func _add_ragdoll() -> void:
	if ragdoll:
		ragdoll.anchor.queue_free()
		ragdoll.env.queue_free()
		ragdoll.queue_free()
	ragdoll = load("res://ragdoll.gd").new()
	add_child(ragdoll)
	ragdoll.build(self, skel)
	ragdoll.build_env(screen / PPM, room_depth, floors)


# The jacket and the straps under it are bound to her chest, not her breasts:
# with the soft springs they swung out through both. A jacket holds them in,
# so with it on they're firm (as they were before the soft springs) and hang
# straight; off, they're soft and weighted to the tip.
var breast_chains: Array[int] = []
func _breast_feel() -> void:
	if jiggle == null:
		return
	var on: bool = outfit_firm
	if squish:
		squish.firm = on
	for i in breast_chains:
		# (stiffer than they were: the swing is a little turn now; squish.gd
		# moves them as a whole, so they don't stretch)
		jiggle.set_stiffness(i, 4.5 if on else 3.6)
		jiggle.set_drag(i, 0.55 if on else 0.4)
		jiggle.set_gravity(i, 0.0 if on else 0.15)


# A straight line along a spring chain, root to tip.
func _ramp(root: float, tip: float) -> Curve:
	var c := Curve.new()
	c.add_point(Vector2(0.0, root))
	c.add_point(Vector2(1.0, tip))
	return c


func _add_jiggle() -> void:
	var have := func(b: String) -> bool: return skel.find_bone(b) >= 0
	var roots := {}
	var chains := JIGGLE.filter(func(c):
		# (one chain per root: a 4-bone tail, else its 3-bone fallback)
		if not (have.call(c[0]) and have.call(c[1])) or roots.has(c[0]):
			return false
		roots[c[0]] = true
		return true)
	jiggle = null
	squish = null
	tail_bones.clear()
	tail_rest.clear()
	# Poking goes after her clips and before the springs, so hair and chest follow it.
	poke = load("res://poke.gd").new()
	poke.name = "Poke"
	skel.add_child(poke)
	if chains.is_empty():
		return
	var sim := SpringBoneSimulator3D.new()
	jiggle = sim
	breast_chains.clear()
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
		if String(c[0]).begins_with("Breast"):
			breast_chains.append(i)
		if String(c[0]).begins_with("Breast") and c[0] != c[1]:
			# Weighted toward the tip: firm where they meet her chest, softer, heavier
			# and slower to settle further out, so the near part barely moves and the
			# outer part sways and lags behind her. (A one-bone breast, as on the
			# Booth avatars, has no length to ramp along: the curve came out NaN.)
			sim.set_stiffness_damping_curve(i, _ramp(1.0, 0.3))
			sim.set_gravity_damping_curve(i, _ramp(0.15, 1.0))
			sim.set_drag_damping_curve(i, _ramp(1.0, 0.55))
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
	# Her breasts rest on her chest (its ball would shove them out); an arm
	# against them presses them aside softly (squish.gd), after the springs.
	if not breast_chains.is_empty():
		squish = load("res://squish.gd").new()
		squish.name = "Squish"
		skel.add_child(squish)
		squish.setup(skel)
		squish.firm = outfit_firm
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
		if state == "tumble":
			ground = 0.0                       # on the floor in a heap: her tail lies on it
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
const SUN := 1.1
var sun: DirectionalLight3D
# A body's "tone" (models/<name>.json): albedo times its colours, light and fill
# times the sun and the fill. Shiromoji's near-white skin and hair, lit for
# Jane's tan, washed out to pure white with no shade.
const OUTLINE_M := 0.0016                   # outline thickness, metres
func _toonify(root: Node, albedo := 1.0) -> void:
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
			if albedo != 1.0:
				m.albedo_color = Color(m.albedo_color.r * albedo, m.albedo_color.g * albedo, m.albedo_color.b * albedo, m.albedo_color.a)
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
	sun = DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-30, 20, 0)
	sun.light_energy = SUN * float(outfits.get("tone", {}).get("light", 1.0))
	add_child(sun)
	# Ambient fill, on only for bodies without their own toon shader (_load_body).
	fill = WorldEnvironment.new()
	fill.environment = Environment.new()
	fill.environment.background_mode = Environment.BG_CLEAR_COLOR
	fill.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	fill.environment.ambient_light_color = Color(1.0, 0.96, 0.98)
	fill.environment.ambient_light_energy = TOON_FILL * float(outfits.get("tone", {}).get("fill", 1.0)) \
			if body_path.ends_with(".glb") else 0.0
	add_child(fill)


# --- the surfaces she can stand on ------------------------------------------
# The bottom of the screen, plus the top edge of every visible widget, read
# straight from the desk's saved layout.
func _read_layout() -> void:
	floors = [[0.0, 0.0, screen.x / PPM]]
	widget_x.clear()
	if ragdoll:
		ragdoll.build_env(screen / PPM, room_depth, floors)    # her walls and floor for tumbling
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
				# The first thing she does for what he just asked: now and then a
				# playful salute ("on it"), then she gets to it.
				if not saluted and t - asked_at < 90.0 and randf() < 0.6 and state in ["idle", "wander", "dance"] \
						and _variant("solo_salute_") != "":
					_set_state("react", 2.6)
					_play("solo_salute_", 0.3)
				saluted = true
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
		"game":
			if msg.get("on", false):
				_game_sleep()
		"chat":
			_stir()
			if msg.get("role", "") == "you":
				asked_at = t
				saluted = false
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
var clip_from := {}                        # clip -> the file it came from (the gallery shows it)
const REMOVED_FILE := "res://clips_removed.txt"   # clips he took out (one name a line; # comments)
func _load_clips() -> void:
	ap = AnimationPlayer.new()
	body.add_child(ap)
	ap.root_node = ap.get_path_to(body)    # clip tracks address %GeneralSkeleton in her scene
	ap.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
	if clip_lib == null:                   # read once; every body plays the same humanoid clips
		clip_lib = AnimationLibrary.new()
		var removed := {}
		if FileAccess.file_exists(REMOVED_FILE):
			for line in FileAccess.get_file_as_string(REMOVED_FILE).split("\n"):
				if line.strip_edges() != "" and not line.begins_with("#"):
					removed[line.strip_edges()] = true
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
					if removed.has(String(name)):
						continue
					if not clip_lib.has_animation(name):
						clip_from[name] = String(path).get_file()
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
# Head direction isn't all: lying on her back, front or side, a clip that
# starts lying another way rolls her torso round in the blend. So each clip's
# pelvis tilt at both ends (which way is up, in her pelvis's own frame; the
# same however she's turned on the floor), and lying, the next clip must start
# tilted near the way she lies now (_variant, _vary).
var lie_up := {}                           # clip -> [start, end] up in her pelvis
var yaw_glide := [0.0, 0.0, -9.0, 1.0]     # [from, to, start, seconds]


func _lying_heads(name: String, anim: Animation) -> void:
	var hips := -1
	for tr in anim.get_track_count():
		if anim.track_get_type(tr) == Animation.TYPE_ROTATION_3D and String(anim.track_get_path(tr)).ends_with(":Hips"):
			hips = tr
	if hips < 0:
		return
	var hi := skel.find_bone("Hips")
	var root := skel.get_bone_global_rest(skel.get_bone_parent(hi)).basis if hi >= 0 and skel.get_bone_parent(hi) >= 0 else Basis()
	var tilt := []
	for at in [0.0, anim.length]:
		tilt.append(((root * Basis(anim.rotation_track_interpolate(hips, at))).orthonormalized().inverse() * Vector3.UP).normalized())
	lie_up[name] = tilt
	lie_up[name + "@r"] = tilt
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
	"Dance": [["Dance", 0.01], ["dance_", 1.5], ["held_", 0.8], ["solo_airguitar_", 0.8]],     # (held_1 reads as a dance, he said)
	"Jump": [["Jump", 0.01], ["fall_", 1.0], ["jump_", 0.3]],
	"Held": [["Jump", 0.01]],                  # (her ragdoll has her when held; held_1 dances now)
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
		["meditate_", "floor"], ["sleep_bed_", "lie"],
		# An episode's beats (docs/PET_EPISODES_PLAN.md): crouched, sitting on the floor.
		["crouch_", "crouch"], ["sitfloor_", "floor"], ["fall_sit_", "floor"], ["rise_", "stand"],
		["trip_fall_", "floor"]]
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
			or name.begins_with("get_up_") or name == "Sitting_Exit" or name == "LayToIdle" \
			or name.begins_with("fall_sit_") or name.begins_with("rise_") or name.begins_with("trip_fall_")    # an episode's own moves (startled down, up with a bug on her hand)


func _transition(from: String, to: String) -> String:
	if from == to:
		return ""
	if from == "lie" and to == "stand" and _lying_now():
		# Up off the floor: whichever get-up starts lying the way she lies now
		# (on her back, the face-down one would roll her over first).
		var best := ""
		var off := INF
		for a in ap.get_animation_list():
			var n := String(a)
			if not n.contains("@") and (n.begins_with("tr_lie_stand_") or GETUPS.any(func(g): return n.begins_with(g))):
				var o := _tilt_off(n)
				if o < off:
					off = o
					best = n
		if best != "":
			return best
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


const TILT_OK := 0.8                       # radians: near enough to blend without a roll


# How far a clip's first frame is tilted from the way her pelvis is now.
func _tilt_off(pick: String) -> float:
	if not lie_up.has(pick) or not bones.has("Hips"):
		return 0.0
	var now := skel.get_bone_global_pose(bones["Hips"]).basis.orthonormalized().inverse() * Vector3.UP
	return now.angle_to(lie_up[pick][0])


func _lying_now() -> bool:
	if not bones.has("Hips"):
		return false
	var now := skel.get_bone_global_pose(bones["Hips"]).basis.orthonormalized().inverse() * Vector3.UP
	var rest := skel.get_bone_global_rest(bones["Hips"]).basis.orthonormalized().inverse() * Vector3.UP
	return now.angle_to(rest) > 1.0


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
	elif role == "Walk" and (walk_style if walk_style != "" else trip_style) != "":
		entries = [[walk_style if walk_style != "" else trip_style, 1.0]]
	elif not ROLES.has(role) and not role.begins_with("play:"):
		if not role.ends_with("_"):
			return role if ap.has_animation(role) else ""
		entries = [[role, 1.0]]                # a prefix: any of its takes (an episode's beat)
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
	if _lying_now() and pool.size() > 1:
		# Lying: only clips that start lying the way she is (else her torso rolls round).
		for i in pool.size():
			if _tilt_off(pool[i]) > TILT_OK and pool.any(func(a): return _tilt_off(a) <= TILT_OK):
				weights[i] = 0.0
	var total := 0.0
	for w in weights:
		total += w
	if total <= 0.0:
		if _lying_now() and pool.size() > 1:   # none left that lies her way but this one: keep lying as she is
			var tilts := pool.map(func(a): return _tilt_off(a))
			return pool[tilts.find(tilts.min())]
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
	# Lying to lying with her head pointing a little another way: her body turns
	# by the difference over the blend, so her head stays put on the floor
	# instead of the blend swinging her round.
	var head_to: Vector2 = (lie_head.get(pick, none) as Array)[0]
	var bl := maxf(blend, _calm_blend(pick))
	if head_now != Vector2.ZERO and head_to != Vector2.ZERO and bl > 0.0:
		var d := wrapf(atan2(head_now.x, head_now.y) - atan2(head_to.x, head_to.y), -PI, PI)
		if absf(d) > 0.1:
			yaw_glide = [yaw, yaw + d, t, bl]
	variant = pick
	ap.play(pick, bl)
	var a := ap.get_animation(pick)
	# A looping clip gets a cycle or three before a change; a one-shot plays out.
	variant_until = t + (a.length * randi_range(1, 3) if a.loop_mode != Animation.LOOP_NONE else a.length) - minf(0.4, a.length * 0.3)


# The least blend between two clips: unhurried, so a change of clip eases in
# instead of snapping. Quick only where it must be (a fall, being grabbed,
# landing); steps and stance moves a little quicker so her feet stay put.
const MIN_BLEND := 0.6
const QUICK := ["Jump", "fall_", "held_", "land_", "knocked_", "Death01", "Held"]
func _calm_blend(pick: String) -> float:
	if state in ["fall", "held", "tumble", "knocked"] or QUICK.any(func(q): return pick.begins_with(q)):
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
	trip_style = _walk_style()
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


# The walk for a trip, by her mood: hands behind her back when she's idling
# along, a hip sway or a skip when she's happy, a slow shuffle when she's sad;
# "" is her ordinary walks (ROLES "Walk"). Tiptoeing is for sneaking up on things.
const WALK_STYLES := ["walk_hands_", "walk_sway_", "walk_skip_", "walk_sad_"]
func _walk_style() -> String:
	var joy := _feeling("joy")
	var weights := {"": 1.0, "walk_hands_": 0.7 + _feeling("bored") * 0.4,
			"walk_sway_": 0.25 + joy * 0.7, "walk_skip_": 0.1 + _feeling("light") * 0.9 + joy * 0.4,
			"walk_sad_": _feeling("sorrow") * 1.6}
	var total := 0.0
	for k in weights.keys():
		if k != "" and not Array(ap.get_animation_list()).any(func(a): return String(a).begins_with(k)):
			weights.erase(k)
		else:
			total += weights[k]
	var r := randf() * total
	for k in weights:
		r -= weights[k]
		if r <= 0.0:
			return k
	return ""


# The tip of her hand (where a bug would sit on her finger), in the world.
func hand_point(side: String) -> Vector3:
	var h: int = skel.find_bone(side + "Hand") if skel else -1
	if h < 0:
		return Vector3(pos.x, 1.0, depth)
	var xf := _bone_xf(h)
	var up := _bone_xf(skel.get_bone_parent(h)).origin
	return xf.origin + (xf.origin - up).normalized() * 0.08


# In front of her face, `ahead` metres out along the way she faces (her nose
# at about 0.07): where a butterfly lands, a spider hangs.
func face_point(ahead: float) -> Vector3:
	var h: int = bones.get("Head", -1)
	var base := _bone_xf(h).origin + Vector3(0, 0.07, 0) if h >= 0 else Vector3(pos.x, 1.5, depth)
	return base + Vector3(sin(yaw), 0.0, cos(yaw)) * ahead


# Looking at something in the world for a while: a point, or a thing that moves.
func look_at_world(at: Variant, seconds: float) -> void:
	look_node = at if at is Node3D else null
	look_spot = at if at is Vector3 else Vector3.INF
	look_until = t + seconds


# A spot on the floor in front of her, `ahead` metres along her facing.
func ground_ahead(ahead: float) -> Vector3:
	var f := Vector3(sin(yaw), 0.0, cos(yaw))
	return Vector3(pos.x, 0.0, depth) + f * ahead


# How fast her body moves for the clip playing: its measured stride if it's
# a locomotion loop, else the old fixed pace.
# Stride is set by leg length, not hip height: the clips' source skeleton
# (Kimodo's SOMA) has hips at 1 m and 0.855 m from hip joint to ankle, and the
# velocity is in its hip-heights, so her legs over SOMA's give her pace.
# (Scaling by hip height left Jane 13% fast: her feet slid forward.)
const SOMA_LEG := 0.855
const JANE_LEG := 0.805                    # Jane's legs (the body most of her tuning was done on)
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
	if state in ["held", "fall", "tumble"] or floor_y > 0.01 or flesh.is_empty():
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
		if _lying_now() and _tilt_off(next) > TILT_OK:
			var alt := _variant(clip)              # picked before the transition: one lying this way instead
			if alt != "" and _tilt_off(alt) < _tilt_off(next):
				next = alt
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
	# (before outfits there was a jacket switch: off is Jane's "No jacket")
	var wear := str(av.get("outfit", "")) if av.has("outfit") else ("" if av.get("jacket", true) else "No jacket")
	outfit = {"name": wear, "weapon": bool(av.get("weapon", false))}
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
	var busy: bool = state in ["wander", "fall", "held", "tumble", "getup", "react", "dance", "knocked"] or speaking or t < mood_until or (slab and slab.visible)
	Engine.max_fps = FPS_BUSY if busy else FPS_IDLE


func _think(_delta: float) -> void:
	if state in ["fall", "held", "tumble"] or (state in ["knocked", "getup"] and t < state_until):
		return
	if allow["nap"] and state != "sleep" and t - last_activity > SLEEP_AFTER and state in ["idle", "sit", "rest"] \
			and _variant("Crouch_Idle") != "":   # (no pose to sleep in since his clip pass: she stays up)
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
		"held", "tumble":
			pass                               # her physical bones have her (ragdoll.gd)
		"getup":
			pos.y = floor_y
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
	elif t > look_until and state not in ["wander", "stopping"] and not _lying_now():   # lying, a glance would spin her on the floor
		yaw_target = sin(t * 0.17) * 0.25
	if t < yaw_glide[2] + yaw_glide[3]:
		# Turning in step with a blend between two lying clips (_play_variant).
		yaw = lerp_angle(yaw_glide[0], yaw_glide[1], clampf((t - yaw_glide[2]) / yaw_glide[3], 0.0, 1.0))
		yaw_target = yaw
	else:
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
	if state in RAGDOLL and ragdoll and ragdoll.on:
		if shadow:
			shadow.visible = false
		return                                 # the ragdoll is in the world; her frame stays put
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
	if state == "fall":                        # rolled on the screen, whichever way she faces
		body.basis = Basis(Vector3.BACK, roll) * Basis(Vector3.UP, yaw + spin)
	if spin != 0.0:                            # round the chair's centre, not her feet
		var c: Vector3 = (room.items["chair"] as Node3D).position
		var off := body.position - Vector3(c.x, body.position.y, c.z)
		body.position = Vector3(c.x, body.position.y, c.z) + off.rotated(Vector3.UP, spin)
	if state == "fall":
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
	elif t < look_until and cam and bones.has("Head") and (is_instance_valid(look_node) or look_spot != Vector3.INF):
		var at: Vector3 = look_node.global_position if is_instance_valid(look_node) else look_spot
		var head := skel.global_transform * skel.get_bone_global_pose(bones["Head"]).origin
		var d := cam.unproject_position(at) - cam.unproject_position(head)
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
		# Now and then a double blink; slower and further apart when she's calm or tired.
		blink_again = not blink_again and randf() < 0.15
		var slow: float = 1.0 + float(moods.get("sleepy", 0.0)) + float(moods.get("fun", 0.0))
		next_blink = t + (0.22 if blink_again else randf_range(2.0, 5.5) * slow)
	blink = maxf(0.0, blink - delta * (9.0 if moods.get("sleepy", 0.0) < 0.3 else 5.0))
	var eyes := 1.0 if state == "sleep" else clampf(blink * 1.6, 0.0, 1.0)
	if face_test != "":
		_shape(face_test, 1.0)
		_alive_face(delta)
		_face_apply()
		return

	if t > mood_until:
		for k in mood_target:
			mood_target[k] = 0.1 if k == "fun" else 0.0
	for k in moods:
		moods[k] = lerpf(moods[k], mood_target[k], clampf(delta * 6.0, 0.0, 1.0))

	_speech_frame(delta)
	_body_face(delta)
	_shape("blink", eyes * (1.0 - moods["joy"]) * (1.0 - wince))
	for k in moods:
		# Anger counts for more: at the weight a voice line gives it (0.6) it barely showed.
		_shape(k, moods[k] * (1.5 if k == "angry" else 1.0) * (1.0 - flung * 0.8))
	for v in mouth:
		_shape(v, mouth[v] if allow["lip_sync"] else 0.0)
	_shape("squint", squint * (1.0 - flung))
	_shape("flung", flung)
	_shape("wince", wince)
	if state != "sleep":
		_alive_face(delta)
	_face_apply()


# What her body is doing shows on her face: hands up by her eyes make her
# squint; held or flying through the air she's wide-eyed; landed, she winces
# till she's up.
func _body_face(delta: float) -> void:
	var sq := 0.0
	if not (ragdoll and ragdoll.on) and bones.has("Head"):
		var head := skel.get_bone_global_pose(bones["Head"]).origin
		for h in ["LeftHand", "RightHand"]:
			var i := skel.find_bone(h)
			if i >= 0:
				sq = maxf(sq, 1.0 - smoothstep(0.13, 0.3, skel.get_bone_global_pose(i).origin.distance_to(head) / _stride()))
	squint = lerpf(squint, sq, clampf(delta * 8.0, 0.0, 1.0))
	var air: bool = state == "held" or (state == "tumble" and ragdoll and not ragdoll.landed)
	var down: bool = state == "tumble" and ragdoll and ragdoll.landed
	flung = lerpf(flung, 1.0 if air else 0.0, clampf(delta * (12.0 if air else 4.0), 0.0, 1.0))
	wince = lerpf(wince, 1.0 if down else 0.0, clampf(delta * 6.0, 0.0, 1.0))


# Her face is never quite still: brows, lids and the corners of her mouth
# drift a little, her pupils widen when his pointer moves near, and every few
# seconds a passing micro-expression, picked by her mood (a brow flick, a
# smirk, a pout, a squint of a smile, a wink, a puffed cheek).
func _alive_face(delta: float) -> void:
	if not mmd_face:
		return                                 # the drift layer is for the MMD face's shapes
	var joy: float = moods.get("joy", 0.0) + moods.get("stars", 0.0)
	var fun: float = moods.get("fun", 0.0) + moods.get("smirk", 0.0)
	var cross: float = moods.get("angry", 0.0)
	var low: float = moods.get("sorrow", 0.0) + moods.get("bored", 0.0) + moods.get("gloom", 0.0)
	var busy := clampf(flung + wince + float(moods.get("surprised", 0.0)), 0.0, 1.0)
	var drift := func(rate: float, off: float) -> float:
		return 0.6 * sin(t * rate + off) + 0.4 * sin(t * rate * 2.37 + off * 1.7)
	var calm := 1.0 - busy
	_raw("Eyebrow_Up", maxf(0.0, 0.1 + 0.12 * drift.call(0.31, 1.0)) * calm)
	_raw("Eye_Calm", maxf(0.0, 0.12 * drift.call(0.23, 2.0) + low * 0.2) * calm)
	_raw("Eye_Tail_Up", maxf(0.0, 0.15 * joy + 0.08 * drift.call(0.17, 5.0)) * calm)
	if not speaking:
		_raw("Mouth_Smile.L", maxf(0.0, 0.08 + 0.1 * drift.call(0.19, 3.0) + 0.12 * fun) * calm)
		_raw("Mouth_Smile.R", maxf(0.0, 0.05 + 0.1 * drift.call(0.21, 4.0)) * calm)
		_raw("Mouth_Move_Left", maxf(0.0, 0.08 * drift.call(0.13, 6.0)) * calm)
		_raw("Mouth_Move_Right", maxf(0.0, -0.08 * drift.call(0.13, 6.0)) * calm)
	pupil_big = lerpf(pupil_big, 0.3 if t - cursor_at < 1.5 else 0.0, clampf(delta * 3.0, 0.0, 1.0))
	_raw("Pupil_Large", (pupil_big + 0.2 * joy) * calm)
	# A micro-expression now and then, sooner the livelier she is.
	if t > micro_next and busy < 0.3:
		var pool := [["brow", 1.0], ["smirk", 0.4 + fun * 2.0], ["pout", 0.2 + low * 2.0 + cross], ["smile", 0.3 + joy * 3.0],
				["wink", 0.1 + fun + joy * 0.5], ["puff", 0.1 + cross * 2.0 + low], ["glance", 0.6]]
		var total := 0.0
		for p in pool:
			total += float(p[1])
		var r := randf() * total
		for p in pool:
			r -= float(p[1])
			if r <= 0.0:
				micro = p[0]
				break
		micro_at = t
		micro_len = randf_range(0.7, 1.6)
		micro_next = t + randf_range(3.0, 8.0) / (1.0 + joy + fun + cross)
	var k := smoothstep(0.0, 0.2, t - micro_at) * (1.0 - smoothstep(micro_len - 0.3, micro_len, t - micro_at)) * calm
	if k <= 0.0:
		return
	match micro:
		"brow": _raw("Eyebrow_Up", 0.55 * k)
		"smirk":
			if not speaking:
				_raw("Mouth_Smile.L", 0.6 * k); _raw("Mouth_Turn.L", 0.3 * k)
			_raw("Eye_Sharp", 0.25 * k)
		"pout":
			if not speaking:
				_raw("Mouth_U", 0.25 * k); _raw("CheekPuff", 0.2 * k)
			_raw("Eyebrow_Sad", 0.35 * k)
		"smile":
			_raw("Eye_Joyful", 0.45 * k)
			if not speaking:
				_raw("Mouth_Smile", 0.5 * k)
		"wink":
			_raw("Eye_Closed.L", k)
			if not speaking:
				_raw("Mouth_Smile.L", 0.5 * k); _raw("Tongue_Out", 0.35 * k)
		"puff":
			if not speaking:
				_raw("CheekPuff", 0.55 * k)
			_raw("Eyebrow_Angry", 0.3 * k)
		"glance": _raw("Eye_Tail_Down", 0.3 * k); _raw("Eyebrow_Close", 0.2 * k)


# One of the face's own shapes by name, added on top of this frame's faces.
func _raw(shape: String, w: float) -> void:
	if not raw_shapes.has(shape):
		raw_shapes[shape] = _find_shapes(body, shape)
		for pair in raw_shapes[shape]:
			face_slots[[pair[0], pair[1]]] = face_slots.get([pair[0], pair[1]], 0.0)
	for pair in raw_shapes[shape]:
		var slot := [pair[0], pair[1]]
		face_slots[slot] = face_slots.get(slot, 0.0) + w


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
	if state in RAGDOLL and ragdoll and ragdoll.on:
		var box := Rect2(cam.unproject_position(ragdoll.at("Hips")), Vector2.ZERO)
		for b in ragdoll.parts:
			box = box.expand(cam.unproject_position(ragdoll.at(b)))
		_set_click_rect(box.grow(40))
		return
	if state == "fall" and skel:
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


# The click region goes to the window system (X11 shape, KWin) on every change,
# which while she walked was nearly every frame. Snapped outward to a coarse
# grid, it changes only when she has moved a fair way: the same clicks land.
const CLICK_GRID := 48.0
func _set_click_rect(r: Rect2) -> void:
	var lo := (r.position / CLICK_GRID).floor() * CLICK_GRID
	var hi := (r.end / CLICK_GRID).ceil() * CLICK_GRID
	r = Rect2(lo, hi - lo)
	if menu and menu.visible:                  # her menu is open: it takes clicks too
		r = r.merge(Rect2(Vector2(menu.position), Vector2(menu.size)))
	if r == last_rect:
		return
	last_rect = r
	DisplayServer.window_set_mouse_passthrough(PackedVector2Array([
		r.position, r.position + Vector2(r.size.x, 0), r.end, r.position + Vector2(0, r.size.y)]))


func _input(event: InputEvent) -> void:
	# Lying in a heap or getting up: clicks and scrolls leave her be (only a drag picks her up again).
	var heap := state in ["tumble", "getup"]
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_RIGHT and event.pressed:
		_menu_at(event.position)
		return
	if mode == "poke" and (event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT or poking):
		_poke_input(event)
		return
	if event is InputEventMouseButton and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN] \
			and event.pressed and state == "held" and pressing:
		# Held: the wheel carries her toward the glass (up) or back into her room (down).
		grab_z = clampf(grab_z + (DEPTH_STEP if event.button_index == MOUSE_BUTTON_WHEEL_UP else -DEPTH_STEP), -room_depth + 0.15, -0.05)
		return
	if event is InputEventMouseButton and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN] \
			and event.pressed and not heap:
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
			if event.double_click and not heap:
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
			elif mode == "pin" and state == "held" and ragdoll.on:
				ragdoll.pin_here()                  # she stays hanging where he left her
			elif mode == "pin" and not drag_moved and state not in RAGDOLL and not heap:
				_grab_start()                       # a click: pinned right where she stands
				if state == "held":
					ragdoll.pin_here()
			elif drag_moved and state == "held" and not ragdoll.pins.is_empty():
				ragdoll.drop_hold()                 # pinned: she swings back on her pins
			elif drag_moved and state == "held":
				if shakes >= 6:
					play.after_landing = "shaken"
				# Let go: she keeps whatever speed and spin your hand gave her, and tumbles.
				ragdoll.let_go()
				_set_state("tumble", 99.0)
				if held_vel.length() > 4.0:
					_feel("surprised", 0.8, 1.2)
			elif state != "held" and not heap:  # a click, not a drag
				_clicked(play.press_part)
	elif event is InputEventMouseMotion and pressing:
		if event.position.distance_to(drag_from) > 4 and not drag_moved and not play.holding_still:
			drag_moved = true
			_grab_start()
			grab_at = event.position
		if state != "held":
			return
		var v: Vector2 = event.velocity / PPM
		if absf(v.x) > 2.0 and signf(v.x) != signf(held_vel.x) and held_vel.x != 0.0:
			shakes += 1                        # shaken side to side
		grab_at = event.position


# Picked up by the point under drag_from (see _pick_grab). Hanging from pins
# (pin mode), she's caught by another point and the pins stay.
func _grab_start() -> void:
	brain.drop()
	_unperch_now()
	# Caught again mid-tumble or while she hangs: from the pose she's in, and
	# whatever the mode the pins stay (only Let her down takes them out).
	var more: bool = state in RAGDOLL and ragdoll.on
	if grab_bone < 0:
		return
	var at: Vector3 = _bone_xf(grab_bone) * grab_local
	_set_state("held", 1e9)
	_feel("surprised", 0.4, 1.0)
	_play("Held", 0.15)
	roll = 0.0
	grab_prev = drag_from
	grab_at = drag_from
	grab_z = at.z
	held_vel = Vector2.ZERO
	if more:
		ragdoll.grab_more(skel.get_bone_name(grab_bone), at)
	else:
		ragdoll.start(skel.get_bone_name(grab_bone), at)


# Poke mode: pressed, the point under his pointer is pushed in (poke.gd), and
# dragging pushes it along; on the floor in a heap, a poke shoves that part.
func _poke_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if not event.pressed:
			poking = false
			if poke:
				poke.stop()
			return
		_stir()
		_pick_grab(event.position)
		if grab_bone < 0 or poke == null:
			return
		var at: Vector3 = _bone_xf(grab_bone) * grab_local
		if state in RAGDOLL and ragdoll.on:
			ragdoll.shove(skel.get_bone_name(grab_bone), at, Vector3.FORWARD * 2.5)
			return
		poking = true
		poke_z = at.z
		poke.start(grab_bone, at)
		_feel("surprised", 0.3, 0.7)
	elif event is InputEventMouseMotion and poking and poke:
		var hit = Plane(Vector3.BACK, poke_z).intersects_ray(cam.project_ray_origin(event.position), cam.project_ray_normal(event.position))
		if hit != null:
			poke.target = hit


# Her right-click menu: what a left click on her does.
func _menu_at(p: Vector2) -> void:
	if menu == null:
		menu = PopupMenu.new()
		var th := Theme.new()
		var panel := StyleBoxFlat.new()
		panel.bg_color = Color(0.07, 0.05, 0.09, 0.94)
		panel.set_corner_radius_all(10)
		panel.set_border_width_all(1)
		panel.border_color = Color(1.0, 0.25, 0.32, 0.55)
		panel.set_content_margin_all(6)
		var hover := StyleBoxFlat.new()
		hover.bg_color = Color(1.0, 0.18, 0.26, 0.28)
		hover.set_corner_radius_all(6)
		th.set_stylebox("panel", "PopupMenu", panel)
		th.set_stylebox("hover", "PopupMenu", hover)
		th.set_color("font_color", "PopupMenu", Color(0.93, 0.9, 0.92))
		th.set_color("font_hover_color", "PopupMenu", Color.WHITE)
		th.set_color("font_disabled_color", "PopupMenu", Color(0.6, 0.55, 0.6, 0.6))
		th.set_font_size("font_size", "PopupMenu", 15)
		th.set_constant("v_separation", "PopupMenu", 10)
		th.set_constant("h_separation", "PopupMenu", 10)
		menu.theme = th
		menu.add_radio_check_item("Play: tap, hug, pick her up", 0)
		menu.add_radio_check_item("Poke: press on her", 1)
		menu.add_radio_check_item("Pin: let go and she stays", 2)
		menu.add_separator()
		menu.add_item("Let her down", 3)
		menu.id_pressed.connect(_menu_pick)
		menu.popup_hide.connect(func(): last_rect = Rect2(); _update_click_area())
		add_child(menu)
	for i in MODES.size():
		menu.set_item_checked(menu.get_item_index(i), MODES[i] == mode)
	menu.set_item_disabled(menu.get_item_index(3), not (state == "held" and ragdoll and ragdoll.on and not ragdoll.pins.is_empty()))
	menu.reset_size()
	var at := p.clamp(Vector2.ZERO, Vector2(get_window().size) - Vector2(menu.size))
	menu.popup(Rect2i(Vector2i(at), Vector2i.ZERO))
	last_rect = Rect2()
	_update_click_area()


func _menu_pick(id: int) -> void:
	var pinned: bool = state == "held" and ragdoll and ragdoll.on and not pressing
	if id == 3 and pinned:                     # (another mode leaves her hanging till this)
		ragdoll.let_go()                       # down she comes
		_set_state("tumble", 99.0)
	if id < 3:
		mode = MODES[id]
		var f := FileAccess.open(MODE_FILE, FileAccess.WRITE)
		if f:
			f.store_string(mode)


# Where a bone is drawn, in the world. While she's a ragdoll her physical parts
# place her: the skeleton's own pose, read outside its modifiers, is still the
# clip's ("Held"), up to a metre from what's on screen.
func _bone_xf(i: int) -> Transform3D:
	if state in RAGDOLL and ragdoll and ragdoll.on:
		var chain := Transform3D()
		var j := i
		while j >= 0 and not ragdoll.parts.has(skel.get_bone_name(j)):
			chain = skel.get_bone_pose(j) * chain
			j = skel.get_bone_parent(j)
		if j >= 0:
			var pb: PhysicalBone3D = ragdoll.parts[skel.get_bone_name(j)]
			var ph := pb.global_transform * pb.body_offset.affine_inverse()
			return Transform3D(ph.basis.orthonormalized() * Basis.from_scale(skel.global_basis.get_scale()), ph.origin) * chain
	return skel.global_transform * skel.get_bone_global_pose(i)


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
		var a := _bone_xf(ia).origin
		var b: Vector3
		if s[1] != "" and skel.find_bone(s[1]) >= 0:
			b = _bone_xf(skel.find_bone(s[1])).origin
		else:                                  # the top of her head, her fingers: past the joint
			var pa := _bone_xf(skel.get_bone_parent(ia)).origin
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
	grab_local = _bone_xf(grab_bone).affine_inverse() * at


# Held: the point he grabbed follows his pointer (drawn to the glass); let go,
# she tumbles till she's still, then gets up the way she's lying.
func _held_frame(delta: float) -> void:
	if not (ragdoll and ragdoll.on) or delta <= 0.0:
		return
	if state not in RAGDOLL and state != "getup":
		ragdoll.stop()                         # something else took her over (a verb from Aries): back to her clips
		return
	if state == "held":
		var hit = Plane(Vector3.BACK, grab_z).intersects_ray(cam.project_ray_origin(grab_at), cam.project_ray_normal(grab_at))
		if hit != null:
			ragdoll.target = hit
		var v := (grab_at - grab_prev) / delta / PPM
		grab_prev = grab_at
		held_vel = held_vel.lerp(Vector2(v.x, -v.y), clampf(delta * 14.0, 0.0, 1.0))
	elif state == "tumble" and ((ragdoll.still_for > 0.35 and ragdoll.since_drop > 0.6) or ragdoll.since_drop > 5.0):
		_get_up()


# Up from wherever she ended: the get-up for how she's lying, her frame put
# under where she lies (and turned the way her head points), the ragdoll
# easing into the clip's first pose.
# Each get-up is matched by how its own first frame lies (measured once), so
# she never blends from her back into a clip that starts on her front (her
# torso spinning round): the one tilted most like her wins.
const GETUPS := ["getup_", "get_up_", "tr_lie_stand_", "tr_floor_stand_", "LayToIdle"]
var getup_kind := {}                       # clip -> up, in its first frame's pelvis
func _get_up() -> void:
	var how: String = ragdoll.lie()
	# Which way is up from her pelvis: the same for any turn about the vertical,
	# so a clip's first frame and the ragdoll compare straight off.
	if getup_kind.is_empty():
		for a in ap.get_animation_list():
			var n := String(a)
			if not n.contains("@") and GETUPS.any(func(g): return n.begins_with(g)):
				ap.play(n, 0.0)
				ap.seek(0.0, true)
				getup_kind[n] = (skel.global_basis * skel.get_bone_global_pose(skel.find_bone("Hips")).basis).inverse() * Vector3.UP
	var up_r: Vector3 = ragdoll.hips_up()
	var pick := ""
	var best := INF
	for c in getup_kind:
		# The nearest tilt wins; the get-ups made for this (getup_) by a little.
		var off: float = up_r.angle_to(getup_kind[c]) - (0.2 if String(c).begins_with("getup_") else 0.0)
		if off < best:
			best = off
			pick = c
	if pick == "":
		pick = _variant_of("get_up_")
	var hips_w: Vector3 = ragdoll.joint("Hips")
	var head_w: Vector3 = ragdoll.joint("Head")
	# The clip's first frame, in her own frame (yaw 0): where its hips and head are.
	ap.play(pick, 0.0)
	ap.seek(0.0, true)
	# (her skeleton's place in her body frame doesn't turn with her: this is already yaw 0)
	var to_body := body.global_transform.affine_inverse() * skel.global_transform
	var hips_c: Vector3 = to_body * skel.get_bone_global_pose(skel.find_bone("Hips")).origin
	var head_c: Vector3 = to_body * skel.get_bone_global_pose(skel.find_bone("Head")).origin
	var dc := head_c - hips_c
	var dr := head_w - hips_w
	if how == "sit":                           # sitting up: face the way her chest does
		yaw = atan2(ragdoll.fwd_now().x, ragdoll.fwd_now().z)
	else:
		yaw = atan2(dr.x, dr.z) - atan2(dc.x, dc.z)
	yaw_target = yaw
	var at := hips_w - Basis(Vector3.UP, yaw) * hips_c
	pos = Vector2(at.x, 0.0)
	depth = clampf(at.z, -room_depth, 0.0)
	_land()
	pos.y = floor_y
	roll = 0.0
	clip = "Idle"
	variant = pick
	pending = ""
	var a := ap.get_animation(pick)
	variant_until = t + a.length - 0.4
	look_until = t + a.length + 1.0
	_set_state("getup", a.length - 0.3)
	ragdoll.ease_out(0.7)
	play.landed(ragdoll.impact > HARD_LANDING, a.length)
	if OS.get_environment("PET_SNAPSHOT_SEQ").begins_with("grab:"):
		print("GETUP %s %s off %.0fdeg impact %.1f yaw %.2f at %s" % [how, pick, rad_to_deg(best), ragdoll.impact, yaw, at])


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
	if state in ["held", "fall", "tumble", "knocked", "sleep"]:
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
	if state not in ["held", "fall", "tumble", "knocked"]:
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
	if what.begins_with("chest:"):               # her chest close up through a bouncy clip: does anything poke through?
		_chest_test(what.substr(6))
		return
	if what == "faces":                          # her face close up: each face, then each emote
		_faces_test()
		return
	if what.begins_with("grab:"):                # picked up by a bone, lifted, swung, held still
		depth = -0.3
		_set_state("idle", 99.0)
		_grab_test(what.substr(5))
	if what.begins_with("poke:") or what.begins_with("pin:"):   # a mode's click on a bone (_mode_test)
		_set_state("idle", 99.0)
		_mode_test(what.get_slice(":", 0), what.get_slice(":", 1))
	if what == "gallery":                        # every clip on her, frames for pet/import/gallery.py
		await _gallery(OS.get_environment("PET_GALLERY_DIR"))
		get_tree().quit()
		return
	if what.begins_with("walk:"):                # a walk style (walk_hands_ ...), across the room and back
		depth = -0.8
		_set_state("idle", 0.5)
		var st := what.substr(5)
		brain.doing = "test"
		brain.plan = [{"go": Vector2(pos.x + 2.5, -1.2), "walk": st}, {"go": Vector2(pos.x - 1.5, -0.6), "walk": st},
				{"play": "Idle", "for": 30.0}]
	if what.begins_with("episode:"):             # an episode (episodes.json), with ending N if given
		depth = -0.7
		_set_state("idle", 0.5)
		var ep := what.split(":")
		brain.force_branch = int(ep[2]) if ep.size() > 2 else -1
		brain.doing = "episode"
		brain.plan = brain._beats(brain.episodes[ep[1]]["beats"])
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
			get_tree().create_timer(8.0).timeout.connect(func():
				var P := Performance
				print("MEM static %d MB, msg buf %d, objects %d, resources %d, nodes %d" % [P.get_monitor(P.MEMORY_STATIC) / 1048576, P.get_monitor(P.MEMORY_MESSAGE_BUFFER_MAX), P.get_monitor(P.OBJECT_COUNT), P.get_monitor(P.OBJECT_RESOURCE_COUNT), P.get_monitor(P.OBJECT_NODE_COUNT)])
				print("VRAM total %d MB, textures %d MB, buffers %d MB" % [P.get_monitor(P.RENDER_VIDEO_MEM_USED) / 1048576, P.get_monitor(P.RENDER_TEXTURE_MEM_USED) / 1048576, P.get_monitor(P.RENDER_BUFFER_MEM_USED) / 1048576])
				print("window %s, viewport %s, msaa %d, scale %.2f" % [get_window().size, get_viewport().size, get_viewport().msaa_3d, get_viewport().scaling_3d_scale])
				var anims := 0
				var keys := 0
				for a in ap.get_animation_list():
					anims += 1
					var an := ap.get_animation(a)
					for tr in an.get_track_count():
						keys += an.track_get_key_count(tr)
				print("ANIMS %d clips, %d keys" % [anims, keys]))
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
	for i in (int(OS.get_environment("PET_SEQ_N")) if OS.get_environment("PET_SEQ_N") != "" else 14):
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


# A test run's close look at her chest through a lively clip, side-on and
# front, a picture every 0.1 s: straps and jacket against the breast springs.
func _chest_test(pick: String) -> void:
	brain_quiet = true
	_set_state("react", 1e9)
	var c := Camera3D.new()
	add_child(c)
	await get_tree().process_frame
	ap.play(pick, 0.0)
	c.fov = 16.0
	c.current = true
	for i in 24:
		var chest := skel.global_transform * skel.get_bone_global_pose(skel.find_bone(OS.get_environment("PET_CAM_BONE") if OS.get_environment("PET_CAM_BONE") != "" else "Chest")).origin
		var side := i % 2 == 0
		c.global_position = chest + (Vector3(1.6, 0.0, 0.5) if side else Vector3(0.0, 0.05, 1.7))
		c.look_at(chest)
		await get_tree().create_timer(0.1).timeout
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(snapshot_path.replace(".png", "_chest_%02d.png" % i))
		if squish:
			print("SQUISH %d arm in %.3f m bounce %.3f m" % [i, squish.most_in, squish.most_bounce])
			squish.most_bounce = 0.0
	get_tree().quit()


# Every clip she has, played once from its start on her (in place, her springs
# and face living as usual), filmed by a small camera of its own at 15 fps
# into <dir>/<clip>/NNN.png, with <dir>/clips.json (name, seconds, frames,
# source file). Her own window draws nothing meanwhile, so she doesn't dance
# about his desktop for half an hour. pet/import/gallery.py makes the page.
func _gallery(dir: String) -> void:
	brain_quiet = true
	_set_state("react", 1e9)
	get_viewport().disable_3d = true
	DisplayServer.window_set_mouse_passthrough(PackedVector2Array([Vector2.ZERO, Vector2(1, 0), Vector2(1, 1)]))
	var sv := SubViewport.new()
	sv.size = Vector2i(300, 400)
	sv.transparent_bg = true
	sv.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(sv)
	var c := Camera3D.new()
	c.fov = 42.0
	sv.add_child(c)
	c.current = true
	var at := Vector3(pos.x, 0.0, depth)
	c.global_position = at + Vector3(0.0, 0.95, 2.9)
	c.look_at(at + Vector3(0.0, 0.82, 0.0))
	DirAccess.make_dir_recursive_absolute(dir)
	var only := OS.get_environment("PET_GALLERY_ONLY")       # a few, by prefix: "walk_,crouch_"
	var names := Array(ap.get_animation_list()).filter(func(n): return not String(n).contains("@") and n != "RESET" \
			and (only == "" or Array(only.split(",")).any(func(p): return String(n).begins_with(p))))
	names.sort()
	var made := []
	for n in names:
		var a := ap.get_animation(n)
		var secs := clampf(a.length * (ceilf(2.5 / maxf(a.length, 0.1)) if a.loop_mode != Animation.LOOP_NONE else 1.0), 0.5, 8.0)
		ap.play(n, 0.0)
		ap.seek(0.0, true)
		clip = n
		variant = n
		variant_until = 1e9
		var sub := dir.path_join(String(n).validate_filename())
		DirAccess.make_dir_recursive_absolute(sub)
		var count := int(ceil(secs * 15.0))
		for k in count:
			await get_tree().create_timer(1.0 / 15.0).timeout
			await RenderingServer.frame_post_draw
			sv.get_texture().get_image().save_png(sub.path_join("%03d.png" % k))
		made.append({"name": n, "seconds": snappedf(a.length, 0.01), "frames": count,
				"loops": a.loop_mode != Animation.LOOP_NONE, "from": clip_from.get(n, "")})
		print("GALLERY %d/%d %s" % [made.size(), names.size(), n])
	var f := FileAccess.open(dir.path_join("clips.json"), FileAccess.WRITE)
	f.store_string(JSON.stringify(made))
	f.close()


# A test run's close look at her face: each of her body-driven faces and a few
# moods held a moment (face_test), then every emote in turn; one picture each.
func _faces_test() -> void:
	brain_quiet = true
	_set_state("idle", 1e9)
	_play("Idle", 0.0)
	var c := Camera3D.new()
	add_child(c)
	await get_tree().process_frame
	var head := skel.global_transform * skel.get_bone_global_pose(bones["Head"]).origin
	c.fov = 14.0
	ap.speed_scale = 0.0                       # held still, so each face is framed the same
	for f in ["", "angry", "squint", "flung", "wince", "joy", "surprised", "sorrow", "fun"]:
		c.global_position = head + Vector3(0.0, 0.05, 1.6)
		c.look_at(head + Vector3(0, 0.03, 0))
		c.current = true
		face_test = f
		for k in 20:
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(snapshot_path.replace(".png", "_face_%s.png" % (f if f != "" else "neutral")))
	face_test = ""
	# Her chest at rest and just after a hop, side on: how the softer springs hang and swing.
	var chest := skel.global_transform * skel.get_bone_global_pose(skel.find_bone("Chest")).origin
	for shot in ["rest", "side"]:
		c.global_position = chest + (Vector3(0.0, 0.0, 2.2) if shot == "rest" else Vector3(2.2, 0.0, 0.3))
		c.look_at(chest)
		for k in 30:
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(snapshot_path.replace(".png", "_chest_%s.png" % shot))
	for e in play.emote_tex:
		c.global_position = head + Vector3(0.15, 0.3, 1.6)
		c.look_at(head + Vector3(0.13, 0.33, 0))
		play.show_emote(e)
		for k in 9:
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(snapshot_path.replace(".png", "_emote_%s.png" % e))
	get_tree().quit()


# A test run's hand picking her up by one bone: press on it, lift, swing side
# to side, hold still. Logs how far the grabbed point is from the pointer.
func _grab_test(bone: String) -> void:
	await get_tree().create_timer(0.6).timeout
	if OS.get_environment("PET_CHESTCAM") != "":
		# (a close look at her chest from the side the whole time: does it hang the right way?)
		var c := Camera3D.new()
		c.fov = 22.0
		add_child(c)
		c.current = true
		get_tree().process_frame.connect(func():
			if ragdoll and ragdoll.on and ragdoll.parts.has("Chest"):
				var at: Vector3 = ragdoll.at("Chest")
				var f: Vector3 = ragdoll.fwd_now()
				c.global_position = at + f * 1.3 + f.cross(Vector3.UP).normalized() * 0.9
				c.look_at(at)
				if squish and Engine.get_process_frames() % 20 == 0:
					print("HANG %.3f m tip %.2f rad flat %.2f" % [(squish.sides[0][5][0] as Vector3).length(), (squish.sides[0][5][5] as Vector3).length(), float(squish.sides[0][5][6])]))
	var p := cam.unproject_position(skel.global_transform * skel.get_bone_global_pose(skel.find_bone(bone)).origin)
	var e := InputEventMouseButton.new()
	e.button_index = MOUSE_BUTTON_LEFT
	e.pressed = true
	e.position = p
	_input(e)
	for i in 160:
		var at := p + Vector2(0, -minf(i, 30) * 10.0)
		if i >= 50 and i < 110:
			at.x += sin((i - 50) * 0.2) * 160.0
		if i >= 140:
			at += Vector2((i - 140) * 25.0, -(i - 140) * 6.0)     # a toss to the right
		var m := InputEventMouseMotion.new()
		m.position = at
		m.velocity = (at - grab_at) * 30.0
		_input(m)
		await get_tree().process_frame
		if i % 10 == 0 and state == "held":
			var pb: Node3D = ragdoll.parts[ragdoll._part_for(bone)]
			print("GRAB %d %s gap %.1f px state %s" % [i, bone, cam.unproject_position(pb.global_position).distance_to(grab_at), state])
	e = InputEventMouseButton.new()
	e.button_index = MOUSE_BUTTON_LEFT
	e.pressed = false
	e.position = grab_at
	_input(e)
	for i in 600:
		await get_tree().process_frame
		if i % 20 == 0:
			print("TUMBLE %d state %s still %.2f landed %s hips %s" % [i, state, ragdoll.still_for, ragdoll.landed, ragdoll.at("Hips")])
		if state not in RAGDOLL and state != "getup":
			print("UP after %d frames: %s" % [i, state])
			break


# A test run of a click mode on one bone. poke: pressed 0.6 s, dragged right
# a little, let go. pin: lifted up and right, let go (she stays), then a second
# point caught and pinned left of the first. Logs the pressed bone's travel.
func _mode_test(m: String, bone: String) -> void:
	mode = m
	await get_tree().create_timer(0.6).timeout
	var b := skel.find_bone(bone)
	var p := cam.unproject_position(_bone_xf(b).origin)
	var start := _bone_xf(b).origin
	var press := func(at: Vector2, down: bool) -> void:
		var e := InputEventMouseButton.new()
		e.button_index = MOUSE_BUTTON_LEFT
		e.pressed = down
		e.position = at
		_input(e)
	var move := func(at: Vector2) -> void:
		var e := InputEventMouseMotion.new()
		e.position = at
		e.velocity = Vector2.ZERO
		_input(e)
	press.call(p, true)
	var at := p
	for i in 60:
		if m == "poke" and i > 20:
			at = p + Vector2((i - 20) * 1.5, 0.0)
		elif m == "pin":
			at = p + Vector2(minf(i, 40) * 4.0, -minf(i, 40) * 6.0)
		move.call(at)
		await get_tree().process_frame
		if i % 10 == 0:
			var now := _bone_xf(b).origin
			print("MODE %s %d %s moved %.3f m state %s" % [m, i, bone, now.distance_to(start), state])
	press.call(at, false)
	if m == "pin":
		for i in 90:
			await get_tree().process_frame
		var h := skel.find_bone("LeftHand" if bone != "LeftHand" else "RightHand")
		var q := cam.unproject_position(_bone_xf(h).origin)
		press.call(q, true)
		for i in 40:
			move.call(q + Vector2(-minf(i, 30) * 6.0, -minf(i, 30) * 3.0))
			await get_tree().process_frame
		press.call(q + Vector2(-180, -90), false)
		print("PINS %d state %s" % [ragdoll.pins.size(), state])
		# The other modes leave the pins be: a drag in play, a click in poke.
		for m2 in ["play", "poke"]:
			mode = m2
			var hp := cam.unproject_position(_bone_xf(skel.find_bone("Hips")).origin)
			press.call(hp, true)
			for i in 20:
				move.call(hp + Vector2(i * 4.0 if m2 == "play" else 0.0, 0.0))
				await get_tree().process_frame
			press.call(hp + Vector2(80, 0), false)
			for i in 30:
				await get_tree().process_frame
			print("PINS after %s: %d state %s" % [m2, ragdoll.pins.size(), state])
	for i in 120:
		await get_tree().process_frame
		if i % 20 == 0:
			var now := _bone_xf(b).origin
			print("AFTER %d %s moved %.3f m state %s" % [i, bone, now.distance_to(start), state])


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
	if OS.get_environment("PET_FPS_CAP") != "":
		Engine.max_fps = int(OS.get_environment("PET_FPS_CAP"))     # a test run at her live frame rate (the cap is set in _process, which tests skip)
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
