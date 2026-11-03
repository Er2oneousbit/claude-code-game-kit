#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_bdf.py
# Purpose : a bitmap font you downloaded (BDF, such as an OFL-licensed CJK pixel font) to a Godot-ready BMFont .fnt,
#           cut down to the characters the game's own strings use, with a coverage check that names every character
#           the font lacks and where it appears.
# Usage   : pack spec "bdf": [{"name": "ja", "source": "assets_src/fonts/ark-pixel-12px-proportional-ja.bdf",
#                              "license": "assets_src/fonts/OFL.txt", "strings": ["data/strings_ja.json"]}]
#           strings: text / JSON (every string value, nested) / CSV / PO / POT files in the game, read as fonts-check
#           reads them; "chars": extra characters;
#           "ascii": false to leave out printable ASCII (kept by default); "all": true keeps every glyph (big);
#           "scale": whole-number upscale of the glyphs (1 to 16, default 1).
# Notes   : The font's licence file is required and is copied next to the .fnt (the SIL Open Font License asks for it
#           to travel with the font, cut down or not; check the licence names no Reserved Font Name before you rename
#           or subset, and credit the font in docs/ASSET_LOG.md). A character the strings use that the font lacks
#           stops the run (exit 1) with the file and key it came from. White ink: tint it with font_color in Godot.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os
import re
import shutil
import unicodedata

import numpy as np
from PIL import Image

import fcore as core
import fontcheck

PAGE = 256           # px, each side of a font page
MAX_GLYPH = 256      # px, a BBX width or height past this is refused before any array is made (pixel fonts: a few dozen)
MAX_SCALE = 16       # "scale" the lane accepts
HEX_ROW = re.compile(r"[0-9A-Fa-f]+\Z")


