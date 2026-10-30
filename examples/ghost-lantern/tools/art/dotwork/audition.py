#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# audition.py
# Purpose : extra takes of one character clip (seeds x motion wordings) laid out and scored side by side, without
#           touching the shipped clip; --promote ships a take without re-rendering it.
# Usage   : dotwork.py audition --name guard --clip walk_e --seeds 8101 8102 8103 [--motion "" "wording"]
#           [--feature-hue 30-56]
# Notes   : The score only sorts the sheet: the turn warning misses some turns; judge the sheet.
#           Takes live in <work>/<name>/audition/<clip>/; the sheet is copied to <src>/review/.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import json
import os
import shutil

import numpy as np
from PIL import Image

import fcore as core
import qa

import engine as lib  # noqa: E402


class _NoManifest:
    """Character() notes assumptions in the pack manifest; an audition ships nothing, so they are dropped."""
    def assume(self, *_a, **_k):
        pass

    add = assume


def front_feature(im, facing, hue):
    """Bright pixels of the signature hue in the half of the body that faces forward (west = left half)."""
    im = im.convert("RGBA")
    a = np.array(im)
    op = a[..., 3] > 127
    if not op.any():
        return 0
    hsv = np.array(im.convert("RGB").convert("HSV")).astype(np.float32)
    h, s, v = hsv[..., 0] * 360 / 255, hsv[..., 1] / 255, hsv[..., 2] / 255
    m = op & (h >= hue[0]) & (h <= hue[1]) & (s >= 0.5) & (v >= 0.75)
    cx = np.median(np.nonzero(op)[1])
    xs = np.arange(a.shape[1])[None, :]
    front = xs < cx if facing == "w" else xs > cx
    return int((m & front).sum())


def reach(frames, facing):
    """Pixels the silhouette extends past frame 0 in the facing direction (does the punch actually go out)."""
    bbs = [f.getbbox() for f in frames if f.getbbox()]
    if facing == "w":
        return bbs[0][0] - min(b[0] for b in bbs)
    if facing == "e":
        return max(b[2] for b in bbs) - bbs[0][2]
    return 0  # front/back views: no meaningful sideways reach


def score_take(fr, notes, facing, ref, hue):
    turned = any("turn-around" in n for n in notes)
    drift = any("height drift" in n for n in notes)
    out = {"turned": turned, "height_drift": drift, "reach_px": reach(fr, facing)}
    if hue:
        base = max(1, front_feature(ref, facing, hue))
        per = [front_feature(f, facing, hue) for f in fr]
        # median, capped at 100%: the worst frame was too noisy (one dull mid-swing frame zeroed the best take,
        # 2026-10-29), and more brass than the rotation sprite is not "better"
        out.update(feature_per_frame=per, feature_ref=base,
                   feature_retention=round(min(1.0, float(np.median(per)) / base), 2))
    out["score"] = round(-100 * turned - 20 * drift + 50 * out.get("feature_retention", 0) + out["reach_px"], 1)
    return out


