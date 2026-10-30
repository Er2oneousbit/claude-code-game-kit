#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# pose.py
# Purpose : pose-driven animation: a procedural skeleton (walk, run, idle, attack, jump; side view and front / back
#           view) drawn as OpenPose-style frames over exactly where the sprite sits on the model canvas, and the Wan 2.2
#           Fun-Control graph that animates the sprite to follow it. The motion comes from the skeleton, so a clip does
#           what it is told: no drift into another view, the same stride every time, a loop that closes.
# Usage   : character entry "skeleton": ["walk", "run"] (lane_character renders those actions with control_graph);
#           python pose.py ACTION DIRECTION OUT_DIR  writes the skeleton frames for a look.
# Notes   : Needs the "pose" model tier (Get-Models / models.lock.json): wan2.2_fun_control_{high,low}_noise_14B_Q4_K_M
#           .gguf (Apache-2.0), with the same VAE and text encoder as the animate tier. Proportions are chibi (a big
#           head, hips at two thirds of the height), like the characters the sprite lane draws.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

ACTIONS = ("walk", "run", "idle", "attack", "jump")
VERSION = 2   # in the clip cache key: a new skeleton re-renders the clips made from the old one
MODELS = ("wan2.2_fun_control_high_noise_14B_Q4_K_M.gguf", "wan2.2_fun_control_low_noise_14B_Q4_K_M.gguf")
# OpenPose 18: 0 nose, 1 neck, 2 r_shoulder, 3 r_elbow, 4 r_wrist, 5 l_shoulder, 6 l_elbow, 7 l_wrist, 8 r_hip,
# 9 r_knee, 10 r_ankle, 11 l_hip, 12 l_knee, 13 l_ankle, 14 r_eye, 15 l_eye, 16 r_ear, 17 l_ear
LIMBS = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13), (1, 0),
         (0, 14), (14, 16), (0, 15), (15, 17)]
COLOURS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0),
           (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255),
           (170, 0, 255), (255, 0, 255), (255, 0, 85), (255, 0, 170)]
# chibi heights (share of the figure, from the feet up). Face, neck and shoulder are the fallbacks for a sprite whose
# face does not show (fit() measures them per sprite): measured 2026-10-30 on five front sprites, faces sit at
# 0.60-0.66 of the height and chins at 0.52-0.58. The first skeleton had the nose at 0.80, on the hood, and Wan drew a
# second face there (goggles over the real one); arms reached 0.25 below the shoulder, where a chibi hand is at 0.13
H = {"ankle": 0.03, "knee": 0.17, "hip": 0.34, "shoulder": 0.48, "neck": 0.52, "face": 0.62}
ARM, FORE, THIGH, SHIN = 0.07, 0.06, 0.17, 0.15


def _leg(hip, angle, bend, side_view):
    """(knee, ankle) from the hip, a swing angle (radians, + forward) and a knee bend (radians)."""
    if side_view:
        k = (hip[0] + THIGH * math.sin(angle), hip[1] - THIGH * math.cos(angle))
        a = (k[0] + SHIN * math.sin(angle - bend), k[1] - SHIN * math.cos(angle - bend))
    else:   # seen from the front: a step is a lift, the knee rises toward the camera
        lift = max(0.0, math.sin(angle)) * 0.06
        k = (hip[0], hip[1] - THIGH + lift)
        a = (hip[0], hip[1] - THIGH - SHIN + lift * 1.6)
    return k, a


def _arm(sh, angle, bend, side_view, out=0.0):
    if side_view:
        e = (sh[0] + ARM * math.sin(angle), sh[1] - ARM * math.cos(angle))
        w = (e[0] + FORE * math.sin(angle + bend), e[1] - FORE * math.cos(angle + bend))
    else:
        e = (sh[0] + out, sh[1] - ARM + max(0.0, math.sin(angle)) * 0.03)
        w = (e[0] + out * 0.6, e[1] - FORE + max(0.0, math.sin(angle)) * 0.05)
    return e, w


