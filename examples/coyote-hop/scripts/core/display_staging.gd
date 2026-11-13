# ---------------------------------------------------------------------------
# display_staging.gd
# Purpose : The Display tab's Apply (#308, SOP-19 section 2): Display changes wait for Apply while every other tab
#           applies at once; Apply sends only the changed fields, mode before resolution; a mode or resolution change
#           opens a "Keep these display settings?" countdown that puts back exactly what that Apply replaced.
# Usage   : var st := DisplayStaging.new(Shell.settings["display"])
#           st.stage("mode", "fullscreen")        # the control shows st.value("mode"); nothing applied yet
#           for call: Array in st.apply(): Shell.set_value("display", call[0], call[1])
#           st.tick_real(Time.get_ticks_usec())   # each frame while st.confirming(): the revert calls when time is up
#           st.keep() | st.revert() | st.back()   # back() -> ["revert" | "warn" | "leave", calls]
# Notes   : Engine-free: it never touches the window, it returns the [field, value] calls the shell makes. The
#           reference is DisplayStaging in tools/golden_vectors.py; tests/test_golden_shell.gd runs every
#           display_staging case of data/golden/shell.json. Values compare by value (numbers as numbers, arrays item
#           by item): JSON gives floats, the controls ints, and 1 == 1.0 must count as "unchanged". Feed tick() real
#           seconds (Time.get_ticks_usec()), never a frame delta: the countdown must not follow game speed, a hitstop,
#           a paused tree or --fixed-fps.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name DisplayStaging
extends RefCounted

const APPLY_ORDER: PackedStringArray = ["mode", "resolution", "vsync", "frame_cap", "ui_scale"] # mode first
const CONFIRM_FIELDS: PackedStringArray = ["mode", "resolution"] # can black out the screen: Apply asks "keep these?"
const CONFIRM_S: float = 15.0 # real seconds before an unanswered confirm reverts

var applied: Dictionary = {}
var pending: Dictionary = {}
var replaced: Dictionary = {} # field -> the value the last apply replaced
var left: float = -1.0 # confirm countdown in seconds; below 0 when closed
var warned: bool = false
var clock_us: int = -1 # tick_real(): the time of the last tick, -1 before the first one of a confirm


func _init(p_applied: Dictionary) -> void:
	applied = p_applied.duplicate(true)


## The value the control shows: the pending one, else the applied one.
func value(field: String) -> Variant:
	return pending[field] if pending.has(field) else applied[field]


func confirming() -> bool:
	return left >= 0.0


func has_pending() -> bool:
	return not pending.is_empty()


## A pending change; staging the applied value drops it. "busy" while a confirm is open (controls are disabled then).
func stage(field: String, v: Variant) -> String:
	if confirming():
		return "busy"
	if same(v, applied[field]):
		pending.erase(field)
	else:
		pending[field] = _copy(v)
	warned = false
	return "staged"


## The pending fields that differ from the applied ones, as [field, value] calls in APPLY_ORDER.
func apply() -> Array:
	var changed: Dictionary = {}
	for f: String in pending:
		if not same(pending[f], applied[f]):
			changed[f] = pending[f]
	replaced = {}
	for f: String in changed:
		replaced[f] = _copy(applied[f])
	pending = {}
	warned = false
	var calls: Array = _assign(changed)
	for f: String in CONFIRM_FIELDS:
		if changed.has(f):
			left = CONFIRM_S
			clock_us = -1
			break
	return calls


## ceil(seconds left) for "Reverting in N s", or -1 when no confirm is open.
func seconds() -> int:
	return ceili(left) if confirming() else -1


## The countdown: returns the revert calls when it reaches 0, else [].
func tick(dt: float) -> Array:
	if not confirming():
		return []
	left -= dt
	return revert() if left <= 0.0 else []


## tick() from a real clock in microseconds (Time.get_ticks_usec()): the first call of a confirm only starts it.
func tick_real(now_us: int) -> Array:
	if not confirming():
		clock_us = -1
		return []
	if clock_us < 0:
		clock_us = now_us
		return []
	var dt: float = float(now_us - clock_us) / 1000000.0
	clock_us = now_us
	return tick(dt)


func keep() -> void:
	left = -1.0
	replaced = {}


## Puts back exactly what the last apply replaced.
func revert() -> Array:
	var calls: Array = _assign(replaced)
	left = -1.0
	replaced = {}
	return calls


## ["revert", calls] while a confirm is open; ["warn", []] the first time with pending changes; else
## ["leave", []] (pending changes discarded).
func back() -> Array:
	if confirming():
		return ["revert", revert()]
	if not pending.is_empty() and not warned:
		warned = true
		return ["warn", []]
	pending = {}
	warned = false
	return ["leave", []]


## Value equality across JSON floats and control ints: numbers by value, arrays and dictionaries item by item.
static func same(a: Variant, b: Variant) -> bool:
	var num: Array = [TYPE_INT, TYPE_FLOAT]
	if typeof(a) in num and typeof(b) in num:
		return is_equal_approx(float(a), float(b))
	if typeof(a) != typeof(b):
		return false
	if typeof(a) == TYPE_ARRAY:
		if (a as Array).size() != (b as Array).size():
			return false
		for i: int in (a as Array).size():
			if not same(a[i], b[i]):
				return false
		return true
	if typeof(a) == TYPE_DICTIONARY:
		if (a as Dictionary).size() != (b as Dictionary).size():
			return false
		for k: Variant in a:
			if not (b as Dictionary).has(k) or not same(a[k], b[k]):
				return false
		return true
	return a == b


func _assign(values: Dictionary) -> Array:
	var calls: Array = []
	for f: String in APPLY_ORDER:
		if values.has(f):
			applied[f] = _copy(values[f])
			calls.append([f, _copy(values[f])])
	return calls


static func _copy(v: Variant) -> Variant:
	if typeof(v) == TYPE_ARRAY:
		return (v as Array).duplicate(true)
	if typeof(v) == TYPE_DICTIONARY:
		return (v as Dictionary).duplicate(true)
	return v
