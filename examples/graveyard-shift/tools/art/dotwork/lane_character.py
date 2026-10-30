#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_character.py
# Purpose : one character from a prompt or an existing south sprite: rotated to 4 directions (Qwen multi-angle),
#           animated per action with Wan 2.2 (idle / walk / attack ...), cleaned (ground shadow, specks, palette
#           lock), optional still poses (battle facing left, field emotes), exported as frames, sheets and Godot
#           SpriteFrames.
# Usage   : pack spec "characters": [{"name": "guard", "prompt": "a town guard in a brass helmet", "actions":
#           ["idle", "walk"], "poses": "battle", "clip_fix": {"walk_n": {"seed": 4247}}}] or dotwork.py character
#           --name guard --prompt ...
# Notes   : Keys: prompt | source, seeds, asymmetric (generate west instead of mirroring), actions, directions, east_edit,
#           subject, motions {action: wording}, clip_fix {clip: {seed, keep, motion}}, poses (battle | field | {name: wording}),
#           pose_dirs, pose_text. Back-view idles are a procedural 1 px bob (Wan paints faces on the back of heads).
#           Renders resume from <work>/<name>/ (south, rot/, clips/, poses/). Review sheet: <src>/art/characters/<name>/.
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
import qa
import spritekiln

import engine as lib  # noqa: E402

COMFY_WORK = lib.comfy_out("dotwork_work")  # where ComfyUI writes Dotwork temp outputs
ROT_ORDER = ["s", "w", "n", "e"]  # rotation workflow output, screen-clockwise from south (verified)
VIEW = {"s": "front view", "e": "side view", "w": "side view", "n": "keep facing direction"}
# Wan negative prompt, Dotwork's own wording. NOTE: wf10 samples at cfg 1.0 (4-step lightning LoRAs), and at cfg 1.0
# the negative prompt has NO effect. Kept for the day cfg > 1 is used; shadows are handled by rendering unlocked +
# qa.deshadow_blob, faces on back views by the procedural idle.
WAN_NEG = ("still image, frozen frame, blurry, smeared detail, oversaturated, washed out, low quality, compression "
           "artifacts, deformed body, extra limbs, extra fingers, melted hands, walking backwards, crowd, busy "
           "background, camera movement, camera pan, zoom, background change, morphing, text, watermark, "
           "ground shadow, drop shadow, cast shadow, shadow under the feet, floor, ground plane, dark ellipse")
# "poses": "battle" -> side-view battle stills (the party faces left in 16-bit RPG battles: pose_dirs ["w"]);
# attack / walk come from the animated clips (punch_w, walk_w ...)
BATTLE_POSES = {  # wordings auditioned 2026-10-29 on the Tinkerer (vague wording = klein returns the idle pose)
    "ready": "the character takes a wide boxing stance: feet apart, knees bent, both fists raised in front of the "
             "chest, the body and head still in side profile facing left",
    "weak": "the character has collapsed down onto one knee: the body is much lower, crouched near the ground, head "
            "hanging down, one hand pressed on the ground, side profile facing left",
    "ko": "the character lies collapsed flat on the ground on his back, knocked out with eyes closed, lying "
          "horizontally",
    "victory": "the character raises one fist high above his head in victory with a big grin, facing left",
    "hurt": "the character flinches in pain: the upper body tilts back a little, head ducked, eyes squeezed shut, "
            "both arms pulled in close, both feet still on the ground, side profile facing left",
    "defend": "the character hunches forward behind his raised forearm held up in front of his face like a shield, "
              "the other arm tucked in, side profile facing left",
    "cast": "the character thrusts both hands forward casting a spell, a small glow of light between the hands, "
            "facing left",
    "item": "the character holds a small glowing potion bottle up high in one raised hand, side profile facing left",
    "jump": "the character leaps high into the air with both knees tucked up and both feet off the ground, side "
            "profile facing left",
}
# "poses": "field" -> cutscene / emote stills facing the camera (pose_dirs ["s"]); same wording rules as battle
FIELD_POSES = {
    "surprised": "the character jumps back in surprise with both hands raised, eyes wide and mouth open, facing the viewer",
    "laugh": "the character laughs heartily with eyes closed, head tilted back, one hand on the belly, facing the viewer",
    "angry": "the character leans forward angrily with both fists clenched and raised, eyebrows sharply down, teeth "
             "gritted, facing the viewer",
    "sad": "the character looks down sadly with the head hanging low, shoulders slumped forward, a tear on the cheek, "
           "facing the viewer",
    "kneel": "the character drops down onto one knee: the body much lower, one knee on the ground, head bowed, "
             "facing the viewer",
    "collapsed": "the character lies collapsed face down flat on the ground, lying horizontally",
    "sleep": "the character lies flat on his back on the ground fast asleep with eyes closed, lying horizontally",
    "point": "the character points forward with one arm fully extended, determined expression, facing the viewer",
    "arms_crossed": "the character stands with both arms crossed over the chest, confident smirk, facing the viewer",
    "thinking": "the character holds his chin in one hand thinking, looking up, facing the viewer",
}
NPC_TPL = ("pixel art sprite, high top-down RPG character sprite of {s}, full body, standing, front view facing the "
           "viewer, face clearly visible, chibi proportions, drawn in the exact pixel art style, palette, outline "
           "and shading of image 1, steampunk, crisp dark outline")


