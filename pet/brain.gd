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
	"idle": [10.0, false], "wander": [35.0, false], "look_around": [60.0, false], "stretch": [120.0, false],
	"think": [60.0, false], "explore": [40.0, true], "sit_floor": [60.0, true], "lie": [90.0, true],
	"nap": [300.0, true], "sit_ledge": [60.0, false], "dance": [20.0, false],
	"watch_him": [45.0, true], "find_him": [60.0, true], "cheer": [120.0, false], "follow": [90.0, true],
	# At her furniture (room.gd, docs/PET_LIFE_PLAN.md).
	"sleep_bed": [600.0, true], "work": [120.0, true], "game": [150.0, true], "eat": [600.0, true],
	"read": [180.0, true], "phone": [150.0, true], "meditate": [240.0, true], "workout": [300.0, true],
	"drink": [240.0, true], "water": [900.0, true], "tidy": [300.0, true],
	# Staying where she is: another way of being at the same place (lying back, then onto her side).
	"linger": [20.0, false],
	# One of her interactions (play.json: on her own, with her things, at the glass).
	"play": [50.0, false], "play_more": [240.0, false],
	# Her things anywhere (phase 9): her phone on her feet, a book on the floor.
	"phone_about": [200.0, true], "read_floor": [240.0, true],
	# A little story (episodes.json, docs/PET_EPISODES_PLAN.md): a few beats, and how it ends.
	"episode": [150.0, true],
}
var episodes := {}                         # episodes.json
var episode_at := {}                       # episode -> when it last ran (pet.t)
var force_branch := -1                     # a test run's chosen ending
var watered_at := -1e9


func _init(owner) -> void:
	pet = owner
	var raw = JSON.parse_string(FileAccess.get_file_as_string("res://episodes.json")) \
			if FileAccess.file_exists("res://episodes.json") else null
	if raw is Dictionary:
		for k in raw:
			if not String(k).begins_with("_"):
				episodes[k] = raw[k]


# He grabbed her, gave her an order, or woke her: whatever she meant to do is off.
func drop() -> void:
	plan.clear()
	follow_until = 0.0
	pet.walk_style = ""
	if pet.things and pet.things.is_out():
		pet.things.do("flee")                  # whatever it was scuttles off


# He's talking to her: she stops what she's doing, turns, and comes up to the front.
func attend() -> void:
	if doing == "attend" and plan_left():
		return
	drop()
	doing = "attend"
	if pet.pstate != "":
		# In bed or at the desk: she sits up (or turns round) where she is and waves.
		var to: String = pet.places.talk_state(pet.pstate)
		plan = [{"play": to, "state": "rest", "for": 2.0}, {"play": to + ":react", "state": "rest", "for": 2.5},
				{"play": to, "state": "rest", "for": randf_range(8, 12)}]
		return
	if pet.floor_y < 0.01 and pet.depth < -0.5:
		plan.append({"go": Vector2(clampf(pet.pos.x, _x0(), _x1()), -randf_range(0.15, 0.35))})
	plan.append({"play": "play:listen" if pet.play and not pet.play.entry("listen").is_empty() else "Idle",
			"front": true, "for": randf_range(8, 14)})


# He wiggled the pointer at her: over she comes, and follows it about a while.
func come_to_cursor() -> void:
	drop()
	doing = "follow"
	last_done["find_him"] = pet.t
	plan = [{"go": Vector2(clampf(_cursor_x(), _x0(), _x1()), -0.25)},
			{"play": "Interact", "state": "react", "front": true, "for": 1.8},
			{"follow": pet.t + randf_range(10, 16)},
			{"play": "Idle", "front": true, "for": randf_range(3, 6)}]


# Asked to be somewhere (her avatar tool): there, maybe with a thing fetched first.
func be(st: String, thing: String, secs: float) -> void:
	drop()
	doing = "asked"
	if pet.life.THINGS.has(thing):
		plan += _fetch(thing)
	plan += [_to(pet.places.spot(st)), {"play": st, "state": "rest", "for": secs}]
	if pet.life.THINGS.has(thing):
		plan.append({"done_with": thing})


func plan_left() -> bool:
	return not plan.is_empty()


