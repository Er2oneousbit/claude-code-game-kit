#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_props.py
# Purpose : single sprites: props (with a y-sortable collision scene each), icons at 16 and 32 px, portraits. The
#           sprite lane: klein + optional style reference, refine on an exact 8 px grid, palette lock, colour cap,
#           outline.
# Usage   : pack spec "props": [{"name": "gas_lamp", "prompt": "a cast iron gas street lamp", "size": 56,
#           "footprint": "trunk"}], "icons": [...], "portraits": [...]
# Notes   : size = longest side; template iso; palette env; solid false; footprint base | trunk | [w, h];
#           holes true clears white background trapped inside open shapes (frames, rings; off by default:
#           flat white glass looks the same), and pockets that might be trapped background are named in the log and
#           the manifest QA either way; slab "remove" strips a light-grey ground slab under the prop (qa.deslab:
#           opt-in for props, because an iso plinth looks like one). A changed prompt / seed / size / palette
#           re-renders that entry.
#           fit_sprite() re-renders smaller when the refine pass grows a figure past its canvas (never rescales pixels).
#           Icons: only the largest size is rendered; smaller ones are derived from it (derive_small: same design,
#           1 px margin, fresh outline), because a separate 14 px render came back as a blob for 5 of 39 icons and
#           a crashed run left sizes missing (2026-10-30 art audit D10). "small": "render" renders each size instead.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot
import qa

import engine as lib  # noqa: E402

PROP_TPL = ("pixel art sprite, top-down {genre} game asset, single object: {s}, seen from a high three-quarter top-down "
            "angle, centered, drawn in the exact pixel art style, palette, outline and shading of image 1, "
            "{setting}, crisp dark outline")
ICON_TPL = ("pixel art sprite, pixel art item icon of {s}, single object, centered, bold simple shape, dark outline, "
            "inventory icon, drawn in the exact pixel art style, palette, outline and shading of image 1, {setting}")
ISO_TPL = ("pixel art sprite, isometric pixel art game asset, 2:1 isometric projection, single {s}, centered, drawn "
           "in the exact pixel art style, palette, outline and shading of image 1, {setting}, crisp dark outline")
PORT_TPL = ("pixel art sprite, pixel art {genre} dialogue portrait, close-up bust of {s}, head and shoulders only, "
            "front facing, expressive face, drawn in the exact pixel art style, palette and shading of image 1, "
            "{setting}")


def fit_sprite(prompt, seed, tag, fig, canvas, tries=3, **kw):
    """lib.sprite, but the result must fit its canvas: the refine pass can grow a figure past the size it was drawn
    at (a 32 px icon came back 59x62, 2026-10-29) and the canvas step then leaves it uncropped. Retry the same seed
    at a proportionally smaller figure size instead of rescaling pixels."""
    for _ in range(tries):
        o = lib.sprite(prompt, seed, tag, fig=fig, canvas=canvas, **kw)
        w, h = Image.open(o["path"]).size
        if w <= canvas and h <= canvas:
            return o
        fig = max(4, int(fig * canvas / max(w, h) * 0.92))
        core.log(f"[!] {tag}: {w}x{h} > canvas {canvas}, retry at fig {fig}")
    raise core.JobError(f"{tag}: still larger than its {canvas} px canvas after {tries} tries")


def _ref_once(conf, box):
    """Start ComfyUI and upload the style reference the first time a render needs them, so a re-run with every
    entry up to date starts nothing (it used to start ComfyUI, about 20 s, before checking a single entry)."""
    if "ref" not in box:
        core.ensure_comfy()
        box["ref"] = lib.ref(conf["design"]["character"].get("style_ref", "cast"))
    return box["ref"]


def _ship(man, tmp_path, dst, kind, prompt, seed, size, anchor, request=None, notes=None):
    im = Image.open(tmp_path).convert("RGBA")
    core.save_clean(im, dst)
    bb = im.getbbox() or (0, 0, im.width, im.height)
    man.add(dst, kind, prompt=prompt, seed=seed, workflow="Dotwork sprite lane (klein refine loop)",
            routes=("klein",), size=[im.width, im.height], content_bbox=list(bb), anchor=anchor, request=request,
            qa=notes or None)


def _art(pack, conf, *parts):
    return core.art(conf, *parts)


