#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# l10n_exchange.py
# Purpose : The translator's file of the localization round trip (l10n.py): one file per language, XLIFF 1.2 (what
#           translation tools such as OmegaT, Poedit, Weblate and memoQ open) or CSV (a spreadsheet), holding every
#           English line with its key, its context note, its length budget, the translation and its review state.
# Usage   : import l10n_exchange as ex
#           ex.write(path, units, meta)       # .xlf / .xliff -> XLIFF 1.2, .csv -> CSV
#           units, meta = ex.read(path)       # ValueError on a broken or unsafe file
# Notes   : Review states are XLIFF 1.2's own: needs-translation (empty), needs-review-translation (a machine draft,
#           state-qualifier mt-suggestion), translated (a person wrote or accepted it), signed-off and final; an
#           approved="yes" unit counts as signed-off. Only translated, signed-off and final lines are imported.
#           The file header records the exported keys (count and sha256), so the import sees units a tool lost.
#           Notes from="l10n.py" are the tool's own (rewritten each time); other notes (a translator's) are kept.
#           A file with a DOCTYPE or an entity declaration is refused before parsing (a translator's file is
#           untrusted input). CSV is written UTF-8 with a byte order mark so Excel reads the accents; its second
#           row (key "@export") carries the record. In a CSV, a target typed into a row whose state is empty or
#           needs-translation counts as translated; an edited draft row stays a draft until its state is changed to
#           translated (or l10n.py review accepts it). Standard library only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   write: header (languages, export record) + one trans-unit (or CSV row) per unit, escaped
#   read : refuse DOCTYPE/ENTITY; parse; per unit: key, source, target, state (approved -> signed-off), notes, max
import csv
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

# ---- constants -------------------------------------------------------------------------------------------------
NS = "urn:oasis:names:tc:xliff:document:1.2"
TOOL = "l10n.py"
STATES_IMPORTED = ("translated", "signed-off", "final")
STATE_EMPTY = "needs-translation"
STATE_DRAFT = "needs-review-translation"
DRAFT_QUALIFIER = "mt-suggestion"
CSV_COLUMNS = ("key", "source", "target", "state", "max", "note", "tool_note")
CSV_RECORD_KEY = "@export"
UNSAFE_XML = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.I)


class Unit(object):
    """One line to translate. max: the visible-length budget in characters (None: the pseudo-locale's 40 %)."""

    def __init__(self, key, source, target="", state=STATE_EMPTY, note="", max_len=None, qualifier="",
                 tool_notes=None, other_notes=None):
        self.key, self.source, self.target, self.state = key, source, target, state
        self.note, self.max_len, self.qualifier = note, max_len, qualifier
        self.tool_notes = list(tool_notes or [])      # the tool's flags (a rejected draft, a back-translation score)
        self.other_notes = list(other_notes or [])    # [(from, text)] a translator's notes, kept as they are

    def is_draft(self):
        return self.state == STATE_DRAFT

    def imported(self):
        return self.state in STATES_IMPORTED and self.target != ""

    def __repr__(self):
        return f"Unit({self.key!r}, state={self.state!r})"


def key_record(keys):
    """'keys=N sha256=<16 hex>' for the exported key list (in order)."""
    digest = hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:16]
    return f"keys={len(keys)} sha256={digest}"


def parse_record(text):
    m = re.search(r"keys=(\d+) sha256=([0-9a-f]{16})", text or "")
    return (int(m.group(1)), m.group(2)) if m else None


def write(path, units, meta):
    """meta: {"source": "en", "target": "fr", "original": "data/i18n/en.json"}. Writes XLIFF or CSV by extension."""
    text = to_csv(units, meta) if str(path).lower().endswith(".csv") else to_xliff(units, meta)
    with open(path, "w", encoding="utf-8-sig" if str(path).lower().endswith(".csv") else "utf-8",
              newline="") as f:
        f.write(text)


