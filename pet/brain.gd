extends RefCounted
# What she does with her time (docs/PET_AI_PLAN.md, phase 3). Every activity
# scores from her needs (life.gd), her feelings, the hour, what's going on
# (music, him nearby), where she is, and what she did lately; the best of a
# slightly shuffled lot wins. Each activity is a short plan: go somewhere in
# the room, then do something there for a while, so she looks like she means
# it. pet.gd owns her body: the brain only hands it the next step.

var pet                                    # pet.gd
var plan: Array = []                       # steps left: {go}, {play}, {hop_down}, {jump_up}, {call}
var doing := ""                            # the activity the plan belongs to
var last_done := {}                        # activity -> when it last started (pet.t)
var follow_until := 0.0                    # following his pointer about until then
var logging := OS.get_environment("PET_BRAIN_LOG") != ""

# name: [cooldown seconds, needs the floor (hops down first)]
const ACTIVITIES := {
	"idle": [10.0, false], "wander": [12.0, false], "look_around": [25.0, false], "stretch": [60.0, false],
	"think": [30.0, false], "explore": [40.0, true], "sit_floor": [60.0, true], "lie": [90.0, true],
	"nap": [300.0, true], "sit_ledge": [60.0, false], "dance": [20.0, false], "ball": [90.0, true],
	"watch_him": [45.0, true], "find_him": [60.0, true], "cheer": [60.0, false], "follow": [90.0, true],
	# At her furniture (room.gd, docs/PET_LIFE_PLAN.md).
	"sleep_bed": [600.0, true], "work": [120.0, true], "game": [150.0, true], "eat": [600.0, true],
	"read": [180.0, true], "phone": [150.0, true], "meditate": [240.0, true], "workout": [300.0, true],
	"drink": [240.0, true], "water": [900.0, true],
}
var watered_at := -1e9


func _init(owner) -> void:
	pet = owner


# He grabbed her, gave her an order, or woke her: whatever she meant to do is off.
func drop() -> void:
	plan.clear()
	follow_until = 0.0


# He's talking to her: she stops what she's doing, turns, and comes up to the front.
func attend() -> void:
	if doing == "attend" and plan_left():
		return
	drop()
	doing = "attend"
	if pet.floor_y < 0.01 and pet.depth < -0.5:
		plan.append({"go": Vector2(clampf(pet.pos.x, _x0(), _x1()), -randf_range(0.15, 0.35))})
	plan.append({"play": "Idle", "front": true, "for": randf_range(8, 14)})


# He wiggled the pointer at her: over she comes, and follows it about a while.
func come_to_cursor() -> void:
	drop()
	doing = "follow"
	last_done["find_him"] = pet.t
	plan = [{"go": Vector2(clampf(_cursor_x(), _x0(), _x1()), -0.25)},
			{"play": "Interact", "state": "react", "front": true, "for": 1.8},
			{"follow": pet.t + randf_range(10, 16)},
			{"play": "Idle", "front": true, "for": randf_range(3, 6)}]


func plan_left() -> bool:
	return not plan.is_empty()


