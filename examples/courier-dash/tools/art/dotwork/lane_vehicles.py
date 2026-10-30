#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_vehicles.py
# Purpose : overworld vehicles with 8 facing directions (Qwen multi-angle, directions 8) and a code-drawn ground
#           shadow; a scene with the hull raised by an altitude.
# Usage   : pack spec "vehicles": [{"name": "airship", "prompt": "a steampunk airship", "size": 72, "altitude": 24}]
# Notes   : The rotation model treats the view it is given as the front and turns from there, so the three-quarter
#           source (facing sw) came back with every view one step round (2026-10-30). A straight front view is worse:
#           the model reads it as a flat cutout (paper-thin sides, the front again as the back). So the source stays
#           three-quarter, all 8 views are generated, and "source_facing": "auto" (default) picks the labelling whose
#           views mirror each other the way a real turn does. "sw" / "se" / "s" ... sets it; rot_order overrides.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os
import shutil

import numpy as np
from PIL import Image

import fcore as core
import godot
from lane_character import COMFY_WORK, _saves, _wf
from lane_props import fit_sprite

import engine as lib  # noqa: E402

TPL = ("pixel art sprite, top-down {genre} overworld vehicle: {s}, seen from a high three-quarter top-down angle, its front "
       "turned toward the lower left, centered, drawn in the exact pixel art style, palette, outline and shading of "
       "image 1, crisp dark outline")
ROT8 = ["s", "sw", "w", "nw", "n", "ne", "e", "se"]   # what the 8 outputs face for a front-view source (screen-clockwise)
AUTO_FACINGS = ("sw", "s", "se")   # the source is drawn facing the viewer; which of these the mirror test decides
PAIRS = (("e", "w"), ("ne", "nw"), ("se", "sw"))   # views that mirror each other in a correct turn


def rotation_plan(e):
    """(labels for the rotation's 8 outputs or None for auto, mirror_west, cache-key extra) for a vehicle entry.

    The rotation model treats the view it is given as the front and turns from there, so a source facing sw shifts
    the ring by one: output k faces ROT8[(k + 1) % 8]. Mirroring the east half onto the west only holds for a source
    facing s or n (the mirror axis is then the screen's vertical); any other facing generates all 8 views."""
    src = str(e.get("source_facing", "auto")).lower()
    if src not in ROT8 and src != "auto":
        raise core.ToolError(f"vehicle {e.get('name')}: source_facing {src!r} is auto or one of {', '.join(ROT8)}")
    asym = bool(e.get("asymmetric", False))
    if e.get("rot_order"):   # manual override: the user read the review sheet and listed what each output faces
        order = [str(d).lower() for d in e["rot_order"]]
        if sorted(order) != sorted(ROT8):
            raise core.ToolError(f"vehicle {e.get('name')}: rot_order must list each of {', '.join(ROT8)} once")
        # the order is in the cache key (a corrected order used to reuse the old labels), and mirroring holds
        # only when the first output (the source) faces s or n, as for source_facing (2026-10-30 Kimi audit)
        return order, not asym and order[0] in ("s", "n"), (asym, "order", *order)
    if src == "auto":   # all 8 generated; labels come from pick_facing() once the views exist
        return None, False, (asym, "auto8")
    return ring(src), not asym and src in ("s", "n"), (asym, src)


def ring(src):
    """Labels of the rotation's 8 outputs for a source facing src."""
    i = ROT8.index(src)
    return [ROT8[(k + i) % 8] for k in range(8)]


def _mask(im):
    """Content silhouette, cropped, as a bool array."""
    a = np.asarray(im.convert("RGBA"))[..., 3] >= 128
    ys, xs = np.nonzero(a)
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(ys) else a


def mirror_fit(a, b):
    """IoU of silhouette a and silhouette b mirrored, bottom-centre aligned (1.0 = exact mirror images)."""
    ma, mb = _mask(a), _mask(b)[:, ::-1]
    H, W = max(ma.shape[0], mb.shape[0]), max(ma.shape[1], mb.shape[1])
    pa, pb = np.zeros((H, W), bool), np.zeros((H, W), bool)
    for m, p in ((ma, pa), (mb, pb)):
        x = (W - m.shape[1]) // 2
        p[H - m.shape[0]:, x:x + m.shape[1]] = m
    u = (pa | pb).sum()
    return float((pa & pb).sum() / u) if u else 0.0


def pick_facing(views):
    """(source facing, {facing: score}) for 8 generated views in output order. A correct labelling makes e/w, ne/nw
    and se/sw mirror pairs and s, n each symmetric; a labelling one step off pairs views a quarter-turn apart."""
    scores = {}
    for f in AUTO_FACINGS:
        lab = dict(zip(ring(f), views))
        fits = [mirror_fit(lab[x], lab[y]) for x, y in PAIRS] + [mirror_fit(lab[d], lab[d]) for d in ("s", "n")]
        scores[f] = round(float(np.mean(fits)), 3)
    return max(scores, key=scores.get), scores


def shadow(width, height):
    """Dithered dark ellipse (alpha via a checker so it stays pixel art over any ground)."""
    w, h = max(8, width), max(4, height)
    yy, xx = np.mgrid[0:h, 0:w]
    inside = ((xx - (w - 1) / 2) / (w / 2)) ** 2 + ((yy - (h - 1) / 2) / (h / 2)) ** 2 <= 1
    core_ = ((xx - (w - 1) / 2) / (w / 2.6)) ** 2 + ((yy - (h - 1) / 2) / (h / 2.6)) ** 2 <= 1
    a = np.where(core_, 120, np.where(inside & ((xx + yy) % 2 == 0), 120, 0)).astype(np.uint8)
    return np.dstack([np.full((h, w, 3), 12, np.uint8), a])


