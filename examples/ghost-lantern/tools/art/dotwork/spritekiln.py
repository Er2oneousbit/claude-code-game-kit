#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# spritekiln.py
# Purpose : load SpriteKiln's API-format workflows (rotation, animation, edits, inpaint, normal maps) from the
#           user's own SpriteKiln clone and apply Dotwork's runtime patches. Dotwork bundles none of SpriteKiln's files
#           (GPL-3.0); the node pack and its workflows are installed by the user (README: Setup).
# Usage   : g = spritekiln.load("10_animate_sprite")     # workflows/api/<NN>_<name>.api.json
#           spritekiln.check()                           # used by `dotwork.py setup --check`
# Notes   : Found via SPRITEKILN_ROOT (the repo clone: it holds ComfyUI-SpriteKiln/ and workflows/api/) or the
#           config key spritekiln_root. The pinned commit is the one Dotwork was tested against; a different commit is
#           a warning (node inputs may have moved), a missing clone is a setup error.
#           Patches: any FLUX.2 VAE -> the Apache-2.0 klein VAE (the flux2-dev VAE file is non-commercial).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import json
import os

import fcore

PINNED = "864d188071ed45e6f673029d2bc7eb918e17edd7"   # brunocpf/spritekiln, audited 2026-10-28
USED = ["04_edit_pixel_art", "05_inpaint_pixel_art", "07_rotate_hq_qwen_multiangle", "10_animate_sprite",
        "28_sprite_normal_maps"]
KLEIN_VAE = "flux2-vae-klein.safetensors"
_CONF = None


def _lines(path, **kw):
    """The file's lines, closed afterwards."""
    with open(path, **kw) as f:
        return f.read().splitlines(True)


def bind(conf):
    global _CONF
    _CONF = conf


def root():
    r = (_CONF or {}).get("spritekiln_root") or os.environ.get("SPRITEKILN_ROOT", "")
    if not r:
        raise fcore.ToolError("SpriteKiln not configured: clone it (README: Setup, 'Node packs') and set SPRITEKILN_ROOT "
                              "or spritekiln_root in dotwork.config.json")
    if not os.path.isdir(os.path.join(r, "workflows", "api")):
        raise fcore.ToolError(f"SPRITEKILN_ROOT={r} has no workflows/api/ folder (point it at the SpriteKiln repo clone, "
                              "the folder that holds ComfyUI-SpriteKiln/ and workflows/)")
    return r


def commit(r):
    """The clone's HEAD commit (plain file read: no git needed), or None."""
    head = os.path.join(r, ".git", "HEAD")
    try:
        ref = open(head, encoding="utf-8").read().strip()
        if ref.startswith("ref:"):
            p = os.path.join(r, ".git", *ref[5:].strip().split("/"))
            if os.path.exists(p):
                return open(p, encoding="utf-8").read().strip()
            packed = os.path.join(r, ".git", "packed-refs")
            for line in _lines(packed, encoding="utf-8"):
                if line.strip().endswith(ref[5:].strip()):
                    return line.split()[0]
            return None
        return ref
    except OSError:
        pinned = os.path.join(r, "PINNED.txt")   # a copy without .git (the quarantine review's PINNED record)
        if os.path.exists(pinned):
            txt = open(pinned, encoding="utf-8").read()
            return PINNED if PINNED in txt else txt.split("@")[-1].split()[0] if "@" in txt else None
        return None


def path(name):
    r = root()
    hits = glob.glob(os.path.join(r, "workflows", "api", f"*{name}.api.json"))
    if not hits:
        raise fcore.ToolError(f"SpriteKiln workflow {name}.api.json not found under {r}/workflows/api (wrong commit? "
                              f"Dotwork expects {PINNED[:12]})")
    return hits[0]


def load(name):
    """The workflow as an API graph, with the klein VAE swapped in."""
    with open(path(name), encoding="utf-8") as f:
        g = json.load(f)
    for n in g.values():
        if n.get("class_type") == "VAELoader" and n["inputs"].get("vae_name") == "flux2-vae.safetensors":
            n["inputs"]["vae_name"] = KLEIN_VAE
    return g


def check():
    """[(level, message)] for `dotwork.py setup --check`."""
    out = []
    try:
        r = root()
    except fcore.ToolError as exc:
        return [("error", str(exc))]
    c = commit(r)
    if c is None:   # a copy without .git (the quarantine routine copies without it): fine, but unconfirmed
        out.append(("warn", f"SpriteKiln at {r} has no .git to read its commit from: make sure it is "
                            f"{PINNED[:12]} (README: Setup 2)"))
    elif c != PINNED:
        out.append(("warn", f"SpriteKiln at {r} is commit {str(c)[:12]}, Dotwork was tested on {PINNED[:12]} "
                            "(workflow node ids may differ)"))
    else:
        out.append(("ok", f"SpriteKiln {PINNED[:12]} at {r}"))
    for n in USED:
        try:
            path(n)
        except fcore.ToolError as exc:
            out.append(("error", str(exc)))
    if not os.path.isdir(os.path.join(r, "ComfyUI-SpriteKiln")):
        out.append(("warn", "ComfyUI-SpriteKiln/ not in the clone: make sure the node pack is installed in "
                            "ComfyUI/custom_nodes (README: Setup)"))
    return out
