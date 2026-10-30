#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_portraits.py
# Purpose : dialogue portraits: the neutral bust (lane_props.run_portraits) plus expressions made from it by a
#           palette-locked instruction edit (SpriteKiln wf04, klein), so every expression is the same character.
# Usage   : pack spec "portraits": [{"name": "mechanic", "prompt": "a young mechanic with goggles",
#           "expressions": true}]   expressions: true (happy, angry, sad, surprised, hurt), a list of names from
#           EXPRESSIONS, or {"name": "your own wording"}; expression_fix: {"angry": {"seed": 6123}} for another take;
#           face_only (default true): only the face region of the edit is kept, hair / clothes / framing stay
#           pixel-identical to the neutral portrait. talking: true adds the talk and blink frames (only the mouth band
#           and the eye band of their edits are kept) and a SpriteFrames with idle, talk (the mouth flap a dialogue box
#           plays while text prints) and blink, plus portrait_<name>.tscn.
# Notes   : Files: spr_<name>_portrait.png (neutral) and spr_<name>_portrait_<expression>.png, same canvas, so a
#           dialogue box swaps textures without moving. The review sheet shows them side by side.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import os
import shutil

import numpy as np
from PIL import Image

import fcore as core
from lane_props import run_portraits as neutral

import engine as lib  # noqa: E402

EXPRESSIONS = {
    "happy": "a warm open smile with cheerful, slightly narrowed eyes",
    "angry": "an angry glare: eyebrows pulled down and together, teeth gritted",
    "sad": "a sad face: eyebrows raised in the middle, eyes looking down, mouth turned down",
    "surprised": "a surprised face: eyebrows raised high, eyes wide open, mouth open in a small round O",
    "hurt": "a pained wince: eyes squeezed shut, teeth clenched",
    "smirk": "a confident one-sided smirk",
    "worried": "a worried face: eyebrows raised and tilted up in the middle, a small uneasy frown",
    "talk": "the mouth slightly open as if speaking, the eyes unchanged",
    "blink": "the eyes gently closed, the mouth and everything else unchanged",
}
# rows of the bust (share of its height) an edit may change. Measured 2026-10-30 on two test portraits: hair and cap
# churn at 0-0.13 (the edit redraws the silhouette top), brows and eyes at 0.26-0.50, mouth and chin at 0.52-0.80, the
# collar edge at 0.86+. The face box used to run from the top to 0.62, so it kept the hair churn and cut most mouths.
FACE_ROWS = (0.15, 0.82)
REGION_ROWS = {"talk": (0.52, 0.82), "blink": (0.26, 0.50)}   # a talking loop must not flicker anything else
TALK = ["idle", "talk", "talk", "idle", "talk", "idle"]      # an uneven flap reads as speech, a strict 1-2 as a puppet
DEFAULT_SET = ("happy", "angry", "sad", "surprised", "hurt")


def wanted(e):
    """{expression name: wording} for an entry (talking adds talk and blink)."""
    out = _wanted(e)
    if e.get("talking"):
        for k in ("talk", "blink"):
            out.setdefault(k, EXPRESSIONS[k])
    return out


def _wanted(e):
    x = e.get("expressions")
    if not x:
        return {}
    if x is True:
        return {k: EXPRESSIONS[k] for k in DEFAULT_SET}
    if isinstance(x, dict):
        return {core.snake(k): str(v) for k, v in x.items()}
    if isinstance(x, list):
        bad = [k for k in x if k not in EXPRESSIONS]
        if bad:
            raise core.ToolError(f"portrait {e['name']}: unknown expression {bad[0]!r} (known: {', '.join(EXPRESSIONS)};"
                                 " or give {\"name\": \"your own wording\"})")
        return {k: EXPRESSIONS[k] for k in x}
    raise core.ToolError(f"portrait {e['name']}: expressions is true, a list of names or a {{name: wording}} object")


