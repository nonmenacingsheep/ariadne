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
	"play_ball": true, "nap": true, "seek_cursor": true, "react_to_work": true, "lip_sync": true}
var shown := true                          # Desktop: her body
var settings_mtime := 0
var settings_check := 0.0

const FACE := {   # VRoid face shapes
	"blink": "Fcl_EYE_Close", "joy": "Fcl_ALL_Joy", "sorrow": "Fcl_ALL_Sorrow",
	"angry": "Fcl_ALL_Angry", "surprised": "Fcl_ALL_Surprised", "fun": "Fcl_ALL_Fun",
	"a": "Fcl_MTH_A", "i": "Fcl_MTH_I", "u": "Fcl_MTH_U", "e": "Fcl_MTH_E", "o": "Fcl_MTH_O",
}
# Her voice's emotion marks (Cartesia's names) onto her face.
const EMOTION_FACE := {
	"happy": "joy", "excited": "joy", "content": "fun", "calm": "fun", "sarcastic": "fun",
	"sad": "sorrow", "angry": "angry", "surprised": "surprised", "curious": "surprised",
}

var tcp := StreamPeerTCP.new()
var inbox := ""
var retry_in := 0.0
var said_hello := false

var body: Node3D
var skel: Skeleton3D
var ap: AnimationPlayer
var face := {}                            # key -> [[mesh, index], ...]
var bones := {}
var cam: Camera3D
var screen := Vector2(3440, 1366)

# Where she is (metres, origin bottom-left of the window) and what she's doing.
var pos := Vector2(3.0, 0.0)
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
var drag_from := Vector2.ZERO
var drag_moved := false
var last_rect := Rect2()
var snapshot_path := OS.get_environment("PET_SNAPSHOT")


func _ready() -> void:
	get_viewport().transparent_bg = true
	get_window().title = "ariadne2-pet"      # KWin finds her by this (desk/kwin_layer.js)
	_cover_ultrawide()
	body = (load(MODEL) as PackedScene).instantiate()
	add_child(body)
	skel = _find(body, "Skeleton3D")
	for key in FACE:
		face[key] = _find_shapes(body, FACE[key])
	for k in moods:
		mood_target[k] = moods[k]
	for b in ["Neck", "Head", "Hips"]:
		var i := skel.find_bone(b)
		if i >= 0:
			bones[b] = i
	_load_clips()
	_sample_carry_pose()
	_make_slab()
	_camera()
	life = load("res://life.gd").new()
	add_child(life)
	life.setup(self)
	_read_layout()
	pos = Vector2(screen.x / PPM * 0.3, 0.0)
	_land()
	_play("Idle")
	if snapshot_path != "":
		_snapshot.call_deferred()
	else:
		_connect()


# --- window and camera ------------------------------------------------------
func _cover_ultrawide() -> void:
	if snapshot_path != "":
		get_window().size = Vector2i(1500, 700)
		return
	for s in DisplayServer.get_screen_count():
		var r := DisplayServer.screen_get_usable_rect(s)
		if r.size.x >= 3000:
			screen = Vector2(r.size)
			get_window().position = r.position
			get_window().size = r.size


func _camera() -> void:
	cam = Camera3D.new()
	cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	cam.size = screen.y / PPM                 # orthographic: one metre is PPM pixels
	cam.position = Vector3(screen.x / PPM / 2.0, screen.y / PPM / 2.0, 10.0)
	add_child(cam)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-30, 20, 0)
	light.light_energy = 1.1
	add_child(light)


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
		if name != "core":
			floors.append([(screen.y - float(r[1])) / PPM, x0 + 0.15, x1 - 0.15])


func _land() -> void:
	# The highest surface at or below her feet that she's over.
	var best := [0.0, 0.0, screen.x / PPM]
	for fl in floors:
		if pos.x >= fl[1] and pos.x <= fl[2] and fl[0] <= pos.y + 0.05 and fl[0] >= best[0]:
			best = fl
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
				_react("Idle_No")
		"flow":
			if msg.get("phase", "") == "fired":
				_watch(str(msg.get("widget", "")), 2.0)
		"chat":
			_stir()
			if msg.get("role", "") == "you" and msg.get("done", false):
				life.bump("affection", 0.03)
		"state":
			if msg.get("widget", "") == "spotify" and msg.get("data") is Dictionary:
				spotify_playing = msg["data"].get("status", "") == "playing"


