#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# l10n_fonts.py
# Purpose : Which characters a font can draw, for the localization check (l10n.py check): TrueType / OpenType
#           fonts (.ttf, .otf, the first font of a .ttc) through their cmap table, built AngelCode fonts (.fnt), and
#           Dotwork glyph files (glyphs/*.txt). Also finds the fonts a game ships.
# Usage   : import l10n_fonts as fonts
#           have = fonts.font_chars("src/shell/fonts/AtkinsonHyperlegible-Regular.ttf")   # set of characters
#           fonts.missing(have, "Привет")                                                 # ['П', 'р', ...]
#           fonts.discover(project_root)                                                  # [Path, ...]
# Notes   : cmap subtables read: format 4 (the Basic Multilingual Plane), 12 (every plane), 0 and 6 (small
#           fonts), from the Unicode (platform 0) and Windows Unicode (3,1 / 3,10) encodings; a code point mapped
#           to glyph 0 (.notdef, the empty box) does not count. Characters no font draws are not checked: line
#           breaks, tabs and other controls, and format characters such as zero-width joiners, except the soft
#           hyphen (drawn when a line breaks there): the same rule as Dotwork's fonts-check. The text is checked in
#           its composed form (NFC). WOFF and WOFF2 are not read (they are web wrappers of these fonts).
#           discover() skips build, cache and dependency folders by their path relative to the project.
#           Standard library only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   sfnt: table directory -> cmap -> each Unicode subtable -> code points whose glyph id is not 0
#   .fnt: every "char id=N" line; glyph file: every "char X" / "char U+XXXX" line, plus the space
#   missing(have, text) = characters of NFC(text) a font draws that `have` lacks, first-seen order
import os
import re
import struct
import unicodedata
from pathlib import Path

# ---- constants -------------------------------------------------------------------------------------------------
FONT_EXTS = (".ttf", ".otf", ".ttc", ".fnt")
SKIP_CATEGORIES = ("Cc", "Zl", "Zp", "Cf")
CHECKED_FORMAT = "­"   # soft hyphen
# folders a game never ships fonts from (dependencies, engine caches, build output), relative to the project root
SKIP_DIRS = {".git", ".godot", ".import", "node_modules", "Library", "Temp", "Logs", "obj", "Obj", "Intermediate",
             "Binaries", "Saved", "DerivedDataCache", "build", "builds", "dist", "target", "export", ".vs",
             ".vscode", "captures", "__pycache__", "addons", "tools", "examples", "golden"}


class FontError(ValueError):
    pass


def font_chars(path):
    """The set of characters the font at path draws. FontError when the file cannot be read as a font."""
    path = str(path)
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".ttf", ".otf", ".ttc"):
            with open(path, "rb") as f:
                return sfnt_chars(f.read())
        if ext == ".fnt":
            with open(path, encoding="utf-8", errors="replace") as f:
                return {chr(int(m)) for m in re.findall(r"^char\s+id=(\d+)\b", f.read(), re.M)}
        with open(path, encoding="utf-8") as f:
            return glyph_file_chars(f.read())
    except OSError as e:
        raise FontError(f"{path}: not readable ({e})")
    except (struct.error, IndexError, UnicodeDecodeError) as e:
        raise FontError(f"{path}: not a font this check reads ({e})")


def glyph_file_chars(text):
    """A Dotwork glyph file: 'char X' or 'char U+00A0' lines, plus the space every built font has."""
    have = {" "}
    for line in text.splitlines():
        if line.startswith("char "):
            c = line[5:]
            if len(c) > 2 and c.startswith("U+"):
                c = chr(int(c[2:], 16))
            if len(c) == 1:
                have.add(c)
    return have


