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
#           flat white glass looks the same). A changed prompt / seed / size / palette re-renders that entry.
#           fit_sprite() re-renders smaller when the refine pass grows a figure past its canvas (never rescales pixels).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

from PIL import Image

import fcore as core
import godot
import qa

import engine as lib  # noqa: E402

PROP_TPL = ("pixel art sprite, top-down RPG game asset, single object: {s}, seen from a high three-quarter top-down "
            "angle, centered, drawn in the exact pixel art style, palette, outline and shading of image 1, "
            "steampunk, crisp dark outline")
ICON_TPL = ("pixel art sprite, pixel art item icon of {s}, single object, centered, bold simple shape, dark outline, "
            "inventory icon, drawn in the exact pixel art style, palette, outline and shading of image 1, steampunk")
ISO_TPL = ("pixel art sprite, isometric pixel art game asset, 2:1 isometric projection, single {s}, centered, drawn "
           "in the exact pixel art style, palette, outline and shading of image 1, steampunk, crisp dark outline")
PORT_TPL = ("pixel art sprite, pixel art RPG dialogue portrait, close-up bust of {s}, head and shoulders only, "
            "front facing, expressive face, drawn in the exact pixel art style, palette and shading of image 1, "
            "steampunk")


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


def _ship(man, tmp_path, dst, kind, prompt, seed, size, anchor, request=None):
    im = Image.open(tmp_path).convert("RGBA")
    core.save_clean(im, dst)
    bb = im.getbbox() or (0, 0, im.width, im.height)
    man.add(dst, kind, prompt=prompt, seed=seed, workflow="Dotwork sprite lane (klein refine loop)",
            routes=("klein",), size=[im.width, im.height], content_bbox=list(bb), anchor=anchor, request=request)


def _art(pack, conf, *parts):
    return core.art(conf, *parts)


def run_props(entries, pack, man, conf):
    core.ensure_comfy()
    ref = lib.ref(conf["design"]["character"].get("style_ref", "cast"))
    p = conf["design"]["prop"]
    for k, e in enumerate(entries):
        name, seed = core.snake(e["name"]), core.seed_of(e, 4000)
        dst = _art(pack, conf, "props", f"spr_{name}.png")
        prompt = (ISO_TPL if e.get("template") == "iso" else PROP_TPL).format(s=e["prompt"])
        # terrain-like props (grass blocks, water tiles) need the environment palette: the character palette has
        # almost no greens and turned an iso grass block tan (2026-10-29)
        pal = conf["fixed"]["env_palette"] if e.get("palette") == "env" else conf["fixed"]["palette"]
        # size: longest side for big props (trees, fountains, stalls); canvas = size + room, on the 8 px grid
        fig = int(e.get("size", p["longest_side"]))
        canvas = max(p["canvas"], (fig + 16 + 7) // 8 * 8)
        req = core.key(prompt, seed, fig, canvas, core.palette_key(pal), bool(e.get("holes")), lib.ref_key(conf))
        if man.current(dst, req):
            continue
        o = fit_sprite(prompt, seed, f"dotwork/props/{name}", fig, canvas, baseline=canvas - 2, ref_fn=ref,
                       fit="longest", palette=pal)
        if e.get("holes"):
            # opt-in: background trapped inside open shapes (a beam frame, a ring). Not the default: flat white
            # lamp glass and porcelain look exactly like trapped background
            im, removed, note = qa.white_pockets(Image.open(o["path"]), force=True)
            im.save(o["path"])
            if note:
                core.log(f"prop {name}: {note}")
        _ship(man, o["path"], dst, "prop", prompt, seed, [canvas] * 2, "bottom_center", request=req)
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


def run_icons(entries, pack, man, conf):
    core.ensure_comfy()
    ref = lib.ref(conf["design"]["character"].get("style_ref", "cast"))
    for k, e in enumerate(entries):
        name = core.snake(e["name"])
        for px in conf["design"]["icon_sizes"]:
            seed = core.seed_of(e, 5000)
            dst = _art(pack, conf, "ui", "icons", f"ui_icon_{name}_{px}.png")
            prompt = ICON_TPL.format(s=e["prompt"])
            req = core.key(prompt, seed, px, lib.ref_key(conf))
            if man.current(dst, req):
                continue
            # icons keep the 8 px grid sample's colours (max_colors only acts with a palette lock); 1 px outline
            o = fit_sprite(prompt, seed, f"dotwork/icons/{name}_{px}", px - 2 if px <= 16 else px - 4, px,
                           baseline=px - 1, ref_fn=ref, fit="longest", max_colors=12 if px <= 16 else 24)
            _ship(man, o["path"], dst, "icon", prompt, seed, [px, px], "center", request=req)
            core.log(f"icon {name} {px}px: {o['seconds']}s")


def run_portraits(entries, pack, man, conf):
    core.ensure_comfy()
    ref = lib.ref(conf["design"]["character"].get("style_ref", "cast"))
    size = conf["design"]["portrait"]
    for k, e in enumerate(entries):
        name, seed = core.snake(e["name"]), core.seed_of(e, 6000)
        dst = _art(pack, conf, "portraits", f"spr_{name}_portrait.png")
        prompt = PORT_TPL.format(s=e["prompt"])
        req = core.key(prompt, seed, size, lib.ref_key(conf))
        if man.current(dst, req):
            continue
        o = fit_sprite(prompt, seed, f"dotwork/portraits/{name}", size, size, baseline=size, ref_fn=ref,
                       fit="longest")
        _ship(man, o["path"], dst, "portrait", prompt, seed, [size, size], "bottom_center", request=req)
        core.log(f"portrait {name}: {o['seconds']}s")


def run(entries, pack, man, conf):  # dotwork.py pack calls lane_props.run for "props"
    run_props(entries, pack, man, conf)
    prop_scenes(entries, pack, man, conf)