# Called when she's free: the next step of the plan, or a new plan.
func next() -> void:
	if plan.is_empty():
		_pick()
	if plan.is_empty():
		pet._set_state("idle", 2.0)
		pet._play("Idle", 0.4)
		return
	var step: Dictionary = plan[0]
	if logging:
		print("STEP %.1f %s pstate=%s clip=%s variant=%s pending=%s perched=%s" % [pet.t, str(step), pet.pstate, pet.clip, pet.variant, pet.pending, pet.perched])
	if step.has("go") or step.has("hop_down") or step.has("jump_up") or step.has("follow"):
		if pet.pstate != "" or (pet.perch.has("t0") and pet.places.has(pet.clip)):
			# Out of bed or up from the desk first: the moves back to her feet play in turn.
			if pet.clip != "Idle":
				pet._play("Idle", 0.4)
			var wait := 0.3
			if pet.pending != "":
				wait = pet.variant_until - pet.t        # the move playing now
			if pet.perch.has("t0"):
				wait = maxf(wait, float(pet.perch["t0"]) + float(pet.perch["dur"]) - pet.t)
			pet._set_state("idle", maxf(0.1, wait) + 0.1)
			return
		if pet.perched != "":
			# Off the furniture first: she gets up while her body slides back to where she stood.
			if not pet.perch.has("off"):
				pet._play("Idle", 0.4)
				pet._unperch(maxf(0.5, pet.variant_until - pet.t) if pet._stance(pet.variant) != "stand" else 0.5)
			pet._set_state("idle", maxf(0.1, float(pet.perch.get("t0", pet.t)) + float(pet.perch.get("dur", 0.0)) - pet.t) + 0.1)
			return
		if pet._stance(pet.variant) != "stand" or pet.pending != "":
			# Up off the floor or the ledge first: the stance move plays, then the step.
			pet._set_state("idle", maxf(0.3, pet.variant_until - pet.t) + 0.1)
			pet._play("Idle", 0.4)
			return
	plan.pop_front()
	if step.has("go"):
		var g: Vector2 = step["go"]
		if not step.get("routed", false):
			# Round the furniture: the waypoints go in front of the rest of the plan.
			var way: Array[Vector2] = pet.room.route(Vector2(pet.pos.x, pet.depth), g)
			for i in range(way.size() - 1, 0, -1):
				plan.push_front({"go": way[i], "routed": true})
			g = way[0]
		pet.target_x = g.x
		pet.target_z = g.y
		if pet._to_target().length() > 0.3:
			pet._set_off(30.0)
		else:
			next()
	elif step.has("hop_down"):
		var x: float = clampf(pet.pos.x + randf_range(-0.6, 0.6), _x0(), _x1())
		pet._jump(x, 0.0)
	elif step.has("jump_up"):
		pet._jump(float(step["jump_up"].x), float(step["jump_up"].y))
	elif step.has("follow"):
		# Trailing his pointer along the front of the room until the time's up.
		follow_until = float(step["follow"])
		if pet.t >= follow_until:
			next()
			return
		plan.push_front(step)
		pet.target_x = clampf(_cursor_x(), _x0(), _x1())
		pet.target_z = -0.3
		if pet._to_target().length() > 0.6:
			pet._set_off(30.0)
		else:
			pet._set_state("idle", 0.8)
			pet._face_front(0.8)
	elif step.has("call"):
		pet.call(step["call"])
	elif step.has("hold"):
		var item: String = step["hold"]
		pet.life._hold(item)
		if item == "can" and pet.room.items.has("watering_can"):
			pet.room.items["watering_can"].visible = false      # it's in her hand now
		next()
	elif step.has("release"):
		pet.life._hold("")
		if pet.room.items.has("watering_can"):
			pet.room.items["watering_can"].visible = true
		next()
	else:
		pet._set_state(step.get("state", "idle"), float(step.get("for", 4.0)))
		if step.get("front", false):
			pet._face_front(float(step.get("for", 4.0)))
		pet._play(step["play"], 0.4, float(step.get("speed", 1.0)))
		if step.has("perch"):
			# Onto the furniture while the move into the stance plays (sitting down, lying down).
			pet._perch_on(step["perch"], maxf(0.4, pet.variant_until - pet.t) if pet.pending != "" else 0.4)
		for k in step.get("gain", {}):
			pet.life.bump(k, float(step["gain"][k]))


func _pick() -> void:
	var on_widget: bool = pet.floor_y > 0.01
	var best := ""
	var best_score := 0.0
	var scores := {}
	for a in ACTIVITIES:
		var s := _score(a, on_widget)
		if s <= 0.0:
			continue
		var since: float = pet.t - float(last_done.get(a, -1e9))
		var cool: float = ACTIVITIES[a][0]
		if cool > 0.0:
			s *= clampf(since / cool, 0.1, 1.0)    # just did it: less likely again so soon
		if a == doing:
			s *= 0.5
		s *= randf_range(0.7, 1.3)
		scores[a] = s
		if s > best_score:
			best = a
			best_score = s
	if best == "":
		return
	doing = best
	last_done[best] = pet.t
	plan = _plan(best, on_widget)
	if ACTIVITIES[best][1] and on_widget and not plan.is_empty():
		plan.push_front({"hop_down": true})
	if logging:
		var top := scores.keys()
		top.sort_custom(func(x, y): return scores[x] > scores[y])
		print("BRAIN %.0f %s  [%s]" % [pet.t, best, ", ".join(top.slice(0, 4).map(
				func(k): return "%s %.2f" % [k, scores[k]]))])