def parse_bdf(path):
    """-> (meta, {codepoint: (bitmap bool HxW, xoff, yoff, dwidth)}). meta: ascent, descent, family.
    A BDF is a download, so it is checked before anything is allocated: a bad number, a short BBX, a bitmap row that
    is not hex, more rows than the BBX height or a glyph over MAX_GLYPH px stops the run naming the font and line."""
    base = os.path.basename(path)
    meta = {"ascent": None, "descent": None, "family": ""}
    glyphs = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()

    def bad(n, msg):
        return core.ToolError(f"{base}: line {n + 1}: {msg}")

    def ints(n, count, what):
        """The first count whole numbers after the keyword on line n."""
        vals = lines[n].split()[1:1 + count]
        try:
            if len(vals) < count:
                raise ValueError
            return [int(v) for v in vals]
        except ValueError:
            raise bad(n, f"{what} needs {count} whole number{'s' if count > 1 else ''}: {lines[n].strip()[:60]!r}")

    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("FONT_ASCENT "):
            meta["ascent"] = ints(i, 1, "FONT_ASCENT")[0]
        elif ln.startswith("FONT_DESCENT "):
            meta["descent"] = ints(i, 1, "FONT_DESCENT")[0]
        elif ln.startswith("FAMILY_NAME "):
            meta["family"] = ln.split(" ", 1)[1].strip().strip('"')
        elif ln.startswith("STARTCHAR"):
            enc, bbx, dw, rows = None, None, None, []
            i += 1
            while i < len(lines) and not lines[i].startswith("ENDCHAR"):
                t = lines[i]
                if t.startswith("ENCODING "):
                    enc = ints(i, 1, "ENCODING")[0]
                elif t.startswith("DWIDTH "):
                    dw = ints(i, 1, "DWIDTH")[0]
                elif t.startswith("BBX "):
                    bbx = ints(i, 4, "BBX")
                    if not (0 <= bbx[0] <= MAX_GLYPH and 0 <= bbx[1] <= MAX_GLYPH):
                        raise bad(i, f"BBX {bbx[0]} x {bbx[1]}: a glyph is 0 to {MAX_GLYPH} px each way")
                elif t == "BITMAP":
                    i += 1
                    while i < len(lines) and lines[i] != "ENDCHAR":
                        r = lines[i].strip()
                        if r and not HEX_ROW.match(r):
                            raise bad(i, f"bitmap row {r[:40]!r} is not hex")
                        rows.append((i, r))
                        i += 1
                    break
                i += 1
            if enc is not None and enc >= 0 and bbx is not None:
                w, h, xo, yo = bbx
                if len(rows) > h:
                    raise bad(rows[h][0], f"{len(rows)} bitmap rows, but BBX says {h}")
                bm = np.zeros((h, w), bool)
                for y, (_, r) in enumerate(rows):
                    r = r[:(w + 7) // 8 * 2]   # the row's whole bytes; the bits past w are padding
                    bits = bin(int(r, 16))[2:].zfill(len(r) * 4) if r else ""
                    for x in range(min(w, len(bits))):
                        bm[y, x] = bits[x] == "1"
                glyphs[enc] = (bm, xo, yo, dw if dw is not None else w)
        i += 1
    if meta["ascent"] is None or meta["descent"] is None:
        raise core.ToolError(f"{base}: not a BDF font with FONT_ASCENT / FONT_DESCENT")
    return meta, glyphs


def strings_of(path):
    """[(where, text)] from a strings file, read the way fonts-check reads it (fontcheck.read_strings: JSON string
    values, CSV, gettext PO / POT with continuation lines and escapes, plain text): where = 'file:string id'. The text
    is in composed form (NFC), the form the shaper draws, so "e" + a combining accent needs the font's own accented
    letter."""
    base = os.path.basename(path)
    try:
        rows = fontcheck.read_strings(path)
    except FileNotFoundError:
        raise core.ToolError(f"strings file {path} not found")
    except (ValueError, UnicodeDecodeError) as exc:
        raise core.ToolError(f"strings file {path}: {exc} (strings files are UTF-8)")
    return [(f"{base}:{sid}", unicodedata.normalize("NFC", text)) for _, sid, text in rows]


def glyph_chars(text):
    """The characters of text that are drawn (composed form; no line breaks, tabs or other control and format
    characters, as fontcheck.needed decides). The space is kept: the font's space glyph gives its advance."""
    return [c for c in unicodedata.normalize("NFC", text) if c == " " or fontcheck.needed(c)]


def coverage(glyphs, sources):
    """{char: [where ...]} for every character the strings use that the font has no glyph for (spaces, line breaks
    and other controls are layout, not glyphs)."""
    missing = {}
    for where, text in sources:
        for c in glyph_chars(text):
            if c == " " or ord(c) in glyphs:
                continue
            missing.setdefault(c, [])
            if where not in missing[c] and len(missing[c]) < 3:
                missing[c].append(where)
    return missing


def pack_pages(boxes):
    """Shelf-pack (cp, w, h) into PAGE x PAGE pages with 1 px gaps -> {cp: (page, x, y)}, page count."""
    pos, page, x, y, row_h = {}, 0, 1, 1, 0
    for cp, w, h in sorted(boxes, key=lambda b: (-b[2], b[0])):
        if x + w + 1 > PAGE:
            x, y, row_h = 1, y + row_h + 1, 0
        if y + h + 1 > PAGE:
            page, x, y, row_h = page + 1, 1, 1, 0
        pos[cp] = (page, x, y)
        x += w + 1
        row_h = max(row_h, h)
    return pos, page + 1


def build(name, meta, glyphs, keep, out_dir, scale=1):
    """Write font_<name>.fnt + font_<name>_<page>.png for the codepoints in keep. Returns (fnt path, page paths)."""
    keep = sorted(cp for cp in keep if cp in glyphs)
    boxes = [(cp, glyphs[cp][0].shape[1] * scale, glyphs[cp][0].shape[0] * scale) for cp in keep]
    for cp, w, h in boxes:   # a page holds a glyph with a 1 px gap on each side
        if w + 2 > PAGE or h + 2 > PAGE:
            raise core.ToolError(f"bdf {name}: glyph U+{cp:04X} is {w} x {h} px at scale {scale}, over the "
                                 f"{PAGE - 2} px a {PAGE} px font page holds (lower \"scale\")")
    pos, pages = pack_pages(boxes)
    imgs = [np.zeros((PAGE, PAGE, 4), np.uint8) for _ in range(pages)]
    base = meta["ascent"] * scale
    lines = []
    for cp in keep:
        bm, xo, yo, dw = glyphs[cp]
        big = np.kron(bm, np.ones((scale, scale), bool)) if scale > 1 else bm
        p, x, y = pos[cp]
        h, w = big.shape
        imgs[p][y:y + h, x:x + w][big] = (255, 255, 255, 255)
        lines.append(f"char id={cp} x={x} y={y} width={w} height={h} xoffset={xo * scale} "
                     f"yoffset={base - (yo + bm.shape[0]) * scale} xadvance={dw * scale} page={p} chnl=15")
    os.makedirs(out_dir, exist_ok=True)
    page_files = []
    for p, a in enumerate(imgs):
        fn = f"font_{name}_{p}.png"
        page_files.append(core.save_clean(Image.fromarray(a), os.path.join(out_dir, fn)))
    head = [f'info face="{name}" size={(meta["ascent"] + meta["descent"]) * scale} bold=0 italic=0 charset="" unicode=1 '
            f'stretchH=100 smooth=0 aa=1 padding=0,0,0,0 spacing=1,1 outline=0',
            f'common lineHeight={(meta["ascent"] + meta["descent"]) * scale} base={base} scaleW={PAGE} scaleH={PAGE} '
            f'pages={pages} packed=0 alphaChnl=0 redChnl=4 greenChnl=4 blueChnl=4']
    head += [f'page id={p} file="font_{name}_{p}.png"' for p in range(pages)]
    head.append(f"chars count={len(lines)}")
    fnt = core.write_text(os.path.join(out_dir, f"font_{name}.fnt"), "\n".join(head + lines) + "\n")
    return fnt, page_files


def run(entries, pack, man, conf):
    for e in entries:
        name = core.snake(e["name"])
        src = core.source_path(e["source"])
        if not e.get("license"):
            raise core.ToolError(f"bdf {name}: needs \"license\": the font's licence file (it ships with the font)")
        lic = core.source_path(e["license"])
        scale = e.get("scale", 1)
        if (isinstance(scale, bool) or not isinstance(scale, (int, float)) or not 1 <= scale <= MAX_SCALE
                or scale != int(scale)):
            raise core.ToolError(f"bdf {name}: \"scale\" is a whole number from 1 to {MAX_SCALE} (got {scale!r})")
        meta, glyphs = parse_bdf(src)
        sources = [(f"spec:{name}.chars", e.get("chars", ""))]
        for sp in e.get("strings", []):
            sources += strings_of(core.source_path(sp))
        missing = coverage(glyphs, sources)
        if missing:
            listed = "; ".join(f"{c!r} U+{ord(c):04X} in {', '.join(w)}" for c, w in sorted(missing.items())[:20])
            raise core.JobError(f"bdf {name}: {len(missing)} characters the strings use are not in "
                                f"{os.path.basename(src)}: {listed}")
        keep = set(glyphs) if e.get("all") else {ord(c) for _, t in sources for c in glyph_chars(t)}
        if e.get("ascii", True):
            keep |= set(range(32, 127))
        out = core.art(conf, "fonts", name)
        man.drop_dir(out)
        fnt, pages = build(name, meta, glyphs, keep, out, int(scale))
        lic_dst = os.path.join(out, f"font_{name}_LICENSE.txt")
        shutil.copyfile(lic, lic_dst)
        man.add(fnt, "font", glyphs=len([c for c in keep if c in glyphs]), pages=len(pages), family=meta["family"],
                source_font=os.path.basename(src), license_file=os.path.basename(lic_dst),
                workflow="Dotwork bdf (BDF subset to BMFont, no model)")
        for p in pages:
            man.add(p, "font_page")
        man.add(lic_dst, "license", note=f"licence of {meta['family'] or os.path.basename(src)}; ships with the font")
        core.log(f"bdf {name}: {len([c for c in keep if c in glyphs])} of {len(glyphs)} glyphs from "
                 f"{os.path.basename(src)} in {len(pages)} page(s); every character the strings use is covered")