def fit(sprite):
    """Where this sprite's head and face sit, in figure units (feet 0, top 1): {"x": the head's middle column, and
    when a face shows "face", "neck", "shoulder", "ear"}. The head is the run of columns around the widest one in the
    top 55 % (a bow or a staff does not widen it; the bbox middle sat 0.09 of the height off the scout's head); the
    face is light warm skin in it (the skin test of qa.face_side). A sprite with no face showing keeps H."""
    a = np.asarray(sprite.convert("RGBA")).astype(int)
    op = a[..., 3] > 127
    ys, xs = np.nonzero(op)
    if not len(ys):
        return {"x": 0.0}
    top, bot = ys.min(), ys.max()
    h = bot - top + 1
    rows = slice(top, top + max(4, int(h * 0.55)))
    head = op[rows]
    prof = head.sum(0)
    wide = prof >= 0.35 * prof.max()
    x0 = x1 = int(np.argmax(prof))
    while x0 > 0 and wide[x0 - 1]:
        x0 -= 1
    while x1 < len(wide) - 1 and wide[x1 + 1]:
        x1 += 1
    out = {"x": ((x0 + x1) / 2 - (xs.min() + xs.max()) / 2) / h, "ear": (x1 - x0 + 1) / 2 / h * 0.85}
    r, g, b = (a[rows][..., k] for k in range(3))
    skin = head & (r >= 200) & (g >= 130) & (b >= 100) & (r > g) & (g > b) & (r - b >= 35) & (r - b <= 120)
    skin[:, :x0] = False
    skin[:, x1 + 1:] = False
    sy = np.nonzero(skin)[0]
    if len(sy) < 8:
        return {"x": out["x"]}
    fy = (bot - (sy + top)) / h
    out["face"] = float(np.median(fy))
    out["neck"] = float(np.percentile(fy, 5)) - 0.02      # just under the chin
    out["shoulder"] = out["neck"] - 0.04
    return out


