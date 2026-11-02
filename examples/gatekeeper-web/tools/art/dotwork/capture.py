#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# capture.py
# Purpose : trailer and review frames from any scene of the game with Godot's Movie Maker: a fixed frame rate, every
#           frame written (no drops, the same frames on every run), then an optional GIF and a contact strip.
# Usage   : python dotwork.py capture --scene res://assets/art/screens/loading/screen_loading.tscn --frames 90
#           [--fps 30] [--size 640x360] [--out assets_src/captures/loading] [--gif]
# Notes   : Movie Maker renders in a real window (headless Godot has no renderer), so a window opens for the length of
#           the capture. Godot writes <out>/frame00000000.png ... (and frame.wav with the game's audio). The kit's own
#           tools/capture.gd (dev.py smoke --record) takes real-time bursts of the running game; this one steps time
#           exactly, for trailer cuts and side-by-side reviews. Exit 0 ok, 1 Godot failed or wrote the wrong number of
#           frames, 2 usage.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import os
import re

import numpy as np
from PIL import Image

import fcore
import godotrun


def parse_size(s):
    m = re.fullmatch(r"(\d{2,5})x(\d{2,5})", str(s or ""))
    if not m:
        raise fcore.ToolError(f"--size {s!r}: use WIDTHxHEIGHT, such as 640x360")
    return int(m.group(1)), int(m.group(2))


def build_cmd(godot, project, scene_res, out_dir, frames, fps, size=None):
    """The Movie Maker command line: --write-movie with a .png path writes a numbered PNG sequence; --fixed-fps steps
    game time exactly; --quit-after ends it after `frames` frames."""
    cmd = [godot, "--path", project, "--write-movie", os.path.join(out_dir, "frame.png"), "--fixed-fps", str(fps),
           "--quit-after", str(frames)]
    if size:
        cmd += ["--resolution", f"{size[0]}x{size[1]}"]
    return cmd + [scene_res]


def collect(out_dir):
    """The PNG frames Godot wrote, in order."""
    return sorted(glob.glob(os.path.join(out_dir, "frame[0-9]*.png")))


def differ(a_path, b_path):
    """Changed pixels between two frames (0 = identical)."""
    a = np.array(Image.open(a_path).convert("RGB"), np.int16)
    b = np.array(Image.open(b_path).convert("RGB"), np.int16)
    if a.shape != b.shape:
        return a.shape[0] * a.shape[1]
    return int((np.abs(a - b).sum(2) > 0).sum())


def gif(frames, path, fps):
    ims = [Image.open(f).convert("RGB") for f in frames]
    ims[0].save(path, save_all=True, append_images=ims[1:], duration=max(10, round(1000 / fps)), loop=0,
                optimize=False)
    return path


def strip(frames, path, n=6, height=180):
    """n frames spread over the capture side by side (review only: scaled to a fixed height)."""
    pick = [frames[round(i * (len(frames) - 1) / max(1, n - 1))] for i in range(min(n, len(frames)))]
    tiles = []
    for f in pick:
        im = Image.open(f).convert("RGB")
        tiles.append(im.resize((max(1, round(im.width * height / im.height)), height), Image.NEAREST))
    sheet = Image.new("RGB", (sum(t.width + 4 for t in tiles) + 4, height + 8), (30, 30, 36))
    x = 4
    for t in tiles:
        sheet.paste(t, (x, 4))
        x += t.width + 4
    sheet.save(path)
    return path


def run(settings, scene, frames=90, fps=30, size=None, out=None, make_gif=False):
    godotrun.project_ok(settings)
    if frames < 2:
        raise fcore.ToolError("--frames must be at least 2")
    if not 1 <= fps <= 240:
        raise fcore.ToolError("--fps must be between 1 and 240")
    if scene.startswith("res://"):
        scene_res = scene
        local = os.path.join(settings.project, scene[len("res://"):])
    else:
        local = fcore.contained(scene, settings.project, what="scene")
        scene_res = godotrun.res_of(settings, local)
    if not os.path.isfile(local):
        raise fcore.ToolError(f"scene {scene} not found in the game")
    name = os.path.splitext(os.path.basename(local))[0]
    out_dir = fcore.contained(out, settings.project, what="--out") if out else os.path.join(
        settings.project, settings.conf["fixed"]["src_dir"], "captures", name)
    os.makedirs(out_dir, exist_ok=True)
    for old in collect(out_dir):   # a shorter capture must not leave the last run's tail behind
        os.remove(old)
    cmd = build_cmd(godotrun.godot_bin(settings.conf), settings.project, scene_res, out_dir, frames, fps, size)
    fcore.log(f"capture {name}: {frames} frames at {fps} fps (a Godot window opens for the capture)")
    code, log = fcore.run(cmd, cwd=settings.project, timeout=max(120, frames // fps * 4 + 120))
    got = collect(out_dir)
    result = {"scene": scene_res, "out": out_dir, "frames": len(got), "fps": fps, "exit": code}
    if code != 0 or len(got) < frames:
        tail = "\n".join(log.splitlines()[-8:])
        raise fcore.JobError(f"capture {name}: Godot exit {code}, {len(got)} of {frames} frames written\n{tail}")
    result["first_last_changed_px"] = differ(got[0], got[-1])
    result["strip"] = strip(got, os.path.join(out_dir, f"{name}_strip.png"))
    if make_gif:
        result["gif"] = gif(got, os.path.join(out_dir, f"{name}.gif"), fps)
    return result
