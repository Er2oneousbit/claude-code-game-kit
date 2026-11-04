#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# aseprite.py
# Purpose : the Aseprite round trip: build editable .aseprite sources (one tag per animation, indexed on the asset's
#           own colours when that loses nothing, each frame timed by its hold), and re-export hand-polished files back
#           to the shipped PNGs, sheets and SpriteFrames (frame times included). The editor-neutral half is
#           handpolish.py.
# Usage   : dotwork.py aseprite [--overwrite] then dotwork.py aseprite --reexport
# Notes   : Needs ASEPRITE_BIN (optional tool). Pixelorama users: pixelorama.py, the same round trip. A build never
#           replaces a source that may hold hand polish without --overwrite (the same rule as pixelorama.py).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): a character whose clips have different sizes gets one
#           canvas, each clip centred on its bottom edge (handpolish.clip_box); the re-export crops each back (#82)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): the palette scan reads pixels without Image.getdata
#           (deprecated in Pillow 12, removed in 14) where Pillow has get_flattened_data (#185)
# ---------------------------------------------------------------------------
import glob
import os
from collections import Counter

from PIL import Image

import fcore as core
import handpolish

_Manifests = handpolish.GameManifests   # the old name, kept for callers of the 0.8.0 module
# opaque colours an indexed sprite holds without loss: 256 entries, and index 0 is the transparent colour
INDEXED_MAX = 255


BUILD_LUA = r'''
-- Dotwork: build one .aseprite from a list file of "tag|duration_seconds|x|y|png" lines (x, y: where the frame sits
-- on the canvas; a clip smaller than the canvas is placed by Dotwork, issue #82)
local p = app.params
local items, order, tags = {}, {}, {}
for line in io.lines(p.list) do
  local tag, dur, x, y, path = line:match("^([^|]*)|([^|]*)|([^|]*)|([^|]*)|(.+)$")
  if path then
    table.insert(items, {tag = tag, dur = tonumber(dur), x = tonumber(x), y = tonumber(y), path = path})
    if not tags[tag] then tags[tag] = {first = #items, last = #items}; table.insert(order, tag)
    else tags[tag].last = #items end
  end
end
local spr = Sprite(tonumber(p.w), tonumber(p.h), ColorMode.RGB)
local layer = spr.layers[1]
layer.name = "art"
for i, it in ipairs(items) do
  if i > 1 then spr:newEmptyFrame() end
  spr:newCel(layer, i, Image{ fromFile = it.path }, Point(it.x, it.y))
  spr.frames[i].duration = it.dur
end
for _, name in ipairs(order) do
  if name ~= "" then
    local t = spr:newTag(tags[name].first, tags[name].last)
    t.name = name
  end
end
spr:setPalette(Palette{ fromFile = p.palette })
spr.transparentColor = 0
-- indexed only when that loses nothing (Dotwork checks the frames first): a portrait of 1805 colours came back
-- quantized from an indexed sprite, and an untouched re-export shipped it (2026-11-01 live check)
if p.indexed == "1" then
  app.command.ChangePixelFormat{ format = "indexed", dithering = "none" }
end
spr:saveAs(p.out)
print("DOTWORK_ASE_OK " .. p.out .. " frames=" .. #items)
'''

EXPORT_LUA = r'''
-- Dotwork: export every frame of a .aseprite as "<prefix>_<tag>_<NN>.png" (or "<prefix>.png" for one untagged frame)
local p = app.params
local spr = app.open(p.file)
-- export in RGB (in memory only; an indexed .aseprite stays indexed): saving an indexed Image on its own drops the
-- palette and every color comes out black (round-trip test, 2026-10-29)
app.command.ChangePixelFormat{ format = "rgb" }
local function save(frameNumber, path)
  local img = Image(spr.spec)
  img:drawSprite(spr, frameNumber)
  img:saveAs(path)
  -- the frame's time on screen first (seconds): a path can hold spaces
  print(string.format("DOTWORK_ASE_PNG %.6f %s", spr.frames[frameNumber].duration, path))
end
-- tag names become file names: stop before writing anything when one could leave the export folder, or when two
-- tags share a name (ignoring case, as Windows file names do): each numbers its frames from 00, so the second one
-- overwrote the first one's frames and the shipped clip came back mixed (issue #81)
local seen = {}
for _, t in ipairs(spr.tags) do
  if not t.name:match("^[%w_]+$") then
    print("DOTWORK_ASE_BADTAG " .. t.name)
    return
  end
  if seen[t.name:lower()] then
    print("DOTWORK_ASE_DUPTAG " .. t.name)
    return
  end
  seen[t.name:lower()] = true
end
if #spr.tags == 0 then
  save(1, p.prefix .. ".png")
else
  for _, t in ipairs(spr.tags) do
    local k = 0
    for f = t.fromFrame.frameNumber, t.toFrame.frameNumber do
      save(f, string.format("%s_%s_%02d.png", p.prefix, t.name, k))
      k = k + 1
    end
  end
end
'''


