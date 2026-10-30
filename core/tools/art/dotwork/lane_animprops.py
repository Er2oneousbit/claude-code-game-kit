#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_animprops.py
# Purpose : interactive props with state animations: chest (closed -> half -> open), door (closed -> ajar -> open),
#           lever (off / on), save point (glow loop); AnimatedSprite2D scenes, footprint for solid ones.
# Usage   : pack spec "animprops": [{"name": "chest", "kind": "chest", "prompt": "a wooden treasure chest"}]
#           ambient loops: {"name": "torch", "kind": "flame", "prompt": "a wall torch with a lit flame"}; kinds flame,
#           flag (pole "left" / "right"), smoke (emit [x, y] in the sprite, default its top), spin (sym: the part's
#           rotational symmetry, default 8; render the turning part on its own), sway; frames / fps override.
# Notes   : Chest / door states are klein edits of the closed render, and only the moving part of each edit is kept
#           (moving_part): the chest's lid (the upper half and anything above it), the door's panel inside its frame.
#           The rest stays pixel-identical to the closed render, so the chest opens instead of morphing into another
#           drawing (2026-10-30 art audit D8, issue #27); whole_edit true keeps the full edit. The lever's on state
#           is its mirror; the glow is code.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import json
import os
import shutil

import numpy as np
from PIL import Image, ImageOps

import fcore as core
import godot
from lane_character import COMFY_WORK, _wf
from lane_props import PROP_TPL, fit_sprite

import engine as lib  # noqa: E402

EDITS = {
    "chest": [("half", "the lid of the chest is half open, a little golden light glows inside"),
              ("open", "the lid of the chest is wide open and the chest is empty inside")],
    "door": [("ajar", "the door is slightly ajar, a thin dark gap shows at its edge"),
             ("open", "the door is swung wide open, showing a dark doorway inside the frame")],
}
FRONT_TPL = ("pixel art sprite, straight-on front view of {s}, a building part for a {style} {genre} town, drawn in the "
             "exact pixel art style, palette, outline and shading of image 1, {setting}, crisp dark outline, centered")


def edit(src, instr, seed, tag, keep_bg=False):
    """Palette-locked klein edit of one sprite (cached by instruction + seed). keep_bg: skip the workflow's border
    flood; a door fills its whole cell, so the flood ate light planks at the edge and left holes (2026-10-30)."""
    os.makedirs(os.path.dirname(tag), exist_ok=True)
    out, meta = tag + ".png", tag + ".json"
    want = {"instr": instr, "seed": seed, "keep_bg": bool(keep_bg)}
    if os.path.exists(out) and os.path.exists(meta) and json.load(open(meta)) == want:
        return out
    core.ensure_comfy()
    fn = f"dotwork_anim_{os.path.basename(tag)}.png"
    fn = lib.put(Image.open(src), fn)
    g = _wf("04_edit_pixel_art")
    rel = f"animprops/{os.path.basename(tag)}"
    shutil.rmtree(os.path.join(COMFY_WORK, *rel.split("/")), ignore_errors=True)
    g["31"]["inputs"].update(filename_prefix=f"dotwork_work/{rel}/free", upscale=1, as_animation=False)
    g["32"]["inputs"].update(filename_prefix=f"dotwork_work/{rel}/locked", upscale=1, as_animation=False)
    g["2"]["inputs"]["image"] = fn
    g["5"]["inputs"]["image"] = fn
    g["19"]["inputs"]["noise_seed"] = seed
    if keep_bg:
        for n in g.values():
            if n["class_type"] == "SK_BackgroundRemove":
                n["inputs"]["enabled"] = False
    g["13"]["inputs"]["text"] = (f"Edit the pixel art sprite in image 1: {instr}. Keep the same object, same size, same "
                                 "position, same pixel art style, colors and outline.")
    lib.run_job(g, timeout=1200)
    outs = sorted(glob.glob(os.path.join(COMFY_WORK, *rel.split("/"), "locked*.png")))
    if not outs:
        raise core.JobError(f"animprops edit {tag}: no output")
    # same canvas as the source so frames line up
    im = Image.open(outs[0]).convert("RGBA")
    base = Image.open(src)
    if im.size != base.size:
        can = Image.new("RGBA", base.size, (0, 0, 0, 0))
        can.alpha_composite(im.crop(im.getbbox()), ((base.width - im.crop(im.getbbox()).width) // 2,
                                                     base.height - im.crop(im.getbbox()).height))
        im = can
    im.save(out)
    with open(core.safe_dest(meta), "w", encoding="utf-8") as fh:
        json.dump(want, fh)
    return out


