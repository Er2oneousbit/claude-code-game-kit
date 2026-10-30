#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_fonts.py
# Purpose : the glyph tool: pixel fonts from text bitmaps (glyphs/<font>.txt) to a PNG page + AngelCode BMFont .fnt
#           that Godot imports as a FontFile. No model: glyphs are authored as text.
# Usage   : pack spec "fonts": [{"name": "dialogue", "glyphs": "glyphs/dialogue.txt", "scale": 2, "effect":
#           "shadow"}]
# Notes   : effect shadow | outline | none; gradient brass | steel | copper | [hex...]; caps_only; export {char: file}.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
INK = (255, 255, 255, 255)
DARK = (34, 32, 52, 255)
SAMPLE = ["The quick brown fox jumps over the lazy dog.",
          "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG!",
          "0123456789 ?!.,:;'\"()[]{}<>+-*/=%&#$@_~|\\^`",
          "Welcome to the mining town. Got any coin, kid?"]


def _lines(path, **kw):
    """The file's lines, closed afterwards."""
    with open(path, **kw) as f:
        return f.read().splitlines(True)


def parse(path):
    """-> (meta dict, {char: bool array H x W})"""
    meta = {"height": 9, "baseline": 7, "spacing": 1, "space": 3}
    glyphs, cur, rows = {}, None, []

    def close():
        if cur is not None:
            w = max((len(r) for r in rows), default=1)
            a = np.zeros((meta["height"], w), bool)
            for y, r in enumerate(rows[:meta["height"]]):
                for x, c in enumerate(r):
                    a[y, x] = c == "#"
            glyphs[cur] = a

    for raw in _lines(path, encoding="utf-8"):
        line = raw.rstrip("\n").rstrip("\r")
        if not line or line.startswith("# "):
            continue
        if line.startswith("char "):
            close()
            cur, rows = line[5:], []
            if len(cur) != 1:
                raise ValueError(f"{path}: 'char' needs exactly one character, got {cur!r}")
            continue
        if cur is None:
            k, v = line.split()
            meta[k] = int(v)
            continue
        if set(line) - {"#", "."}:
            raise ValueError(f"{path}: glyph {cur!r} has a row with characters other than '#' and '.': {line!r}")
        rows.append(line)
    close()
    return meta, glyphs


