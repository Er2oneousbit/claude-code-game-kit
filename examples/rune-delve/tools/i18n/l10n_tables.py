#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# l10n_tables.py
# Purpose : Read and write the game's string tables (data/i18n/<locale>.json, the same flat JSON in every engine)
#           without wrecking their layout: a written table follows en.json line for line (its blank lines and
#           grouping), with the translated value on each key's line.
# Usage   : import l10n_tables as tables
#           en = tables.load(path_to_en)                         # {key: text}, ValueError on a broken table
#           text = tables.render(en_text, table, old_text=None)   # the new file's text
# Notes   : Layout rule: when en.json has one "key": "value" pair per line, the output is en.json's lines with each
#           key's value swapped for the translation; keys the translation lacks are left out (they fall back to
#           English at runtime); keys only the translation has (looked up with a fallback) stay after the key
#           they followed in the old file. Otherwise (a hand-made en.json with pairs spread over lines) the table is
#           written with json.dumps in en.json's key order and indent. The result is parsed back and compared with
#           the table before it is returned, so a layout bug can never write wrong strings. Standard library only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   if every key of en.json sits on its own line: walk en.json's lines, keep the non-key lines, swap each key line's
#     value (or drop the line when the table lacks the key), insert the table's extra keys after their old neighbour,
#     fix the trailing commas
#   else: json.dumps(ordered table, indent = en.json's indent)
#   parse the result; it must equal the table, or raise
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # tools/: check_i18n's table reader
import check_i18n  # noqa: E402

KEY_LINE = re.compile(r'^(\s*)("(?:[^"\\]|\\.)*")\s*:\s*("(?:[^"\\]|\\.)*")\s*(,?)\s*$')


def load(path):
    """{key: text} from a table file; ValueError (naming the file) when it is not a JSON object of strings."""
    return check_i18n.load_table(Path(path))


def _ascii_only(text):
    """True when an existing table writes non-ASCII as \\u escapes (keep doing so)."""
    return "\\u" in text and all(ord(c) < 128 for c in text)


def _dump(value, ascii_only):
    return json.dumps(value, ensure_ascii=ascii_only)


def _indent_of(text):
    m = re.search(r'^([ \t]+)"', text, re.M)
    return m.group(1) if m else " "


def render(en_text, table, old_text=None):
    """The text of a table file holding `table`, laid out like en.json (see Notes). Raises ValueError if the result
    would not read back as exactly `table`."""
    en = json.loads(en_text)
    old_order = list(json.loads(old_text)) if old_text else []
    ascii_only = _ascii_only(old_text) if old_text else False
    nl = "\r\n" if "\r\n" in (old_text or en_text) else "\n"
    lines = en_text.replace("\r\n", "\n").split("\n")
    key_lines = [ln for ln in lines if KEY_LINE.match(ln)]
    if len(key_lines) == len(en) and len(en) > 0:
        out = _render_lines(lines, table, old_order, ascii_only)
    else:
        ordered = {k: table[k] for k in en if k in table}
        ordered.update((k, v) for k, v in table.items() if k not in ordered)
        indent = _indent_of(en_text)
        out = json.dumps(ordered, ensure_ascii=ascii_only, indent=indent)
        out += "\n" if en_text.endswith("\n") else ""
    out = out.replace("\n", nl) if nl != "\n" else out
    back = json.loads(out)
    if back != table:
        raise ValueError("the rewritten table would not read back as the translation (a layout bug): not written")
    return out


def _render_lines(lines, table, old_order, ascii_only):
    """en.json's lines with the table's values; extra keys after their old neighbour; trailing commas fixed."""
    out, seen, indent = [], set(), None
    for ln in lines:
        m = KEY_LINE.match(ln)
        if not m:
            out.append(ln)
            continue
        indent = m.group(1) if indent is None else indent
        key = json.loads(m.group(2))
        if key in table:
            out.append((m.group(1), key))
            seen.add(key)
    extras = [k for k in table if k not in seen]
    for key in extras:
        # after the key that came before it in the old file (when that key is still written), else after the last
        pos = None
        if key in old_order:
            i = old_order.index(key)
            for prev in reversed(old_order[:i]):
                hit = [j for j, x in enumerate(out) if isinstance(x, tuple) and x[1] == prev]
                if hit:
                    pos = hit[0] + 1
                    break
        if pos is None:
            idx = [j for j, x in enumerate(out) if isinstance(x, tuple)]
            pos = idx[-1] + 1 if idx else _first_brace(out) + 1
        out.insert(pos, (indent or " ", key))
    last = max((j for j, x in enumerate(out) if isinstance(x, tuple)), default=-1)
    text = []
    for j, x in enumerate(out):
        if isinstance(x, tuple):
            ind, key = x
            text.append(f"{ind}{_dump(key, ascii_only)}: {_dump(table[key], ascii_only)}{',' if j != last else ''}")
        else:
            text.append(x)
    return "\n".join(text)


def _first_brace(out):
    for j, x in enumerate(out):
        if isinstance(x, str) and x.strip().startswith("{"):
            return j
    return 0
