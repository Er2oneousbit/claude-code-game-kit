#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# handpolish.py
# Purpose : the editor-neutral half of the hand-polish round trips (aseprite.py, pixelorama.py): which of the game's
#           assets get an editable source (characters, effects and single images, read from the manifests), each
#           clip's frame holds, and how polished frames go back into the game (PNGs, sheets, SpriteFrames, manifest
#           rows). A frame that still looks the same keeps its shipped file byte for byte, and an unchanged hold
#           keeps its exact value.
# Usage   : imported by aseprite.py and pixelorama.py
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import datetime
import glob
import json
import os
import re
from collections import Counter

import numpy as np
from PIL import Image

import fcore as core
import godot

# s: an editor time within this of the old hold keeps the old value (Aseprite keeps whole milliseconds, and the list
# Dotwork hands it has 4 decimals); a deliberate change is far larger than 1.5 ms
HOLD_TOLERANCE_S = 0.0015
TAG_NAME = re.compile(r"[A-Za-z0-9_]+")   # animation names become file names: nothing that can leave the folder
# a character frame an editor exports, after spr_<name>_: <animation>_<frame number>.png (the number is the last part,
# so animation names may hold digits and _)
FRAME_NAME = re.compile(r"(.+)_([0-9]+)\.png")
MAX_CLIP = 100       # frames per animation: the shipped names carry two digits (spr_<name>_<anim>_NN.png)
# what a row added for a new file (a frame or clip made in the editor) takes from its sibling's row: where the art
# came from. Holds (durations), checks (qa) and generation inputs (request, seed, prompt) belong to the sibling's own
# file: a 2-frame clip added next to an attack inherited its 4 holds and timed itself by them (2026-11-01 review)
PROVENANCE = ("models", "workflow", "routes", "blend")
# one animation of a SpriteFrames .tres, as godot.sprite_frames and Godot itself write it
TRES_ANIM = re.compile(r'"loop": (true|false),\s*"name": &"([^"]*)",\s*"speed": ([0-9.]+)')


class GameManifests:
    """Every Dotwork manifest of the game (<src_dir>/dotwork/manifest_*.json) as one row list. record() brings a
    re-exported file's rows up to date in place: provenance and row order stay, and a manifest is saved only when one
    of its rows really changed."""

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

    def current(self):
        """One row per file. Two packs can write the same character, so two manifests can list one file: the row
        whose SHA-256 matches the file on disk wins, else the last one read."""
        by = {}
        for r in self.data["assets"]:
            by.setdefault(r["file"], []).append(r)
        out = []
        for f, rows in by.items():
            if len(rows) > 1:
                p = os.path.join(core.PROJECT, f)
                sha = core.sha256_file(p) if os.path.exists(p) else None
                rows = [r for r in rows if r.get("sha256") == sha] or rows
            out.append(rows[-1])
        return out

    def record(self, path, kind, note, changed, like=None, force=(), **fields):
        """The rows of one re-exported file. changed: the file's bytes changed in this re-export.
        Every manifest row listing the file is updated in place, keeping its other keys (models, workflow, canvas,
        anchor, blend, qa ...), its date and its position: a changed file gets its new sha256, the polish note (added
        once) and the given fields. An unchanged file's rows stay exactly as they are, except the keys named in
        force (a retimed clip: its sheet PNG is the same, its holds are not), so an untouched round trip saves no
        manifest at all. A file no row lists yet (a frame or clip added in the editor) gets a new row: the given
        fields, plus the PROVENANCE keys of like (a sibling row: same models and workflow) and nothing else of it,
        never a default model list; with no sibling, models is empty."""
        rel = os.path.relpath(path, core.PROJECT).replace(os.sep, "/")
        found = False
        for m in self.mans:
            dirty = False
            for r in m.data["assets"]:
                if r["file"] != rel:
                    continue
                found = True
                for k, v in fields.items():
                    if not (changed or k in force):
                        continue
                    if v is None:
                        if k in r:
                            del r[k]
                            dirty = True
                    elif r.get(k) != v:
                        r[k] = v
                        dirty = True
                if changed:
                    r["sha256"] = core.sha256_file(path)
                    if note not in (r.get("note") or ""):
                        r["note"] = f'{r["note"]}; {note}' if r.get("note") else note
                    dirty = True
            if dirty:
                m.save()
        if found or not changed:
            return
        row = {"file": rel, "kind": kind, "sha256": core.sha256_file(path), "date": datetime.date.today().isoformat(),
               "models": []}
        row.update({k: like[k] for k in PROVENANCE if like and k in like})
        row.update({k: v for k, v in fields.items() if v is not None})
        row["note"] = note
        home = next((m for m in self.mans if like and any(r["file"] == like.get("file") for r in m.data["assets"])),
                    self.mans[0])
        home.data["assets"].append(row)
        home.save()

    def forget_stale(self, folder, pattern, keep):
        """Delete the files in folder matching pattern that this re-export did not write, and their manifest rows.
        Frames trimmed in the editor used to stay on disk and in the asset log (2026-10-30 Kimi audit)."""
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


