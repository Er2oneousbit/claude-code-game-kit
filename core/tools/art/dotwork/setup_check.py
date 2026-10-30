#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# setup_check.py
# Purpose : `dotwork.py setup --check`: is this machine ready to run Dotwork? Python + Pillow + numpy, the kit's
#           comfy_local.py, a ComfyUI server (version, GPU), every node class Dotwork's graphs and the SpriteKiln
#           workflows use, every model in models.lock.json (asked from the server's own loader lists, so it works for
#           any ComfyUI install), the SpriteKiln clone and its pinned commit, Godot, Aseprite (optional), palettes.
# Usage   : python dotwork.py setup --check [--tier sprites|rotate|animate|all] [--hash]
# Notes   : Never downloads anything: missing models are listed with their pinned URL and the ComfyUI models/
#           folder they belong in. --hash also checks SHA-256 (needs COMFYUI_ROOT; reads tens of GB).
#           Exit 0 when every check for the chosen tier passes (warnings allowed), 2 when something must be set up.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os
import platform
import sys

import fcore
import spritekiln

CORE_NODES = ["UNETLoader", "LoraLoaderModelOnly", "CLIPLoader", "VAELoader", "CLIPTextEncode", "ConditioningZeroOut",
              "LoadImage", "ImageScaleToTotalPixels", "VAEEncode", "ReferenceLatent", "LoadImageMask",
              "SetLatentNoiseMask", "Flux2Scheduler", "SplitSigmasDenoise", "EmptyFlux2LatentImage", "RandomNoise",
              "CFGGuider", "KSamplerSelect", "SamplerCustomAdvanced", "VAEDecode", "SaveImage"]
TIER_WORKFLOWS = {"sprites": ["04_edit_pixel_art", "05_inpaint_pixel_art", "28_sprite_normal_maps"],
                  "rotate": ["07_rotate_hq_qwen_multiangle"], "animate": ["10_animate_sprite"]}


def say(level, msg, results):
    tag = {"ok": "[ OK ]", "warn": "[warn]", "error": "[FAIL]", "info": "[info]"}[level]
    print(f"{tag} {msg}")
    results.append(level)


def model_lines(m):
    """One model as two lines: the name to save it under (when the download is named differently), size, licence,
    the ComfyUI folder and the pinned URL."""
    up = m["path"].rsplit("/", 1)[-1]
    name = m["file"] if up == m["file"] else f"{m['file']}  (save it under this name; the download is called {up})"
    return (f"         {name}  ({m['size'] / 1024 ** 3:.1f} GB, {m['license']})\n"
            f"           -> ComfyUI/models/{m['folder']}/   {m['url']}")


def tier_line(t, tinfo, models):
    gb = sum(m["size"] for m in models) / 1024 ** 3
    return (f"tier {t}: {len(models)} files, {gb:.1f} GB; an NVIDIA GPU with {tinfo['vram_gb']} GB VRAM and "
            f"{tinfo['ram_gb']} GB RAM ({tinfo['for']})")