def run(entries, pack, man, conf):
    root = core.art(conf, "vehicles")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/vehicles'
    for k, e in enumerate(entries):
        name = core.snake(e["name"])
        seed = core.seed_of(e, 9600)
        size = int(e.get("size", 72))
        canvas = (size + 16 + 7) // 8 * 8
        work = os.path.join(core.WORK, "vehicles", name)
        os.makedirs(work, exist_ok=True)
        tag = core.key(e["prompt"], seed, size, core.palette_key(conf["fixed"]["palette"]), lib.ref_key(conf), core.prompt(TPL, s=e["prompt"]))
        south = os.path.join(work, f"south_{tag}.png")
        if not os.path.exists(south):
            core.ensure_comfy()
            ref = lib.ref(conf["design"]["character"].get("style_ref", "cast"))
            o = fit_sprite(core.prompt(TPL, s=e["prompt"]), seed, f"dotwork/vehicles/{name}", size, canvas,
                           baseline=canvas - 2, ref_fn=ref, fit="longest", palette=conf["fixed"]["palette"])
            shutil.copyfile(o["path"], south)
        order, mirror, extra = rotation_plan(e)
        rtag = core.key(tag, *extra)
        have = {d: os.path.join(work, f"{d}_{rtag}.png") for d in ROT8}
        if not all(os.path.exists(p) for p in have.values()):
            core.ensure_comfy()
            core.require_ram()   # Qwen-Image-Edit + its 7B text encoder load next
            fn = f"dotwork_vehicle_{name}.png"
            fn = lib.put(Image.open(south), fn)
            g = _saves(_wf("07_rotate_hq_qwen_multiangle"), f"dotwork_work/vehicles/{name}/r")
            shutil.rmtree(os.path.join(COMFY_WORK, "vehicles", name), ignore_errors=True)
            g["2"]["inputs"]["image"] = fn
            g["5"]["inputs"].update(directions="8", mirror_west=mirror)
            r = lib.run_job(g, timeout=3600)
            files = lib.job_files(r, "r_*.png")   # this job's outputs only (lane_character's rule)
            if len(files) < 8:
                raise core.JobError(f"vehicle {name}: rotation returned {len(files)} images, expected 8")
            if order is None:   # auto: label the views by the mirror test
                facing, scores = pick_facing([Image.open(p) for p in files[:8]])
                order = ring(facing)
                close = sorted(scores.values())[-2:]
                core.log(f"vehicle {name}: source faces {facing} (mirror fit {scores})"
                         + ("; close call: check the review sheet, set source_facing" if close[1] - close[0] < 0.03
                            else ""))
            for d, f in zip(order, files):
                shutil.copyfile(f, have[d])
            core.free_models()
            core.log(f"vehicle {name}: 8-way rotation {r['seconds']:.0f}s (outputs face {' '.join(order)}, "
                     f"mirror_west={mirror})")
        out = os.path.join(root, name)
        man.drop_dir(out)
        ims = {d: Image.open(p).convert("RGBA") for d, p in have.items()}
        W = max(i.width for i in ims.values())
        H = max(i.height for i in ims.values())
        anims, widths = {}, []
        for d, im in ims.items():
            bb = im.getbbox()
            c = im.crop(bb)
            widths.append(c.width)
            can = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            can.alpha_composite(c, ((W - c.width) // 2, H - c.height))
            fn = f"spr_{name}_{d}.png"
            dst = core.save_clean(can, os.path.join(out, fn))
            man.add(dst, "frame", animation=f"idle_{d}", canvas=[W, H], anchor="hull_bottom_center",
                    routes=("klein", "qwen_rotate"))
            anims[f"idle_{d}"] = ([fn], 1, False)
        sw = int(np.median(widths) * 0.8)
        sp = core.save_clean(Image.fromarray(shadow(sw, max(4, sw // 3))), os.path.join(out, f"spr_{name}_shadow.png"))
        man.add(sp, "shadow", routes=(), workflow="Dotwork vehicle shadow (drawn in code)")
        tres = godot.sprite_frames(os.path.join(out, f"{name}_frames.tres"), f"{res}/{name}", anims)
        man.add(tres, "sprite_frames", animations=sorted(anims), canvas=[W, H])
        alt = int(e.get("altitude", 24))
        scn = godot._write(os.path.join(out, f"{name}.tscn"), "\n".join([
            '[gd_scene load_steps=3 format=3]', "",
            f'[ext_resource type="SpriteFrames" path="{res}/{name}/{name}_frames.tres" id="1_sf"]',
            f'[ext_resource type="Texture2D" path="{res}/{name}/spr_{name}_shadow.png" id="2_sh"]', "",
            f'[node name="{name.title().replace("_", "")}" type="Node2D"]', "",
            '[node name="Shadow" type="Sprite2D" parent="."]', "texture_filter = 1", 'texture = ExtResource("2_sh")', "",
            '[node name="Hull" type="AnimatedSprite2D" parent="."]', "texture_filter = 1",
            'sprite_frames = ExtResource("1_sf")', 'animation = &"idle_s"',
            f"offset = Vector2(0, {-(H // 2) - alt})", ""]))
        man.add(scn, "scene", node="Node2D (Shadow + Hull)", altitude=alt, directions=ROT8)
        # the sheet always runs s, sw, w ... screen-clockwise, so a wrong view shows as a break in the turn
        lib.sheet([("dirs " + " ".join(ROT8), [os.path.join(out, f"spr_{name}_{d}.png") for d in ROT8])],
                  core.src(conf, "art", "vehicles", f"{name}_review.png"), scale=2)
        core.log(f"vehicle {name}: 8 directions + shadow, canvas {W}x{H}")