def face_box(im, rows=FACE_ROWS):
    """(x0, y0, x1, y1) of the face in a front-facing bust: the middle 60 % of the figure's width, rows from rows[0] to
    rows[1] of its height (below the hair top, down to the chin: see FACE_ROWS)."""
    bb = im.getbbox() or (0, 0, im.width, im.height)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    return (bb[0] + round(w * 0.2), bb[1] + round(h * rows[0]), bb[0] + round(w * 0.8), bb[1] + round(h * rows[1]))


def keep_face(base, edit, rows=FACE_ROWS):
    """The edit inside face_box(base), the neutral portrait everywhere else; (image, share of the edit's changes that
    fell outside the box), the second a QA hint that the edit moved more than the face."""
    a, b = np.array(base.convert("RGBA")), np.array(edit.convert("RGBA").resize(base.size, Image.NEAREST))
    x0, y0, x1, y1 = face_box(base, rows)
    box = np.zeros(a.shape[:2], bool)
    box[y0:y1, x0:x1] = True
    changed = (a != b).any(-1) & ((a[..., 3] > 0) | (b[..., 3] > 0))   # visible pixels only (hidden RGB varies)
    outside = float((changed & ~box).sum() / max(1, changed.sum()))
    out = a.copy()
    out[box] = b[box]
    return Image.fromarray(out), outside


def edit(src, instr, seed, tag):
    """One wf04 edit of src (palette locked to src's own colours); returns the locked output path."""
    from lane_character import COMFY_WORK, _wf
    fn = lib.put(Image.open(src), f"dotwork_portrait_{tag.replace('/', '_')}.png")
    g = _wf("04_edit_pixel_art")
    shutil.rmtree(os.path.join(COMFY_WORK, *tag.split("/")), ignore_errors=True)
    g["31"]["inputs"].update(filename_prefix=f"dotwork_work/{tag}/free", upscale=1, as_animation=False)
    g["32"]["inputs"].update(filename_prefix=f"dotwork_work/{tag}/locked", upscale=1, as_animation=False)
    g["2"]["inputs"]["image"] = fn
    g["5"]["inputs"]["image"] = fn
    g["19"]["inputs"]["noise_seed"] = int(seed)
    g["13"]["inputs"]["text"] = (f"Edit the pixel art portrait in image 1: change only the facial expression to {instr}. "
                                 "Keep the same character, the same hair, clothes, colors, framing and pixel art "
                                 "style.")
    r = lib.run_job(g, timeout=1200)
    outs = lib.job_files(r, "locked*.png")
    if not outs:
        raise core.JobError(f"portrait expression {tag}: the edit saved nothing")
    return outs[0], r["seconds"]


def expressions(e, man, conf):
    from lane_tools import _settle
    name = core.snake(e["name"])
    want = wanted(e)
    if not want:
        return []
    base_p = core.art(conf, "portraits", f"spr_{name}_portrait.png")
    base = Image.open(base_p).convert("RGBA")
    work = core.work("portraits", name)
    fix = e.get("expression_fix") or {}
    face_only = e.get("face_only", True)
    made = []
    for ex, instr in want.items():
        seed = int((fix.get(ex) or {}).get("seed", core.seed_of(e, 6000) + 101))
        key = core.key(instr, seed, core.sha256_file(base_p)[:12], core.palette_key(conf["fixed"]["palette"]))
        cache = os.path.join(work, f"{ex}_{key}.png")
        if not os.path.exists(cache):
            core.ensure_comfy()
            out, sec = edit(base_p, instr, seed, f"portraits/{name}/{ex}")
            _settle(out, base, conf).save(cache)
            core.log(f"portrait {name}: {ex} {sec:.0f}s (seed {seed})")
        im = Image.open(cache).convert("RGBA")
        qa = []
        if face_only or ex in REGION_ROWS:   # the talk / blink frames always stay in their band
            im, outside = keep_face(base, im, REGION_ROWS.get(ex, FACE_ROWS))
            # a talk / blink band keeps a sliver of the edit by design: only say so when almost nothing landed in it
            if outside > (0.97 if ex in REGION_ROWS else 0.5):
                qa.append(f"{outside:.0%} of the edit's changes fell outside the face and were dropped: if the "
                          "expression looks unchanged, try face_only false or another seed")
        dst = core.save_clean(im, core.art(conf, "portraits", f"spr_{name}_portrait_{ex}.png"))
        man.add(dst, "portrait", expression=ex, prompt=instr, seed=seed, face_only=bool(face_only), qa=qa,
                routes=("klein",), workflow="SpriteKiln wf04 (klein edit of the neutral portrait, palette locked)",
                source=f"spr_{name}_portrait.png")
        made.append(dst)
        if qa:
            core.log(f"portrait {name}: QA {ex}: {qa[0]}")
    lib.sheet([(name, [base_p] + made)], core.src(conf, "art", "portraits", f"{name}_expressions_review.png"), scale=3)
    if e.get("talking"):
        talking(name, man, conf)
    with open(os.path.join(work, "expressions.json"), "w", encoding="utf-8") as f:
        json.dump(sorted(want), f)
    return made