func _score(a: String, on_widget: bool) -> float:
	var n: Dictionary = pet.life.needs
	var allow: Dictionary = pet.allow
	var tired: float = pet._feeling("tired") + (0.4 if _night() else 0.0)
	var bored: float = pet._feeling("bored")
	var joy: float = pet._feeling("joy")
	var sorrow: float = pet._feeling("sorrow")
	var lonely := maxf(0.0, 0.6 - float(n["affection"])) * 2.5
	var near: bool = pet.t - pet.cursor_at < 4.0            # his pointer moving about
	match a:
		"idle": return 0.4
		"wander": return (0.8 + bored * 0.5 - tired * 0.3) if allow["wander"] else 0.0
		"look_around": return 0.35 + bored * 0.3 if _has("look_around_") else 0.0
		"stretch": return (0.2 + tired * 0.4 + (1.0 if doing in ["nap", "lie", "sit_floor"] else 0.0)) \
				if _has("stretch_") else 0.0
		"think": return 0.3
		"explore": return (0.35 + bored * 0.6) if allow["wander"] and _has("crouch_idle_") else 0.0
		"sit_floor": return 0.25 + tired * 0.6 + sorrow * 0.3 if _has("floor_sit_") else 0.0
		"lie": return 0.1 + tired * 0.7 + sorrow * 0.2 if _has("lie_idle_") else 0.0
		"nap":
			if not allow["nap"] or _bed():
				return 0.0
			return 3.0 if float(n["energy"]) < 0.2 else maxf(0.0, tired - 0.5) * 0.8
		"sit_ledge":
			if not allow["sit_on_widgets"] or (not on_widget and _ledges().is_empty()):
				return 0.0
			return (0.6 if on_widget else 0.3) + tired * 0.3
		"dance":
			if not (pet.spotify_playing and allow["dance_to_music"]):
				return 0.0
			return 1.0 + maxf(0.0, 0.7 - float(n["fun"])) * 2.0 + joy * 0.4
		"ball": return maxf(0.0, (0.75 - float(n["fun"])) * 1.6 - tired * 0.3) if allow["play_ball"] else 0.0
		"watch_him": return 0.25 + lonely * 0.5 + (0.5 if near else 0.0)
		"find_him":
			if not allow["seek_cursor"]:
				return 0.0
			return (1.5 if float(n["affection"]) < 0.3 else lonely * 0.3) + (0.2 if near else 0.0)
		"cheer": return joy * 0.25 if _has("cheer_") else 0.0
		"follow": return (0.3 + lonely * 0.4) if near and allow["seek_cursor"] else 0.0
		"sleep_bed":
			if not (allow["nap"] and _bed()):
				return 0.0
			return 3.0 if float(n["energy"]) < 0.2 else maxf(0.0, tired - 0.4) * 1.2 + (1.2 if _night() and tired > 0.3 else 0.0)
		"work":
			if not (_room("desk") and _has("work_")):
				return 0.0
			return maxf(0.0, 0.8 - float(n.get("purpose", 0.6))) * 1.6 + (0.35 if _work_hours() else 0.05) - tired * 0.3
		"game": return (0.15 + maxf(0.0, 0.7 - float(n["fun"])) * 1.2) if _room("desk") and _has("game_") else 0.0
		"eat":
			if not (_room("cushion") and _has("eat_")):
				return 0.0
			return maxf(0.0, 0.65 - float(n["hunger"])) * 3.5 + (0.35 if _meal_time() else 0.0)
		"read": return (0.25 + bored * 0.3) if _room("cushion") and _room("shelf") and _has("read_") else 0.0
		"phone": return (0.15 + lonely * 0.3 + bored * 0.2) if _room("cushion") and _has("phone_") else 0.0
		"meditate": return (0.08 + sorrow * 0.4 + float(pet.moods.get("angry", 0.0))) \
				if _room("mat") and _has("meditate_") else 0.0
		"workout":
			if not (_room("mat") and _has("workout_")) or float(n["energy"]) < 0.35 or _night():
				return 0.0
			return maxf(0.0, 0.75 - float(n.get("fitness", 0.6))) * 1.8 + joy * 0.1
		"drink": return 0.2 + maxf(0.0, 0.6 - float(n["hunger"])) * 0.5 if _room("kitchen") and _has("drink_") else 0.0
		"water":
			if not (_room("plant") and _room("can") and _has("water_plant_")):
				return 0.0
			return minf(1.0, (pet.t - watered_at) / 7200.0) * 0.7
	return 0.0