def moving_part(base, kind):
    """Mask of the pixels a state edit may change, from the closed render's content box: a chest's lid is everything
    above the middle of the closed chest (an opened lid rises past its top), a door's panel is the inside of its frame
    (the outer 15 % of the width each side and of the height on top stay: lintel and jambs)."""
    a = np.array(base.convert("RGBA"))
    bb = base.getbbox() or (0, 0, a.shape[1], a.shape[0])
    m = np.zeros(a.shape[:2], bool)
    if kind == "chest":
        m[:bb[1] + (bb[3] - bb[1]) // 2] = True
    else:
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        m[bb[1] + round(h * 0.15):bb[3], bb[0] + round(w * 0.15):bb[2] - round(w * 0.15)] = True
    return m


def keep_moving(base_p, edit_p, kind, out_p):
    """Write the closed render with only the moving part taken from the edit; returns the share of the edit's visible
    changes that fell outside the moving part and were dropped (a QA hint: the edit redrew the whole object)."""
    a = np.array(Image.open(base_p).convert("RGBA"))
    b = np.array(Image.open(edit_p).convert("RGBA").resize((a.shape[1], a.shape[0]), Image.NEAREST))
    m = moving_part(Image.fromarray(a), kind)
    changed = (a != b).any(-1) & ((a[..., 3] > 0) | (b[..., 3] > 0))
    out = a.copy()
    out[m] = b[m]
    if kind == "door":   # a doorway is dark, never see-through: a hole in the edit's panel keeps the closed planks
        hole = m & (b[..., 3] == 0) & (a[..., 3] == 255)
        out[hole] = a[hole]
    Image.fromarray(out).save(out_p)
    return float((changed & ~m).sum() / max(1, changed.sum()))


def glow_frames(src, n=8, seed=3):
    """Save-point loop: bright pixels pulse, the upper 60% floats 1 px, a few sparkles twinkle."""
    base = np.array(Image.open(src).convert("RGBA")).astype(np.float32)
    a = base[..., 3] > 0
    ys, xs = np.nonzero(a)
    top, bot = ys.min(), ys.max()
    split = int(top + (bot - top) * 0.6)
    lum = base[..., :3].mean(2)
    bright = a & (lum > np.percentile(lum[a], 60))
    rng = np.random.default_rng(seed)
    spark_pts = [(int(rng.integers(top, split)), int(rng.integers(xs.min(), xs.max() + 1))) for _ in range(10)]
    out = []
    for f in range(n):
        im = base.copy()
        k = 1 + 0.18 * np.sin(2 * np.pi * f / n)
        im[bright, :3] = np.clip(im[bright, :3] * k, 0, 255)
        if f in (2, 3, 4):  # float: the crystal part rises 1 px for part of the loop
            up = np.zeros_like(im)
            up[:split - 1] = im[1:split]
            up[split - 1:] = im[split - 1:]
            im = up
        for j, (py, px) in enumerate(spark_pts):
            if (f + j) % 4 == 0 and 0 < py < im.shape[0] - 1 and 0 < px < im.shape[1] - 1:
                im[py, px] = (255, 255, 255, 255)
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    im[py + dy, px + dx] = (190, 230, 255, 255)
        out.append(Image.fromarray(im.astype(np.uint8)))
    return out


# ---- ambient loops: code-driven motion on a rendered prop (no animation model, so they loop exactly) ----------------
AMBIENT = {   # kind: (frames, fps, solid by default)
    "flame": (6, 10, False), "flag": (6, 8, False), "smoke": (8, 8, True), "spin": (4, 8, False), "sway": (6, 6, False),
}


def _snap(arr, keep):
    """Opaque pixels snapped to the colours in keep (N, 3): brightness changes stay inside the sprite's palette."""
    return lib.quantize(arr, keep)


def flame_frames(src, n=6, seed=5):
    """Torch / brazier / campfire: the warm bright pixels (the fire) cycle through three brightness bands out of phase,
    and the flame's top edge flickers by a pixel per column, so the fire dances while the holder stays still."""
    base = np.array(Image.open(src).convert("RGBA"))
    rgb = base[..., :3].astype(int)
    op = base[..., 3] == 255
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    fire = op & (rgb[..., 0] > 140) & (rgb[..., 0] >= rgb[..., 1]) & (rgb[..., 1] >= rgb[..., 2]) & \
        (rgb[..., 0] - rgb[..., 2] > 60) & (lum > 110)
    if fire.sum() < 6:
        raise core.JobError("flame: no fire colours (bright warm pixels) in the render; reword the prompt to show a lit "
                            "flame, or give the entry another seed")
    keep = np.unique(base[op][:, :3], axis=0)
    ranks = np.zeros(base.shape[:2], int)
    ranks[fire] = np.digitize(lum[fire], np.percentile(lum[fire], [33, 66]))
    rng = np.random.default_rng(seed)
    cols = np.nonzero(fire.any(0))[0]
    tops = {x: np.nonzero(fire[:, x])[0].min() for x in cols}
    jitter = rng.integers(-1, 2, (n, len(cols)))
    out = []
    for f in range(n):
        a = base.copy()
        k = 1 + 0.22 * np.sin(2 * np.pi * (f / n + ranks / 3))
        a[fire, :3] = np.clip(rgb[fire] * k[fire, None], 0, 255).astype(np.uint8)
        hot = rgb[fire][lum[fire].argmax()]
        for j, x in enumerate(cols):
            y = tops[x]
            if jitter[f, j] > 0 and y > 0 and not op[y - 1, x]:     # a tongue licks one pixel higher
                a[y - 1, x, :3], a[y - 1, x, 3] = hot, 255
            elif jitter[f, j] < 0 and fire[y, x] and (y + 1 < a.shape[0] and fire[y + 1, x]):
                a[y, x, 3] = 0                                      # or dips one lower
        out.append(Image.fromarray(_snap(a, keep)))
    return out


def flag_frames(src, n=6, pole="left", amp=1.5):
    """Banner / flag: the cloth waves (columns shift up and down in a travelling sine) and stays pinned at the pole;
    the pole (the 15 % of the width at the pole side) never moves."""
    base = np.array(Image.open(src).convert("RGBA"))
    bb = Image.open(src).getbbox()
    x0, x1 = bb[0], bb[2]
    w = x1 - x0
    pin = x0 + round(w * 0.15) if pole == "left" else x1 - round(w * 0.15)
    out = []
    for f in range(n):
        a = np.zeros_like(base)
        a[:] = base
        for x in range(x0, x1):
            reach = (x - pin) / max(1, x1 - pin) if pole == "left" else (pin - x) / max(1, pin - x0)
            if reach <= 0:
                continue
            dy = int(round(amp * reach * np.sin(2 * np.pi * f / n - reach * 3.0)))
            if dy:
                col = base[:, x].copy()
                a[:, x] = 0
                lo, hi = max(0, dy), min(base.shape[0], base.shape[0] + dy)
                a[lo:hi, x] = col[lo - dy:hi - dy]
        out.append(Image.fromarray(a))
    return out


def smoke_frames(src, n=8, emit=None, pad=28):
    """Chimney / smokestack: grey puffs rise from the top of the sprite (or emit [x, y]), grow, drift and thin out. The
    canvas grows by pad px on top so the smoke has room; the prop's feet stay at the bottom."""
    base = Image.open(src).convert("RGBA")
    can = Image.new("RGBA", (base.width, base.height + pad), (0, 0, 0, 0))
    can.alpha_composite(base, (0, pad))
    a0 = np.array(can)
    if emit:
        ex, ey = int(emit[0]), int(emit[1]) + pad
    else:
        ys, xs = np.nonzero(a0[..., 3] == 255)
        ey = ys.min()
        ex = int(np.median(xs[ys <= ey + 1]))
    greys = [(196, 196, 200), (150, 150, 158), (110, 110, 120)]
    out = []
    for f in range(n):
        a = a0.copy()
        for p in range(3):
            t = ((f / n) + p / 3) % 1.0
            cy, cx = ey - 2 - t * (pad - 4), ex + t * 5
            r = 1 + t * 2.5
            yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
            disc = (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r
            if t > 0.6:   # thinning out: a checker, then gone
                disc &= (yy + xx) % 2 == 0
            col = greys[min(2, int(t * 3))]
            m = disc & (a[..., 3] == 0)
            a[m, :3], a[m, 3] = col, 255
        out.append(Image.fromarray(a))
    return out


def spin_frames(src, n=4, sym=8):
    """Gear / waterwheel / fan rendered on its own: the whole sprite turns by one symmetry step (360 / sym degrees)
    over the loop, so frame n would equal frame 0. Nearest-neighbour, so it stays pixel art (a little jagged at
    large sizes: keep spinners small or use few frames)."""
    base = Image.open(src).convert("RGBA")
    bb = base.getbbox()
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    return [base.rotate(-(360 / sym) * f / n, resample=Image.NEAREST, center=(cx, cy)) for f in range(n)]


def sway_frames(src, n=6, amp=1.5):
    """Plants / lanterns on a hook: rows above the lower 40 % shift sideways in a sine, most at the top."""
    base = np.array(Image.open(src).convert("RGBA"))
    bb = Image.open(src).getbbox()
    top, bot = bb[1], bb[3]
    root = top + round((bot - top) * 0.6)
    out = []
    for f in range(n):
        a = base.copy()
        for y in range(top, root):
            dx = int(round(amp * (root - y) / max(1, root - top) * np.sin(2 * np.pi * f / n)))
            if dx:
                a[y] = np.roll(base[y], dx, axis=0)
        out.append(Image.fromarray(a))
    return out


AMBIENT_FN = {"flame": flame_frames, "flag": flag_frames, "smoke": smoke_frames, "spin": spin_frames,
              "sway": sway_frames}


def _scene(path, frames_res, anim, name, solid, size, bb):
    w, h = size
    x0, y0, x1, y1 = bb
    off = (round(w / 2 - (x0 + x1) / 2), round(h / 2 - y1))
    fw = max(4, round((x1 - x0) * 0.8))
    lines = [f'[gd_scene load_steps={3 if solid else 2} format=3]', "",
             f'[ext_resource type="SpriteFrames" path="{frames_res}" id="1_sf"]', ""]
    if solid:
        lines += ['[sub_resource type="RectangleShape2D" id="RectangleShape2D_1"]', f"size = Vector2({fw}, 12)", ""]
    lines += [f'[node name="{name}" type="{"StaticBody2D" if solid else "Node2D"}"]', "",
              '[node name="Sprite" type="AnimatedSprite2D" parent="."]', "texture_filter = 1",
              'sprite_frames = ExtResource("1_sf")', f'animation = &"{anim}"', f'autoplay = "{anim}"',
              f"offset = Vector2({off[0]}, {off[1]})", ""]
    if solid:
        lines += ['[node name="CollisionShape2D" type="CollisionShape2D" parent="."]', "position = Vector2(0, -6)",
                  'shape = SubResource("RectangleShape2D_1")', ""]
    return godot._write(path, "\n".join(lines))


def run(entries, pack, man, conf):
    root = core.art(conf, "props", "anim")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/props/anim'
    work = os.path.join(core.WORK, "animprops")
    os.makedirs(work, exist_ok=True)
    pal = conf["fixed"]["palette"]
    ref = None
    known = set(EDITS) | {"lever", "glow"} | set(AMBIENT)
    for e in entries:   # spec errors before any render
        if e.get("kind") not in known:
            raise core.ToolError(f"animprops {e.get('name')}: kind {e.get('kind')!r} is not one of {', '.join(sorted(known))}")
    for k, e in enumerate(entries):
        name, kind = core.snake(e["name"]), e["kind"]
        seed = core.seed_of(e, 9500)
        if kind == "door":
            w, h = e.get("cells", [1, 2])
            T = conf["design"]["tile_px"]
            W_, H_ = w * T, h * T
            canvas, fig, tpl, fit = max(W_, H_), max(W_, H_) - 2, FRONT_TPL, (10 ** 4, H_ - 2)
        else:
            size = int(e.get("size", 32))
            canvas = (size + 16 + 7) // 8 * 8
            fig, tpl, fit = size, PROP_TPL, "longest"
        # every state builds on the base render, so one key covers all of them: a new prompt, size or palette
        # re-renders the base and its states (the base used to be cached by name + seed only)
        ck = core.key(core.prompt(tpl, s=e['prompt']), kind, canvas, e.get('cells'), core.palette_key(pal),
                      lib.ref_key(conf))
        stem = os.path.join(work, f"{name}_s{seed}_{ck}")
        base = stem + "_closed.png"
        if not os.path.exists(base):
            core.ensure_comfy()
            ref = ref or lib.ref(conf["design"]["character"].get("style_ref", "cast"))
            o = fit_sprite(core.prompt(tpl, s=e["prompt"]), seed, f"dotwork/animprops/{name}", fig, canvas,
                           baseline=canvas - 2, ref_fn=ref, fit=fit, palette=pal)
            im = Image.open(o["path"]).convert("RGBA")
            if kind == "door":  # bottom-aligned, centred door-sized crop
                x0 = (canvas - W_) // 2
                im = im.crop((x0, canvas - H_, x0 + W_, canvas))
            im.save(base)
        if Image.open(base).getbbox() is None:
            raise core.JobError(f"animprops {name}: the base render came out empty; give the entry another seed")
        states = {}
        if kind in EDITS:
            seq = [base]
            for i, (st, instr) in enumerate(EDITS[kind]):
                ed = edit(base, instr, seed + 1 + i, f"{stem}_{st}", keep_bg=kind == "door")
                if e.get("whole_edit"):
                    seq.append(ed)
                    continue
                merged = f"{stem}_{st}_kept.png"
                dropped = keep_moving(base, ed, kind, merged)
                if dropped > 0.5:
                    core.log(f"animprops {name}: QA {st}: {dropped:.0%} of the edit's changes were outside the "
                             f"{'lid' if kind == 'chest' else 'door panel'} and were dropped; if the state looks "
                             "unchanged, give the entry another seed or whole_edit true")
                seq.append(merged)
            states = {"closed": [seq[0]], "open": seq, "opened": [seq[-1]], "close": seq[::-1]}
            fps, default, solid = 8, "closed", True
        elif kind == "lever":
            on = stem + "_on.png"
            ImageOps.mirror(Image.open(base)).save(on)
            states = {"off": [base], "on": [on], "flip_on": [base, on], "flip_off": [on, base]}
            fps, default, solid = 8, "off", True
        elif kind in AMBIENT:
            n, fps, solid = AMBIENT[kind]
            n, fps = int(e.get("frames", n)), int(e.get("fps", fps))
            solid = bool(e.get("solid", solid))
            kw = {"flag": {"pole": e.get("pole", "left")}, "smoke": {"emit": e.get("emit")},
                  "spin": {"sym": int(e.get("sym", 8))}}.get(kind, {})
            paths = []
            for i, f in enumerate(AMBIENT_FN[kind](base, n=n, **kw)):
                p = f"{stem}_{kind}{i}.png"
                f.save(p)
                paths.append(p)
            states, default = {"idle": paths}, "idle"
            if kind == "smoke":   # the smoke canvas is taller: the base keeps the feet anchor, so use frame 0's box
                base = paths[0]
        else:  # glow
            gl = glow_frames(base)
            paths = []
            for i, f in enumerate(gl):
                p = f"{stem}_glow{i}.png"
                f.save(p)
                paths.append(p)
            states = {"idle": paths}
            fps, default, solid = 8, "idle", False
        out = os.path.join(root, name)
        man.drop_dir(out)
        anims, size_wh, bb = {}, None, None
        for st, paths in states.items():
            files = []
            for i, p in enumerate(paths):
                im = Image.open(p).convert("RGBA")
                size_wh = im.size
                bb = Image.open(base).getbbox()
                fn = f"spr_{name}_{st}_{i:02d}.png"
                dst = core.save_clean(im, os.path.join(out, fn))
                man.add(dst, "frame", animation=st, routes=("klein",), canvas=list(im.size), anchor="feet_bottom_center")
                files.append(fn)
            anims[st] = (files, fps, kind == "glow" or kind in AMBIENT)
        tres = godot.sprite_frames(os.path.join(out, f"{name}_frames.tres"), f"{res}/{name}", anims)
        man.add(tres, "sprite_frames", animations=list(anims), node="AnimatedSprite2D")
        scn = _scene(os.path.join(out, f"{name}.tscn"), f"{res}/{name}/{name}_frames.tres", default,
                     name.title().replace("_", ""), solid, size_wh, bb)
        man.add(scn, "scene", node="StaticBody2D + AnimatedSprite2D" if solid else "Node2D + AnimatedSprite2D",
                animations=list(anims), autoplay=default, origin="feet")
        core.log(f"animprops {name}: {kind}, states {list(anims)}")