def keypoints(action, t, view, fitted=None):
    """18 (x, y) points in figure units (feet at y = 0, up is +y, x + is the facing side in side view) for loop phase
    t in [0, 1); view "side", "quarter" (three-quarter: the side motion foreshortened, half-width shoulders and hips)
    or "front" ("back" = front or quarter mirrored by the caller); fitted: fit() of the sprite (face, neck, shoulder
    heights and ear spread)."""
    hh = dict(H, **{k: v for k, v in (fitted or {}).items() if k in H})
    ear = (fitted or {}).get("ear", 0.12)
    side = view in ("side", "quarter")
    quarter = view == "quarter"
    ph = 2 * math.pi * t
    lean, bob, jump_y = 0.0, 0.0, 0.0
    swing, bend_k, arm_sw, arm_bend = 0.0, 0.1, 0.0, 0.2
    attack_arm = None
    if action == "walk":
        swing, bob, arm_sw = math.radians(24) * math.sin(ph), 0.012 * math.cos(2 * ph), math.radians(22) * math.sin(ph)
        bend_k = math.radians(28) * max(0.0, -math.sin(ph))
    elif action == "run":
        swing, bob, arm_sw = math.radians(38) * math.sin(ph), 0.025 * math.cos(2 * ph), math.radians(40) * math.sin(ph)
        bend_k, lean, arm_bend = math.radians(55) * max(0.0, -math.sin(ph)), 0.04, 1.2
    elif action == "idle":
        bob = 0.008 * math.sin(ph)
    elif action == "attack":   # wind up behind, swing over and through, back to rest
        a = (math.radians(-130) + math.radians(200) * min(1.0, max(0.0, (t - 0.25) / 0.35))) if t >= 0.25 else \
            math.radians(-40) - math.radians(90) * (t / 0.25)
        if t > 0.75:
            a = a + (math.radians(-20) - a) * ((t - 0.75) / 0.25)
        attack_arm = a
        lean = 0.05 * math.sin(math.pi * min(1.0, t / 0.75))
    elif action == "jump":   # crouch, rise, tuck, land
        crouch = math.sin(math.pi * min(1.0, t / 0.2)) if t < 0.2 else 0.0
        air = math.sin(math.pi * (t - 0.2) / 0.6) if 0.2 <= t <= 0.8 else 0.0
        land = math.sin(math.pi * (t - 0.8) / 0.2) if t > 0.8 else 0.0
        jump_y = 0.18 * air   # higher leaves the model canvas (a 72 px sprite fills 70 % of it)
        bob = -0.08 * (crouch + land)
        bend_k = math.radians(60) * (crouch + land) + math.radians(70) * air
        arm_sw = math.radians(-60) * (crouch + land) + math.radians(150) * air
    else:
        raise ValueError(f"pose action {action!r}: one of {', '.join(ACTIONS)}")
    hip_h = hh["hip"] + bob + jump_y
    x0 = lean
    half_hip, half_sh = (0.05, 0.09) if quarter else (0.02, 0.03) if side else (0.08, 0.15)
    r_hip, l_hip = (x0 - half_hip, hip_h), (x0 + half_hip, hip_h)
    sh_h = hh["shoulder"] + bob + jump_y
    r_sh, l_sh = (x0 + lean - half_sh, sh_h), (x0 + lean + half_sh, sh_h)
    neck = (x0 + lean, hh["neck"] + bob + jump_y)
    rk, ra = _leg(r_hip, swing, bend_k, side)
    lk, la = _leg(l_hip, -swing, bend_k if action in ("jump", "idle") else math.radians(28) * max(0.0, math.sin(ph))
                  if action == "walk" else bend_k, side)
    if attack_arm is not None:
        re_, rw = _arm(r_sh, attack_arm, 0.15, side, -0.06)
        le, lw = _arm(l_sh, math.radians(-20), 0.4, side, 0.06)
    else:
        re_, rw = _arm(r_sh, -arm_sw, arm_bend, side, -0.06)
        le, lw = _arm(l_sh, arm_sw, arm_bend, side, 0.06)
    face = hh["face"] + bob + jump_y
    if side:   # facing +x: the face points forward, one eye and one ear show
        nose = (x0 + lean + 0.12, face)
        r_eye, l_eye = (x0 + lean + 0.09, face + 0.04), (x0 + lean + 0.09, face + 0.04)
        r_ear, l_ear = (x0 + lean - 0.04, face + 0.02), (x0 + lean - 0.04, face + 0.02)
    else:
        nose = (x0, face)
        r_eye, l_eye = (x0 - 0.05, face + 0.04), (x0 + 0.05, face + 0.04)
        r_ear, l_ear = (x0 - ear, face + 0.02), (x0 + ear, face + 0.02)
    pts = [nose, neck, r_sh, re_, rw, l_sh, le, lw, r_hip, rk, ra, l_hip, lk, la, r_eye, l_eye, r_ear, l_ear]
    if quarter:   # turned 45 degrees: motion along the facing axis shows at about 0.7 of its length
        pts = [(x0 + (x - x0) * 0.7, y) for x, y in pts]
    return pts