# Called when she's free: the next step of the plan, or a new plan.
func next() -> void:
	if pet.pending != "" and pet._is_state_role(pet.clip):
		# Still on the way into a state (lying back, sitting up): its time starts when she's there.
		pet._set_state(pet.state, maxf(0.1, pet.variant_until - pet.t) + 0.05)
		return
	if plan.is_empty():
		_pick()
	if plan.is_empty():
		pet._set_state("idle", 2.0)
		pet._play("Idle", 0.4)
		return
	var step: Dictionary = plan[0]
	if step.has("to") and pet.pstate != "" and pet.room.spot(pet.places.spot(pet.pstate)).get("approach") == step["go"]:
		plan.pop_front()                       # already there (in bed, at the desk)
		next()
		return
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
	if step.has("walk"):
		pet.walk_style = step["walk"] if _has(step["walk"]) else ""
	elif not step.has("go"):
		pet.walk_style = ""
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
	elif step.has("thing"):
		# Something appears on the floor a little in front of her (and to one side).
		var side := Vector3(cos(pet.yaw), 0, -sin(pet.yaw))
		var at: Vector3 = pet.ground_ahead(float(step.get("at", 0.45))) + side * randf_range(-0.12, 0.12)
		match step.get("where", "floor"):
			"above": at = pet.face_point(0.16) + Vector3(0, 1.1, 0)                 # a spider's thread, a leaf
			"air": at = pet.face_point(0.5) + side * (0.9 if randf() < 0.5 else -0.9)    # a butterfly coming by
		pet.things.spawn(step["thing"], at)
		next()
	elif step.has("thing_do"):
		var to: Vector3 = pet.ground_ahead(0.22) if step.get("to", "") == "her" else Vector3.ZERO
		pet.things.do(step["thing_do"], to)
		next()
	elif step.has("hold"):
		var item: String = step["hold"]
		pet.life._hold(item)
		if item == "can" and pet.room.items.has("watering_can"):
			pet.room.items["watering_can"].visible = false      # it's in her hand now
		next()
	elif step.has("interact"):
		if not pet.play.run(step["interact"], true):
			next()
	elif step.has("take"):
		pet.life.take(step["take"])
		next()
	elif step.has("put"):
		pet.life.leave(step["put"])
		next()
	elif step.has("done_with"):
		# Finished with it: now and then left where she is (a book on the bed,
		# the bowl on the table), else put back where it lives.
		var th: String = step["done_with"]
		var here: String = pet.perched
		var home: String = pet.life.THINGS.get(th, "")
		if pet.life.holding != th:
			pass
		elif here == home or (here != "" and pet.room.spot(here).has("drop") and randf() < 0.35):
			pet.life.leave(here)
		else:
			plan = _put_away(th) + plan
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
		if step.has("face"):
			# Reaching for something on the desk or the bed: turned to it.
			var at: Vector3 = pet.room.spot(step["face"]).get("drop", Vector3(pet.pos.x, 0, pet.depth - 1.0))
			pet.yaw_target = atan2(at.x - pet.pos.x, at.z - pet.depth)
			pet.look_until = pet.t + float(step.get("for", 2.0))
		pet._play(_first_clip(step["play"]), 0.25 if step.get("quick", false) else 0.4, float(step.get("speed", 1.0)))
		if step.get("end", false):
			# To the end of the clip (and the move into its stance before it, if any).
			var secs := maxf(0.3, pet.variant_until - pet.t)
			if pet.pending != "" and pet.ap.has_animation(pet.pending):
				secs += pet.ap.get_animation(pet.pending).length / maxf(0.1, float(step.get("speed", 1.0)))
			pet._set_state(step.get("state", "idle"), maxf(0.3, secs - 0.15))
		var secs_for: float = float(step.get("for", 3.0))
		if step.has("mood"):
			pet._feel(step["mood"], float(step.get("mood_w", 0.8)), secs_for + 1.0)
		if step.has("emote") and pet.play:
			pet.play.show_emote(step["emote"])
		match step.get("look", ""):
			"ground": pet.look_at_world(pet.ground_ahead(0.45), secs_for)
			"thing": pet.look_at_world(pet.things.thing, secs_for + 1.0)
			"front": pet._face_front(secs_for)
		if step.has("perch"):
			# Onto the furniture while the move into the stance plays (sitting down, lying down).
			pet._perch_on(step["perch"], maxf(0.4, pet.variant_until - pet.t) if pet.pending != "" else 0.4)
		for k in step.get("gain", {}):
			pet.life.bump(k, float(step["gain"][k]))


# A beat's clip: the first of its choices she has ("crouch_peer_" before the
# plain crouch, until the new takes are in).
func _first_clip(c: Variant) -> String:
	if c is Array:
		for x in c:
			if _has(x) or pet.ROLES.has(x):
				return x
		return (c as Array).back()
	return c


