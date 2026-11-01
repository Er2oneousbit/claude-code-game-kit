#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# fontcheck.py
# Purpose : font coverage check: every character a game's strings use must be in the font that draws them. Reads
#           strings files (JSON string values at any depth, CSV / Godot translation CSV, gettext PO / POT, plain text)
#           and lists each missing character with the languages and string ids where it appears.
# Usage   : python tools/art/dotwork/dotwork.py fonts-check --font glyphs/dialogue_latin.txt --strings i18n/fr.json
#           pack spec: "fonts": [{"name": "dialogue", "glyphs": "glyphs/dialogue_latin.txt",
#                                 "check": ["assets/i18n/strings.csv"]}]
# Notes   : --font takes a glyph file (as typed, Dotwork's folder, then the game) or a built .fnt. Exit 1
#           when a needed glyph is missing. Languages come from the nearest language key in a JSON path ("fr",
#           "pt_BR"), a CSV header ("keys,en,fr"), a PO "Language:" header, or the file name (fr.json, menu_de.po).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import csv
import io
import json
import os
import re
import unicodedata

# language codes recognised on their own (ISO 639-1, plus fil). Codes that are also everyday JSON keys or English
# words ("id", "no", "is", "to" ...) count only with a region ("id_ID", "no_NO"), so {"id": 3} is not Indonesian.
LANGS = set("af ar az bg bn bs ca cs cy da de el en eo es et eu fa fi fil fr ga gd gl gu ha he hi hr hu hy it ja ka "
            "kk km kn ko ku ky la lb lo lt lv mk ml mn mr ms mt nb ne nl nn pa pl ps pt ro ru si sk sl sq sr sv sw ta "
            "te tg th tk tl tr uk ur uz vi xh yi yo zh zu".split())
REGION_ONLY = set("am as be id is my no or so to".split())
LANG_RE = re.compile(r"^([A-Za-z]{2,3})(?:[-_]([A-Za-z]{2}|[A-Za-z]{4}|[0-9]{3}))?$")
# drawn as nothing by Godot's text server: line breaks, tabs and other controls, format characters (zero-width
# joiners, bidi marks, the byte order mark). The soft hyphen is a format character too, but it is drawn as a hyphen
# when a line breaks there, so it stays checked.
SKIP_CATEGORIES = ("Cc", "Zl", "Zp", "Cf")
CHECKED_FORMAT = "\u00ad"   # soft hyphen
SHOW_IDS = 4   # string ids listed per language before "(+N more)"
ID_KEYS = ("id", "key")   # a JSON record's own name: used as its string id, not checked as text


def lang_code(token):
    """'fr' -> 'fr', 'pt-BR' / 'pt_br' -> 'pt_BR', 'zh_Hans' -> 'zh_Hans'; anything else -> None."""
    m = LANG_RE.match(str(token))
    if not m:
        return None
    base, region = m.group(1).lower(), m.group(2)
    if base not in LANGS and not (region and base in REGION_ONLY):
        return None
    if region:
        region = region.upper() if len(region) == 2 else region.title()
        return f"{base}_{region}"
    return base


def lang_of_path(path):
    """A language named by the file or its folder: fr.json, strings_fr.po, menu.pt-BR.csv, de/dialogue.json."""
    parts = os.path.normpath(path).split(os.sep)
    stem = os.path.splitext(parts[-1])[0]
    for piece in [stem] + ([parts[-2]] if len(parts) > 1 else []):
        toks = [t for t in re.split(r"[._\s-]+", piece) if t]
        for i in range(len(toks) - 1, -1, -1):   # the last code wins ("ui_en_fr" -> fr)
            if i + 1 < len(toks) and lang_code(f"{toks[i]}_{toks[i + 1]}"):
                return lang_code(f"{toks[i]}_{toks[i + 1]}")
            if lang_code(toks[i]):
                return lang_code(toks[i])
    return ""


# ---- readers: each returns [(language, string id, text)] ----------------------------------------------------------
def _read_text(path):
    with open(path, encoding="utf-8-sig") as f:   # -sig: a BOM from a spreadsheet export is not a character
        return f.read()