def canvas_map(sprite_w, sprite_h, pad=8, target=640):
    """(scale, ox, oy): sprite pixel (x, y) sits at canvas (x * scale + ox, y * scale + oy) after SpriteKiln's
    SK_ToCanvas (padding pad, target target x target), so the skeleton lands on the figure."""
    w0, h0 = sprite_w + 2 * pad, sprite_h + 2 * pad
    s = max(1, min(target // w0, target // h0))
    aw, ah = max(w0, target // s), max(h0, target // s)
    px, py = (aw - w0) // 2, (ah - h0) // 2
    return s, (pad + px) * s, (pad + py) * s


def frames(action, direction, sprite, n=33, size=640, pad=8, face=True):
    """n control frames (PIL RGB, size x size) for one clip: the skeleton fitted to the sprite's figure (its height,
    feet line and centre), facing direction (e / w side, s front, n back). One loop over the clip, last = first."""
    im = sprite.convert("RGBA")
    bb = im.getbbox()
    s, ox, oy = canvas_map(im.width, im.height, pad, size)
    fh = (bb[3] - bb[1]) * s
    fitted = fit(im)   # the face and the head, not the bbox: a bow or a staff widens the bbox
    cx = ((bb[0] + bb[2]) / 2) * s + ox + fitted["x"] * fh
    feet = bb[3] * s + oy
    view = "side" if direction in ("e", "w") else "quarter" if len(direction) == 2 else "front"
    flip = -1 if direction in ("w", "sw", "nw") else 1
    out = []
    stick = max(4, round(size / 110))
    for i in range(n):
        t = (i % (n - 1)) / (n - 1)
        kp = keypoints(action, t, view, fitted)
        if direction in ("n", "ne", "nw"):   # seen from behind: the character's right is on the screen's right
            kp = [(-x, y) for x, y in kp]
        pts = [(cx + flip * x * fh, feet - y * fh) for x, y in kp]
        if direction in ("n", "ne", "nw"):   # no face from behind: OpenPose draws nose / eyes only when seen
            for j in (0, 14, 15):
                pts[j] = None
        if not face:   # body only: the reference sprite keeps its own face
            for j in (0, 14, 15, 16, 17):
                pts[j] = None
        img = Image.new("RGB", (size, size), (0, 0, 0))
        d = ImageDraw.Draw(img)
        for k, (a, b) in enumerate(LIMBS):
            if pts[a] is None or pts[b] is None:
                continue
            col = tuple(int(c * 0.6) for c in COLOURS[k])
            d.line([pts[a], pts[b]], fill=col, width=stick)
        for j, p in enumerate(pts):
            if p is not None:
                d.ellipse([p[0] - stick, p[1] - stick, p[0] + stick, p[1] + stick], fill=COLOURS[j])
        out.append(img)
    return out


def control_graph(g, control_names, high, low, drop_loras=()):
    """The SpriteKiln animate graph (wf10, already loaded and saved-path-set) turned into a pose-driven one: the
    Fun-Control models replace the i2v models, Wan22FunControlToVideo replaces WanImageToVideo (the sprite canvas is
    the reference, the uploaded skeleton frames the control video). The rest (prompt preset, two-stage sampling,
    pixel clean-up) is unchanged."""
    i2v = next(k for k, n in g.items() if n["class_type"] == "WanImageToVideo")
    loaders = [k for k, n in g.items() if n["class_type"] == "UnetLoaderGGUF"]
    if len(loaders) != 2:
        raise ValueError("animate graph: expected two GGUF loaders (high and low noise)")
    for k, name in zip(sorted(loaders, key=int), (high, low)):
        g[k]["inputs"]["unet_name"] = name
    for k, n in list(g.items()):   # bypass a LoRA made for the image-to-video model: its output feeds the next node
        if n["class_type"] == "LoraLoaderModelOnly" and n["inputs"]["lora_name"] in drop_loras:
            src = n["inputs"]["model"]
            for m in g.values():
                for key, v in m["inputs"].items():
                    if v == [k, 0]:
                        m["inputs"][key] = src
            del g[k]
    nid = max(int(k) for k in g) + 1
    prev = None
    for j, fn in enumerate(control_names):
        g[str(nid)] = {"class_type": "LoadImage", "inputs": {"image": fn}}
        cur = [str(nid), 0]
        nid += 1
        if prev is not None:
            g[str(nid)] = {"class_type": "ImageBatch", "inputs": {"image1": prev, "image2": cur}}
            cur = [str(nid), 0]
            nid += 1
        prev = cur
    inp = dict(g[i2v]["inputs"])
    ref = inp.pop("start_image", None)
    inp.pop("clip_vision_output", None)
    inp["ref_image"] = ref
    inp["control_video"] = prev
    inp["length"] = len(control_names)
    g[i2v] = {"class_type": "Wan22FunControlToVideo", "inputs": inp}
    return g


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ACTIONS:
        print("usage: python pose.py ACTION DIRECTION OUT_DIR   (ACTION: " + ", ".join(ACTIONS) + "; DIRECTION: s e n w)")
        sys.exit(2)
    os.makedirs(sys.argv[3], exist_ok=True)
    dummy = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
    dummy.paste((200, 100, 60, 255), (24, 6, 48, 70))
    for i, f in enumerate(frames(sys.argv[1], sys.argv[2], dummy)):
        f.save(os.path.join(sys.argv[3], f"pose_{i:02d}.png"))
    print(f"[ OK ] {sys.argv[3]}")