# Each activity's steps. A spot is (x, depth) on the floor; depth 0 is the front.
func _plan(a: String, on_widget: bool) -> Array:
	var rd: float = pet.room_depth
	match a:
		"idle": return [{"play": "Idle", "for": randf_range(4, 8)}]
		"wander":
			if on_widget:
				return [{"go": Vector2(clampf(pet.pos.x + randf_range(-1.0, 1.0), pet.floor_span.x + 0.2,
						pet.floor_span.y - 0.2), 0.0)}, {"play": "Idle", "for": randf_range(2, 4)}]
			return [{"go": _spot(randf_range(1.0, 3.5))}, {"play": "Idle", "for": randf_range(2, 5)}]
		"look_around": return [{"play": "LookAround", "for": randf_range(5, 9)}]
		"stretch": return [{"play": "Stretch", "for": randf_range(4, 6)}]
		"think": return [{"play": "Idle_FoldArms", "for": randf_range(5, 10)}]
		"explore":
			# Off somewhere further, then down on her heels to look at something on the floor.
			return [{"go": _spot(randf_range(2.0, 5.0))}, {"play": "Crouching", "for": randf_range(5, 9)},
					{"play": "LookAround", "for": 4.0}]
		"sit_floor": return [{"go": _spot(randf_range(0.5, 2.5))}, {"play": "FloorSit", "state": "rest", "for": randf_range(15, 35)}]
		"lie": return [{"go": _corner()}, {"play": "LieDown", "state": "rest", "for": randf_range(20, 45)}]
		"nap": return [{"go": _corner()}, {"call": "_nap"}]
		"sit_ledge":
			if on_widget:
				return [{"play": "Sitting_Idle", "state": "sit", "for": randf_range(15, 30)}]
			var l: Array = _ledges().pick_random()
			var x := clampf(pet.pos.x, float(l[1]) + 0.3, float(l[2]) - 0.3)
			# Ledges are widget tops at the front: walk up to it, hop on, sit.
			return [{"go": Vector2(x, 0.0)}, {"jump_up": Vector2(x, float(l[0]))},
					{"play": "Sitting_Idle", "state": "sit", "for": randf_range(15, 30)}]
		"dance": return [{"go": Vector2(_mid(), -rd * randf_range(0.15, 0.45))},
				{"play": "Dance", "state": "dance", "for": randf_range(10, 18), "speed": 0.9}]
		"ball": return [{"call": "_play_ball"}]
		"watch_him":
			return [{"go": Vector2(clampf(_cursor_x(), _x0(), _x1()), -0.25)},
					{"play": "Idle" if randf() < 0.6 else "Idle_FoldArms", "front": true, "for": randf_range(8, 16)}]
		"find_him":
			return [{"go": Vector2(clampf(_cursor_x(), _x0(), _x1()), -0.2)},
					{"play": "Interact", "state": "react", "front": true, "for": 2.0},
					{"play": "Idle", "front": true, "for": randf_range(4, 8)}]
		"cheer": return [{"play": "Cheer", "for": 3.0}]
		"follow": return [{"follow": pet.t + randf_range(8, 14)}, {"play": "Idle", "front": true, "for": 3.0}]
		# At her furniture. A spot's approach is where she walks to; "perch" puts her on it.
		# A state (pet/states.json) as the play: her body finds the moves into it.
		"sleep_bed": return [_to("bed_edge"), {"call": "_bed_sleep"}]
		"work": return [_to("desk"), {"play": "Desk_Sit", "state": "work", "for": randf_range(45, 90),
				"gain": {"purpose": 0.3, "energy": -0.03, "fun": -0.03}}]
		"game": return [_to("desk"), {"hold": "controller"}, {"play": "Desk_Sit", "state": "work",
				"for": randf_range(30, 60), "gain": {"fun": 0.3, "energy": -0.02}}, {"release": true}]
		"eat":
			var e: Array = []
			if _room("kitchen") and _has("cook_"):
				e += [_to("kitchen"), {"play": "Kitchen_Stand", "for": randf_range(6, 9)}]
			return e + [{"hold": "bowl"}, _to("cushion"), {"play": "Cushion_Sit", "state": "rest",
					"for": randf_range(20, 35), "gain": {"hunger": 0.6}}, {"release": true}]
		"read": return [_to("shelf"), {"play": "PickUp_Table", "state": "react", "perch": "shelf", "for": 1.4},
				{"hold": "book"}, _to("cushion"), {"play": "Cushion_Sit", "state": "rest",
				"for": randf_range(30, 60), "gain": {"fun": 0.15}}, {"release": true}]
		"phone": return [_to("cushion"), {"hold": "phone"}, {"play": "Cushion_Sit", "state": "rest",
				"for": randf_range(20, 40), "gain": {"fun": 0.1, "affection": 0.03}}, {"release": true}]
		"meditate": return [_to("mat"), {"play": "Mat_Sit", "state": "rest", "for": randf_range(25, 45),
				"gain": {"energy": 0.04}}]
		"workout": return [_to("mat"), {"play": "Mat_Stand", "state": "workout",
				"for": randf_range(30, 50), "gain": {"fitness": 0.3, "energy": -0.08, "fun": 0.05}},
				{"play": "Stretch", "for": 4.0}]
		"drink": return [_to("kitchen"), {"hold": "drink"}, {"play": "Kitchen_Stand",
				"for": randf_range(6, 10), "gain": {"hunger": 0.08}}, {"release": true}]
		"water":
			watered_at = pet.t
			return [_to("can"), {"play": "PickUp_Table", "state": "react", "perch": "can", "for": 1.4},
					{"hold": "can"}, _to("plant"), {"play": "Water", "perch": "plant", "for": randf_range(6, 8)},
					{"release": true}]
	return []


