#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# sync_examples.py
# Purpose : Kit maintenance: bring every game in examples/ up to the current kit. Each example is copied to a work
#           folder outside the repo (the scaffolder refuses a destination inside the kit), upgraded there with
#           new_game.py --upgrade, and every kit file whose upgraded copy is the pristine kit version is copied back.
# Usage   : python scripts/sync_examples.py <scratch>/sync1                  # all examples
#           python scripts/sync_examples.py <scratch>/sync2 --only coyote-hop ghost-lantern
#           Run it twice (two fresh folders): the second run must report "0 synced" everywhere.
# Exit    : 0 ok, 1 an upgrade failed (any nonzero scaffolder exit, including 1 = unresolved placeholders) or a
#           conflict (.gold) needs a hand merge, 2 usage or the work folder cannot be created
# Notes   : Syncs by CONTENT, not by parsing the scaffolder's output: a file is copied back when its upgraded copy matches
#           the hash recorded in .game-kit.json (so it is the kit's version) and differs from the example's. Files the
#           game edited are never overwritten: the scaffolder leaves the kit's version as <file>.gold in the work
#           folder; merge those by hand. Name and engine come from each example's .game-kit.json. Keep the work
#           folder short on Windows (C++ and Unreal hit path limits). Heavy folders (node_modules, Library, ...) are
#           not copied.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-30 with Claude (Opus 5.5, claude-opus-5-5): a scaffolder exit 1 fails the example (nothing copied
#           back, its [WARN] lines shown), work folder errors exit 2, numbered .goldN copies are reported
# Updated : 2026-11-01 with Claude (Opus 5.5, claude-opus-5-5): a run with nothing to sync leaves the example untouched
#           (it used to copy .game-kit.json back anyway, adding one history entry per run)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   for each example with a .game-kit.json: copy (skipping heavy folders) -> new_game.py --upgrade on the copy
#   -> nonzero exit: [FAIL] with the scaffolder's [WARN] lines, copy nothing back
#   -> for each tracked file: copy back if upgraded == recorded hash != example
#   -> copy back .gitignore and .claude/settings.json when the upgrade changed them
#   -> copy back .game-kit.json only when something above changed, a .gold conflict is open, or its recorded state
#      (version, hashes, ...) moved; never just for the upgrade's own history entry
#   -> report synced files and any .gold conflicts
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
EXAMPLES = KIT / "examples"
GOLD_RE = re.compile(r"\.gold\d*$")       # conflict copies new_game.py writes: x.gd.gold, x.gd.gold2, ...
SKIP = shutil.ignore_patterns(".git", "node_modules", "dist", "build", ".godot", ".asset_cache", "__pycache__",
                              "Binaries", "Intermediate", "Saved", "DerivedDataCache", "Content", "Packaged",
                              "Library", "Temp", "Logs", "UserSettings", "Build", "*.slnx", "*.csproj", "*.sln",
                              "vcpkg_installed", "addons", "models")


def file_hash(path):
    """SHA-256 the way the scaffolder records hashes: CRLF folded to LF for UTF-8 text, raw bytes for binary files
    (a PNG's signature itself holds a CRLF, so folding every file kept binary kit files from ever syncing)."""
    data = path.read_bytes()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return hashlib.sha256(data).hexdigest()
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def recorded_state(meta):
    """.game-kit.json without the upgrade's own log: what a no-op upgrade must leave exactly as it was."""
    return {k: v for k, v in meta.items() if k not in ("history", "last_upgrade")}


def sync_one(src, work):
    meta = json.loads((src / ".game-kit.json").read_text(encoding="utf-8"))
    tmp = work / src.name
    shutil.copytree(src, tmp, ignore=SKIP)
    r = subprocess.run([sys.executable, "-B", str(KIT / "scripts" / "new_game.py"), "--name", meta["game_name"],
                        "--engine", meta["engine"], "--dest", str(tmp), "--upgrade"],
                       capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        # Exit 1 means unresolved placeholders in the kit's output: copying that back would spread the breakage
        out = r.stdout + r.stderr
        warns = [l.strip() for l in out.splitlines() if l.lstrip().startswith(("[WARN]", "[error]"))]
        detail = "\n       ".join(warns) if warns else out[-600:]
        return None, [f"upgrade failed (exit {r.returncode}), nothing copied back:\n       {detail}"]
    upgraded = json.loads((tmp / ".game-kit.json").read_text(encoding="utf-8"))
    synced = []
    for rel, recorded in upgraded["files"].items():
        a, b = tmp / rel, src / rel
        if a.is_file() and file_hash(a) == recorded and (not b.is_file() or file_hash(b) != recorded):
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(a, b)
            synced.append(rel)
    # .gitignore is not hash-tracked (core part + the engine's lines); settings.json neither: the upgrade merges the
    # kit's rules into the game's file (lists unioned, the game's own rules kept). Each comes back when it changed.
    for rel in (".gitignore", ".claude/settings.json"):
        a, b = tmp / rel, src / rel
        if a.is_file() and (not b.is_file() or file_hash(a) != file_hash(b)):
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(a, b)
            synced.append(rel)
    # .gold, .gold2, ... (the scaffolder numbers a new copy when an older one is mid-merge); not e.g. x.golden.png
    golds = sorted(p.relative_to(tmp).as_posix() for p in tmp.rglob("*.gold*")
                   if p.is_file() and GOLD_RE.search(p.name))
    # The upgrade always appends a history entry. Bring the file back only when the sync did something, a conflict
    # needs recording, or the recorded state moved; otherwise every no-op run would grow every example's history.
    if synced or golds or recorded_state(upgraded) != recorded_state(meta):
        shutil.copy2(tmp / ".game-kit.json", src / ".game-kit.json")
    return synced, golds


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Upgrade every example to the current kit through a copy outside the repo.",
                                 epilog="Exit codes: 0 ok, 1 an upgrade failed (any nonzero scaffolder exit) or a "
                                        ".gold conflict needs a hand merge, 2 usage or the work folder cannot be "
                                        "created.")
    ap.add_argument("work", help="a NEW folder outside the repo for the copies (short path on Windows)")
    ap.add_argument("--only", nargs="*", help="example folder names (default: every example with a .game-kit.json)")
    args = ap.parse_args(argv)
    work = Path(args.work).resolve()
    if work.exists():
        print(f"[error] {work} exists; use a fresh folder", file=sys.stderr)
        return 2
    if KIT in work.parents or work == KIT:
        print("[error] the work folder must be outside the kit", file=sys.stderr)
        return 2
    examples = sorted(p.parent for p in EXAMPLES.glob("*/.game-kit.json"))
    if args.only:
        examples = [p for p in examples if p.name in args.only]
        missing = sorted(set(args.only) - {p.name for p in examples})
        if missing:
            print(f"[error] not an example: {', '.join(missing)}", file=sys.stderr)
            return 2
    try:
        work.mkdir(parents=True)
    except OSError as exc:
        print(f"[error] cannot create the work folder {work}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    code = 0
    for src in examples:
        synced, golds = sync_one(src, work)
        if synced is None:
            print(f"[FAIL] {src.name}: {golds[0]}")
            code = 1
            continue
        print(f"[ OK ] {src.name}: {len(synced)} synced" + (f" {synced}" if synced else ""))
        if golds:
            print(f"[warn] {src.name}: hand-merge the kit's version into the game's file: {', '.join(golds)} "
                  f"(in {work / src.name})")
            code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