func _stir() -> void:
	last_activity = t
	if state == "sleep":
		_set_state("idle", 2.0)
		_play("Idle")


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
	var lib := AnimationLibrary.new()
	for path in CLIPS:
		var src: Node = (load(path) as PackedScene).instantiate()
		var player := _find(src, "AnimationPlayer") as AnimationPlayer
		if player:
			for name in player.get_animation_list():
				if not lib.has_animation(name):
					lib.add_animation(name, player.get_animation(name))
		src.free()
	ap.add_animation_library("", lib)


func _play(name: String, blend := 0.3, speed := 1.0) -> void:
	if not ap.has_animation(name):
		return
	if clip == name and ap.is_playing():
		ap.speed_scale = speed
		return
	clip = name
	ap.play(name, blend)
	ap.speed_scale = speed


func _set_state(s: String, seconds: float) -> void:
	state = s
	state_until = t + seconds


# What she does next when she's free: mostly idle and wandering, sometimes
# sitting on a widget's edge, folding her arms, or dancing if music is on.
func _choose() -> void:
	var on_widget := floor_y > 0.01
	match life.wish():
		"sleep":
			_set_state("sleep", 1e9)
			_play("Sitting_Idle" if on_widget else "Crouch_Idle", 1.0, 0.6)
			return
		"find_him":
			var cursor := DisplayServer.mouse_get_position() - get_window().position
			target_x = clampf(cursor.x / PPM, floor_span.x, floor_span.y)
			if absf(target_x - pos.x) > 0.3:
				_set_state("wander", 20.0)
				_play("Walk", 0.3, 0.75)
				return
			_set_state("react", 2.0)
			_play("Interact", 0.3)
			_face_front(2.5)
			return
		"ball":
			life.play_ball()
			return
		"dance":
			_set_state("dance", randf_range(8, 14))
			_play("Dance", 0.4, 0.9)
			return
	var r := randf()
	if spotify_playing and r < 0.3 and allow["dance_to_music"]:
		_set_state("dance", randf_range(6, 12))
		_play("Dance", 0.4, 0.9)
	elif r < 0.55 and allow["wander"]:
		target_x = clampf(pos.x + randf_range(-2.5, 2.5), floor_span.x, floor_span.y)
		if absf(target_x - pos.x) > 0.3:
			_set_state("wander", 20.0)
			_play("Walk", 0.3, 0.75)
			return
		_set_state("idle", 3.0)
	elif r < 0.7 and on_widget and allow["sit_on_widgets"]:
		_set_state("sit", randf_range(10, 25))
		_play("Sitting_Idle", 0.5)
	elif r < 0.78:
		_set_state("idle", randf_range(4, 8))
		_play("Idle_FoldArms", 0.4)
	else:
		_set_state("idle", randf_range(3, 7))
		_play("Idle", 0.4)


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
	if av.has("size") and absf(float(av["size"]) - PPM) > 0.5:
		PPM = clampf(float(av["size"]), 200, 840)
		screen = Vector2.ZERO                 # forces the camera to re-fit
	# Hidden while she wears another body (a Live2D model: ariadne2/pet2d).
	var want_shown: bool = bool(desk.get("body", true)) and str(av.get("model", "aries")) == "aries"
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
		cam.size = screen.y / PPM
		cam.position = Vector3(screen.x / PPM / 2.0, screen.y / PPM / 2.0, 10.0)
		_read_layout()
		_land()


func fetch(x: float) -> void:
	target_x = clampf(x, floor_span.x, floor_span.y)
	_set_state("fetch", 30.0)
	_play("Jog_Fwd", 0.25, 0.8)


