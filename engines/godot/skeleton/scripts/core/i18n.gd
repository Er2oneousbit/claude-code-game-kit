# ---------------------------------------------------------------------------
# i18n.gd
# Purpose : Localization logic (engine-free): string tables with a fallback chain (fr-CA -> fr -> en), {name}
#           placeholders, CLDR plural categories, clean-language variants with a word mask, and the pseudo-locale
#           that makes untranslated, clipped or truncated text easy to spot.
# Usage   : var tables := I18n.load_tables("res://data/i18n")             # {"en": {...}, "fr": {...}}
#           I18n.translate(tables, "fr-CA", "menu.play")                  # "Jouer"
#           I18n.translate(tables, "en", "greet", {"name": "Ana"})        # "Hello, Ana!"
#           I18n.translate_plural(tables, "ru", "hits", 3)                # the "few" line (CLDR)
#           I18n.translate(tables, "en", "guard.insult", {}, true, words) # @clean line, listed words masked
#           I18n.pseudo("Play")                                           # "[Pláý~~]"
# Notes   : In the game, call Shell.t(key), which picks the player's locale, the clean-language switch and the
#           word lists, and handles "pseudo". Not named tr(): every Godot Object already has a tr() for the engine's
#           own TranslationServer, which this kit does not use. A missing key returns the key itself, so it shows on
#           screen. Tables are flat JSON objects (data/i18n/<locale>.json); word lists are
#           data/i18n/mature/<locale>.json ({"words": [...]}). Plural rules are CLDR 46's for whole numbers
#           (tools/golden_vectors.py PLURAL_FAMILIES). Godot strings index code points, so the word mask counts
#           them as the reference does. Tested against data/golden/shell.json.
#
# Pseudocode:
#   chain(locale) = [locale, its language part, "en"] without repeats
#   translate: per locale of the chain, key@clean (clean on) then key; fill {name}; clean -> mask_words
#   translate_plural: per locale, key.<its own category> then key.other (each @clean first)
#   pseudo: accent letters, keep {name} and %s %d %i %f %% as they are, add ~ for 40 % of the visible
#     characters, wrap in [ ]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): CLDR 46 plural rules, the .other fallback per
#           locale, @clean variants, mask_words, mature_words and load_mature (#207, #87)
# Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): compile_words and mask_word_set, so Shell folds its word
#           list once per locale and list (#207)
# ---------------------------------------------------------------------------
class_name I18n
extends RefCounted

const FALLBACK: String = "en"
const PSEUDO_LOCALE: String = "pseudo"
const PSEUDO_GROWTH: float = 0.40 # translated English runs about 40 % longer
const PSEUDO_MAP: Dictionary = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "c": "ç", "n": "ñ", "y": "ý",
		"A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú", "C": "Ç", "N": "Ñ", "Y": "Ý"}
const PRINTF_CODES: String = "sdif%"
const CLEAN_SUFFIX: String = "@clean" # "guard.insult@clean": the line with the clean-language setting on
const GRAWLIX: String = "#@$%" # the mask: one character per code point, from the start again for each word
# CLDR 46 whole-number plural rules: family -> languages (the reference's PLURAL_LANGUAGES)
const PLURAL_LANGUAGES: Dictionary = {
	"other": "ja zh ko vi th id ms lo my km yo ig jv su",
	"one": "en de nl sv da nb nn no fi et gl el hu tr bg eu af sq ka kk ky mn az uz ur sw ta te ml mr",
	"zero_one": "hi bn fa gu kn hy", "one_many": "es it ca", "zero_one_many": "fr pt", "one_21": "is mk",
	"fil": "fil tl", "east_slavic": "ru uk be", "pl": "pl", "cs": "cs sk", "lt": "lt", "balkan": "hr sr bs",
	"ro": "ro mo", "lv": "lv", "he": "he", "sl": "sl", "ga": "ga", "ar": "ar", "cy": "cy",
}
const PLURAL_LOCALE_FAMILIES: Dictionary = {"pt-pt": "one_many"} # a region with its own rule
const MILLION: int = 1000000
# code point ranges that are never part of a word (the reference's MASK_BOUNDARY_RANGES)
const MASK_BOUNDARY_RANGES: Array = [
	[0x0080, 0x00BF], [0x00D7, 0x00D7], [0x00F7, 0x00F7], [0x2000, 0x2BFF], [0x2E00, 0x2E7F], [0x3000, 0x303F],
	[0xFE00, 0xFE0F], [0xFE10, 0xFE1F], [0xFE30, 0xFE6F], [0xFEFF, 0xFEFF], [0xFF00, 0xFF0F], [0xFF1A, 0xFF20],
	[0xFF3B, 0xFF40], [0xFF5B, 0xFF65], [0x1F000, 0x1FAFF],
]


static func locale_chain(locale: String, fallback: String = FALLBACK) -> PackedStringArray:
	var chain: PackedStringArray = []
	for loc: String in [locale, locale.split("-")[0].split("_")[0], fallback]:
		if loc != "" and not chain.has(loc):
			chain.append(loc)
	return chain