def name_after(f, folder):
    parts = f.split("/")
    return parts[parts.index(folder) + 1] if folder in parts else None


def groups(pack):
    """Collect animated assets from the manifests: characters (frame rows), fx (fx_frame rows) and single images,
    plus each clip's (fps, loop) (read it with rate()), each effect's animation name and each character clip's holds
    ({(character, animation): [relative durations]}, from the sheet rows that carry them). Sheets without an
    animation name (status marks, spells, talking portraits) are not clips of a character and are skipped. A file two
    manifests list counts once (GameManifests.current)."""
    rows = GameManifests().current()
    chars, fx, single, holds, fps, other = {}, {}, [], {}, {}, 0
    for a in rows:
        f = a["file"]
        if a["kind"] == "frame" and name_after(f, "characters") and "animation" in a:   # .../characters/<name>/frames/
            chars.setdefault(name_after(f, "characters"), {}).setdefault(a["animation"], []).append(f)
        elif a["kind"] == "fx_frame" and name_after(f, "fx"):
            name = name_after(f, "fx")
            # only the effects lane's layout, .../fx/<name>/spr_fx_<name>_NN.png (hit effects share it): spells and
            # VFX keep their own folders and names, which a write-back under fx/<name>/spr_fx_<name>_NN would break
            if f.split("/")[-2] == name and os.path.basename(f).startswith(f"spr_fx_{name}_"):
                fx.setdefault(name, []).append(f)
            else:
                other += 1
        elif a["kind"] in ("prop", "icon", "portrait", "ui_9slice"):
            single.append(f)
        elif a["kind"] == "sheet" and "animation" in a:
            fps[a["animation"]] = (a.get("fps", 8), a.get("loop", True))
            if name_after(f, "characters"):
                fps[(name_after(f, "characters"), a["animation"])] = fps[a["animation"]]
                if a.get("durations"):
                    holds[(name_after(f, "characters"), a["animation"])] = [float(d) for d in a["durations"]]
    if other:
        core.log(f"hand polish: {other} effect frames from other lanes (spells, VFX) have no editable source; they "
                 "are drawn from their specs")
    fx_loop = {}
    for a in rows:
        if a["kind"] == "sprite_frames" and name_after(a["file"], "fx"):
            fx_loop[name_after(a["file"], "fx")] = a.get("animations", ["play"])[0]
    return chars, fx, single, fps, fx_loop, holds


def rate(fps, name, anim):
    """(fps, loop) of one character's clip: its own sheet row, else a sheet of that animation, else (8, True)."""
    return fps.get((name, anim)) or fps.get(anim, (8, True))