def _bin(conf):
    b = conf["fixed"].get("aseprite_bin") or os.environ.get("ASEPRITE_BIN", "")
    if not b or not os.path.exists(b):
        raise core.ToolError("Aseprite not configured: set ASEPRITE_BIN (or aseprite_bin in dotwork.config.json) to the "
                             "Aseprite executable; the round trip is optional")
    return b


def _run(conf, lua_text, lua_name, params):
    lua = os.path.join(core.WORK, lua_name)
    os.makedirs(os.path.dirname(lua), exist_ok=True)
    with open(core.safe_dest(lua), "w", encoding="utf-8", newline="\n") as f:
        f.write(lua_text)
    cmd = [_bin(conf), "-b"]
    for k, v in params.items():
        cmd += ["--script-param", f"{k}={v}"]
    cmd += ["--script", lua]
    code, out = core.run(cmd, timeout=600)   # a hung batch Aseprite is stopped instead of blocking Dotwork forever
    if code != 0 or "DOTWORK_ASE" not in out:
        raise core.JobError(f"Aseprite failed ({code}): {out[-600:]}")
    return out


def _pixels(im):
    """Every pixel of an image as a list of tuples. Image.getdata warns from Pillow 12 and is gone in Pillow 14;
    get_flattened_data replaces it but is missing from the older Pillow that Python 3.8 installs (issue #185)."""
    flat = getattr(im, "get_flattened_data", None)
    return list(flat() if flat else im.getdata())


