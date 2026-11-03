# ---------------------------------------------------------------------------
# telemetry.gd
# Purpose : Local, opt-in play telemetry (engine-free): one CSV row per event, written only when the player said
#           yes. Nothing is sent anywhere; the file stays in the game's data folder.
# Usage   : Telemetry.append(path, GameSettings.telemetry_allowed(settings), session_id, "level_start", "1-2")
#           In the game: Shell.telemetry("level_start", "1-2")
# Notes   : Consent "unset" (never asked, or "Later") and "no" both mean no file at all. Columns, the same in
#           every engine: time (UTC, ISO 8601, whole seconds, 2026-11-02T14:05:03Z), session (8 hex digits, random
#           per launch), event, detail. Tested against data/golden/telemetry.json. To send data somewhere, read
#           docs/ENGINE_FLOW.md "Telemetry" first: an endpoint changes what the privacy policy must say.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name Telemetry
extends RefCounted

const HEADER: String = "time,session,event,detail"
const SESSION_LENGTH: int = 8 # hex digits in a session id


static func new_session() -> String:
	# A random id per launch, so rows of one run can be grouped
	return "%08x" % randi()


static func time_string(unix_s: float) -> String:
	# Whole seconds: a fraction is dropped, not rounded (as the reference does)
	return Time.get_datetime_string_from_unix_time(int(floor(unix_s))) + "Z"


static func csv_field(value: String) -> String:
	# Quote fields with commas, quotes or line breaks (RFC 4180)
	if value.contains(",") or value.contains("\"") or value.contains("\n") or value.contains("\r"):
		return "\"" + value.replace("\"", "\"\"") + "\""
	return value


static func row(time: String, session: String, event: String, detail: String) -> String:
	return ",".join([csv_field(time), csv_field(session), csv_field(event), csv_field(detail)])


static func append(path: String, allowed: bool, session: String, event: String, detail: String = "") -> bool:
	# Returns true when a row was written
	if not allowed:
		return false
	var is_new: bool = not FileAccess.file_exists(path)
	if is_new:
		DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var f: FileAccess = FileAccess.open(path, FileAccess.WRITE if is_new else FileAccess.READ_WRITE)
	if f == null:
		return false
	if is_new:
		f.store_line(HEADER)
	else:
		f.seek_end()
	f.store_line(row(time_string(Time.get_unix_time_from_system()), session, event, detail))
	f.close()
	return true

# {{FOOTER}}
