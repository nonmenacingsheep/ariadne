extends SceneTree
# Does a body load, and can her clips drive it? (ariadne2/core/body3d.py, after
# importing a drop-in.) godot --headless --path pet --script res://import/check_body.gd -- res://models/dropin/x.glb
# One line: BODYCHECK {"ok", "missing", "mapped", "fingers", "height" (head, m), "meshes", "skeleton_path"}.

const NEED := ["Hips", "Spine", "Head", "LeftUpperArm", "LeftLowerArm", "LeftHand", "RightUpperArm",
		"RightLowerArm", "RightHand", "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "RightUpperLeg", "RightLowerLeg", "RightFoot"]


func _init() -> void:
	var out := {"ok": false}
	var args := OS.get_cmdline_user_args()
	var ps = load(args[0]) if args.size() > 0 and ResourceLoader.exists(args[0]) else null
	if not ps is PackedScene:
		out["why"] = "Godot couldn't load it"
	else:
		var root: Node = (ps as PackedScene).instantiate()
		get_root().add_child(root)
		var found := root.find_children("*", "Skeleton3D", true, false)
		if found.is_empty():
			out["why"] = "it has no skeleton"
		else:
			var sk := found[0] as Skeleton3D
			out["skeleton_path"] = String(root.get_path_to(sk))
			var profile := SkeletonProfileHumanoid.new()
			var mapped := 0
			for i in profile.bone_size:
				if sk.find_bone(profile.get_bone_name(i)) >= 0:
					mapped += 1
			out["mapped"] = mapped
			out["fingers"] = sk.find_bone("LeftIndexProximal") >= 0
			out["missing"] = NEED.filter(func(b): return sk.find_bone(b) < 0)
			out["meshes"] = root.find_children("*", "MeshInstance3D", true, false).size()
			if sk.find_bone("Head") >= 0:
				out["height"] = (sk.global_transform * sk.get_bone_global_rest(sk.find_bone("Head"))).origin.y
			out["ok"] = (out["missing"] as Array).is_empty() and int(out["meshes"]) > 0
			if int(out["meshes"]) == 0:
				out["why"] = "it has no meshes to show"
	print("BODYCHECK " + JSON.stringify(out))
	quit()