def _palette_file(pngs, path):
    """GIMP palette of every opaque color in the frames, with index 0 reserved for transparency. Returns (how many
    colours, True when the frames can be indexed without loss: at most INDEXED_MAX opaque colours and no partly clear
    pixel, which an indexed sprite would turn opaque or clear)."""
    cols, partial = set(), False
    for p in pngs:
        with Image.open(p) as im:
            px = _pixels(im.convert("RGBA"))
        cols |= {c[:3] for c in px if c[3] == 255}
        partial = partial or any(0 < c[3] < 255 for c in px)
    cols = sorted(cols)
    lines = ["GIMP Palette", "Name: Dotwork", "Columns: 16", "#", "255   0 255\ttransparent"]
    lines += [f"{r:3d} {g:3d} {b:3d}\tc" for r, g, b in cols]
    with open(core.safe_dest(path), "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    return len(cols), len(cols) <= INDEXED_MAX and not partial


def _export(conf, file, prefix):
    """EXPORT_LUA on one .aseprite: ([(PNG path, seconds that frame shows)] in the order Aseprite wrote them, why the
    export cannot be used or None). It cannot when a tag name could leave the export folder or two tags share a name
    (EXPORT_LUA writes nothing for such a file), or when two frames came out under one file name (issue #81)."""
    lines = _run(conf, EXPORT_LUA, "ase_export.lua", {"file": file, "prefix": prefix}).splitlines()
    for ln in lines:
        if ln.startswith("DOTWORK_ASE_BADTAG "):
            return [], f"tag {ln.split(' ', 1)[1].strip()!r}: animation names use letters, digits and _ only"
        if ln.startswith("DOTWORK_ASE_DUPTAG "):
            return [], (f"two tags share the name {ln.split(' ', 1)[1].strip()!r}: each animation is one tag "
                        "(rename or remove one)")
    pngs = []
    for ln in lines:
        if ln.startswith("DOTWORK_ASE_PNG "):
            parts = ln.split(" ", 2)
            try:
                pngs.append((parts[2].strip(), float(parts[1])))
            except (IndexError, ValueError):   # an older script's line (path only): the frame keeps its hold
                pass
    # one file name twice means a later frame overwrote an earlier one: refuse rather than ship the mix
    names = Counter(os.path.basename(p).lower() for p, _ in pngs)
    twice = sorted(n for n, c in names.items() if c > 1)
    if twice:
        return [], f"two frames were exported as {twice[0]!r}: two tags share a name (rename or remove one)"
    return pngs, None


def _shows_the_game(conf, path, items, canvas):
    """True when the .aseprite at path still shows what a build from items (the game's frames) holds: Aseprite
    exports it (EXPORT_LUA), and the tags, the frames in each, every frame's look (handpolish.same_look, the game's
    frame placed on the canvas as the build places it) and, in a tag, its time on screen (within HOLD_TOLERANCE_S:
    Aseprite keeps whole milliseconds) all match. Anything else may be hand polish not re-exported yet, so build
    keeps the file (issue #64: it was overwritten)."""
    tmp = os.path.join(core.WORK, "ase_check")
    os.makedirs(tmp, exist_ok=True)
    for p in glob.glob(os.path.join(tmp, "*.png")):
        os.remove(p)
    want, k = {}, Counter()     # {png name EXPORT_LUA writes: (the game's png, seconds or None)}
    for tag, secs, png in items:
        if tag:
            want[f"f_{tag}_{k[tag]:02d}.png"] = (png, secs)
            k[tag] += 1
        else:                   # one untagged frame (a single image): its time does not matter
            want["f.png"] = (png, None)
    pngs, bad = _export(conf, path, os.path.join(tmp, "f"))
    names = [os.path.basename(p) for p, _ in pngs]
    if bad or len(names) != len(set(names)) or set(names) != set(want):
        return False
    for name, secs in zip(names, (s for _, s in pngs)):
        game, should = want[name]
        if should is not None and abs(secs - should) > handpolish.HOLD_TOLERANCE_S:
            return False
        with Image.open(os.path.join(tmp, name)) as a, Image.open(game) as b:
            if not handpolish.same_look(a.convert("RGBA"), handpolish.pad(b, canvas)):
                return False
    return True


def build(pack, conf, overwrite=False):
    """Write <src_dir>/aseprite/{characters,fx,single}/<name>.aseprite. A file that already exists is exported first:
    one that still shows the game's frames is left as it is; one that differs may hold hand polish (or the game's
    art changed since) and is kept unless overwrite, and a file overwrite replaces is first copied to
    <name>.aseprite.bak (one level, as pixelorama.build does). A character whose clips have different sizes gets the
    widest and tallest as its canvas, each clip centred on its bottom edge (handpolish.clip_box), and the re-export
    crops each one back. Nothing is written when an effect's frames are not all one size (ToolError naming the
    sizes).
    Returns {"written": [...], "unchanged": [...], "kept": [...], "backups": [the .bak files written]}."""
    _bin(conf)   # no Aseprite = stop before anything is written into the game's tracked folders
    src = core.src(conf, "aseprite")
    chars, fx, single, fps, fx_loop, holds = handpolish.groups(pack)
    jobs = []
    for name, anims in chars.items():
        items = []
        for anim in sorted(anims):
            files = sorted(anims[anim])
            secs = handpolish.frame_seconds(holds.get((name, anim)), handpolish.rate(fps, name, anim)[0], len(files))
            items += [(anim, d, os.path.join(pack, f)) for d, f in zip(secs, files)]
        jobs.append((os.path.join(src, "characters", f"{name}.aseprite"), items))
    for name, files in fx.items():
        tag = fx_loop.get(name, "play")
        rate = handpolish.fx_rate(conf, name, tag)[0]
        jobs.append((os.path.join(src, "fx", f"{name}.aseprite"),
                     [(tag, 1.0 / rate, os.path.join(pack, f)) for f in sorted(files)]))
    for f in single:
        jobs.append((os.path.join(src, "single", os.path.basename(f)[:-4] + ".aseprite"),
                     [("", 0.1, os.path.join(pack, f))]))
    # an Aseprite sprite has one canvas: BUILD_LUA sized it from the first frame, so clips of another size came back
    # from a re-export padded or cropped to it, off their anchor, with verify passing (issue #82). A character's
    # clips now share the largest canvas, each placed by handpolish.clip_box (the re-export crops it back from
    # there); an effect has no clips to tell apart, so its frames must be one size. Every source is checked before
    # any is written.
    canvas, place = {}, {}
    for out, items in jobs:
        size_of = {}
        for _, _, p in items:
            with Image.open(p) as im:   # the header only: no pixels are read here
                size_of[p] = im.size
        sizes = set(size_of.values())
        if len(sizes) > 1 and os.path.basename(os.path.dirname(out)) != "characters":
            raise core.ToolError(f"{os.path.relpath(out, pack)}: frames of {len(sizes)} sizes "
                                 f"({', '.join('%dx%d' % s for s in sorted(sizes))}): an Aseprite sprite has one "
                                 "canvas (give every frame the same size)")
        canvas[out] = handpolish.canvas_of(sizes)
        place.update({p: handpolish.clip_box(canvas[out], s) for p, s in size_of.items()})
    done = {"written": [], "unchanged": [], "kept": [], "backups": []}
    for out, items in jobs:
        rel = os.path.relpath(out, pack)
        if os.path.exists(out):
            if _shows_the_game(conf, out, items, canvas[out]):
                done["unchanged"].append(out)
                continue
            if not overwrite:
                done["kept"].append(out)
                core.log(f"aseprite build {rel}: kept (it differs from the game's frames; --overwrite replaces it)")
                continue
            # the file being replaced may hold polish that was never re-exported: keep it beside the new one
            with open(out, "rb") as fh:
                old = fh.read()
            with open(core.safe_dest(out + ".bak"), "wb") as fh:
                fh.write(old)
            done["backups"].append(out + ".bak")
            core.log(f"aseprite build {rel}: the file it replaces is kept as {os.path.basename(out)}.bak")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        # BUILD_LUA's frame list and palette go to the work folder and are removed after: the .gpl used to stay
        # beside every .aseprite in the game's tracked sources (issue #109)
        work = os.path.join(core.WORK, "ase_build")
        os.makedirs(work, exist_ok=True)
        stem = os.path.join(work, os.path.basename(out)[:-9])
        lst, pal = stem + ".list.txt", stem + ".gpl"
        try:
            with open(core.safe_dest(lst), "w", encoding="utf-8") as fh:
                fh.write("\n".join(f"{t}|{d:.4f}|{place[p][0]}|{place[p][1]}|{p}" for t, d, p in items) + "\n")
            n, indexed = _palette_file([p for _, _, p in items], pal)
            w, h = canvas[out]
            _run(conf, BUILD_LUA, "ase_build.lua", {"list": lst, "w": w, "h": h, "palette": pal, "out": out,
                                                     "indexed": "1" if indexed else "0"})
        finally:
            for p in (lst, pal):
                if os.path.exists(p):
                    os.remove(p)
        done["written"].append(out)
        core.log(f"aseprite build {rel}: {len(items)} frames, {n} colors"
                 + ("" if indexed else ", RGB (too many colours or partly clear pixels to index without loss)"))
    return done


def reexport(pack, conf):
    """Hand-polished .aseprite -> shipped PNGs (+ .tres, sheets, manifest rows), then verify."""
    _bin(conf)
    tmp = os.path.join(core.WORK, "ase_export")
    os.makedirs(tmp, exist_ok=True)

    def export(file, prefix):
        for p in glob.glob(os.path.join(tmp, "*.png")):
            os.remove(p)
        pngs, bad = _export(conf, file, os.path.join(tmp, prefix))
        if bad:
            raise core.ToolError(f"{os.path.relpath(file, pack)}: {bad}")
        secs = {os.path.basename(p): s for p, s in pngs}
        return sorted(glob.glob(os.path.join(tmp, "*.png"))), secs

    return handpolish.write_back(pack, conf, core.src(conf, "aseprite"), ".aseprite", export, "Aseprite")