func _process(delta: float) -> void:
	t += delta
	_sync_screen()
	_poll_core(delta)
	layout_check -= delta
	if layout_check <= 0.0 and snapshot_path == "":   # pick up layout changes every few seconds
		layout_check = 4.0
		var path := OS.get_environment("HOME") + "/.config/ariadne2/layout.json"
		if FileAccess.get_modified_time(path) != layout_mtime:
			_read_layout()
			_land()

	settings_check -= delta
	if settings_check <= 0.0 and snapshot_path == "":
		settings_check = 3.0
		_read_settings()
	if not shown:
		Engine.max_fps = 5                  # still reading settings, so she can come back
		return
	_think(delta)
	_move(delta)
	ap.advance(delta)                       # clips first, then her arms, head and face on top
	_carry_frame(delta)
	_head()
	_face_frame(delta)
	_place_body()
	_update_click_area()
	var busy: bool = state in ["wander", "fall", "held", "react", "dance", "knocked", "fetch", "throw", "eat", "pickup"] or (life != null and life.ball_live) or speaking or t < mood_until or (slab and slab.visible)
	Engine.max_fps = FPS_BUSY if busy else FPS_IDLE


func _think(_delta: float) -> void:
	if state in ["fall", "held"] or (state == "knocked" and t < state_until):
		return
	if state == "hug":
		_play("Idle_FoldArms", 0.4)          # arms round the plush
	if allow["nap"] and state != "sleep" and t - last_activity > SLEEP_AFTER and state in ["idle", "sit"]:
		_set_state("sleep", 1e9)
		_play("Sitting_Idle" if floor_y > 0.01 else "Crouch_Idle", 1.0, 0.6)
		return
	if state == "fetch":
		return
	if speaking and state in ["idle", "wander"]:
		if state == "wander":
			_set_state("idle", 2.0)
		_play("Idle_Talking", 0.3)
		yaw_target = 0.0
		return
	if t > state_until and state != "sleep":
		if state == "sit":
			_play("Sitting_Exit", 0.2)
			_set_state("idle", 1.2)
			return
		if state == "hug":
			life._hold("")
		_choose()


func _move(delta: float) -> void:
	match state:
		"wander":
			var dir := signf(target_x - pos.x)
			pos.x += dir * WALK_SPEED * delta
			yaw_target = dir * 1.2
			if absf(target_x - pos.x) < 0.05:
				_set_state("idle", randf_range(2, 5))
				_play("Idle", 0.3)
				yaw_target = 0.0
			elif (pos.x < floor_span.x or pos.x > floor_span.y) and not allow["walk_off_edges"]:
				pos.x = clampf(pos.x, floor_span.x, floor_span.y)   # stays on her widget
				_set_state("idle", 2.0)
				_play("Idle", 0.3)
			elif pos.x < floor_span.x or pos.x > floor_span.y:
				# Walked off the edge of a widget: down she goes.
				_set_state("fall", 99.0)
				vel = Vector2(dir * WALK_SPEED, 0.0)
				_play("Jump", 0.15)
		"fall":
			var before := pos.y
			vel.y -= GRAVITY * delta
			pos += vel * delta
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
				if pos.x >= fl[1] and pos.x <= fl[2] and pos.y <= fl[0] and before >= fl[0] - 0.02:
					pos.y = fl[0]
					landed = true
			if pos.y <= 0.0:
				pos.y = 0.0
				landed = true
			if landed:
				var impact := -vel.y
				vel = Vector2.ZERO
				spin = 0.0
				_land()
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
		"fetch":
			var fdir := signf(target_x - pos.x)
			pos.x += fdir * WALK_SPEED * 2.4 * delta
			yaw_target = fdir * 1.3
			pos.y = floor_y
			if absf(target_x - pos.x) < 0.1:
				yaw_target = 0.0
				_set_state("pickup", 1.3)
				_play("PickUp_Table", 0.2)
				get_tree().create_timer(0.8).timeout.connect(func(): life.picked_up_ball())
		"held":
			# Dangling from your cursor: she sways behind the way you move her.
			roll = lerpf(roll, clampf(-held_vel.x * 0.09, -0.7, 0.7), clampf(delta * 6.0, 0.0, 1.0))
		"knocked":
			pos.y = floor_y
			if t > state_until - 1.4 and clip != "LayToIdle":
				_play("LayToIdle", 0.25)
		_:
			pos.y = floor_y
	if state not in ["fall", "held"]:
		roll = lerpf(roll, 0.0, clampf(delta * 8.0, 0.0, 1.0))
	pos.x = clampf(pos.x, 0.3, screen.x / PPM - 0.3)
	if t > look_until and state != "wander":
		yaw_target = sin(t * 0.17) * 0.25
	yaw = lerp_angle(yaw, yaw_target, clampf(delta * 5.0, 0.0, 1.0))