def _wf(name):
    """A SpriteKiln workflow (API format) from the user's clone, klein VAE swapped in (spritekiln.load)."""
    return spritekiln.load(name)


def _saves(g, prefix):
    for n in g.values():
        if n["class_type"] == "SK_SavePixelArt":
            n["inputs"].update(filename_prefix=prefix, upscale=1, as_animation=False)
        if n["class_type"] == "SaveAnimatedWEBP":
            n["inputs"]["filename_prefix"] = prefix + "_raw"
    return g


def _score(path):
    """Quality score for picking among seeds: prefer ~66 px tall, ~40 colors, few isolated pixels, front facing."""
    im = Image.open(path).convert("RGBA")
    a = np.array(im)
    op = a[..., 3] == 255
    bb = im.getbbox()
    h = (bb[3] - bb[1]) if bb else 0
    cols = len(np.unique(a[op][:, :3], axis=0))
    key = np.where(op, (a[..., 0].astype(int) << 16) | (a[..., 1].astype(int) << 8) | a[..., 2], -1)
    pad = np.pad(key, 1, constant_values=-2)
    same = np.zeros_like(op)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                same |= pad[1 + dy:1 + dy + key.shape[0], 1 + dx:1 + dx + key.shape[1]] == key
    orph = (op & ~same).sum() / max(1, op.sum())
    front = qa.facing(im)[0] == "front"
    return -abs(h - 66) * 0.5 - abs(cols - 40) * 0.2 - orph * 100 + (5 if front else 0)


