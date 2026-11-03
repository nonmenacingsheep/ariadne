extends RefCounted
# Her places' states (docs/PET_STATES_PLAN.md): the ways she can be at a piece
# of furniture (sitting on the bed's edge, lying back, asleep) and the moves
# between them, from pet/states.json. pet.gd asks for a state like it asks for
# a role ("Bed_Sleep"); next_exit() says which move gets her one step closer,
# so from standing she sits on the edge, lies back, then sleeps, and never
# stands up between two ways of being in bed. "" is standing on her feet.

const FILE := "res://states.json"

var pet
var table := {}                            # state -> its entry in states.json
var usable := {}                           # clip prefix -> she has a clip for it


func _init(owner) -> void:
	pet = owner
	var f := FileAccess.open(FILE, FileAccess.READ)
	if f:
		var d = JSON.parse_string(f.get_as_text())
		if d is Dictionary:
			for k in d:
				if not String(k).begins_with("_"):
					table[k] = d[k]


func has(s: String) -> bool:
	return table.has(s)


func spot(s: String) -> String:
	return str(table.get(s, {}).get("spot", ""))


# What she does in a state: its idles, or the ones for what she's holding.
func pool(s: String, holding: String) -> Array:
	var e: Dictionary = table.get(s, {})
	var items: Dictionary = e.get("items", {})
	if holding != "" and items.has(holding) and (items[holding] as Array).any(func(x): return _has_clip(str(x[0]))):
		return items[holding]
	return e.get("idles", [])


func react(s: String) -> Array:
	var e: Dictionary = table.get(s, {})
	return e.get("react", e.get("idles", []))


func sleep_state(s: String) -> String:
	return str(table.get(s, {}).get("sleep", s))


func wake_state(s: String) -> String:
	return str(table.get(s, {}).get("wake", s))


func talk_state(s: String) -> String:
	var to := str(table.get(s, {}).get("talk", s))
	return to if reachable(to) else s


# The place a state belongs to: the bit before the underscore (Bed_SitEdge: Bed).
func place_of(s: String) -> String:
	return s.get_slice("_", 0) if has(s) else ""


# Every move out of a state: [to, clip prefix, lift]. Out of standing, the
# move into each state that can be entered from standing.
func _edges(s: String) -> Array:
	var out := []
	if s == "":
		for k in table:
			if table[k].has("enter"):
				out.append([k, str(table[k]["enter"]), "lerp"])
		return out
	var e: Dictionary = table.get(s, {})
	if e.has("leave"):
		out.append(["", str(e["leave"]), "lerp"])
	var ex: Dictionary = e.get("exits", {})
	for k in ex:
		out.append([k, str(ex[k].get("clip", "")), str(ex[k].get("lift", "lerp"))])
	return out


func _has_clip(prefix: String) -> bool:
	if prefix == "":
		return true
	if not usable.has(prefix):
		usable[prefix] = pet.ap.has_animation(prefix) or pet._variant_of(prefix) != ""
	return usable[prefix]


# The first move on the shortest way from one state to another (breadth
# first over moves she has clips for): {to, clip, lift}, or {} if there's no
# way (or she's there).
func next_exit(from: String, to: String) -> Dictionary:
	if from == to:
		return {}
	var first := {from: []}
	var queue := [from]
	while not queue.is_empty():
		var s: String = queue.pop_front()
		for e in _edges(s):
			if first.has(e[0]) or not _has_clip(e[1]):
				continue
			first[e[0]] = first[s] if s != from else e
			if e[0] == to:
				var m: Array = first[to]
				return {"to": m[0], "clip": m[1], "lift": m[2]}
			if e[0] != "":                     # through standing means walking: not a way within a place
				queue.append(e[0])
	return {}


func reachable(s: String) -> bool:
	return has(s) and (not next_exit("", s).is_empty())


# She can be in that state doing something there with what she's holding.
func can(s: String, holding := "") -> bool:
	if not reachable(s):
		return false
	for e in pool(s, holding):
		if _has_clip(str(e[0])):
			return true
	return false


# A clip that is one of the moves (it's played once, as the way between).
func is_move(name: String) -> bool:
	for s in table:
		for e in _edges(s):
			if e[1] != "" and name.begins_with(e[1]):
				return true
	for e in _edges(""):
		if e[1] != "" and name.begins_with(e[1]):
			return true
	return false