# Walking to a piece of furniture's spot.
func _to(name: String) -> Dictionary:
	return {"go": pet.room.spot(name).get("approach", Vector2(pet.pos.x, pet.depth))}


# Her bed, and the clips to get into it asleep.
func _bed() -> bool:
	return _room("bed_edge") and pet.places.reachable("Bed_Sleep")


func _room(piece: String) -> bool:
	return pet.room != null and pet.furniture and not pet.room.spot(piece).is_empty()


func _work_hours() -> bool:
	var d := Time.get_datetime_dict_from_system()
	return int(d["weekday"]) in [1, 2, 3, 4, 5] and int(d["hour"]) >= 9 and int(d["hour"]) < 17


func _meal_time() -> bool:
	var h: int = Time.get_time_dict_from_system()["hour"]
	return h in [7, 8, 12, 13, 18, 19]


# A floor spot about `dist` metres from her, anywhere in the room's depth.
func _spot(dist: float) -> Vector2:
	var rd: float = pet.room_depth
	for i in 8:
		var ang := randf() * TAU
		var p := Vector2(pet.pos.x, pet.depth) + Vector2(cos(ang), sin(ang)) * dist
		if p.x > _x0() and p.x < _x1() and p.y < -0.1 and p.y > -rd and not pet.room.blocked(p):
			return p
	return Vector2(randf_range(_x0(), _x1()), randf_range(-rd, -0.1))


# A back corner of the room, the nearer side: somewhere quiet to lie down.
func _corner() -> Vector2:
	var left: bool = pet.pos.x < _mid()
	return Vector2((_x0() + randf_range(0.2, 1.2)) if left else (_x1() - randf_range(0.2, 1.2)),
			-pet.room_depth + randf_range(0.2, 0.6))


func _ledges() -> Array:
	return pet.floors.filter(func(f): return float(f[0]) > 0.01 and float(f[2]) - float(f[1]) > 0.8)


func _has(prefix: String) -> bool:
	return pet._variant_of(prefix) != ""


func _night() -> bool:
	var h: int = Time.get_time_dict_from_system()["hour"]
	return h >= 23 or h < 6


func _mid() -> float:
	return pet.screen.x / pet.PPM / 2.0


func _x0() -> float:
	return 0.6


func _x1() -> float:
	return pet.screen.x / pet.PPM - 0.6


# His pointer, from the desktop's relay (pet.cursor) or, without it, the window system.
func _cursor_x() -> float:
	if pet.cursor_at > -50.0:
		return pet.cursor.x / pet.PPM
	var c: Vector2 = Vector2(DisplayServer.mouse_get_position() - pet.get_window().position)
	return c.x / pet.PPM