def run_props(entries, pack, man, conf):
    box = {}   # ComfyUI and the style reference, set up by the first render (_ref_once)
    p = conf["design"]["prop"]
    for k, e in enumerate(entries):
        name, seed = core.snake(e["name"]), core.seed_of(e, 4000)
        dst = _art(pack, conf, "props", f"spr_{name}.png")
        prompt = core.prompt(ISO_TPL if e.get("template") == "iso" else PROP_TPL, s=e["prompt"])
        # terrain-like props (grass blocks, water tiles) need the environment palette: the character palette has
        # almost no greens and turned an iso grass block tan (2026-10-29)
        pal = conf["fixed"]["env_palette"] if e.get("palette") == "env" else conf["fixed"]["palette"]
        # size: longest side for big props (trees, fountains, stalls); canvas = size + room, on the 8 px grid
        fig = int(e.get("size", p["longest_side"]))
        canvas = max(p["canvas"], (fig + 16 + 7) // 8 * 8)
        req = core.key(prompt, seed, fig, canvas, core.palette_key(pal), bool(e.get("holes")), lib.ref_key(conf),
                       e.get("slab") == "remove")
        if man.current(dst, req):
            continue
        o = fit_sprite(prompt, seed, f"dotwork/props/{name}", fig, canvas, baseline=canvas - 2, ref_fn=_ref_once(conf, box),
                       fit="longest", palette=pal)
        if e.get("holes"):
            # opt-in: background trapped inside open shapes (a beam frame, a ring). Not the default: flat white
            # lamp glass and porcelain look exactly like trapped background
            im, removed, note = qa.white_pockets(Image.open(o["path"]), force=True)
            im.save(o["path"])
            if note:
                core.log(f"prop {name}: {note}")
        if e.get("slab") == "remove":
            im, _, note = qa.deslab(Image.open(o["path"]))
            im.save(o["path"])
            if note:
                core.log(f"prop {name}: {note}")
        flags = [] if e.get("holes") else [
            f"white pocket {w}x{h} at {x},{y} ({n} px): trapped background? set holes true to clear it (leave it if "
            "it is glass, paper or a dial)" for x, y, w, h, n in qa.pocket_report(Image.open(o["path"]))]
        for f in flags:
            core.log(f"prop {name}: QA {f}")
        _ship(man, o["path"], dst, "prop", prompt, seed, [canvas] * 2, "bottom_center", request=req, notes=flags)
        core.log(f"prop {name}: {o['seconds']}s")


def prop_scenes(entries, pack, man, conf):
    """A y-sortable Godot scene per prop (StaticBody2D footprint unless "solid": false; "footprint": base / trunk /
    [w, h]). Origin = the prop's feet, so a Node2D with y_sort_enabled layers characters correctly."""
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/props'
    for e in entries:
        if e.get("scene") is False:
            continue
        name = core.snake(e["name"])
        png = _art(pack, conf, "props", f"spr_{name}.png")
        if not os.path.exists(png):
            continue
        im = Image.open(png)
        bb = im.getbbox() or (0, 0, im.width, im.height)
        scn, fp = godot.prop_scene(_art(pack, conf, "props", f"prop_{name}.tscn"), f"{res}/spr_{name}.png",
                                   im.size, bb, node_name=name.title().replace("_", ""),
                                   solid=e.get("solid", True), footprint=e.get("footprint", "base"))
        man.add(scn, "scene", node="StaticBody2D" if e.get("solid", True) else "Node2D", origin="feet",
                footprint=list(fp) if e.get("solid", True) else None, y_sort="parent Node2D y_sort_enabled")


OUTLINE = lib.hexrgb("#050407")   # engine.finish's outline colour


def derive_small(im, px, margin=1):
    """A px-size icon from a bigger one, same design: the big icon's interior (its outline peeled off) is reduced
    to px - 2 * margin - 2 pixels by majority colour per footprint, then a fresh 1 px outline goes around it, so the
    result keeps a `margin` px gap to the canvas edge on every side."""
    a = np.array(im.convert("RGBA"))
    op = a[..., 3] == 255
    interior = op & lib.erode(op)
    ys, xs = np.nonzero(interior)
    if not len(ys):
        raise core.JobError(f"icon: nothing inside the outline to reduce to {px} px")
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    interior = interior[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    ih, iw = interior.shape
    s = (px - 2 * margin - 2) / max(ih, iw)
    th, tw = max(1, round(ih * s)), max(1, round(iw * s))
    res = np.zeros((th, tw, 4), np.uint8)
    for j in range(th):
        y0 = int(j / s)
        y1 = max(y0 + 1, int(round((j + 1) / s)))
        for i in range(tw):
            x0 = int(i / s)
            x1 = max(x0 + 1, int(round((i + 1) / s)))
            m = interior[y0:y1, x0:x1]
            if m.mean() < 0.4:   # mostly outside the figure in the big icon
                continue
            v, c = np.unique(a[y0:y1, x0:x1][m][:, :3], axis=0, return_counts=True)
            res[j, i, :3] = v[c.argmax()]
            res[j, i, 3] = 255
    can = np.zeros((px, px, 4), np.uint8)
    oy, ox = (px - th) // 2, (px - tw) // 2
    can[oy:oy + th, ox:ox + tw] = res
    op = can[..., 3] == 255
    ring = lib.dilate(op) & ~op
    can[ring, :3] = OUTLINE
    can[ring, 3] = 255
    return Image.fromarray(can)


def run_icons(entries, pack, man, conf):
    box = {}   # ComfyUI and the style reference, set up by the first render (_ref_once)
    sizes = sorted({int(x) for x in conf["design"]["icon_sizes"]}, reverse=True)
    for k, e in enumerate(entries):
        name = core.snake(e["name"])
        seed = core.seed_of(e, 5000)
        prompt = core.prompt(ICON_TPL, s=e["prompt"])
        render = sizes if e.get("small", "derive") == "render" else sizes[:1]
        for px in sizes:
            dst = _art(pack, conf, "ui", "icons", f"ui_icon_{name}_{px}.png")
            if px in render:
                req = core.key(prompt, seed, px, lib.ref_key(conf))
                if man.current(dst, req):
                    continue
                # icons keep the 8 px grid sample's colours (max_colors only acts with a palette lock); 1 px outline
                o = fit_sprite(prompt, seed, f"dotwork/icons/{name}_{px}", px - 2 if px <= 16 else px - 4, px,
                               baseline=px - 1, ref_fn=_ref_once(conf, box), fit="longest", max_colors=12 if px <= 16 else 24)
                _ship(man, o["path"], dst, "icon", prompt, seed, [px, px], "center", request=req)
                core.log(f"icon {name} {px}px: {o['seconds']}s")
            else:   # derived from the largest size: same design, cheap, so always rebuilt
                big = _art(pack, conf, "ui", "icons", f"ui_icon_{name}_{sizes[0]}.png")
                im = derive_small(Image.open(big), px)
                core.save_clean(im, dst)
                man.add(dst, "icon", prompt=prompt, seed=seed, routes=("klein",), size=[px, px],
                        content_bbox=list(im.getbbox()), anchor="center", derived_from=os.path.basename(big),
                        workflow="Dotwork icon reduce (derive_small, drawn in code from the largest size)")
                core.log(f"icon {name} {px}px: derived from {sizes[0]}px")
        missing = [px for px in sizes if not os.path.exists(_art(pack, conf, "ui", "icons", f"ui_icon_{name}_{px}.png"))]
        if missing:   # every icon ships in every size, or the run says so (D10: a crashed run left half sets)
            raise core.JobError(f"icon {name}: no {', '.join(map(str, missing))} px file after the run")


def run_portraits(entries, pack, man, conf):
    box = {}   # ComfyUI and the style reference, set up by the first render (_ref_once)
    size = conf["design"]["portrait"]
    for k, e in enumerate(entries):
        name, seed = core.snake(e["name"]), core.seed_of(e, 6000)
        dst = _art(pack, conf, "portraits", f"spr_{name}_portrait.png")
        prompt = core.prompt(PORT_TPL, s=e["prompt"])
        req = core.key(prompt, seed, size, lib.ref_key(conf))
        if man.current(dst, req):
            continue
        o = fit_sprite(prompt, seed, f"dotwork/portraits/{name}", size, size, baseline=size, ref_fn=_ref_once(conf, box),
                       fit="longest")
        _ship(man, o["path"], dst, "portrait", prompt, seed, [size, size], "bottom_center", request=req)
        core.log(f"portrait {name}: {o['seconds']}s")


def run(entries, pack, man, conf):  # dotwork.py pack calls lane_props.run for "props"
    run_props(entries, pack, man, conf)
    prop_scenes(entries, pack, man, conf)