# An episode: the one picked from those she can do (their clips are here, the
# hour suits, not too soon again), its beats laid out as plan steps, and one
# of its endings chosen now.
func _episode() -> Array:
	var best := ""
	var best_w := 0.0
	for k in episodes:
		var e: Dictionary = episodes[k]
		if pet.t - float(episode_at.get(k, -1e9)) < float(e.get("cool", 900)):
			continue
		if e.get("night", false) and not _night() or e.get("day", false) and _night():
			continue
		if not (e.get("needs", []) as Array).all(func(c): return _has(c) or pet.ROLES.has(c)):
			continue
		var w: float = float(e.get("weight", 1.0))
		for f in e.get("mood", {}):
			w += pet._feeling(f) * float(e["mood"][f])
		w *= randf_range(0.6, 1.4)
		if w > best_w:
			best = k
			best_w = w
	if best == "":
		return []
	episode_at[best] = pet.t
	if logging:
		print("EPISODE %.0f %s" % [pet.t, best])
	return _beats(episodes[best]["beats"])


func _beats(beats: Array) -> Array:
	var out := []
	for b in beats:
		var d: Dictionary = (b as Dictionary).duplicate()
		if d.has("branch"):
			var total := 0.0
			for c in d["branch"]:
				total += float(c[0])
			if force_branch >= 0 and force_branch < (d["branch"] as Array).size():
				out += _beats(d["branch"][force_branch][1])
				continue
			var r := randf() * total
			for c in d["branch"]:
				r -= float(c[0])
				if r <= 0.0:
					out += _beats(c[1])
					break
			continue
		if d.has("go") and d["go"] is String:
			match d["go"]:
				"corner": d["go"] = _corner()
				"near": d["go"] = _spot(randf_range(0.8, 1.8))
				"far": d["go"] = _spot(randf_range(2.5, 4.5))
				"front": d["go"] = Vector2(clampf(pet.pos.x, _x0(), _x1()), -0.3)
				_: d["go"] = _spot(randf_range(1.5, 3.5))
		out.append(d)
	return out


func _pick() -> void:
	var on_widget: bool = pet.floor_y > 0.01
	var best := ""
	var best_score := 0.0
	var scores := {}
	for a in ACTIVITIES:
		if pet.pstate != "" and a in ["idle", "look_around", "stretch", "think", "cheer"]:
			continue                           # in bed or at the desk, "linger" covers these
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
		"idle": return 0.75
		"wander": return (1.0 + bored * 0.5 - tired * 0.3) if allow["wander"] else 0.0       # he likes watching her walk
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
		"read": return (0.25 + bored * 0.3 + tired * 0.1) if _room("shelf") and not _with("book").is_empty() else 0.0
		"phone": return (0.15 + lonely * 0.3 + bored * 0.2) if _room("desk") and not _with("phone").is_empty() else 0.0
		"meditate": return (0.08 + sorrow * 0.4 + float(pet.moods.get("angry", 0.0))) \
				if _room("mat") and _has("meditate_") else 0.0
		"workout":
			if not (_room("mat") and _has("workout_")) or float(n["energy"]) < 0.35 or _night():
				return 0.0
			return maxf(0.0, 0.75 - float(n.get("fitness", 0.6))) * 1.8 + joy * 0.1
		"drink": return 0.2 + maxf(0.0, 0.6 - float(n["hunger"])) * 0.5 if _room("kitchen") and _has("drink_") else 0.0
		"phone_about": return (0.1 + lonely * 0.2 + bored * 0.2) if _room("desk") and _has("stand_phone_") else 0.0
		"read_floor": return (0.1 + bored * 0.2 + tired * 0.15) if _room("shelf") and _has("floor_front_read_") else 0.0
		"play", "play_more":
			if pet.play == null or pet.play.names().is_empty():
				return 0.0
			return (0.5 if a == "play" else 0.12) + bored * 0.35 + joy * 0.1 - tired * 0.3
		"linger":
			if pet.pstate == "" or _stay_in().is_empty():
				return 0.0
			return 0.55 + tired * 0.2 + (0.3 if pet.state == "rest" else 0.0)
		"tidy": return (0.15 + 0.12 * pet.life.left.size() + bored * 0.2) if not pet.life.left.is_empty() else 0.0
		"episode": return (0.45 + bored * 0.5 + joy * 0.1 - tired * 0.3) if not episodes.is_empty() and allow["wander"] else 0.0
		"water":
			if not (_room("plant") and _room("can") and _has("water_plant_")):
				return 0.0
			return minf(1.0, (pet.t - watered_at) / 7200.0) * 0.7
	return 0.0


