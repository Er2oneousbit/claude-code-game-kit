#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# check_i18n.py
# Purpose : Check the game's translations (data/i18n/<locale>.json) against the English table (en.json): every
#           English key has a value in each other language, that value is not the English text left in place, and
#           its {placeholders} are the same. A table that is still partial (missing keys fall back to English at
#           runtime) is fine while you work, this is the check before you call a language done (SOP-19).
# Usage   : python tools/check_i18n.py                    # every table next to en.json (pseudo is generated, skipped)
#           python tools/check_i18n.py --locale fr        # just French
#           python tools/check_i18n.py --same "Okay"      # an English text that is also right in the other language
#           python tools/check_i18n.py --dir path/to/i18n --debug
# Exit    : 0 every table complete (or the project has no data/i18n/ at all), 1 a key missing, untranslated or with
#           other placeholders, 2 usage problem (a --dir or data/i18n/ without en.json, a table that is not a JSON
#           object of strings)
# Notes   : Plural forms are plain keys (apples.one, apples.other), so they are checked like any other key. A value
#           made only of placeholders and punctuation ("{name}", "{v}") has nothing to translate. SAME_IN_EVERY_
#           LANGUAGE lists the English texts the kit's own tables keep as they are: proper names and units; add a
#           game's own with --same. Keys only the other table has (a name the code looks up with a fallback, like
#           Unity's binding.key.*) are listed with --debug, never an error. Standard library only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   en = <dir>/en.json; tables = the other <locale>.json files (or --locale)
#   for each table, for each English key:
#     missing -> problem; placeholders differ -> problem
#     same text as English, not placeholders-only, not in SAME_IN_EVERY_LANGUAGE or --same -> problem
#   print the problems per table; exit 1 if any
import argparse
import json
import re
import sys
import traceback
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# ---- constants -------------------------------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = "data/i18n"
BASE = "en"
SKIP_LOCALES = {"pseudo"}                     # generated from English at runtime, never a file to translate
PLACEHOLDER = re.compile(r"\{\{?[A-Za-z0-9_]+\}?\}")   # {n}, {name}; Lockpick MZ before scaffolding
NOTHING_TO_TRANSLATE = re.compile(r"^[\W_]*$")         # what is left of a value once its placeholders are gone
# English texts that are right as they are in the other languages the kit ships (French): proper names (brands,
# languages written in their own language), words French spells the same, and units. Kept short on purpose.
SAME_IN_EVERY_LANGUAGE = {
    "Xbox": "a brand", "PlayStation": "a brand",
    "English": "a language name in its own language", "Français": "a language name in its own language",
    "Audio": "the same word in French", "Pause": "the same word in French", "Normal": "the same word in French",
    "Guide": "a speaker's name (Bevy's sample line)",
    "Version {version}": "the same word in French", "v{version}": "the version abbreviation",
    "{n}x": "a unit (times)", "{w} x {h}": "a unit (width by height)",
}
DEBUG = False


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def load_table(path):
    """A string table: a JSON object of strings. Raises ValueError naming the file when it is not one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"{path}: not readable JSON ({e})")
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ValueError(f"{path}: not a JSON object of strings")
    return data


def placeholders(text):
    return sorted(PLACEHOLDER.findall(text))


def needs_translation(text, same=()):
    """False for a text that stays as it is: only placeholders and punctuation, or a listed proper name or unit."""
    if text in SAME_IN_EVERY_LANGUAGE or text in same:
        return False
    return not NOTHING_TO_TRANSLATE.match(PLACEHOLDER.sub("", text))


def table_problems(en, other, same=()):
    """The problems of one table against English, as 'key: reason' lines (sorted by English key order)."""
    problems = []
    for key, text in en.items():
        if key not in other:
            problems.append(f"{key}: missing (English: {text!r})")
        elif placeholders(other[key]) != placeholders(text):
            problems.append(f"{key}: placeholders {placeholders(other[key])} instead of {placeholders(text)}")
        elif other[key] == text and needs_translation(text, same):
            problems.append(f"{key}: still English ({text!r})")
    return problems


def check_dir(folder, locales=None, same=()):
    """{locale: [problems]} for the tables in folder. Raises ValueError for a missing or broken table."""
    folder = Path(folder)
    en_file = folder / f"{BASE}.json"
    if not en_file.is_file():
        raise ValueError(f"no {en_file}")
    en = load_table(en_file)
    if locales:
        files = [folder / f"{loc}.json" for loc in locales]
        for f in files:
            if not f.is_file():
                raise ValueError(f"no {f}")
    else:
        files = sorted(f for f in folder.glob("*.json") if f.stem != BASE and f.stem not in SKIP_LOCALES)
    result = {}
    for f in files:
        table = load_table(f)
        extra = [k for k in table if k not in en]
        if extra:
            dbg(f"{f.name}: keys English does not have (looked up with a fallback?): {', '.join(extra)}")
        result[f.stem] = table_problems(en, table, same)
    return result


def main(argv=None):
    global DEBUG
    ap = argparse.ArgumentParser(
        description="Check data/i18n/<locale>.json against en.json: every key there, translated, same placeholders.",
        epilog="Exit 0 complete, 1 problems found, 2 usage problem. The pseudo locale is generated and skipped.")
    ap.add_argument("--dir", default=None, help=f"the string tables' folder (default: {I18N_DIR} in the project)")
    ap.add_argument("--locale", action="append", default=[], metavar="LANG",
                    help="check only this table (repeatable; default: every <locale>.json but en and pseudo)")
    ap.add_argument("--same", action="append", default=[], metavar="TEXT",
                    help="an English text that is right untranslated too (a name, a unit; repeatable)")
    ap.add_argument("--debug", action="store_true", help="tracebacks, and keys only the other tables have")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    folder = Path(args.dir) if args.dir else ROOT / I18N_DIR
    if not args.dir and not folder.is_dir():
        # A project with no string tables at all (RPG Maker MZ): the tool ships into every game, so the plain
        # run passes there. A --dir that is wrong or holds no en.json is still a usage problem (exit 2).
        print(f"[ OK ] no string tables ({I18N_DIR}/ does not exist), nothing to check")
        return 0
    try:
        result = check_dir(folder, args.locale, set(args.same))
    except ValueError as e:
        print(f"[error] {e}")
        return 2
    except Exception as e:                    # a bug here, not in the tables
        print(f"[error] {e}")
        if DEBUG:
            traceback.print_exc()
        return 2
    if not result:
        print(f"[ OK ] {folder}: English only, nothing to check")
        return 0
    bad = 0
    for loc, problems in result.items():
        if problems:
            bad += 1
            print(f"[FAIL] {loc}.json: {len(problems)} problem(s)")
            for p in problems:
                print(f"  {p}")
        else:
            print(f"[ OK ] {loc}.json: every English key translated")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