GRADIENTS = {  # top -> bottom ink rows (spec "gradient": a name here or a list of hex colors)
    "brass": ["fff2b8", "f6d264", "e2aa3c", "c0842a", "8e5a1e"],
    "steel": ["f4f8fc", "c8d4e0", "9aa8b8", "6e7c8e", "4a5464"],
    "copper": ["ffd2a8", "f0a064", "d0743c", "a0502a", "6e321e"],
}


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def render_glyph(a, scale, effect, gradient=None, height=None):
    """bool glyph -> RGBA (scaled, effect baked). Shadow/outline add 1 glyph px of room right/bottom (and left/top
    for outline)."""
    pad = 1 if effect in ("shadow", "outline") else 0
    lead = 1 if effect == "outline" else 0
    h, w = a.shape
    can = np.zeros((h + pad + lead, w + pad + lead), np.uint8)  # 0 empty, 1 dark, 2 ink
    ink = np.zeros_like(can, bool)
    ink[lead:lead + h, lead:lead + w] = a
    if effect == "shadow":
        sh = np.zeros_like(ink)
        sh[1:, 1:] = ink[:-1, :-1]
        can[sh] = 1
    elif effect == "outline":
        ring = np.zeros_like(ink)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                ring |= np.roll(np.roll(ink, dy, 0), dx, 1)
        can[ring] = 1
    can[ink] = 2
    rgba = np.zeros(can.shape + (4,), np.uint8)
    rgba[can == 1] = DARK
    if gradient:  # ink color by glyph row (same rows -> same color in every glyph, so a word reads as one plate)
        cols = [_hex(c) for c in (GRADIENTS[gradient] if isinstance(gradient, str) else gradient)]
        n = height or h
        for r in range(can.shape[0]):
            k = min(len(cols) - 1, max(0, (r - lead) * len(cols) // n))
            row = can[r] == 2
            rgba[r][row] = cols[k]
    else:
        rgba[can == 2] = INK
    return np.kron(rgba, np.ones((scale, scale, 1), np.uint8)), lead


def build(name, glyph_path, out_dir, scale=2, effect="shadow", gradient=None, caps_only=False):
    meta, glyphs = parse(glyph_path)
    if caps_only:  # title fonts: lowercase codes reuse the capitals (small-caps style)
        for c in "abcdefghijklmnopqrstuvwxyz":
            if c not in glyphs and c.upper() in glyphs:
                glyphs[c] = glyphs[c.upper()]
    rendered = {c: render_glyph(a, scale, effect, gradient, meta["height"]) for c, a in glyphs.items()}
    # shelf-pack into a page 512 px wide
    W, x, y, row_h, pos = 512, 0, 0, 0, {}
    for c, (im, _) in rendered.items():
        h, w = im.shape[:2]
        if x + w > W:
            x, y, row_h = 0, y + row_h + 1, 0
        pos[c] = (x, y)
        x, row_h = x + w + 1, max(row_h, h)
    H = 1 << (y + row_h).bit_length()  # power of two height
    page = np.zeros((H, W, 4), np.uint8)
    for c, (im, _) in rendered.items():
        px, py = pos[c]
        page[py:py + im.shape[0], px:px + im.shape[1]] = im
    png = f"font_{name}.png"
    core.save_clean(Image.fromarray(page), os.path.join(out_dir, png))
    # glyph rows + room the effect adds (shadow 1, outline 2) + 1 row of air between lines
    line_h = (meta["height"] + {"shadow": 1, "outline": 2}.get(effect, 0) + 1) * scale
    base = meta["baseline"] * scale
    lines = [f'info face="dotwork_{name}" size={meta["height"] * scale} bold=0 italic=0 charset="" unicode=1 '
             f'stretchH=100 smooth=0 aa=1 padding=0,0,0,0 spacing=1,1 outline=0',
             f"common lineHeight={line_h} base={base} scaleW={W} scaleH={H} pages=1 packed=0",
             f'page id=0 file="{png}"', f"chars count={len(rendered) + 1}",
             f"char id=32 x=0 y=0 width=0 height=0 xoffset=0 yoffset=0 xadvance={meta['space'] * scale} page=0 chnl=15"]
    for c, (im, lead) in rendered.items():
        px, py = pos[c]
        gw = glyphs[c].shape[1]
        lines.append(f"char id={ord(c)} x={px} y={py} width={im.shape[1]} height={im.shape[0]} "
                     f"xoffset={-lead * scale} yoffset={-lead * scale} "
                     f"xadvance={(gw + meta['spacing']) * scale} page=0 chnl=15")
    fnt = os.path.join(out_dir, f"font_{name}.fnt")
    with open(core.safe_dest(fnt), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return fnt, os.path.join(out_dir, png), meta, rendered, line_h, glyphs


def preview(rendered, glyphs, meta, scale, line_h, text_lines, path, bg=(24, 40, 104)):
    """Sample text on an FF-style blue panel, laid out with the same advances the .fnt declares."""
    def adv(c):
        return (glyphs[c].shape[1] + meta["spacing"]) * scale if c in glyphs else meta["space"] * scale

    width = 16 + max(sum(adv(c) for c in t) for t in text_lines)
    img = Image.new("RGBA", (max(320, width), 16 + line_h * len(text_lines)), bg + (255,))
    for i, t in enumerate(text_lines):
        x = 8
        for c in t:
            if c in rendered:
                im, lead = rendered[c]
                img.alpha_composite(Image.fromarray(im), (x - lead * scale, 8 + i * line_h - lead * scale))
            x += adv(c)
    core.save_clean(img.convert("RGB"), path)
    return path


def run(entries, pack, man, conf):
    out = core.art(conf, "ui", "fonts")
    src = core.src(conf, "art", "ui", "fonts")
    os.makedirs(out, exist_ok=True)
    os.makedirs(src, exist_ok=True)
    for e in entries:
        name = core.snake(e["name"])
        # Dotwork's own glyphs/ folder first ("glyphs/dialogue.txt"), then the game ("assets_src/fonts/runes.txt")
        gp = core.contained(e["glyphs"], core.HERE, core.PROJECT, what=f"font {name} glyphs")
        if not os.path.exists(gp):
            gp = core.contained(e["glyphs"], core.PROJECT, what=f"font {name} glyphs")
        if not os.path.exists(gp):
            raise core.ToolError(f"font {name}: glyph file {e['glyphs']!r} not found in Dotwork's folder or the game")
        scale, effect = int(e.get("scale", 2)), e.get("effect", "shadow")
        fnt, png, meta, rendered, line_h, glyphs = build(name, gp, out, scale, effect, e.get("gradient"),
                                                          bool(e.get("caps_only")))
        missing = [chr(c) for c in range(33, 127) if chr(c) not in rendered]
        text = e.get("sample") or ([t for t in SAMPLE] if not missing else ["".join(sorted(rendered))])
        pv = preview(rendered, glyphs, meta, scale, line_h, text, os.path.join(src, f"font_{name}_preview.png"))
        man.add(png, "font_page", font=f"font_{name}.fnt", scale=scale, effect=effect, routes=(),
                workflow="Dotwork glyph tool (glyphs authored as text by Claude; no model)")
        man.add(fnt, "font", format="AngelCode BMFont text", glyphs=len(rendered), line_height=line_h,
                baseline=meta["baseline"] * scale, effect=effect, scale=scale,
                source=os.path.relpath(gp, core.HERE).replace("\\", "/"), preview=os.path.basename(pv),
                missing_ascii="".join(missing) or None,
                gradient=e.get("gradient"), caps_only=bool(e.get("caps_only")),
                usage="Godot: load as FontFile (theme font or LabelSettings.font); font size = line height; "
                      + ("colored ink (gradient): leave font_color white" if e.get("gradient")
                         else "white ink, tint with font_color"))
        # export: single glyphs as standalone PNGs (hand cursor, menu arrows) for Sprite2D / TextureRect use
        for ch, fn in (e.get("export") or {}).items():
            im, _ = rendered[ch]
            # the file name comes from the spec: snake it like every other name (a raw "../../x" wrote outside the
            # game, and a \\host\share name opened a network path: 2026-10-30 Kimi audit)
            ep = core.save_clean(Image.fromarray(im), core.art(conf, "ui", "symbols", f"{core.snake(fn)}.png"))
            man.add(ep, "ui_symbol", glyph=ch, font=f"font_{name}.fnt", scale=scale, effect=effect, routes=(),
                    workflow="Dotwork glyph tool (single glyph export)")
        # a symbols or caps-only font leaves most of ASCII out on purpose: the count is the news, the list is detail
        core.log(f"font {name}: covers {len(rendered)} glyphs, scale {scale}, {effect}, line {line_h}px")
        if missing:
            core.dbg(f"font {name}: ASCII not covered {''.join(missing)!r} (also in the manifest: missing_ascii)")