def run(settings, a):
    import engine
    r = []
    tiers = ["sprites", "rotate", "animate"] if a.tier == "all" else [a.tier]
    say("ok" if sys.version_info >= (3, 8) else "error",   # the kit's floor
        f"Python {platform.python_version()} ({sys.executable})" + ("" if sys.version_info >= (3, 8) else ": 3.8+ needed"), r)
    try:
        import numpy
        import PIL
        say("ok", f"Pillow {PIL.__version__}, numpy {numpy.__version__}", r)
    except ImportError as exc:
        say("error", f"missing Python package: {exc.name} (pip install pillow numpy, or use the ComfyUI venv's Python)", r)
    if engine.cl is None:
        say("error", "the kit's tools/art/comfy_local.py is not next to dotwork/ (Dotwork runs from the kit's tools/art/)", r)
        return 2
    if settings.is_game():
        say("ok", f"game project {settings.project} ({'Godot' if settings.godot() else 'engine none'})", r)
    else:   # pack and the other writing commands refuse this folder; say so here first
        want = "project.godot" if settings.godot() else "project.godot, .game-kit.json or CLAUDE.md"
        say("warn", f"{settings.project} is not a game folder (no {want}): run Dotwork from the game's root folder or "
                    "pass --project GAME", r)
    # ComfyUI
    try:
        base = engine.base_url()
        stats = engine.cl.get_json(base, "/system_stats")
        say("ok", engine.cl.system_text(stats), r)
        info = engine.cl.get_json(base, "/object_info")
    except fcore.ToolError as exc:
        say("error", str(exc), r)
        info = None
    # SpriteKiln clone
    for level, msg in spritekiln.check():
        say(level, msg, r)
    if info is None:   # still show what to download: a newcomer usually has no ComfyUI running yet
        lock = fcore.load_lock()
        say("info", "models from models.lock.json, NOT checked against ComfyUI (start it and re-run to see which are "
                    "missing):", r)
        for t in tiers:
            models = [m for m in lock["models"] if m["tier"] == t]
            print(f"       {tier_line(t, lock['tiers'][t], models)}")
            for m in models:
                print(model_lines(m))
    if info is not None:
        need = set(CORE_NODES)
        for t in tiers:
            for wf in TIER_WORKFLOWS[t]:
                try:
                    need |= {n["class_type"] for n in spritekiln.load(wf).values()}
                except fcore.ToolError:
                    pass
        missing = sorted(need - set(info))
        if missing:
            say("error", f"node types missing in ComfyUI: {', '.join(missing)}. Install the node packs (README: Setup, "
                         "review them first), restart ComfyUI", r)
        else:
            say("ok", f"all {len(need)} node types Dotwork uses are installed", r)
        lock = fcore.load_lock()
        for t in tiers:
            models = [m for m in lock["models"] if m["tier"] in (t,)]
            miss = []
            for m in models:
                node = info.get(m["loader"], {})
                opts = (node.get("input", {}).get("required", {}).get(m["input"]) or [[]])[0]
                opts = opts if isinstance(opts, list) else []
                if m["file"] not in [str(o).replace("\\", "/").split("/")[-1] for o in opts]:
                    miss.append(m)
            tinfo = lock["tiers"][t]
            if miss:
                say("error", f"{tier_line(t, tinfo, models)}: {len(miss)} of {len(models)} model files missing", r)
                for m in miss:
                    print(model_lines(m))
            else:
                say("ok", f"tier {t}: all {len(models)} model files present ({tinfo['for']})", r)
    if a.hash:   # reads the files from disk: needs COMFYUI_ROOT, not a running server (it used to be skipped then)
        root = settings.conf["comfyui"].get("root")
        if not root:
            say("warn", "--hash needs COMFYUI_ROOT (the model files are read from disk)", r)
        else:
            lock = fcore.load_lock()
            for m in [m for m in lock["models"] if m["tier"] in tiers]:
                p = os.path.join(root, "models", m["folder"], m["file"])
                if os.path.exists(p):
                    ok = fcore.sha256_file(p) == m["sha256"]
                    say("ok" if ok else "error", f"{m['file']} SHA-256 {'matches' if ok else 'DIFFERS from'} the lock", r)
                else:
                    say("info", f"{m['file']}: not on disk, nothing to hash", r)
    # Godot / Aseprite / palettes
    gb = settings.conf["fixed"].get("godot_bin") or os.environ.get("GODOT_BIN")
    if settings.godot():
        if gb and os.path.exists(gb):
            code, out = fcore.run([gb, "--version"], timeout=60)
            say("ok" if code == 0 else "warn", f"Godot {out.strip().splitlines()[-1] if out.strip() else '?'} ({gb})", r)
        else:
            say("error", "Godot not found: set GODOT_BIN (maps and verify need it; or use --engine none)", r)
    ab = settings.conf["fixed"].get("aseprite_bin") or os.environ.get("ASEPRITE_BIN")
    say("ok" if ab and os.path.exists(ab) else "info",
        f"Aseprite {'at ' + ab if ab and os.path.exists(ab) else 'not set (optional: the hand-polish round trip)'}", r)
    for key in ("palette", "env_palette"):
        p = settings.conf["fixed"][key]
        say("ok" if os.path.exists(p) else "error", f"{key}: {p}", r)
    refs = settings.conf.get("style_refs") or []
    say("info", f"style_refs: {len(refs)} of your own sprites" if refs else
        "style_refs: none (fine; 3-4 of your own sprites make new art match them more closely)", r)
    bad = "error" in r
    print(f"\n{'[FAIL] setup incomplete: fix the [FAIL] lines above (README: Setup)' if bad else '[ OK ] ready'}")
    return 2 if bad else 0