def sfnt_chars(data):
    """Characters of a TrueType / OpenType font (or the first font of a collection), from its cmap table."""
    offset = 0
    if data[:4] == b"ttcf":
        offset = struct.unpack(">I", data[12:16])[0]
    tag = data[offset:offset + 4]
    if tag not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise FontError(f"not a TrueType or OpenType font (starts with {tag!r})")
    num_tables = struct.unpack(">H", data[offset + 4:offset + 6])[0]
    cmap = None
    for i in range(num_tables):
        rec = offset + 12 + 16 * i
        if data[rec:rec + 4] == b"cmap":
            cmap = struct.unpack(">I", data[rec + 8:rec + 12])[0]
    if cmap is None:
        raise FontError("has no cmap table")
    have = set()
    n_sub = struct.unpack(">H", data[cmap + 2:cmap + 4])[0]
    for i in range(n_sub):
        plat, enc, sub = struct.unpack(">HHI", data[cmap + 4 + 8 * i:cmap + 12 + 8 * i])
        if plat == 0 or (plat == 3 and enc in (1, 10)):
            have |= _cmap_subtable(data, cmap + sub)
    return {chr(c) for c in have if c < 0x110000 and not 0xD800 <= c <= 0xDFFF}


def _cmap_subtable(data, at):
    fmt = struct.unpack(">H", data[at:at + 2])[0]
    out = set()
    if fmt == 4:
        seg2 = struct.unpack(">H", data[at + 6:at + 8])[0]
        n = seg2 // 2
        ends = struct.unpack(f">{n}H", data[at + 14:at + 14 + seg2])
        starts_at = at + 16 + seg2
        starts = struct.unpack(f">{n}H", data[starts_at:starts_at + seg2])
        deltas = struct.unpack(f">{n}h", data[starts_at + seg2:starts_at + 2 * seg2])
        ro_at = starts_at + 2 * seg2
        offsets = struct.unpack(f">{n}H", data[ro_at:ro_at + seg2])
        for s in range(n):
            if starts[s] == 0xFFFF:
                continue
            for c in range(starts[s], ends[s] + 1):
                if offsets[s] == 0:
                    gid = (c + deltas[s]) & 0xFFFF
                else:
                    p = ro_at + 2 * s + offsets[s] + 2 * (c - starts[s])
                    gid = struct.unpack(">H", data[p:p + 2])[0]
                    gid = (gid + deltas[s]) & 0xFFFF if gid else 0
                if gid:
                    out.add(c)
    elif fmt == 12:
        n = struct.unpack(">I", data[at + 12:at + 16])[0]
        for g in range(n):
            start, end, gid = struct.unpack(">III", data[at + 16 + 12 * g:at + 28 + 12 * g])
            first = start if gid else start + 1          # a group starting at glyph 0 maps its first code to .notdef
            out.update(range(first, end + 1))
    elif fmt == 0:
        gids = data[at + 6:at + 6 + 256]
        out.update(c for c in range(256) if gids[c])
    elif fmt == 6:
        first, count = struct.unpack(">HH", data[at + 6:at + 10])
        gids = struct.unpack(f">{count}H", data[at + 10:at + 10 + 2 * count])
        out.update(first + i for i, g in enumerate(gids) if g)
    return out


def needed(ch):
    """True for a character a font must draw (not a control or an invisible format character)."""
    return ch == CHECKED_FORMAT or unicodedata.category(ch) not in SKIP_CATEGORIES


def missing(have, text):
    """Characters of text (composed, NFC) that a font draws but `have` lacks, in first-seen order."""
    out = []
    for ch in unicodedata.normalize("NFC", text):
        if ch not in have and needed(ch) and ch not in out:
            out.append(ch)
    return out


def describe(ch):
    return f"U+{ord(ch):04X} {ch!r} {unicodedata.name(ch, '')}".rstrip()


def discover(project):
    """Font files under the project (sorted), skipping SKIP_DIRS by their path relative to the project root."""
    project = Path(project)
    found = []
    for dirpath, dirnames, filenames in os.walk(project):
        rel = Path(dirpath).relative_to(project)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not (rel == Path(".") and d.startswith(".")))
        for name in filenames:
            if name.lower().endswith(FONT_EXTS):
                found.append(Path(dirpath) / name)
    return sorted(found)
