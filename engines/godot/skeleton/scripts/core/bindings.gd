# ---------------------------------------------------------------------------
# bindings.gd
# Purpose : Input bindings as data (engine-free): the default bindings, rebinding with a swap, which prompt art
#           set to show (keyboard, Xbox, PlayStation, generic) and the glyph file name for one binding.
# Usage   : var r := Bindings.rebind(settings.input.bindings, "jump", 0, "key:k")   # {bindings, conflicts}
#           var gset := Bindings.glyph_set(settings.input.glyphs, Shell.last_device)
#           var art := Bindings.glyph_name(gset, Bindings.prompt_binding(bindings, "jump", gset))  # "key_space"
# Notes   : A binding is "<kind>:<name>": key:space, mouse:left, pad:south (the bottom face button on every pad),
#           pad_axis:leftx- . Slot 0 is the keyboard/mouse binding, slot 1 the gamepad one. Actions named ui_* form
#           one group and everything else another: a binding may repeat across groups (Escape is both ui_cancel and
#           pause) but not inside one. scripts/shell/input_binder.gd turns these strings into Godot InputEvents.
#           Tested against data/golden/shell.json.
#
# Pseudocode:
#   rebind: copy; old = the slot's binding ("" for a new slot); every other (action, slot) of the same group with
#           the new binding is a conflict; set the slot; each conflict gets old (a swap, or "" = unbound)
#   glyph_name: key/mouse -> key_<name>/mouse_<name>; pad -> xbox_/ps_/pad_ + the set's button name; axis -> stick
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Bindings
extends RefCounted

const DEFAULT_BINDINGS: Dictionary = {
	"ui_up": ["key:up", "pad:dpad_up"], "ui_down": ["key:down", "pad:dpad_down"],
	"ui_left": ["key:left", "pad:dpad_left"], "ui_right": ["key:right", "pad:dpad_right"],
	"ui_accept": ["key:enter", "pad:south"], "ui_cancel": ["key:escape", "pad:east"],
	"move_left": ["key:a", "pad:dpad_left"], "move_right": ["key:d", "pad:dpad_right"],
	"move_up": ["key:w", "pad:dpad_up"], "move_down": ["key:s", "pad:dpad_down"],
	"jump": ["key:space", "pad:south"], "attack": ["key:j", "pad:west"],
	"interact": ["key:e", "pad:north"], "pause": ["key:escape", "pad:start"],
}
# Order of the actions in the Controls screen (the game's own actions first)
const ACTION_ORDER: PackedStringArray = ["move_left", "move_right", "move_up", "move_down", "jump", "attack",
		"interact", "pause", "ui_up", "ui_down", "ui_left", "ui_right", "ui_accept", "ui_cancel"]
const DEVICE_SETS: Dictionary = {"keyboard": "keyboard", "mouse": "keyboard", "pad_xbox": "xbox",
		"pad_playstation": "playstation"}
const XBOX: Dictionary = {"south": "a", "east": "b", "west": "x", "north": "y", "l1": "lb", "r1": "rb",
		"l2": "lt", "r2": "rt", "start": "menu", "select": "view"}
const PLAYSTATION: Dictionary = {"south": "cross", "east": "circle", "west": "square", "north": "triangle",
		"start": "options", "select": "share"}


static func defaults() -> Dictionary:
	return DEFAULT_BINDINGS.duplicate(true)


static func group_of(action: String) -> String:
	return "ui" if action.begins_with("ui_") else "game"


static func rebind(bindings: Dictionary, action: String, slot: int, binding: String) -> Dictionary:
	# Returns {"bindings": new copy, "conflicts": [[action, slot], ...] sorted by action}; {} for a slot past the end
	var b: Dictionary = bindings.duplicate(true)
	if not b.has(action):
		b[action] = []
	var lst: Array = b[action]
	if slot > lst.size() or slot < 0:
		push_error("Bindings.rebind: slot %d past the end of %s" % [slot, action])
		return {}
	var old: String = str(lst[slot]) if slot < lst.size() else ""
	var conflicts: Array = []
	var names: Array = b.keys()
	names.sort()
	for other: String in names:
		if group_of(other) != group_of(action):
			continue
		var other_list: Array = b[other]
		for s: int in other_list.size():
			if (other != action or s != slot) and binding != "" and _same(other_list[s], binding):
				conflicts.append([other, s])
	if slot == lst.size():
		lst.append(binding)
	else:
		lst[slot] = binding
	for c: Array in conflicts:
		var target: Array = b[c[0]]
		target[c[1]] = old
	return {"bindings": b, "conflicts": conflicts}


static func duplicates(bindings: Dictionary) -> PackedStringArray:
	# Actions that share a binding with another action of their group (a hand-edited file can do that)
	var seen: Dictionary = {} # "group|binding" -> first action
	var out: PackedStringArray = []
	var names: Array = bindings.keys()
	names.sort()
	for action: String in names:
		var lst: Variant = bindings[action]
		if typeof(lst) != TYPE_ARRAY:
			continue
		for b: Variant in lst:
			if typeof(b) != TYPE_STRING or b == "":
				continue
			var key: String = group_of(action) + "|" + str(b)
			if seen.has(key) and seen[key] != action:
				for name: String in [seen[key], action]:
					if not out.has(name):
						out.append(name)
			else:
				seen[key] = action
	return out


static func glyph_set(setting: String, last_device: String) -> String:
	# Which prompt art to show: the player's choice, or (auto) the last device used
	if setting != "auto":
		return setting
	return str(DEVICE_SETS.get(last_device, "generic"))


static func glyph_name(gset: String, binding: String) -> String:
	var colon: int = binding.find(":")
	var kind: String = binding if colon < 0 else binding.substr(0, colon)
	var name: String = "" if colon < 0 else binding.substr(colon + 1)
	if kind == "key":
		return "key_" + name
	if kind == "mouse":
		return "mouse_" + name
	if kind == "pad_axis":
		name = "lstick" if name.begins_with("left") else "rstick"
	elif kind != "pad":
		return "unknown"
	if gset == "xbox":
		return "xbox_" + str(XBOX.get(name, name))
	if gset == "playstation":
		return "ps_" + str(PLAYSTATION.get(name, name))
	return "pad_" + name


static func prompt_binding(bindings: Dictionary, action: String, gset: String) -> String:
	# The binding to show for an action: slot 0 (keyboard) for the keyboard set, slot 1 (pad) otherwise
	var lst: Variant = bindings.get(action, [])
	if typeof(lst) != TYPE_ARRAY:
		return ""
	var slot: int = 0 if gset == "keyboard" else 1
	return str(lst[slot]) if slot < lst.size() else ""


static func _same(value: Variant, binding: String) -> bool:
	return typeof(value) == TYPE_STRING and value == binding

# {{FOOTER}}
