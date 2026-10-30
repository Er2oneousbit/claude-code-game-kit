#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# godotrun.py
# Purpose : run Godot 4 against the game project itself: find the binary, import the project (the game's own
#           tools/dev.py import when it has one, else `godot --headless --import`), and run a headless GDScript that
#           Dotwork writes into its work folder (mapbuild painting, verify loading).
# Usage   : imported by mapbuild.py and verify.py
# Notes   : The Godot binary comes from GODOT_BIN or dotwork.config.json "godot_bin" (the kit uses GODOT_BIN too).
#           Scripts and job files live under <work_dir> (inside the project, so they have res:// paths) and are
#           removed after each run.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os
import re
import sys

import fcore


def godot_bin(conf):
    b = conf["fixed"].get("godot_bin") or os.environ.get("GODOT_BIN", "")
    if not b:
        raise fcore.ToolError("Godot not configured: set GODOT_BIN (or godot_bin in dotwork.config.json) to your Godot 4 "
                              "binary")
    if not os.path.exists(b):
        raise fcore.ToolError(f"Godot binary {b} not found")
    return b


def project_ok(settings):
    if not os.path.exists(os.path.join(settings.project, "project.godot")):
        raise fcore.ToolError(f"{settings.project} has no project.godot (run Dotwork from the Godot game's folder, or "
                              "pass --project; plain sheets need --engine none)")


def crashed(code, out):
    """Godot died (access violation / signal) rather than reporting errors: a direct exit code outside 0-255, or the
    kit's dev.py relaying one as "import failed (exit N)"."""
    if code < 0 or code > 255 or code in (134, 139):
        return True
    m = re.search(r"failed \(exit (-?\d+)\)", out)
    return bool(m) and (int(m.group(1)) < 0 or int(m.group(1)) > 255)


def import_project(settings):
    """(exit code, output): the game's own import step when it has tools/dev.py, else Godot's --import.
    Godot 4.7 crashed once mid-import of fresh .fnt fonts (access violation; the next run imported cleanly), so a
    crash is retried once and noted at the top of the output. Import errors are never retried."""
    gb = godot_bin(settings.conf)
    dev = os.path.join(settings.project, "tools", "dev.py")
    if os.path.exists(dev):
        cmd = [sys.executable, dev, "--godot", gb, "import"]
    else:
        cmd = [gb, "--headless", "--path", settings.project, "--import"]
    code, out = fcore.run(cmd, cwd=settings.project, timeout=900)
    if not crashed(code, out):
        return code, out
    fcore.log(f"Godot crashed during import (exit {code}); retrying once")
    code, out = fcore.run(cmd, cwd=settings.project, timeout=900)
    return code, "[Dotwork] Godot crashed on the first import attempt; this is the retry\n" + out


def smoke(settings):
    dev = os.path.join(settings.project, "tools", "dev.py")
    if not os.path.exists(dev):
        return None, "no tools/dev.py: smoke test skipped"
    return fcore.run([sys.executable, dev, "--godot", godot_bin(settings.conf), "smoke"], cwd=settings.project,
                     timeout=900)


def res_of(settings, path):
    return "res://" + os.path.relpath(path, settings.project).replace(os.sep, "/")


def run_script(settings, name, gd_text, args=(), timeout=900):
    """Write <work>/<name>.gd, run it headless with `-- args`, remove it. Returns (exit code, output)."""
    gd = os.path.join(settings.work, f"{name}.gd")
    fcore.write_text(gd, gd_text)
    try:
        return fcore.run([godot_bin(settings.conf), "--headless", "--path", settings.project, "--script",
                          res_of(settings, gd), "--", *map(str, args)], cwd=settings.project, timeout=timeout)
    finally:
        for p in (gd, gd + ".uid"):
            try:
                os.remove(p)
            except OSError:
                pass