def read_json(path, text):
    """Every string value at any depth; the id is its key path (menu.start, intro.2), the language the nearest key
    on the path that is a language code. Keys starting with "_" are notes ("_comment") and are skipped; a record in a
    list with an "id" or "key" string is named by it ([{"id": "start", "fr": "..."}] -> start)."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{path}: not valid JSON ({exc})")
    fallback, out = lang_of_path(path), []

    def walk(node, keys, lang):
        if isinstance(node, dict):
            ident = next((node[k] for k in ID_KEYS if isinstance(node.get(k), str)), None)
            if ident is not None and keys and keys[-1].isdigit():
                keys = keys[:-1] + [ident]
            for k, v in node.items():
                if not (str(k).startswith("_") or (k in ID_KEYS and isinstance(v, str))):
                    walk(v, keys + [str(k)], lang_code(k) or lang)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, keys + [str(i)], lang)
        elif isinstance(node, str):   # the id leaves out language keys: fr.menu.start -> menu.start
            sid = ".".join(k for k in keys if not lang_code(k)) or ".".join(keys) or "(root)"
            out.append((lang or fallback, sid, node))

    walk(data, [], "")
    return out


def read_csv(path, text):
    """First column = string id. With a header that names languages (Godot: keys,en,fr,?context) only those columns
    are read; columns starting with "?" or "_" are notes. Without one, every other column, language from the file
    name."""
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        return []
    head = [None if c.startswith(("?", "_")) else lang_code(c.strip()) for c in rows[0]]
    fallback = lang_of_path(path)
    if any(head[1:]):   # a header row: only the language columns are text the game shows
        return [(head[c], r[0] or f"row {n}", r[c]) for n, r in enumerate(rows[1:], 2)
                for c in range(1, min(len(r), len(head))) if head[c]]
    if max(len(r) for r in rows) == 1:   # one column: a list of strings
        return [(fallback, f"row {n}", r[0]) for n, r in enumerate(rows, 1)]
    return [(fallback, r[0] or f"row {n}", r[c]) for n, r in enumerate(rows, 1) for c in range(1, len(r))]


_PO_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def _po_str(s):
    s = s.strip()
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        raise ValueError(f"not a quoted PO string: {s[:40]!r}")
    return re.sub(r'\\(.)', lambda m: _PO_ESC.get(m.group(1), m.group(1)), s[1:-1])


def read_po(path, text):
    """gettext PO / POT: msgstr (and msgstr[n]) per entry, or msgid when nothing is translated yet (a template, or a
    fallback the game shows untranslated). The id is msgctxt|msgid, the language the header's "Language:" or the
    file name."""
    entries, cur, key, line_no = [], {}, None, 0
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            if cur and not line:
                entries.append(cur)
                cur, key = {}, None
            continue
        try:
            if line.startswith('"'):
                if key is None:
                    raise ValueError("a string with no keyword before it")
                cur[key] += _po_str(line)
                continue
            kw, _, rest = line.partition(" ")
            if kw in ("msgid", "msgctxt") and "msgid" in cur:   # the next entry without a blank line between
                entries.append(cur)
                cur = {}
            key = kw
            cur[key] = _po_str(rest)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_no}: {exc}")
    if cur:
        entries.append(cur)
    lang = ""
    for e in entries:
        if e.get("msgid") == "" and "msgstr" in e:
            m = re.search(r"^Language:\s*([^\s\\]+)", e["msgstr"], re.M)
            lang = lang_code(m.group(1)) if m else ""
    lang = lang or lang_of_path(path)
    out = []
    for e in entries:
        if e.get("msgid", "") == "":
            continue   # the header
        sid = (e["msgctxt"] + "|" if "msgctxt" in e else "") + e["msgid"]
        sid = sid if len(sid) <= 40 else sid[:37] + "..."
        tr = [v for k, v in sorted(e.items()) if k.startswith("msgstr") and v]
        for t in tr or [e["msgid"]] + ([e["msgid_plural"]] if e.get("msgid_plural") else []):
            out.append((lang, sid, t))
    return out


def read_plain(path, text):
    lang = lang_of_path(path)
    return [(lang, f"line {n}", t) for n, t in enumerate(text.splitlines(), 1) if t.strip()]


READERS = {".json": read_json, ".csv": read_csv, ".po": read_po, ".pot": read_po}


def read_strings(path):
    """[(language, string id, text)] from one strings file, by extension (anything else is plain text, one string
    per line)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return READERS.get(os.path.splitext(path)[1].lower(), read_plain)(path, _read_text(path))