def run(entry, clip, seeds, motions, hue=None, pack=None):
    import lane_character
    conf = core.cfg()
    action, direction = clip.rsplit("_", 1)
    ch = lane_character.Character(dict(entry, clip_fix={}), pack or core.HERE, _NoManifest(), conf)
    if not os.path.exists(os.path.join(ch.work, "rot", f"{direction}.png")):
        raise core.ToolError(f"no rotations in {ch.work}: run dotwork.py character for {ch.name} first")
    if direction == "w" and ch.mirror:
        raise core.ToolError("west is mirrored from east for symmetric characters: audition the _e clip instead "
                         "(or pass --asymmetric if the character really is asymmetric)")
    rot = ch.rotate(ch.south())  # cached, no render
    root = os.path.join(ch.work, "audition", clip)
    os.makedirs(root, exist_ok=True)
    takes = []
    # shipped clip first, as the baseline row
    ship_dir = os.path.join(ch.work, "clips", clip)
    if glob.glob(os.path.join(ship_dir, "f_*.png")):
        fr, notes = ch.frames(action, direction, rot, clip_dir=ship_dir)
        takes.append(dict(tag="shipped", seed=json.load(open(os.path.join(ship_dir, "meta.json"))).get("seed"),
                          motion=None, notes=notes, dir=ship_dir, frames=fr))
    for k, motion in enumerate(motions or [""]):
        for seed in seeds:
            d = os.path.join(root, f"m{k}_s{seed}")
            meta = os.path.join(d, "meta.json")
            fresh = (glob.glob(os.path.join(d, "f_*.png")) and os.path.exists(meta)
                     and json.load(open(meta)).get("motion_fix") == (motion or None))
            if not fresh:  # resume: a take already rendered with this wording is reused
                ch.render(action, direction, rot[direction], int(seed), d, motion or None)
            fr, notes = ch.frames(action, direction, rot, clip_dir=d)
            takes.append(dict(tag=f"m{k}_s{seed}", seed=int(seed), motion=motion or None, notes=notes, dir=d,
                              frames=fr))
    ref = Image.open(rot[direction])
    for t in takes:
        t.update(score_take(t["frames"], t["notes"], direction, ref, hue))
        qd = os.path.join(t["dir"], "qa") if t["tag"] != "shipped" else os.path.join(root, "shipped_qa")
        shutil.rmtree(qd, ignore_errors=True)
        os.makedirs(qd)
        t["qa_files"] = [core.save_clean(f, os.path.join(qd, f"q_{i:02d}.png")) for i, f in enumerate(t["frames"])]
    ranked = sorted((t for t in takes if t["tag"] != "shipped"), key=lambda t: -t["score"])
    for i, t in enumerate(ranked):
        t["rank"] = i + 1
    rows = []
    for t in takes:
        ret = f" b{int(100 * t['feature_retention'])}" if "feature_retention" in t else ""
        lab = ("ship" if t["tag"] == "shipped" else f"#{t['rank']} {t['tag'].split('_')[0]}") + \
              f" s{t['seed']}{ret}{' T' if t['turned'] else ''}"
        rows.append((lab, t["qa_files"]))
    sheet = lib.sheet(rows, os.path.join(root, "audition.png"), scale=2)
    report = {"clip": clip, "character": ch.name, "feature_hue": hue, "motions": motions,
              # {**a, ...} rather than a | b: dict union is Python 3.9+, the kit's floor is 3.8
              "takes": [{**{k: v for k, v in t.items() if k not in ("frames", "qa_files", "dir")}, "dir": t["dir"]}
                        for t in takes]}
    with open(os.path.join(root, "audition.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    if pack:
        rv = core.src(conf, "review")
        os.makedirs(rv, exist_ok=True)
        shutil.copyfile(sheet, os.path.join(rv, f"{ch.name}_{clip}_audition.png"))
        shutil.copyfile(os.path.join(root, "audition.json"), os.path.join(rv, f"{ch.name}_{clip}_audition.json"))
    core.log(f"audition {ch.name} {clip}: {len(ranked)} takes, best {ranked[0]['tag'] if ranked else '-'} "
             f"score {ranked[0]['score'] if ranked else '-'}")
    return report, sheet, ranked


def promote(entry, clip, tag):
    """Make audition take `tag` the shipped clip; returns its meta (seed, motion_fix) for the --fix hint."""
    import lane_character
    ch = lane_character.Character(dict(entry, clip_fix={}), core.HERE, _NoManifest(), core.cfg())
    root = os.path.join(ch.work, "audition", clip)
    src = os.path.join(root, tag)
    if not glob.glob(os.path.join(src, "f_*.png")):
        raise core.ToolError(f"no take {tag} in {root} (tags are the folder names, e.g. m1_s8101)")
    ship = os.path.join(ch.work, "clips", clip)
    if glob.glob(os.path.join(ship, "f_*.png")):
        old = json.load(open(os.path.join(ship, "meta.json")))
        bak = os.path.join(root, f"prev_s{old.get('seed')}")
        if os.path.abspath(bak) != os.path.abspath(src):  # keep the outgoing clip so it can be promoted back
            shutil.rmtree(bak, ignore_errors=True)
            shutil.copytree(ship, bak, ignore=shutil.ignore_patterns("qa"))
    shutil.rmtree(ship, ignore_errors=True)
    shutil.copytree(src, ship, ignore=shutil.ignore_patterns("qa"))
    meta = json.load(open(os.path.join(ship, "meta.json")))
    core.log(f"audition {ch.name} {clip}: promoted {tag} (seed {meta['seed']}) to the shipped clip")
    return meta


def apply_hint(clip, t):
    """The --fix arguments that make a take the shipped clip."""
    fx = f"{clip}:seed={t['seed']}"
    motion = t.get("motion") or t.get("motion_fix")  # take row or promoted meta.json
    return fx + (f' "{clip}:motion={motion}"' if motion else "")