# Each activity's steps. A spot is (x, depth) on the floor; depth 0 is the front.
func _plan(a: String, on_widget: bool) -> Array:
	var rd: float = pet.room_depth
	match a:
		"idle": return [{"play": "Idle", "for": randf_range(10, 20)}]
		"wander":
			if on_widget:
				return [{"go": Vector2(clampf(pet.pos.x + randf_range(-1.0, 1.0), pet.floor_span.x + 0.2,
						pet.floor_span.y - 0.2), 0.0)}, {"play": "Idle", "for": randf_range(2, 4)}]
			return [{"go": _spot(randf_range(1.5, 4.5))}, {"play": "Idle", "for": randf_range(4, 8)}]
		"look_around": return [{"play": "LookAround", "for": randf_range(5, 9)}]
		"episode": return _episode()
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
		"sleep_bed":
			# Sitting on the edge a moment, maybe lying about a bit, then asleep.
			if pet.places.place_of(pet.pstate) == "Bed":
				return [{"call": "_bed_sleep"}]
			var b := [_to("bed_edge"), {"play": "Bed_SitEdge", "state": "rest", "for": randf_range(3, 7)}]
			for s in ["Bed_LieSide", "Bed_LieBack"]:
				if randf() < 0.4 and pet.places.can(s):
					b.append({"play": s, "state": "rest", "for": randf_range(5, 10)})
					break
			return b + [{"call": "_bed_sleep"}]
		"play", "play_more":
			# One thing, or a little run of them (play_more), walking up to the glass for the glass ones.
			var out := []
			for i in (1 if a == "play" else randi_range(2, 3)):
				var n: String = pet.play.pick()
				if n == "":
					break
				var wid = pet.play.entry(n).get("widget", false)
				var behind: Array = pet.widget_x.keys() if wid is bool else ([wid] if pet.widget_x.has(wid) else [])
				if wid and not behind.is_empty():
					# Behind a widget on the glass: hiding, peeking round it, reading it.
					out.append({"go": Vector2(clampf(float(pet.widget_x[behind.pick_random()]) + randf_range(-0.3, 0.3), _x0(), _x1()),
							-randf_range(0.15, 0.25))})
				elif pet.play.entry(n).get("glass", false):
					out.append({"go": Vector2(clampf(pet.pos.x + randf_range(-1.0, 1.0), _x0(), _x1()), -randf_range(0.12, 0.22))})
				elif i > 0 and randf() < 0.5:
					out.append({"go": _spot(randf_range(0.5, 1.5))})
				out.append({"interact": n})
			return out
		"linger":
			var st: String = _stay_in().pick_random()
			return [{"play": st, "state": "rest", "for": randf_range(12, 30)}]
		"work": return [_to("desk"), {"play": "Desk_Sit", "state": "work", "for": randf_range(45, 90),
				"gain": {"purpose": 0.3, "energy": -0.03, "fun": -0.03}}]
		"game": return _fetch("controller") + [_to("desk"), {"play": "Desk_Sit", "state": "work",
				"for": randf_range(30, 60), "gain": {"fun": 0.3, "energy": -0.02}}, {"done_with": "controller"}]
		"eat":
			var e: Array = []
			if _room("kitchen") and _has("cook_"):
				e += [_to("kitchen"), {"play": "Kitchen_Stand", "for": randf_range(6, 9)}]
			return e + _fetch("bowl") + [_to("cushion"), {"play": "Cushion_Sit", "state": "rest",
					"for": randf_range(20, 35), "gain": {"hunger": 0.6}}, {"done_with": "bowl"}]
		"read": return _fetch("book") + _settle_with("book", randf_range(30, 60), {"fun": 0.15}) + [{"done_with": "book"}]
		"phone": return _fetch("phone") + _settle_with("phone", randf_range(20, 40), {"fun": 0.1, "affection": 0.03}) \
				+ [{"done_with": "phone"}]
		"phone_about":
			# Scrolling on her feet, wandering a little between looks.
			return _fetch("phone") + [{"play": "Idle", "for": randf_range(8, 14), "gain": {"fun": 0.05}},
					{"go": _spot(randf_range(0.8, 2.0))}, {"play": "Idle", "for": randf_range(8, 14)},
					{"done_with": "phone"}]
		"read_floor":
			# Down on the floor wherever she is with a book: sitting, or on her stomach.
			return _fetch("book") + [{"go": _spot(randf_range(0.5, 2.0))},
					{"play": "FloorSit" if randf() < 0.5 else "LieDown", "state": "rest", "for": randf_range(25, 45),
					"gain": {"fun": 0.12}}, {"done_with": "book"}]
		"tidy":
			var th: String = pet.life.left.keys().pick_random()
			return _fetch(th) + _put_away(th)
		"meditate": return [_to("mat"), {"play": "Mat_Meditate", "state": "rest", "for": randf_range(25, 45),
				"gain": {"energy": 0.04}}]
		"workout":
			# A routine down the mat's states: warm-up and standing work, a
			# stretch sitting, floor work on her back, a plank, back up to cool down.
			var w := [_to("mat"), {"play": "Mat_Stand", "state": "workout", "for": randf_range(20, 35),
					"gain": {"fitness": 0.2, "energy": -0.06, "fun": 0.05}}]
			for st in [["Mat_Sit", 8.0], ["Mat_Lie", 14.0], ["Mat_Plank", 8.0], ["Mat_Sit", 5.0]]:
				if pet.places.can(st[0]):
					w.append({"play": st[0], "state": "workout", "for": float(st[1]) * randf_range(0.8, 1.3),
							"gain": {"fitness": 0.04}})
			return w + [{"play": "Mat_Stand", "state": "workout", "for": 0.5}, {"play": "Stretch", "for": 4.0}]
		"drink":
			# A mug of tea at the counter, and now and then taken to bed to finish.
			var d := _fetch("mug") + [_to("kitchen"), {"play": "Kitchen_Stand", "for": randf_range(6, 10),
					"gain": {"hunger": 0.08}}]
			if randf() < 0.4:
				d += _settle_with("mug", randf_range(15, 25), {}, true)
			return d + [{"done_with": "mug"}]
		"water":
			watered_at = pet.t
			return [_to("can"), {"play": "PickUp_Table", "state": "react", "perch": "can", "for": 1.4},
					{"hold": "can"}, _to("plant"), {"play": "Water", "perch": "plant", "for": randf_range(6, 8)},
					{"release": true}]
	return []