def tres_animations(path):
    """[(name, speed, loop)] in the order a SpriteFrames .tres lists its animations; [] when there is no file. The
    re-export keeps that order and each effect's speed, so an untouched SpriteFrames is written back unchanged."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [(n, float(sp), lp == "true") for lp, n, sp in TRES_ANIM.findall(f.read())]


def fx_rate(conf, name, tag):
    """(fps, loop) of an effect: its SpriteFrames as shipped (hit effects play faster than the effects lane's
    default), else the config's effect fps."""
    for n, speed, loop in tres_animations(core.art(conf, "fx", name, f"fx_{name}_frames.tres")):
        if n == tag:
            return speed, loop
    return conf["design"]["effect"]["fps"], tag == "loop"


def frame_seconds(holds, fps, n):
    """How long each of n frames shows in the game: hold / fps (a missing or short hold list counts 1.0)."""
    h = list(holds or [])
    return [(h[i] if i < len(h) else 1.0) / fps for i in range(n)]


def holds_from_seconds(seconds, fps, old=None, what="clip"):
    """Relative durations (Godot's per-frame "duration") from the seconds an editor shows each frame. A frame whose
    time matches its old hold within HOLD_TOLERANCE_S keeps the old value exactly, so an untouched clip writes the
    same files; a seconds entry of None also keeps it. None when the clip had no holds and every frame is still
    1.0 (the SpriteFrames and sheet data then stay as an un-held clip writes them)."""
    old = list(old or [])
    out = []
    for i, s in enumerate(seconds):
        was = old[i] if i < len(old) else 1.0
        if s is None or abs(s - was / fps) <= HOLD_TOLERANCE_S:
            out.append(was)
            continue
        h = round(s * fps, 3)
        if not h > 0:
            raise core.ToolError(f"{what}: frame {i} shows {s:.4f} s, under a thousandth of a frame at {fps} fps")
        out.append(h)
    if not old and all(h == 1.0 for h in out):
        return None
    return out


def same_look(a, b):
    """True when two RGBA images show the same thing: equal size, equal alpha everywhere and equal colour wherever
    alpha is above 0. Editors drop the colour stored under fully clear pixels (Pixelorama writes 0, 0, 0, 0 there)."""
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return False
    seen = a[..., 3] > 0
    return bool(np.array_equal(a[..., 3], b[..., 3]) and np.array_equal(a[..., :3][seen], b[..., :3][seen]))


def keep_or_save(img, path):
    """Save a re-exported frame, unless the shipped file already shows the same thing: then that file stays as it is,
    byte for byte (an untouched frame never changes, whatever the editor did to its clear pixels). True when the
    file was written."""
    img = img.convert("RGBA")
    if os.path.exists(path):
        with Image.open(path) as old:
            if same_look(old.convert("RGBA"), img):
                return False
    core.save_clean(img, path)
    return True