func _place_body() -> void:
	var sitting := clip.begins_with("Sitting") and floor_y > 0.01
	body.position = Vector3(pos.x, pos.y - (SIT_DROP if sitting else 0.0), 0.0)
	# Roll about the point she's held by (her upper chest), not her feet.
	var pivot := Vector3(0, 1.3, 0)
	body.rotation = Vector3(0, yaw, roll)
	if state in ["held", "fall"]:
		body.position += pivot - pivot.rotated(Vector3.FORWARD, -roll)


func _head() -> void:
	if t > look_until:
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


# a i u e o: step through the vowels of the sentence she's saying, at the
# pace the sentence actually lasts, opened as wide as her voice is loud.
func _speech_frame(delta: float) -> void:
	if speech_on.is_empty() and not speech.is_empty():
		speech_on = speech.pop_front()
		speech_at = 0.0
		var em: String = speech_on.get("emotion", "")
		if EMOTION_FACE.has(em):
			_feel(EMOTION_FACE[em], 0.6, float(speech_on["seconds"]) + 0.5)
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
	for pair in face.get(key, []):
		(pair[0] as MeshInstance3D).set_blend_shape_value(pair[1], w)


# --- picking her up -----------------------------------------------------------
func _update_click_area() -> void:
	if snapshot_path != "":
		return
	var sitting := clip.begins_with("Sitting") and floor_y > 0.01
	var feet := cam.unproject_position(Vector3(pos.x, pos.y - (SIT_DROP if sitting else 0.0), 0))
	var head := cam.unproject_position(Vector3(pos.x, pos.y + 1.62, 0))
	var r := Rect2(Vector2(feet.x - 70, head.y - 10), Vector2(140, feet.y - head.y + 20))
	if life != null and life.ring_open:
		r = r.merge(life.ring_rect())
	if r.position.distance_to(last_rect.position) < 3 and r.size.distance_to(last_rect.size) < 3:
		return
	last_rect = r
	DisplayServer.window_set_mouse_passthrough(PackedVector2Array([
		r.position, r.position + Vector2(r.size.x, 0), r.end, r.position + Vector2(0, r.size.y)]))


func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_RIGHT and event.pressed:
		if life.ring_open:
			life.close_ring()
		else:
			life.open_ring(cam.unproject_position(Vector3(pos.x, pos.y + 1.7, 0)))
		return
	if life.ring_open and event is InputEventMouseButton and event.pressed:
		if not life.ring.get_global_rect().has_point(event.position):
			life.close_ring()
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			drag_from = event.position
			drag_moved = false
			held_vel = Vector2.ZERO
			_stir()
			_set_state("held", 1e9)
			_feel("surprised", 0.4, 1.0)
		else:
			if drag_moved:
				# Let go: she keeps the speed you threw her with, and spins with it.
				_set_state("fall", 99.0)
				vel = held_vel.limit_length(MAX_THROW)
				spin = clampf(-vel.x * 1.6, -9.0, 9.0)
				_play("Jump", 0.15)
				if vel.length() > 4.0:
					_feel("surprised", 0.8, 1.2)
			else:                              # a click, not a drag: she nods at you
				life.bump("affection", 0.06)
				_set_state("react", 1.6)
				_play("Yes", 0.2)
				_feel("joy", 0.7, 1.5)
				_face_front(2.0)
	elif event is InputEventMouseMotion and state == "held":
		if event.position.distance_to(drag_from) > 4:
			if not drag_moved:
				_play("Jump", 0.15, 0.0)      # a dangling pose while held
			drag_moved = true
		var v: Vector2 = event.velocity / PPM
		held_vel = held_vel.lerp(Vector2(v.x, -v.y), 0.5)
		pos = Vector2(event.position.x / PPM, (screen.y - event.position.y) / PPM - 1.3)


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
	if not ap.has_animation("Walk_Carry"):
		return
	ap.play("Walk_Carry")
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


# PET_SNAPSHOT=path: render her in a few clips, one image each, then quit.
func _snapshot() -> void:
	floors.append([0.9, 0.0, 99.0])
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
		_place_body()
		await get_tree().process_frame
		await get_tree().process_frame
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(snapshot_path.replace(".png", "_" + s[3] + ".png"))
	get_tree().quit()