def read(path):
    """(units, meta) from an XLIFF or CSV file. ValueError naming the file on anything broken or unsafe."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"{path}: not readable UTF-8 ({e})")
    try:
        if str(path).lower().endswith(".csv"):
            return from_csv(text)
        return from_xliff(text)
    except ValueError as e:
        raise ValueError(f"{path}: {e}")


# ---- XLIFF 1.2 -------------------------------------------------------------------------------------------------
def to_xliff(units, meta):
    record = key_record([u.key for u in units])
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<xliff version="1.2" xmlns="{NS}">',
           f' <file original={quoteattr(meta.get("original", "data/i18n/en.json"))} '
           f'source-language={quoteattr(meta["source"])} target-language={quoteattr(meta["target"])} '
           'datatype="plaintext">',
           "  <header>",
           f'   <tool tool-id="kit-l10n" tool-name="{TOOL}"/>',
           f'   <note from="{TOOL}">export {record}. maxwidth counts the characters a player sees, placeholders '
           'such as {name} and %d count 0. Keep every placeholder exactly as written.</note>',
           "  </header>",
           "  <body>"]
    for u in units:
        attrs = f'id={quoteattr(u.key)} resname={quoteattr(u.key)} xml:space="preserve"'
        if u.max_len:
            attrs += f' maxwidth="{int(u.max_len)}" size-unit="char"'
        out.append(f"   <trans-unit {attrs}>")
        out.append(f"    <source>{_esc(u.source)}</source>")
        if u.target or u.state != STATE_EMPTY:
            q = f" state-qualifier={quoteattr(u.qualifier)}" if u.qualifier else ""
            out.append(f"    <target state={quoteattr(u.state)}{q}>{_esc(u.target)}</target>")
        if u.note:
            out.append(f'    <note from="developer">{_esc(u.note)}</note>')
        for n in u.tool_notes:
            out.append(f'    <note from="{TOOL}">{_esc(n)}</note>')
        for who, n in u.other_notes:
            who_attr = f" from={quoteattr(who)}" if who else ""
            out.append(f"    <note{who_attr}>{_esc(n)}</note>")
        out.append("   </trans-unit>")
    out += ["  </body>", " </file>", "</xliff>", ""]
    return "\n".join(out)


def _esc(text):
    # escape() covers & < >; a lone ']]>' is harmless in text content once '>' is escaped
    return escape(text)


def from_xliff(text):
    if UNSAFE_XML.search(text):
        raise ValueError("has a DOCTYPE or ENTITY declaration: refused (an XLIFF file needs neither)")
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as e:
        raise ValueError(f"not well-formed XML ({e})")
    q = lambda tag: "{" + NS + "}" + tag   # noqa: E731  (an f-string here reads as a scaffold placeholder)
    if root.tag != q("xliff"):
        raise ValueError("not an XLIFF 1.2 file (root element is not xliff in the 1.2 namespace)")
    files = root.findall(q("file"))
    if len(files) != 1:
        raise ValueError(f"has {len(files)} <file> elements, l10n.py writes and reads exactly one")
    f = files[0]
    meta = {"source": f.get("source-language", ""), "target": f.get("target-language", ""),
            "original": f.get("original", ""), "record": None}
    header = f.find(q("header"))
    if header is not None:
        for n in header.findall(q("note")):
            if n.get("from") == TOOL:
                meta["record"] = parse_record(n.text)
    units, seen = [], set()
    body = f.find(q("body"))
    for tu in (body.iter(q("trans-unit")) if body is not None else []):
        key = tu.get("resname") or tu.get("id")
        if not key:
            raise ValueError("a trans-unit has no id")
        if key in seen:
            raise ValueError(f"trans-unit {key!r} appears twice")
        seen.add(key)
        src = tu.find(q("source"))
        tgt = tu.find(q("target"))
        u = Unit(key, _text(src))
        if tgt is not None:
            u.target = _text(tgt)
            u.state = tgt.get("state") or ("translated" if u.target else STATE_EMPTY)
            u.qualifier = tgt.get("state-qualifier", "")
        if tu.get("approved") == "yes" and u.target:
            u.state = "signed-off"
        mw = tu.get("maxwidth")
        u.max_len = int(mw) if mw and mw.isdigit() else None
        for n in tu.findall(q("note")):
            who = n.get("from", "")
            if who == "developer":
                u.note = n.text or ""
            elif who == TOOL:
                u.tool_notes.append(n.text or "")
            else:
                u.other_notes.append((who, n.text or ""))
        units.append(u)
    return units, meta


def _text(el):
    """All the text of an element, inline markup (<g>, <x/>, <mrk>) flattened to its text."""
    return "".join(el.itertext()) if el is not None else ""


# ---- CSV -------------------------------------------------------------------------------------------------------
def to_csv(units, meta):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    w.writerow([CSV_RECORD_KEY, f"{meta['source']} -> {meta['target']}", "", "", "",
                f"export {key_record([u.key for u in units])}", "do not edit this row"])
    for u in units:
        w.writerow([u.key, u.source, u.target, u.state, u.max_len or "", u.note, " | ".join(u.tool_notes)])
    return buf.getvalue()


def from_csv(text):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or [c.strip() for c in rows[0][:len(CSV_COLUMNS)]] != list(CSV_COLUMNS):
        raise ValueError(f"first row must be the columns {', '.join(CSV_COLUMNS)}")
    meta = {"source": "", "target": "", "original": "", "record": None}
    units, seen = [], set()
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        row = (row + [""] * len(CSV_COLUMNS))[:len(CSV_COLUMNS)]
        key, source, target, state, max_len, note, tool_note = row
        if key == CSV_RECORD_KEY:
            langs = [s.strip() for s in source.split("->")]
            if len(langs) == 2:
                meta["source"], meta["target"] = langs
            meta["record"] = parse_record(note)
            continue
        if key in seen:
            raise ValueError(f"key {key!r} appears twice")
        seen.add(key)
        state = state.strip()
        if target and state in ("", STATE_EMPTY):
            state = "translated"     # a person typed it into the sheet; machine drafts say needs-review-translation
        u = Unit(key, source, target, state or STATE_EMPTY, note,
                 int(max_len) if max_len.strip().isdigit() else None,
                 tool_notes=[t for t in tool_note.split(" | ") if t])
        units.append(u)
    return units, meta