def _bytes(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def write_if_changed(path, text):
    """Write a text file only when its content differs, with the system's line ends as the lanes write it (text
    mode). True when it was written."""
    data = text.replace("\n", os.linesep).encode("utf-8")
    if _bytes(path) == data:
        return False
    with open(core.safe_dest(path), "wb") as f:
        f.write(data)
    return True


def write_back(pack, conf, src_dir, ext, export, tool):
    """Hand-polished sources -> shipped PNGs (+ .tres, sheets, manifest rows), then verify.
    src_dir: the editor's folder (characters/, fx/ and single/ inside); ext: the source file extension;
    export(file, prefix) -> (PNG paths, sorted, named <prefix>_<tag>_NN.png, or <prefix>.png for one untagged frame;
    {png basename: seconds that frame shows}); tool: the editor's name for the manifest notes.
    Only what really changed is written: an untouched round trip changes no file and no manifest."""
    import verify
    man = GameManifests()
    rows = {r["file"]: r for r in man.current()}
    chars, fx, single, fps, fx_loop, holds = groups(pack)
    res_root = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}'
    note = f"hand-polished in {tool}"
    touched = []

    def rel(p):
        return os.path.relpath(p, core.PROJECT).replace(os.sep, "/")

    def sibling(kind, folder):
        """A row of this kind for another file of the same asset: the provenance a new file inherits."""
        return next((r for f, r in rows.items() if r["kind"] == kind and f.startswith(folder)), None)

    def frames_of(a_file, prefix):
        pngs, secs = export(a_file, prefix)
        if not pngs:
            raise core.ToolError(f"{os.path.relpath(a_file, pack)}: no frames came out of {tool}")
        return pngs, secs

    def png(img, path, kind, like, force=(), **fields):
        changed = keep_or_save(img, path)
        man.record(path, kind, note, changed, like=like, force=force, **fields)
        if changed:
            touched.append(rel(path))

    def text(path, body, kind, **fields):
        changed = write_if_changed(path, body)
        man.record(path, kind, note, changed, **fields)
        if changed:
            touched.append(rel(path))

    def tres(path, write, **fields):
        before = _bytes(path)
        write()
        changed = _bytes(path) != before
        man.record(path, "sprite_frames", note, changed, **fields)
        if changed:
            touched.append(rel(path))

    # characters: frames, sheets, SpriteFrames
    for name in chars:
        a_file = os.path.join(src_dir, "characters", name + ext)
        if not os.path.exists(a_file):
            continue
        out = core.art(conf, "characters", name)
        home = rel(out) + "/"
        pngs, secs = frames_of(a_file, f"spr_{name}")
        with Image.open(pngs[0]) as im:
            W, H = im.size
        clip_of = {}                                       # png basename -> animation, every name checked first
        for p in pngs:
            base = os.path.basename(p)                     # spr_<name>_<anim>_NN.png
            m = FRAME_NAME.fullmatch(base[len(f"spr_{name}_"):]) if base.startswith(f"spr_{name}_") else None
            if not m:
                raise core.ToolError(f"{os.path.relpath(a_file, pack)}: frame {base!r} is in no tag: each animation "
                                     "is one tag named like the animation (walk_s)")
            if not TAG_NAME.fullmatch(m.group(1)):
                raise core.ToolError(f"{os.path.relpath(a_file, pack)}: tag {m.group(1)!r}: animation names use "
                                     "letters, digits and _ only")
            clip_of[base] = m.group(1)
        # a longer tag used to turn frame 100 (named _100) into a bogus animation "<anim>_" with its own sheet
        for anim, n in sorted(Counter(clip_of.values()).items()):
            if n > MAX_CLIP:
                raise core.ToolError(f"{os.path.relpath(a_file, pack)}: tag {anim} has {n} frames (at most "
                                     f"{MAX_CLIP}: split it into two tags)")
        anims = {}
        for p in pngs:
            base = os.path.basename(p)
            anim = clip_of[base]
            with Image.open(p) as im:
                png(im, os.path.join(out, "frames", base), "frame", sibling("frame", home), animation=anim,
                    canvas=[W, H], anchor="feet_bottom_center")
            anims.setdefault(anim, []).append(base)
        tres_path = os.path.join(out, f"{name}_frames.tres")
        shipped = [n for n, _, _ in tres_animations(tres_path) if n in anims]
        tres_anims = {}
        for anim in shipped + sorted(a for a in anims if a not in shipped):   # the shipped order, new clips after
            files = anims[anim]
            f, loop = rate(fps, name, anim)
            durs = holds_from_seconds([secs.get(fn) for fn in files], f, holds.get((name, anim)),
                                      what=f"{name} {anim}")
            tres_anims[anim] = (files, f, loop) if durs is None else (files, f, loop, durs)
            sheet = Image.new("RGBA", (W * len(files), H), (0, 0, 0, 0))
            for i, fn in enumerate(files):
                with Image.open(os.path.join(out, "frames", fn)) as im:
                    sheet.alpha_composite(im.convert("RGBA"), (i * W, 0))
            sp = os.path.join(out, f"{name}_{anim}_sheet.png")
            retimed = (durs or None) != (holds.get((name, anim)) or None)
            png(sheet, sp, "sheet", sibling("sheet", home), animation=anim, frames=len(files), fps=f, loop=loop,
                canvas=[W, H], anchor="feet_bottom_center", durations=durs, force=("durations",) if retimed else ())
            data = {"frame_w": W, "frame_h": H, "frames": len(files), "fps": f, "loop": loop, "anchor": "bottom_center"}
            if durs is not None:   # other engines read the holds here: frame i shows durations[i] / fps seconds
                data["durations"] = durs
            text(sp[:-4] + ".json", json.dumps(data, indent=1), "sheet_data", animation=anim)
        tres(tres_path, lambda: godot.sprite_frames(tres_path, f"{res_root}/characters/{name}/frames", tres_anims),
             animations=sorted(tres_anims), canvas=[W, H], anchor="feet_bottom_center", node="AnimatedSprite2D",
             offset=[0, -(H // 2)])
        # frames trimmed in the editor (and sheets of animations removed there) leave the game and the manifest
        stale = man.forget_stale(os.path.join(out, "frames"), f"spr_{name}_*.png", {os.path.basename(p) for p in pngs})
        sheets = {f"{name}_{a}_sheet{x}" for a in anims for x in (".png", ".json")}
        stale += man.forget_stale(out, f"{name}_*_sheet.png", sheets) + man.forget_stale(out, f"{name}_*_sheet.json", sheets)
        core.log(f"{tool.lower()} reexport character {name}: {len(pngs)} frames, {len(anims)} animations"
                 + (f", {stale} stale files removed" if stale else ""))
    # effects
    for name in fx:
        a_file = os.path.join(src_dir, "fx", name + ext)
        if not os.path.exists(a_file):
            continue
        out = core.art(conf, "fx", name)
        home = rel(out) + "/"
        pngs, secs = frames_of(a_file, f"spr_fx_{name}")
        tag = fx_loop.get(name, "play")
        fx_fps, loop = fx_rate(conf, name, tag)
        files = []
        like = sibling("fx_frame", home)
        # the effect's frame size and anchor, given: a row added for a new frame takes only provenance from like
        shape = {"anchor": like["anchor"]} if like and "anchor" in like else {}
        for i, p in enumerate(pngs):
            fn = f"spr_fx_{name}_{i:02d}.png"
            with Image.open(p) as im:
                png(im, os.path.join(out, fn), "fx_frame", like, canvas=list(im.size), **shape)
            files.append(fn)
        durs = holds_from_seconds([secs.get(os.path.basename(p)) for p in pngs], fx_fps, what=f"effect {name}")
        tres_path = os.path.join(out, f"fx_{name}_frames.tres")
        tres(tres_path, lambda: godot.sprite_frames(tres_path, f"{res_root}/fx/{name}", {
            tag: (files, fx_fps, loop) if durs is None else (files, fx_fps, loop, durs)}))
        stale = man.forget_stale(out, f"spr_fx_{name}_*.png", set(files))
        core.log(f"{tool.lower()} reexport fx {name}: {len(files)} frames" + (f", {stale} stale removed" if stale else ""))
    # single images keep their shipped path and their row (a hand-polished image is still that model's output)
    for f in single:
        a_file = os.path.join(src_dir, "single", os.path.basename(f)[:-4] + ext)
        if not os.path.exists(a_file):
            continue
        pngs, _ = frames_of(a_file, os.path.basename(f)[:-4])
        with Image.open(pngs[0]) as im:
            png(im, os.path.join(pack, f), rows[f]["kind"], None)
    core.log(f"{tool.lower()} reexport: {len(touched)} files changed"
             + (f" ({', '.join(touched[:8])}{' ...' if len(touched) > 8 else ''})" if touched else ""))
    return verify.verify(core.SETTINGS, sorted({r["file"] for r in man.data["assets"]}))