static func _pick(table: Variant, key: String, clean: bool) -> Variant:
	# One table's text for key: its @clean variant first when clean is on, else key; null when neither
	if typeof(table) != TYPE_DICTIONARY:
		return null
	var t: Dictionary = table
	if clean and t.has(key + CLEAN_SUFFIX):
		return str(t[key + CLEAN_SUFFIX])
	if t.has(key):
		return str(t[key])
	return null


static func lookup(tables: Dictionary, locale: String, key: String, clean: bool = false) -> Variant:
	# The raw string through the chain (per locale: @clean first when clean is on), or null
	for loc: String in locale_chain(locale):
		var text: Variant = _pick(tables.get(loc, {}), key, clean)
		if typeof(text) != TYPE_NIL:
			return text
	return null


static func finish(text: String, args: Dictionary, clean: bool, words: Variant) -> String:
	# words: a PackedStringArray, or a set compile_words built already (the shell's cache)
	var out: String = fill(text, args)
	if not clean:
		return out
	if typeof(words) == TYPE_DICTIONARY:
		return mask_word_set(out, words)
	return mask_words(out, PackedStringArray(words))


static func translate(tables: Dictionary, locale: String, key: String, args: Dictionary = {},
		clean: bool = false, words: PackedStringArray = PackedStringArray()) -> String:
	var text: Variant = lookup(tables, locale, key, clean)
	if typeof(text) == TYPE_NIL:
		return key
	return finish(str(text), args, clean, words)


static func plural_family(locale: String) -> String:
	# The rule family: the full locale (pt-PT) first, then its language, then English's rule
	var norm: String = locale.replace("_", "-").to_lower()
	for name: String in PLURAL_LOCALE_FAMILIES:
		if norm == name or norm.begins_with(name + "-"):
			return str(PLURAL_LOCALE_FAMILIES[name])
	var lang: String = norm.split("-")[0]
	for fam: String in PLURAL_LANGUAGES:
		if lang in str(PLURAL_LANGUAGES[fam]).split(" "):
			return fam
	return "one"


static func plural(locale: String, count: float) -> String:
	# The CLDR category of a whole number (a negative one counts as its absolute value)
	var fam: String = plural_family(locale)
	var n: int = absi(int(count))
	var m10: int = n % 10
	var m100: int = n % 100
	match fam:
		"other":
			return "other"
		"one":
			return "one" if n == 1 else "other"
		"zero_one":
			return "one" if n <= 1 else "other"
		"one_many", "zero_one_many":
			if n == 1 or (n == 0 and fam == "zero_one_many"):
				return "one"
			return "many" if n != 0 and n % MILLION == 0 else "other"
		"one_21":
			return "one" if m10 == 1 and m100 != 11 else "other"
		"fil":
			return "other" if m10 in [4, 6, 9] else "one"
		"east_slavic", "balkan":
			if m10 == 1 and m100 != 11:
				return "one"
			if m10 >= 2 and m10 <= 4 and not (m100 >= 12 and m100 <= 14):
				return "few"
			return "many" if fam == "east_slavic" else "other"
		"pl":
			if n == 1:
				return "one"
			return "few" if m10 >= 2 and m10 <= 4 and not (m100 >= 12 and m100 <= 14) else "many"
		"cs":
			if n == 1:
				return "one"
			return "few" if n >= 2 and n <= 4 else "other"
		"lt":
			if m100 >= 11 and m100 <= 19:
				return "other"
			if m10 == 1:
				return "one"
			return "few" if m10 >= 2 else "other"
		"ro":
			if n == 1:
				return "one"
			return "few" if n == 0 or (m100 >= 1 and m100 <= 19) else "other"
		"lv":
			if m10 == 0 or (m100 >= 11 and m100 <= 19):
				return "zero"
			return "one" if m10 == 1 else "other"
		"he":
			return "one" if n == 1 else ("two" if n == 2 else "other")
		"sl":
			if m100 == 1:
				return "one"
			if m100 == 2:
				return "two"
			return "few" if m100 == 3 or m100 == 4 else "other"
		"ga":
			if n <= 2:
				return ["other", "one", "two"][n]
			if n <= 6:
				return "few"
			return "many" if n <= 10 else "other"
		"ar":
			if n <= 2:
				return ["zero", "one", "two"][n]
			if m100 >= 3 and m100 <= 10:
				return "few"
			return "many" if m100 >= 11 else "other"
		"cy":
			return str({0: "zero", 1: "one", 2: "two", 3: "few", 6: "many"}.get(n, "other"))
	push_error("unknown plural family " + fam)
	return "other"


static func lookup_plural(tables: Dictionary, locale: String, key: String, n: float,
		clean: bool = false) -> Variant:
	# key.<category> through the chain, each locale with its own category, then that locale's key.other
	for loc: String in locale_chain(locale):
		var table: Variant = tables.get(loc, {})
		var cat: String = plural(loc, n)
		for c: String in ([cat, "other"] if cat != "other" else ["other"]):
			var text: Variant = _pick(table, key + "." + c, clean)
			if typeof(text) != TYPE_NIL:
				return text
	return null


