#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# aseprite.py
# Purpose : the Aseprite round trip: build editable .aseprite sources (one tag per animation, indexed on the asset's
#           own colours), and re-export hand-polished files back to the shipped PNGs, sheets and SpriteFrames.
# Usage   : dotwork.py aseprite then dotwork.py aseprite --reexport
# Notes   : Needs ASEPRITE_BIN (optional tool).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import json
import os

from PIL import Image

import fcore as core
import godot


BUILD_LUA = r'''
-- Dotwork: build one .aseprite from a list file of "tag|duration_seconds|png" lines
local p = app.params
local items, order, tags = {}, {}, {}
for line in io.lines(p.list) do
  local tag, dur, path = line:match("^([^|]*)|([^|]*)|(.+)$")
  if path then
    table.insert(items, {tag = tag, dur = tonumber(dur), path = path})
    if not tags[tag] then tags[tag] = {first = #items, last = #items}; table.insert(order, tag)
    else tags[tag].last = #items end
  end
end
local spr = Sprite(tonumber(p.w), tonumber(p.h), ColorMode.RGB)
local layer = spr.layers[1]
layer.name = "art"
for i, it in ipairs(items) do
  if i > 1 then spr:newEmptyFrame() end
  spr:newCel(layer, i, Image{ fromFile = it.path }, Point(0, 0))
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
app.command.ChangePixelFormat{ format = "indexed", dithering = "none" }
spr:saveAs(p.out)
print("DOTWORK_ASE_OK " .. p.out .. " frames=" .. #items)
'''