# Getting one of her things from wherever it is (life.gd where()): a reach at
# its home or where she left it, then it's in her hand.
func _fetch(thing: String) -> Array:
	if pet.life.holding == thing:
		return []
	var at: String = pet.life.where(thing)
	var reach := {"play": "PickUp_Table", "state": "react", "for": 1.4}
	reach["perch" if at in ["shelf", "kitchen"] else "face"] = at
	return [_to(at), reach, {"take": thing}]


func _put_away(thing: String) -> Array:
	var home: String = pet.life.THINGS.get(thing, "")
	var reach := {"play": "PickUp_Table", "state": "react", "for": 1.4}
	reach["perch" if home in ["shelf", "kitchen"] else "face"] = home
	return [_to(home), reach, {"put": home}]


# The states she can settle into with a thing in her hands (a book: sitting
# up in bed, on her stomach, at the desk, on the cushion): any with idles for it.
func _with(thing: String) -> Array:
	var out := []
	for s in pet.places.table:
		if (pet.places.table[s].get("items", {}) as Dictionary).has(thing) and pet.places.can(s, thing) \
				and _room(pet.places.spot(s)):
			out.append(s)
	return out


# Settling in somewhere with it for a while: one or two of those states in a
# row (sitting up reading, then over onto her stomach), so she shifts about.
func _settle_with(thing: String, secs: float, gain: Dictionary, bed_only := false) -> Array:
	var ok := _with(thing).filter(func(s): return not bed_only or s.begins_with("Bed_"))
	if ok.is_empty():
		return []
	var first: String = ok.pick_random()
	var out := [_to(pet.places.spot(first)), {"play": first, "state": "rest", "for": secs, "gain": gain}]
	var more := ok.filter(func(s): return s != first and s.get_slice("_", 0) == first.get_slice("_", 0))
	if not more.is_empty() and randf() < 0.6:
		out[1]["for"] = secs * 0.6
		out.append({"play": more.pick_random(), "state": "rest", "for": secs * 0.4})
	return out


# The other ways of being where she is now (in bed: lying back, on her side,
# sitting up), that she can do with what she's holding; asleep only if tired.
func _stay_in() -> Array:
	var place: String = pet.places.place_of(pet.pstate)
	var out := []
	for s in pet.places.table:
		if s == pet.pstate or pet.places.place_of(s) != place or not pet.places.can(s, pet.life.holding):
			continue
		if pet.places.sleep_state(s) == s and pet.places.table[s].has("wake") and pet._feeling("tired") < 0.6:
			continue                           # not asleep unless she's tired
		out.append(s)
	return out


# Walking to a piece of furniture's spot (no need if she's already at that
# place: from lying in bed to sitting up, she doesn't get out first).
func _to(name: String) -> Dictionary:
	return {"go": pet.room.spot(name).get("approach", Vector2(pet.pos.x, pet.depth)), "to": name}


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