# ---- fonts ----------------------------------------------------------------------------------------------------------
def font_chars(path, caps_only=False):
    """The characters a font draws: a built AngelCode .fnt (its char ids) or a glyph file (with the space every built
    font has, and the caps_only mapping when asked)."""
    if path.lower().endswith(".fnt"):
        have = set()
        for line in _read_text(path).splitlines():
            m = re.match(r"char\s+id=(\d+)\b", line)
            if m:
                have.add(chr(int(m.group(1))))
        return have
    import lane_fonts
    _, glyphs = lane_fonts.parse(path)
    if caps_only:
        lane_fonts.caps_map(glyphs)
    return set(glyphs) | {" "}


def needed(ch):
    return ch == CHECKED_FORMAT or unicodedata.category(ch) not in SKIP_CATEGORIES


def check(have, paths):
    """-> {"missing": {char: {language: [ids]}} (first-seen order), "strings": n, "languages": [...], "files": n}"""
    missing, langs, n = {}, [], 0
    for p in paths:
        try:
            items = read_strings(p)
        except FileNotFoundError:
            raise _tool_error(f"strings file {p} not found")
        except (ValueError, UnicodeDecodeError) as exc:
            raise _tool_error(f"strings file {p}: {exc} (strings files are UTF-8)")
        for lang, sid, text in items:
            n += 1
            lang = lang or "?"
            if lang not in langs:
                langs.append(lang)
            # composed form first: "e" + combining acute is drawn with the font's "\u00e9" (Godot's shaper composes it)
            for ch in unicodedata.normalize("NFC", text):
                if ch not in have and needed(ch):
                    ids = missing.setdefault(ch, {}).setdefault(lang, [])
                    if sid not in ids:
                        ids.append(sid)
    return {"missing": missing, "strings": n, "languages": langs, "files": len(paths)}


def _tool_error(msg):
    try:
        import fcore
        return fcore.ToolError(msg)
    except ImportError:   # used on its own
        return ValueError(msg)


def describe(ch):
    name = unicodedata.name(ch, "")
    shown = ch if unicodedata.category(ch)[0] not in "CZ" else " "
    return f"U+{ord(ch):04X} {shown!r} {name}".rstrip()


def report(res, font_label, files):
    """Log lines: a header, then one line per missing character (languages and the first string ids that use it)."""
    lines = [f"{font_label}: checked {res['strings']} strings ({', '.join(res['languages']) or 'no strings'}) in "
             f"{', '.join(files)}"]
    for ch, by_lang in res["missing"].items():
        where = []
        for lang, ids in by_lang.items():
            more = f" (+{len(ids) - SHOW_IDS} more)" if len(ids) > SHOW_IDS else ""
            where.append(f"{lang}: {', '.join(ids[:SHOW_IDS])}{more}")
        lines.append(f"  missing {describe(ch)} - {'; '.join(where)}")
    if res["missing"]:
        lines.append(f"{font_label}: {len(res['missing'])} characters missing: {''.join(res['missing'])}")
    else:
        lines.append(f"{font_label}: every character is in the font")
    return lines


# ---- command line (dotwork.py fonts-check) ----------------------------------------------------------------------
def find_font(spec, project, here):
    """--font as typed, then Dotwork's own folder (glyphs/dialogue_latin.txt), then the game (--project), the order
    the fonts lane looks in."""
    for p in (spec, os.path.join(here, spec), os.path.join(project, spec)):
        if os.path.isfile(p):
            return p
    return None


def cmd(a, project, here):
    """dotwork.py fonts-check: 0 when every character is in the font, 1 when one is missing (JobError), 2 usage."""
    import fcore
    font = find_font(a.font, project, here)
    if not font:
        raise fcore.ToolError(f"font {a.font!r} not found (a glyph file such as glyphs/dialogue_latin.txt, or a built "
                              ".fnt; looked as typed, in the game and in Dotwork's folder)")
    paths = []
    for s in a.strings:
        p = s if os.path.isfile(s) else os.path.join(project, s)
        if not os.path.isfile(p):
            raise fcore.ToolError(f"strings file {s!r} not found (as typed or in the game)")
        paths.append(p)
    try:
        have = font_chars(font, a.caps_only)
    except ValueError as exc:   # a broken glyph file
        raise fcore.ToolError(str(exc))
    res = check(have, paths)
    for line in report(res, f"font {os.path.basename(font)} ({len(have)} glyphs)", a.strings):
        print(line)
    if res["missing"]:
        raise fcore.JobError(f"{len(res['missing'])} characters the strings use are not in {os.path.basename(font)}")
    print(f"[ OK ] {os.path.basename(font)} has every character of {res['strings']} strings")
    return 0