def talking(name, man, conf):
    """SpriteFrames for a dialogue box: idle (the neutral bust), talk (the mouth flap, looping while text prints) and
    blink (once, every few seconds), all on the neutral canvas; a scene that idles; a sheet + JSON for other engines."""
    art = core.art(conf, "portraits")
    res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/portraits'
    f = {"idle": f"spr_{name}_portrait.png", "talk": f"spr_{name}_portrait_talk.png",
         "blink": f"spr_{name}_portrait_blink.png"}
    anims = {"idle": ([f["idle"]], 1, True), "talk": ([f[k] for k in TALK], 10, True),
             "blink": ([f["idle"], f["blink"], f["idle"]], 10, False)}
    import godot
    tres = godot.sprite_frames(os.path.join(art, f"portrait_{name}_frames.tres"), res, anims)
    man.add(tres, "sprite_frames", animations=sorted(anims), note="play talk while text prints; blink now and then")
    scn = godot._write(os.path.join(art, f"portrait_{name}.tscn"), "\n".join([
        "[gd_scene load_steps=2 format=3]", "",
        f'[ext_resource type="SpriteFrames" path="{res}/portrait_{name}_frames.tres" id="1_sf"]', "",
        f'[node name="Portrait{name.title().replace("_", "")}" type="AnimatedSprite2D"]', "texture_filter = 1",
        'sprite_frames = ExtResource("1_sf")', 'animation = &"idle"', 'autoplay = "idle"', ""]))
    man.add(scn, "scene", node="AnimatedSprite2D (idle / talk / blink)")
    ims = {k: Image.open(os.path.join(art, v)).convert("RGBA") for k, v in f.items()}
    w, h = ims["idle"].size
    seq = TALK + ["idle", "blink", "idle"]
    sheet = Image.new("RGBA", (w * len(seq), h), (0, 0, 0, 0))
    for i, k in enumerate(seq):
        sheet.alpha_composite(ims[k], (i * w, 0))
    sp = core.save_clean(sheet, os.path.join(art, f"portrait_{name}_talk_sheet.png"))
    core.write_text(sp[:-4] + ".json", json.dumps({"frame_w": w, "frame_h": h, "talk": list(range(len(TALK))),
                                                   "blink": [len(TALK), len(TALK) + 1, len(TALK) + 2],
                                                   "talk_fps": 10, "blink_fps": 10}, indent=1) + "\n")
    man.add(sp, "sheet", animations=["talk", "blink"], workflow="Dotwork talking portrait (frames from the expressions)")
    man.add(sp[:-4] + ".json", "sheet_data")
    core.log(f"portrait {name}: talking frames (talk {len(TALK)} frames at 10 fps, blink)")


def run(entries, pack, man, conf):
    for e in entries:
        wanted(e)   # a typo'd expression stops the run before any render
    neutral(entries, pack, man, conf)
    for e in entries:
        expressions(e, man, conf)