class Character:
    def __init__(self, entry, pack_dir, man, conf):
        self.e, self.man, self.conf = entry, man, conf
        self.d = conf["design"]["character"]
        self.name = core.snake(entry["name"])
        self.asym = bool(entry.get("asymmetric", False))
        self.mirror = self.d["mirror_west"] and not self.asym
        # actions and directions become folder and file names (clips/<action>_<dir>, wiped before each render):
        # snake the actions and allow only the four directions ("../.." in a spec action reached shutil.rmtree,
        # 2026-10-30 Kimi audit)
        self.actions = [core.snake(a) for a in (entry.get("actions") or list(self.d["actions"]))]
        self.dirs = list(entry.get("directions") or self.d["directions"])
        bad = [d for d in self.dirs if d not in ("s", "e", "n", "w")]
        if bad:
            raise core.ToolError(f"character {self.name}: directions {bad}: use s, e, n and w")
        self.work = os.path.join(core.WORK, self.name)           # resumable working files
        self.src = core.src(conf, "art", "characters", self.name)
        self.out = core.art(conf, "characters", self.name)   # the configured assets_dir (public/assets for web games)
        self.res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/characters/{self.name}'
        os.makedirs(self.work, exist_ok=True)
        self.stamp_check()
        if self.mirror:
            man.assume(f"{self.name}: west mirrored from east (symmetric character)")
        else:
            man.assume(f"{self.name}: west generated, not mirrored (asymmetric character)")

    # -------------------------------------------------- 0. design stamp
    STAMPED = ("south.png", "candidates.png", "candidates.json", "rot", "clips", "poses", "audition")

    def stamp_check(self):
        """Everything after the south sprite builds on it, so a new design (prompt or source, seeds, height, symmetry,
        east edit, style reference) retires the old renders: moved to <work>/<name>/_old_<stamp>/, never deleted.
        Per-clip seed / motion changes are handled by clip() and keep the rest.
        An entry with neither prompt nor source (audition, audition --promote) defines no design: it reuses the
        renders as they are. It used to count as a new design, retire everything and rewrite the stamp, so one
        audition cost the next run every render (2026-10-30 Kimi audit)."""
        e = self.e
        if not (e.get("prompt") or e.get("source")):
            return
        sp = core.project_path(e["source"]) if e.get("source") else None
        src = core.sha256_file(sp)[:12] if sp and os.path.exists(sp) else e.get("source")
        inputs = {"prompt": e.get("prompt"), "source": src, "seed": e.get("seed", 3000), "seeds": e.get("seeds", 3),
                  "fig_height": self.d["fig_height"], "asymmetric": self.asym, "east_edit": e.get("east_edit"),
                  "ref": lib.ref_key(self.conf)}
        stamp = core.key(*[f"{k}={inputs[k]}" for k in sorted(inputs)])
        path = os.path.join(self.work, "stamp.json")
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = json.load(f).get("stamp")
        stale = [n for n in self.STAMPED if os.path.exists(os.path.join(self.work, n))]
        if old and old != stamp and stale:
            keep = os.path.join(self.work, f"_old_{old}")
            os.makedirs(keep, exist_ok=True)
            for n in stale:
                shutil.move(os.path.join(self.work, n), os.path.join(keep, n))
            core.log(f"{self.name}: design changed, earlier renders moved to {keep}")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"stamp": stamp, "inputs": inputs}, f, indent=1)

    # -------------------------------------------------- 1. south sprite
    def south(self):
        p = os.path.join(self.work, "south.png")
        if os.path.exists(p):
            return p
        if self.e.get("source"):
            Image.open(core.source_path(self.e["source"])).convert("RGBA").save(p)
            core.log(f"{self.name}: south sprite from {self.e['source']}")
            return p
        core.ensure_comfy()
        ref = lib.ref(self.d.get("style_ref", "cast"))
        cands = []
        for k in range(int(self.e.get("seeds", 3))):
            seed = int(self.e.get("seed", 3000)) + k
            o = lib.sprite(NPC_TPL.format(s=self.e["prompt"]), seed, f"dotwork/{self.name}", ref_fn=ref,
                           fig=self.d["fig_height"], canvas=max(self.d["canvas_min"]), baseline=self.d["canvas_min"][1] - 3)
            cands.append((_score(o["path"]), seed, o["path"]))
            core.log(f"{self.name}: candidate seed {seed} score {cands[-1][0]:.1f}")
        cands.sort(reverse=True)
        lib.sheet([("candidates", [c[2] for c in cands])], os.path.join(self.work, "candidates.png"), scale=3)
        shutil.copyfile(cands[0][2], p)
        json.dump([{"score": c[0], "seed": c[1], "file": c[2]} for c in cands],
                  open(os.path.join(self.work, "candidates.json"), "w"), indent=1)
        self.e["_picked_seed"] = cands[0][1]
        core.log(f"{self.name}: picked seed {cands[0][1]}")
        return p

    # -------------------------------------------------- 2-3. rotation (+ optional east edit)
    def rotate(self, south):
        d = os.path.join(self.work, "rot")
        have = {k: os.path.join(d, f"{k}.png") for k in ROT_ORDER}
        if all(os.path.exists(v) for v in have.values()):
            return have
        core.ensure_comfy()
        core.require_ram()   # Qwen-Image-Edit + its 7B text encoder load next
        os.makedirs(d, exist_ok=True)
        fn = f"dotwork_{self.name}_south.png"
        fn = lib.put(Image.open(south), fn)
        g = _saves(_wf("07_rotate_hq_qwen_multiangle"), f"dotwork_work/{self.name}/rot/r")
        g["2"]["inputs"]["image"] = fn
        g["5"]["inputs"].update(directions="4", mirror_west=self.mirror)
        r = lib.run_job(g, timeout=2400)
        files = lib.job_files(r, "r_*.png")
        if len(files) < len(ROT_ORDER):
            raise core.JobError(f"{self.name}: rotation saved {len(files)} views, expected {len(ROT_ORDER)}")
        for k, f in zip(ROT_ORDER, files):
            shutil.copyfile(f, have[k])
        core.log(f"{self.name}: rotation {r['seconds']:.0f}s (mirror_west={self.mirror})")
        if self.e.get("east_edit"):
            self.edit(have["e"], self.e["east_edit"])
        return have

    def edit(self, path, instr):
        core.ensure_comfy()
        fn = f"dotwork_{self.name}_edit.png"
        fn = lib.put(Image.open(path), fn)
        g = _saves(_wf("04_edit_pixel_art"), f"dotwork_work/{self.name}/edit/e")
        g["2"]["inputs"]["image"] = fn
        g["5"]["inputs"]["image"] = fn
        g["13"]["inputs"]["text"] = (f"Edit the pixel art sprite in image 1: {instr}. Keep everything else identical: "
                                     "same pose, same size, same pixel art style, same outline and colors.")
        r = lib.run_job(g, timeout=1200)
        out = lib.job_files(r, "e_*.png")   # both save nodes share the prefix; the first file is the one used
        if not out:
            raise core.JobError(f"{self.name}: the east edit saved no image")
        shutil.copyfile(out[0], path)
        core.log(f"{self.name}: east edit applied ({instr[:50]}...)")

    # -------------------------------------------------- 4. clips
    def fix(self, action, direction):
        """Per-clip fix from the spec: {"punch_w": {"keep": 4}, "punch_n": {"seed": 5151}}."""
        return (self.e.get("clip_fix") or {}).get(f"{action}_{direction}", {})

    def clip(self, action, direction, sprite, seed=4242):
        d = os.path.join(self.work, "clips", f"{action}_{direction}")
        fx = self.fix(action, direction)
        seed = int(fx.get("seed", seed))
        motion = fx.get("motion")  # per-clip motion text (an audition winner); None = action/character default
        meta = os.path.join(d, "meta.json")
        old = {}
        if os.path.exists(meta):
            with open(meta, encoding="utf-8") as f:
                old = json.load(f)
        # re-render only this clip when its seed, per-clip motion or action wording changed (older metas have no
        # motion_fix = None, and no motion_key: those clips are kept)
        mk = self.motion_key(action)
        if (glob.glob(os.path.join(d, "f_*.png")) and old.get("seed", 4242) == seed and old.get("motion_fix") == motion
                and old.get("motion_key", mk) == mk):
            return d
        return self.render(action, direction, sprite, seed, d, motion)

    def motion_key(self, action):
        """What shapes a clip besides its seed: the action_map entry, the character's motion text and subject. Editing
        any of them in the spec re-renders that action's clips (they were ignored before the 2026-10-30 audit)."""
        am = self.conf["action_map"].get(action, {"wan_action": action})
        return core.key(json.dumps(am, sort_keys=True), (self.e.get("motions") or {}).get(action), self.e.get("subject"))

    def render(self, action, direction, sprite, seed, d, motion=None):
        """One Wan clip into d (wiped first). Shared by clip() and audition.py. motion overrides the action_map and
        per-character motion text for this render only."""
        tag = os.path.relpath(d, self.work).replace("\\", "/")  # e.g. clips/punch_w or audition/punch_w/m1_s8103
        comfy_dir = os.path.join(COMFY_WORK, self.name, *tag.split("/"))
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(comfy_dir, ignore_errors=True)
        core.ensure_comfy()
        core.require_ram()
        os.makedirs(d, exist_ok=True)
        am = dict(self.conf["action_map"].get(action, {"wan_action": action}))
        if (self.e.get("motions") or {}).get(action):  # per-character motion text, e.g. "punch with the mech fist"
            am.update(wan_action="custom", motion=self.e["motions"][action])
        if motion:
            am.update(wan_action="custom", motion=motion)
        fn = f"dotwork_{self.name}_{direction}.png"
        fn = lib.put(Image.open(sprite), fn)
        g = _saves(_wf("10_animate_sprite"), f"dotwork_work/{self.name}/{tag}/f")
        for n in g.values():
            if n["class_type"] == "KSamplerAdvanced":
                n["inputs"]["noise_seed"] = seed
        g["2"]["inputs"]["image"] = fn
        # subject: optional per-character wording for the animation prompt (e.g. names a signature prop)
        subject = self.e.get("subject") or f"the pixel art {self.e.get('prompt') or self.name}"
        g["5"]["inputs"].update(subject=subject,
                                action=am["wan_action"], view=VIEW[direction], custom_motion=am.get("motion", ""))
        neg = WAN_NEG + (", " + am["negative"] if am.get("negative") else "")
        g["18"]["inputs"]["text"] = neg
        # v2: skip SpriteKiln's palette lock (node 28). Locked frames paint Wan's ground shadow in the sprite's own
        # darkest colors, so no rule can tell shadow from boots. Unlocked, the shadow stays a neutral grey-blue;
        # frames() removes it and then locks to the sprite palette itself.
        g["29"]["inputs"]["frames"] = ["27", 0]
        r = lib.run_job(g, timeout=3600)
        for f in glob.glob(os.path.join(comfy_dir, "f_*.png")):
            shutil.copyfile(f, os.path.join(d, os.path.basename(f)))
        meta = {"seed": seed, "action": action, "direction": direction, "palette_lock": "dotwork",
                "motion_key": self.motion_key(action)}
        if motion:
            meta["motion_fix"] = motion
        with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f)
        core.free_models()
        core.log(f"{self.name}: clip {action}_{direction} {r['seconds']:.0f}s (seed {seed})"
                 + (f" [{tag}]" if not tag.startswith("clips/") else ""))
        return d

    # -------------------------------------------------- procedural back-view idle
    def procedural(self, action, direction):
        return (action == "idle" and direction in self.d.get("procedural_idle", ["n"])
                and not self.fix(action, direction).get("wan"))

    @staticmethod
    def bob_idle(sprite_path, n=6):
        """Classic pixel-art breathing idle: the upper body (above ~55% of the height) dips 1 px for half the loop.
        Used for back views, where Wan kept painting a face on the back of the head (3 seeds out of 3)."""
        im = Image.open(sprite_path).convert("RGBA")
        bb = im.getbbox()
        if bb is None:
            raise core.JobError(f"{sprite_path}: the sprite is fully transparent; retake it with another seed")
        split = bb[1] + int((bb[3] - bb[1]) * 0.55)
        upper = im.crop((0, 0, im.width, split))
        lower = im.crop((0, split, im.width, im.height))
        out = []
        for i in range(n):
            f = Image.new("RGBA", im.size, (0, 0, 0, 0))
            f.alpha_composite(lower, (0, split))
            f.alpha_composite(upper, (0, 1 if i in (2, 3) else 0))
            out.append(f)
        return out

    # -------------------------------------------------- 5. QA
    def frames(self, action, direction, rot, clip_dir=None):
        """QA'd frames for one clip. clip_dir: read a different render (audition take) instead of the shipped clip."""
        if self.procedural(action, direction) and not clip_dir:
            return self.bob_idle(rot[direction]), ["procedural 1 px breathing idle (back view)"]
        src_dir = "e" if (direction == "w" and self.mirror) else direction
        d = clip_dir or os.path.join(self.work, "clips", f"{action}_{src_dir}")
        fr = [Image.open(p).convert("RGBA") for p in sorted(glob.glob(os.path.join(d, "f_*.png")))]
        if not fr:
            raise core.JobError(f"{self.name}: clip {action}_{src_dir} has no frames in {d} (re-run to render it)")
        notes = []
        meta = os.path.join(d, "meta.json")
        dotwork_lock = False
        if os.path.exists(meta):
            with open(meta, encoding="utf-8") as f:
                dotwork_lock = json.load(f).get("palette_lock") == "dotwork"
        pal = qa.palette_of(Image.open(rot[src_dir]))
        clean, removed = [], 0
        for f in fr:
            if dotwork_lock:  # unlocked clip: drop off-palette neutral pixels near the feet, then lock ourselves
                f, n0 = qa.deshadow_blob(f)
                removed += n0
                f = qa.lock_palette(f, pal)
            f, n1 = qa.deshadow(f)
            f, n2 = qa.deblue(f)
            clean.append(qa.drop_islands(f))
        fr = clean
        if removed:
            notes.append(f"ground shadow removed: {removed} px")
        if direction == "w" and self.mirror:
            fr = [ImageOps.mirror(f) for f in fr]
        refs = {k: Image.open(v) for k, v in rot.items()}
        if self.mirror:  # mirrored west: compare against the mirror of east, as the clip itself is mirrored
            refs["w"] = ImageOps.mirror(refs["e"])
        bad = qa.turned_any(fr[1:], direction, refs)
        if bad is not None:  # heuristic only (false positives seen): note for review, never auto-trim
            notes.append(f"possible turn-around from frame {bad + 1}: review the contact sheet")
        keep = self.fix(action, direction).get("keep")
        if keep:
            fr = qa.ping_pong_trim(fr, int(keep))
            notes.append(f"spec clip_fix keep={keep}: ping-pong trimmed")
        ref_h = Image.open(rot[direction]).getbbox()
        ok, det = qa.height_ok(fr, ref_h[3] - ref_h[1])
        if not ok:
            notes.append("height drift: " + det)
        return fr, notes

    # -------------------------------------------------- 6. export
    def export(self, clips, rot):
        self.man.drop_dir(self.out)  # clean re-export (stale frames from an earlier, longer clip)
        # provenance: klein drew the south sprite (unless it came from --source) and every still pose
        routes = (("klein",) if not self.e.get("source") or self.e.get("poses") else ()) + ("qwen_rotate", "wan")
        allf = [f for fr, _ in clips.values() for f in fr]
        W = max(f.getbbox()[2] - f.getbbox()[0] for f in allf if f.getbbox())
        H = max(f.getbbox()[3] - f.getbbox()[1] for f in allf if f.getbbox())
        W = max(W + W % 2, self.d["canvas_min"][0])
        H = max(H, self.d["canvas_min"][1])
        anims = {}
        acts = self.d["actions"]
        for (action, direction), (fr, notes) in clips.items():
            name = f"{action}_{direction}"
            files = []
            sheet = Image.new("RGBA", (W * len(fr), H), (0, 0, 0, 0))
            for i, f in enumerate(fr):
                bb = f.getbbox()
                f = f.crop(bb)
                can = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                can.alpha_composite(f, ((W - f.width) // 2, H - f.height))
                fn = f"spr_{self.name}_{name}_{i:02d}.png"
                p = core.save_clean(can, os.path.join(self.out, "frames", fn))
                files.append(fn)
                sheet.alpha_composite(can, (i * W, 0))
            fps = acts.get(action, {}).get("fps", 8)
            loop = acts.get(action, {}).get("loop", action in ("idle", "walk", "run"))
            anims[name] = (files, fps, loop)
            sp = core.save_clean(sheet, os.path.join(self.out, f"{self.name}_{name}_sheet.png"))
            with open(sp[:-4] + ".json", "w", encoding="utf-8") as fh:
                json.dump({"frame_w": W, "frame_h": H, "frames": len(fr), "fps": fps, "loop": loop,
                           "anchor": "bottom_center"}, fh, indent=1)
            self.man.add(sp, "sheet", animation=name, frames=len(fr), fps=fps, loop=loop, canvas=[W, H],
                         anchor="feet_bottom_center", qa=notes, routes=routes)
            self.man.add(sp[:-4] + ".json", "sheet_data", animation=name)
            for fn in files:
                self.man.add(os.path.join(self.out, "frames", fn), "frame", animation=name, canvas=[W, H],
                             anchor="feet_bottom_center", routes=routes)
        rows = [(n, [os.path.join(self.out, "frames", f) for f in fs]) for n, (fs, _, _) in sorted(anims.items())]
        os.makedirs(self.src, exist_ok=True)
        lib.sheet(rows, os.path.join(self.src, "review_sheet.png"), scale=2)
        tres = godot.sprite_frames(os.path.join(self.out, f"{self.name}_frames.tres"), self.res + "/frames", anims)
        self.man.add(tres, "sprite_frames", animations=sorted(anims), canvas=[W, H], anchor="feet_bottom_center",
                     node="AnimatedSprite2D", offset=[0, -(H // 2)])
        # editable sources (never under assets/)
        os.makedirs(self.src, exist_ok=True)
        for k, p in rot.items():
            core.save_clean(Image.open(p), os.path.join(self.src, f"rot_{k}.png"))
        for extra in ("candidates.png", "candidates.json", "south.png"):
            if os.path.exists(os.path.join(self.work, extra)):
                shutil.copyfile(os.path.join(self.work, extra), os.path.join(self.src, extra))
        return tres, [W, H]

    # -------------------------------------------------- 4b. still poses (battle / emotes): klein edit of a sprite
    def pose(self, name, direction, instr, sprite):
        """One still pose from the direction sprite (SpriteKiln wf04, palette-locked output). Cached by
        instruction + seed; a per-pose fix {"ko_w": {"seed": 6411}} gives another take."""
        d = os.path.join(self.work, "poses")
        os.makedirs(d, exist_ok=True)
        seed = int(self.fix(name, direction).get("seed", 6400))
        p = os.path.join(d, f"{name}_{direction}.png")
        want = {"instr": instr, "seed": seed}
        if os.path.exists(p) and os.path.exists(p[:-4] + ".json") and json.load(open(p[:-4] + ".json")) == want:
            return p
        core.ensure_comfy()
        fn = f"dotwork_{self.name}_pose_{direction}.png"
        fn = lib.put(Image.open(sprite), fn)
        g = _wf("04_edit_pixel_art")
        tag = f"{self.name}/poses/{name}_{direction}"
        shutil.rmtree(os.path.join(COMFY_WORK, *tag.split("/")), ignore_errors=True)
        g["31"]["inputs"].update(filename_prefix=f"dotwork_work/{tag}/free", upscale=1, as_animation=False)
        g["32"]["inputs"].update(filename_prefix=f"dotwork_work/{tag}/locked", upscale=1, as_animation=False)
        g["2"]["inputs"]["image"] = fn
        g["5"]["inputs"]["image"] = fn
        g["19"]["inputs"]["noise_seed"] = seed
        g["13"]["inputs"]["text"] = (f"Edit the pixel art sprite in image 1: {instr}. Keep the same character, the same "
                                     "outfit, colors and proportions, the same pixel art style, size and outline.")
        r = lib.run_job(g, timeout=1200)
        outs = sorted(glob.glob(os.path.join(COMFY_WORK, *tag.split("/"), "locked*.png")))
        if not outs:
            raise core.JobError(f"pose {name}_{direction}: no output in {tag}")
        shutil.copyfile(outs[0], p)
        with open(p[:-4] + ".json", "w", encoding="utf-8") as fh:
            json.dump(want, fh)
        core.log(f"{self.name}: pose {name}_{direction} {r['seconds']:.0f}s (seed {seed})")
        return p

    def pose_frames(self, path):
        f = Image.open(path).convert("RGBA")
        f, n1 = qa.deshadow(f)
        f, n2 = qa.deblue(f)
        return [qa.drop_islands(f)], (["still pose (klein edit)"] + ([f"shadow/blue px removed {n1 + n2}"]
                                                                     if n1 + n2 else []))

    def run(self):
        core.log(f"=== character {self.name} (asymmetric={self.asym}, actions={self.actions})")
        south = self.south()
        rot = self.rotate(south)
        need = [d for d in self.dirs if not (d == "w" and self.mirror)]
        if "w" in self.dirs and self.mirror and "e" not in need:
            need.append("e")   # mirrored west clips are flipped east ones (--directions s w used to crash)
        for action in self.actions:
            for d in need:
                if not self.procedural(action, d):
                    self.clip(action, d, rot[d])
        clips = {(a, d): self.frames(a, d, rot) for a in self.actions for d in self.dirs}
        poses = self.e.get("poses") or {}
        if poses in ("battle", "field"):
            poses = BATTLE_POSES if poses == "battle" else FIELD_POSES
        poses = dict(poses, **(self.e.get("pose_text") or {}))  # per-character wording, e.g. name a signature prop
        poses = {core.snake(k): v for k, v in poses.items()}   # pose names become folder and file names
        for pname, instr in poses.items():
            # battle stills face left (w); field emotes face the camera (s), as the pose wordings say
            for d in self.e.get("pose_dirs") or (["s"] if self.e.get("poses") == "field" else ["w"]):
                clips[(pname, d)] = self.pose_frames(self.pose(pname, d, instr, rot[d]))
        for (a, d), (fr, notes) in clips.items():
            if notes:
                core.log(f"{self.name}: QA {a}_{d}: {'; '.join(notes)}")
        return self.export(clips, rot)