static func translate_plural(tables: Dictionary, locale: String, key: String, n: float,
		args: Dictionary = {}, clean: bool = false, words: PackedStringArray = PackedStringArray()) -> String:
	var a: Dictionary = args.duplicate()
	a["n"] = n
	var text: Variant = lookup_plural(tables, locale, key, n, clean)
	if typeof(text) == TYPE_NIL:
		return key + "." + plural(locale, n)
	return finish(str(text), a, clean, words)


# ---- the word mask (#207) -----------------------------------------------------------------------

static func is_word_char(cp: int) -> bool:
	if cp < 0x80:
		return (cp >= 0x30 and cp <= 0x39) or (cp >= 0x41 and cp <= 0x5A) or (cp >= 0x61 and cp <= 0x7A)
	for r: Array in MASK_BOUNDARY_RANGES:
		if cp >= int(r[0]) and cp <= int(r[1]):
			return false
	return true


static func fold_char(cp: int) -> int:
	# The pinned case fold (the reference's fold_char): one code point to one code point
	if (cp >= 0x41 and cp <= 0x5A) or (cp >= 0xC0 and cp <= 0xDE and cp != 0xD7):
		return cp + 0x20
	if cp == 0x130:
		return 0x69
	if cp == 0x178:
		return 0xFF
	if ((cp >= 0x100 and cp <= 0x12F) or (cp >= 0x132 and cp <= 0x137) or (cp >= 0x14A and cp <= 0x177)) \
			and cp % 2 == 0:
		return cp + 1
	if ((cp >= 0x139 and cp <= 0x148) or (cp >= 0x179 and cp <= 0x17E)) and cp % 2 == 1:
		return cp + 1
	if cp >= 0x391 and cp <= 0x3AB and cp != 0x3A2:
		return cp + 0x20
	if cp == 0x386:
		return 0x3AC
	if cp >= 0x388 and cp <= 0x38A:
		return cp + 0x25
	if cp == 0x38C:
		return 0x3CC
	if cp == 0x38E or cp == 0x38F:
		return cp + 0x3F
	if cp == 0x3C2:
		return 0x3C3
	if cp >= 0x400 and cp <= 0x40F:
		return cp + 0x50
	if cp >= 0x410 and cp <= 0x42F:
		return cp + 0x20
	return cp


static func _fold_key(text: String, from: int, to: int) -> String:
	var parts: PackedStringArray = []
	for i: int in range(from, to):
		parts.append(str(fold_char(text.unicode_at(i))))
	return ",".join(parts)


static func compile_words(words: PackedStringArray) -> Dictionary:
	# The folded set the mask matches against: build it once per word list (t() runs for every label every frame)
	var wanted: Dictionary = {}
	for w: String in words:
		var ok: bool = w.length() > 0
		for i: int in w.length():
			ok = ok and is_word_char(w.unicode_at(i))
		if ok:
			wanted[_fold_key(w, 0, w.length())] = true
	return wanted


static func mask_words(text: String, words: PackedStringArray) -> String:
	# text with every whole word that is in words (case folded) replaced by a same-length grawlix
	return mask_word_set(text, compile_words(words))


static func mask_word_set(text: String, wanted: Dictionary) -> String:
	# mask_words with the list compiled already (compile_words)
	if wanted.is_empty():
		return text
	var out: String = ""
	var i: int = 0
	while i < text.length():
		if not is_word_char(text.unicode_at(i)):
			out += text[i]
			i += 1
			continue
		var j: int = i
		while j < text.length() and is_word_char(text.unicode_at(j)):
			j += 1
		if wanted.has(_fold_key(text, i, j)):
			for k: int in j - i:
				out += GRAWLIX[k % GRAWLIX.length()]
		else:
			out += text.substr(i, j - i)
		i = j
	return out


static func mature_words(text: Variant) -> PackedStringArray:
	# A word list file's words ({"words": [...]}, strings only); anything else is no words
	var out: PackedStringArray = []
	if typeof(text) != TYPE_STRING:
		return out
	var json: JSON = JSON.new()
	if json.parse(str(text)) != OK or typeof(json.data) != TYPE_DICTIONARY:
		return out
	var words: Variant = (json.data as Dictionary).get("words")
	if typeof(words) != TYPE_ARRAY:
		return out
	for w: Variant in words:
		if typeof(w) == TYPE_STRING:
			out.append(w)
	return out


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
	# Every <locale>.json in dir (not its mature/ folder); a broken file is skipped (and reported by the caller
	# through the result)
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


static func load_mature(dir: String) -> Dictionary:
	# {locale: PackedStringArray} from dir/mature/<locale>.json, the game's word lists for clean language (#207)
	var lists: Dictionary = {}
	var folder: String = dir.path_join("mature")
	if not DirAccess.dir_exists_absolute(folder):
		return lists
	for file: String in DirAccess.get_files_at(folder):
		var name: String = file.trim_suffix(".remap")
		if name.ends_with(".json"):
			lists[name.get_basename()] = mature_words(AtomicFile.read_text(folder.path_join(name)))
	return lists

# {{FOOTER}}