EXPORT_LUA = r'''
-- Dotwork: export every frame of a .aseprite as "<prefix>_<tag>_<NN>.png" (or "<prefix>.png" for one untagged frame)
local p = app.params
local spr = app.open(p.file)
-- export in RGB (in memory only; the .aseprite stays indexed): saving an indexed Image on its own drops the
-- palette and every color comes out black (round-trip test, 2026-10-29)
app.command.ChangePixelFormat{ format = "rgb" }
local function save(frameNumber, path)
  local img = Image(spr.spec)
  img:drawSprite(spr, frameNumber)
  img:saveAs(path)
  print("DOTWORK_ASE_PNG " .. path)
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
    with open(lua, "w", encoding="utf-8", newline="\n") as f:
        f.write(lua_text)
    cmd = [_bin(conf), "-b"]
    for k, v in params.items():
        cmd += ["--script-param", f"{k}={v}"]
    cmd += ["--script", lua]
    code, out = core.run(cmd, timeout=600)   # a hung batch Aseprite is stopped instead of blocking Dotwork forever
    if code != 0 or "DOTWORK_ASE" not in out:
        raise core.JobError(f"Aseprite failed ({code}): {out[-600:]}")
    return out


def _palette_file(pngs, path):
    """GIMP palette of every opaque color in the frames, with index 0 reserved for transparency."""
    cols = set()
    for p in pngs:
        a = Image.open(p).convert("RGBA")
        cols |= {c[:3] for c in a.getdata() if c[3] == 255}
    cols = sorted(cols)
    lines = ["GIMP Palette", "Name: Dotwork", "Columns: 16", "#", "255   0 255\ttransparent"]
    lines += [f"{r:3d} {g:3d} {b:3d}\tc" for r, g, b in cols]
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    return len(cols)


class _Manifests:
    """Every Dotwork manifest of the game (<src_dir>/dotwork/manifest_*.json) as one row list; add() updates the row
    in the manifest that owns the file (re-exported frames keep their pack)."""

    def __init__(self):
        self.mans = [core.Manifest(core.SETTINGS, os.path.basename(p)[9:-5])
                     for p in sorted(glob.glob(os.path.join(core.SETTINGS.src, "dotwork", "manifest_*.json")))]
        if not self.mans:
            raise core.ToolError("no Dotwork manifests in this game yet (build something with `dotwork.py pack` first)")
        # manifests are tracked files a pull request can carry: every row must stay inside the game, because the
        # round trip turns rows into folder names and write paths (2026-10-30 Kimi audit)
        for m in self.mans:
            for r in m.data["assets"]:
                core.contained(r["file"], core.PROJECT, what=f"{os.path.basename(m.path)} row")
        self.data = {"assets": [r for m in self.mans for r in m.data["assets"]]}

    def add(self, path, kind, **meta):
        rel = os.path.relpath(path, core.PROJECT).replace(os.sep, "/")
        owner = next((m for m in self.mans if any(r["file"] == rel for r in m.data["assets"])), self.mans[0])
        return owner.add(path, kind, **meta)

    def forget_stale(self, folder, pattern, keep):
        """Delete the files in folder matching pattern that this re-export did not write, and their manifest rows.
        Frames trimmed in Aseprite used to stay on disk and in the asset log (2026-10-30 Kimi audit)."""
        gone = 0
        for p in sorted(glob.glob(os.path.join(folder, pattern))):
            if os.path.basename(p) in keep:
                continue
            rel = os.path.relpath(p, core.PROJECT).replace(os.sep, "/")
            for m in self.mans:
                before = len(m.data["assets"])
                m.data["assets"] = [r for r in m.data["assets"] if r["file"] != rel]
                if len(m.data["assets"]) != before:
                    m.save()
            os.remove(p)
            gone += 1
        return gone


def _name_after(f, folder):
    parts = f.split("/")
    return parts[parts.index(folder) + 1] if folder in parts else None


def _groups(pack):
    """Collect animated assets from the manifests: characters (frame rows) and fx (fx_frame rows)."""
    m = _Manifests().data
    chars, fx, single = {}, {}, []
    for a in m["assets"]:
        f = a["file"]
        if a["kind"] == "frame" and _name_after(f, "characters"):     # .../characters/<name>/frames/spr_...
            chars.setdefault(_name_after(f, "characters"), {}).setdefault(a["animation"], []).append(f)
        elif a["kind"] == "fx_frame" and _name_after(f, "fx"):        # .../fx/<name>/spr_fx_<name>_NN.png
            fx.setdefault(_name_after(f, "fx"), []).append(f)
        elif a["kind"] in ("prop", "icon", "portrait", "ui_9slice"):
            single.append(f)
    fps = {a["animation"]: (a.get("fps", 8), a.get("loop", True)) for a in m["assets"] if a["kind"] == "sheet"}
    fx_loop = {}
    for a in m["assets"]:
        if a["kind"] == "sprite_frames" and _name_after(a["file"], "fx"):
            fx_loop[_name_after(a["file"], "fx")] = a.get("animations", ["play"])[0]
    return chars, fx, single, fps, fx_loop


def build(pack, conf):
    _bin(conf)   # no Aseprite = stop before anything is written into the game's tracked folders
    src = core.src(conf, "aseprite")
    chars, fx, single, fps, fx_loop = _groups(pack)
    fx_fps = conf["design"]["effect"]["fps"]
    jobs = []
    for name, anims in chars.items():
        items = []
        for anim in sorted(anims):
            dur = 1.0 / fps.get(anim, (8, True))[0]
            items += [(anim, dur, os.path.join(pack, f)) for f in sorted(anims[anim])]
        jobs.append((os.path.join(src, "characters", f"{name}.aseprite"), items))
    for name, files in fx.items():
        tag = fx_loop.get(name, "play")
        jobs.append((os.path.join(src, "fx", f"{name}.aseprite"),
                     [(tag, 1.0 / fx_fps, os.path.join(pack, f)) for f in sorted(files)]))
    for f in single:
        jobs.append((os.path.join(src, "single", os.path.basename(f)[:-4] + ".aseprite"),
                     [("", 0.1, os.path.join(pack, f))]))
    for out, items in jobs:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        lst = out[:-9] + ".list.txt"
        with open(lst, "w", encoding="utf-8") as fh:
            fh.write("\n".join(f"{t}|{d:.4f}|{p}" for t, d, p in items) + "\n")
        pal = out[:-9] + ".gpl"
        n = _palette_file([p for _, _, p in items], pal)
        w, h = Image.open(items[0][2]).size
        _run(conf, BUILD_LUA, "ase_build.lua", {"list": lst, "w": w, "h": h, "palette": pal, "out": out})
        os.remove(lst)
        core.log(f"aseprite build {os.path.relpath(out, pack)}: {len(items)} frames, {n} colors")
    return [j[0] for j in jobs]


def reexport(pack, conf):
    """Hand-polished .aseprite -> shipped PNGs (+ .tres, sheets, manifest rows), then verify."""
    import verify
    _bin(conf)
    src = core.src(conf, "aseprite")
    man = _Manifests()
    chars, fx, single, fps, fx_loop = _groups(pack)
    res_root = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}'
    tmp = os.path.join(core.WORK, "ase_export")
    os.makedirs(tmp, exist_ok=True)

    def export(file, prefix):
        for p in glob.glob(os.path.join(tmp, "*.png")):
            os.remove(p)
        _run(conf, EXPORT_LUA, "ase_export.lua", {"file": file, "prefix": os.path.join(tmp, prefix)})
        return sorted(glob.glob(os.path.join(tmp, "*.png")))

    # characters: frames, sheets, SpriteFrames
    for name in chars:
        a_file = os.path.join(src, "characters", f"{name}.aseprite")
        if not os.path.exists(a_file):
            continue
        out = core.art(conf, "characters", name)
        pngs = export(a_file, f"spr_{name}")
        anims = {}
        for p in pngs:
            base = os.path.basename(p)                     # spr_<name>_<anim>_NN.png
            anim = base[len(f"spr_{name}_"):-7]
            core.save_clean(Image.open(p).convert("RGBA"), os.path.join(out, "frames", base))
            anims.setdefault(anim, []).append(base)
        W, H = Image.open(pngs[0]).size
        tres_anims = {}
        for anim, files in anims.items():
            f, loop = fps.get(anim, (8, True))
            tres_anims[anim] = (files, f, loop)
            sheet = Image.new("RGBA", (W * len(files), H), (0, 0, 0, 0))
            for i, fn in enumerate(files):
                sheet.alpha_composite(Image.open(os.path.join(out, "frames", fn)), (i * W, 0))
                man.add(os.path.join(out, "frames", fn), "frame", animation=anim, canvas=[W, H],
                        anchor="feet_bottom_center", note="hand-polished in Aseprite", routes=("qwen_rotate", "wan"))
            sp = core.save_clean(sheet, os.path.join(out, f"{name}_{anim}_sheet.png"))
            with open(sp[:-4] + ".json", "w", encoding="utf-8") as fh:
                json.dump({"frame_w": W, "frame_h": H, "frames": len(files), "fps": f, "loop": loop,
                           "anchor": "bottom_center"}, fh, indent=1)
            man.add(sp, "sheet", animation=anim, frames=len(files), fps=f, loop=loop, canvas=[W, H],
                    anchor="feet_bottom_center", qa=["hand-polished in Aseprite"], routes=("qwen_rotate", "wan"))
            man.add(sp[:-4] + ".json", "sheet_data", animation=anim)
        tres = godot.sprite_frames(os.path.join(out, f"{name}_frames.tres"), f"{res_root}/characters/{name}/frames",
                                   tres_anims)
        man.add(tres, "sprite_frames", animations=sorted(tres_anims), canvas=[W, H], anchor="feet_bottom_center",
                node="AnimatedSprite2D", offset=[0, -(H // 2)])
        # frames trimmed in Aseprite (and sheets of animations removed there) leave the game and the manifest
        stale = man.forget_stale(os.path.join(out, "frames"), f"spr_{name}_*.png", {os.path.basename(p) for p in pngs})
        sheets = {f"{name}_{a}_sheet{x}" for a in anims for x in (".png", ".json")}
        stale += man.forget_stale(out, f"{name}_*_sheet.png", sheets) + man.forget_stale(out, f"{name}_*_sheet.json", sheets)
        core.log(f"aseprite reexport character {name}: {len(pngs)} frames, {len(anims)} animations"
                 + (f", {stale} stale files removed" if stale else ""))
    # effects
    for name in fx:
        a_file = os.path.join(src, "fx", f"{name}.aseprite")
        if not os.path.exists(a_file):
            continue
        out = core.art(conf, "fx", name)
        pngs = export(a_file, f"spr_fx_{name}")
        tag = fx_loop.get(name, "play")
        files = []
        for i, p in enumerate(pngs):
            fn = f"spr_fx_{name}_{i:02d}.png"
            core.save_clean(Image.open(p).convert("RGBA"), os.path.join(out, fn))
            man.add(os.path.join(out, fn), "fx_frame", note="hand-polished in Aseprite", routes=("klein", "wan"),
                    blend="add")
            files.append(fn)
        godot.sprite_frames(os.path.join(out, f"fx_{name}_frames.tres"), f"{res_root}/fx/{name}",
                            {tag: (files, conf["design"]["effect"]["fps"], tag == "loop")})
        stale = man.forget_stale(out, f"spr_fx_{name}_*.png", set(files))
        core.log(f"aseprite reexport fx {name}: {len(files)} frames" + (f", {stale} stale removed" if stale else ""))
    # single images keep their shipped path
    for f in single:
        a_file = os.path.join(src, "single", os.path.basename(f)[:-4] + ".aseprite")
        if not os.path.exists(a_file):
            continue
        pngs = export(a_file, os.path.basename(f)[:-4])
        core.save_clean(Image.open(pngs[0]).convert("RGBA"), os.path.join(pack, f))
        row = next(a for a in man.data["assets"] if a["file"] == f)
        # the row keeps its models: a hand-polished frame is still model output, now modified
        keep = {k: v for k, v in row.items() if k not in ("file", "kind", "sha256", "date", "note")}
        man.add(os.path.join(pack, f), row["kind"], note="hand-polished in Aseprite", **keep)
    return verify.verify(core.SETTINGS, [r["file"] for r in man.data["assets"]])
