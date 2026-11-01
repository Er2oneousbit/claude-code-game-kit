# ---------------------------------------------------------------------------
# i18n.gd
# Purpose : Localization logic (engine-free): string tables with a fallback chain (fr-CA -> fr -> en), {name}
#           placeholders, plural categories, and the pseudo-locale that makes untranslated, clipped or truncated
#           text easy to spot.
# Usage   : var tables := I18n.load_tables("res://data/i18n")             # {"en": {...}, "fr": {...}}
#           I18n.translate(tables, "fr-CA", "menu.play")                  # "Jouer"
#           I18n.translate(tables, "en", "greet", {"name": "Ana"})        # "Hello, Ana!"
#           I18n.translate_plural(tables, "fr", "apples", 0)              # "0 pomme" (French: 0 and 1 are "one")
#           I18n.pseudo("Play")                                           # "[Pláý~~]"
# Notes   : In the game, call Shell.t(key), which picks the player's locale and handles "pseudo". Not named tr():
#           every Godot Object already has a tr() for the engine's own TranslationServer, which this kit does not
#           use. A missing key returns the key itself, so it shows on screen. Tables are flat JSON objects
#           (data/i18n/<locale>.json). Tested against data/golden/shell.json.
#
# Pseudocode:
#   chain(locale) = [locale, its language part, "en"] without repeats
#   translate: first table in the chain that has the key, then fill {name} placeholders from args
#   pseudo: accent letters, keep {name} and %s %d %i %f %% as they are, add ~ for 40 % of the visible
#     characters, wrap in [ ]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
class_name I18n
extends RefCounted

const FALLBACK: String = "en"
const PSEUDO_LOCALE: String = "pseudo"
const PSEUDO_GROWTH: float = 0.40 # translated English runs about 40 % longer
const PSEUDO_MAP: Dictionary = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "c": "ç", "n": "ñ", "y": "ý",
		"A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú", "C": "Ç", "N": "Ñ", "Y": "Ý"}
const PRINTF_CODES: String = "sdif%"


static func locale_chain(locale: String, fallback: String = FALLBACK) -> PackedStringArray:
	var chain: PackedStringArray = []
	for loc: String in [locale, locale.split("-")[0].split("_")[0], fallback]:
		if loc != "" and not chain.has(loc):
			chain.append(loc)
	return chain


static func lookup(tables: Dictionary, locale: String, key: String) -> Variant:
	# The raw string from the first table in the chain that has key, or null
	for loc: String in locale_chain(locale):
		var table: Variant = tables.get(loc, {})
		if typeof(table) == TYPE_DICTIONARY and (table as Dictionary).has(key):
			return str(table[key])
	return null


static func translate(tables: Dictionary, locale: String, key: String, args: Dictionary = {}) -> String:
	var text: Variant = lookup(tables, locale, key)
	if typeof(text) == TYPE_NIL:
		return key
	return fill(str(text), args)


static func plural(locale: String, n: float) -> String:
	var base: String = locale.split("-")[0].split("_")[0]
	if base in ["ja", "zh", "ko"]:
		return "other"
	if base == "fr":
		return "one" if n == 0.0 or n == 1.0 else "other"
	return "one" if n == 1.0 else "other"


static func translate_plural(tables: Dictionary, locale: String, key: String, n: float,
		args: Dictionary = {}) -> String:
	var a: Dictionary = args.duplicate()
	a["n"] = n
	return translate(tables, locale, key + "." + plural(locale, n), a)


static func fill(text: String, args: Dictionary) -> String:
	# Replace {name} with args[name]; unknown names stay as they are
	var out: String = ""
	var i: int = 0
	while i < text.length():
		if text[i] == "{":
			var j: int = text.find("}", i)
			if j > i:
				var name: String = text.substr(i + 1, j - i - 1)
				if args.has(name):
					out += value_text(args[name])
					i = j + 1
					continue
		out += text[i]
		i += 1
	return out


static func value_text(v: Variant) -> String:
	# A whole float prints as an integer ("3", not Godot's "3.0"), like the other engines of the kit
	if typeof(v) == TYPE_FLOAT and is_finite(v) and float(v) == floorf(float(v)) and absf(v) < 1e15:
		return str(int(v))
	return str(v)


static func pseudo(text: String) -> String:
	var out: String = ""
	var visible: int = 0
	var i: int = 0
	while i < text.length():
		var c: String = text[i]
		if c == "{":
			var j: int = text.find("}", i)
			if j > i:
				out += text.substr(i, j - i + 1)
				i = j + 1
				continue
		if c == "%" and i + 1 < text.length() and PRINTF_CODES.contains(text[i + 1]):
			out += text.substr(i, 2)
			i += 2
			continue
		out += str(PSEUDO_MAP.get(c, c))
		visible += 1
		i += 1
	return "[" + out + "~".repeat(ceili(visible * PSEUDO_GROWTH)) + "]"


static func load_tables(dir: String) -> Dictionary:
	# Every <locale>.json in dir; a broken file is skipped (and reported by the caller through the result)
	var tables: Dictionary = {}
	if not DirAccess.dir_exists_absolute(dir):
		return tables
	for file: String in DirAccess.get_files_at(dir):
		var name: String = file.trim_suffix(".remap") # exported builds may list remapped names
		if not name.ends_with(".json"):
			continue
		var text: Variant = AtomicFile.read_text(dir.path_join(name))
		if typeof(text) == TYPE_NIL:
			continue
		var json: JSON = JSON.new()
		if json.parse(str(text)) == OK and typeof(json.data) == TYPE_DICTIONARY:
			tables[name.get_basename()] = json.data
	return tables
