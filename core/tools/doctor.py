#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# doctor.py
# Purpose : Validate that the project scaffold is healthy: required docs exist,
#           no unresolved {{PLACEHOLDERS}}, HANDOFF not stale, ASSET_LOG matches
#           the assets folder (basic check), Claude config present.
# Usage   : python tools/doctor.py [--debug] [--strict] [--assets-dir DIR]
#           Exit code 0 = healthy, 1 = problems found (or warnings with --strict), 2 = a check itself failed.
# Notes   : Engine-environment checks (is Godot installed, etc.) live in
#           tools/dev.py doctor. This one is engine-agnostic.
#           Standard library only, Python 3.8+.
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-19 with Claude (Opus 5.5, claude-opus-5-5): broken doc reference
#           check (tools/check_links.py), FIRST_HOUR and EVIDENCE now required.
# Updated : 2026-10-20 with Claude (Opus 5.5, claude-opus-5-5): .claude/settings.json must parse
#           and carry deny rules; UTF-8 output, tolerant ASSET_LOG read, each check isolated.
#           Audit pass 7: shared pruning walk with check_links (Unity/VS/CMake caches skipped), kit tokens
#           only, --ignore, HANDOFF 'Last updated' date, filled sample row counts, no .uasset noise
# Updated : 2026-11-03 with Claude (Opus 5.5, claude-opus-5-5): the asset-log check finds public/assets (web, web-3d)
#           and game/img (RPG Maker MZ) too; the placeholder scan reads the overlays' source files and reports the
#           profile tokens ({{FOOTER}} and the like) as well
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): web games get a warning when src/shell/app.ts is
#           present but src/main.ts never reaches it through its imports (the shell sits there unused)
# ---------------------------------------------------------------------------
import argparse
import datetime
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_links  # noqa: E402  (same folder; shares SKIP_DIRS and the pruning walk)

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "CLAUDE.md",
    "README.md",
    "docs/GDD.md",
    "docs/ARCHITECTURE.md",
    "docs/ROADMAP.md",
    "docs/HANDOFF.md",
    "docs/ENGINE.md",
    "docs/ENGINE_FLOW.md",
    "docs/STYLE.md",
    "docs/RESOURCES.md",
    "docs/FIRST_HOUR.md",
    "docs/EVIDENCE.md",
    "docs/BRIEFS.md",
    "docs/ASSET_LOG.md",
    "docs/TROUBLESHOOTING.md",
    "docs/sop/README.md",
    "tools/dev.py",
    ".claude/settings.json",
]
# Only the kit's own tokens (the profile ones too): game data may use {{PLAYER_NAME}} style templates of its own
PLACEHOLDER_RE = re.compile(r"\{\{(?:GAME_NAME|GAME_SLUG|ENGINE|ENGINE_LABEL|DATE|AUTHOR|FOOTER|PROFILE_STYLE|"
                            r"FOOTER_RULE)\}\}")
# Docs and config, plus the source files the overlays ship: a kit file copied back by hand is still a raw template
TEXT_EXT = {".md", ".json", ".py", ".txt", ".toml", ".cfg", ".yml", ".yaml", ".ini",
            ".gd", ".tscn", ".tres", ".godot", ".gdshader",              # Godot
            ".cs", ".asmdef", ".uplugin", ".uproject",                     # Unity, Unreal
            ".cpp", ".hpp", ".h", ".rs", ".lua",                           # C++, Bevy, LÖVE
            ".ts", ".js", ".mjs", ".html", ".css"}                         # web, web-3d, RPG Maker MZ plugins
HANDOFF_STALE_DAYS = 14
# Where each overlay keeps its media (assets_dir in engines/*/engine.json): Godot, Bevy, C++, LÖVE; Unity; Unreal;
# web and web-3d; RPG Maker MZ. The first one present is checked when --assets-dir is not given
ASSET_DIRS = ("assets", "Assets", "Content", "public/assets", "game/img")
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tga", ".psd", ".aseprite", ".pxo", ".ogg", ".wav", ".mp3",
             ".flac", ".aif", ".aiff", ".ttf", ".otf", ".woff", ".woff2", ".glb", ".gltf", ".fbx", ".obj", ".blend"}
# Template files legitimately mention placeholders in prose (they document them).
PLACEHOLDER_ALLOWED = {"tools/doctor.py", "scripts/new_game.py"}
# The web overlay's front end (title, menus, settings, pause): it only runs when the entry module reaches it
SHELL_APP = "src/shell/app.ts"
WEB_ENTRIES = ("src/main.ts", "src/main.js")
SOURCE_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs")
# Runtime imports of a relative module: import x from "./a", import "./a", import("./a"), export { x } from "./a".
# `import type` and `export type` are left out: TypeScript erases them, so they load nothing
IMPORT_RE = re.compile(r"""\bimport(?!\s+type\b)[^'"();]*?\bfrom\s*['"](\.{1,2}/[^'"]+)['"]"""
                       r"""|\bimport\s*\(?\s*['"](\.{1,2}/[^'"]+)['"]"""
                       r"""|\bexport\s+(?!type\b)[^'";]*?\bfrom\s*['"](\.{1,2}/[^'"]+)['"]""")


def log(debug, msg):
    """Print only when --debug is set."""
    if debug:
        print(f"[debug] {msg}")


def check_required(problems):
    for rel in REQUIRED:
        # exact letter case: on Windows docs/gdd.md passed for docs/GDD.md and broke on Linux and CI (#247)
        if not check_links.exact_exists(ROOT, rel):
            problems.append(f"MISSING required file: {rel}" + (" (it exists with other letter case)"
                                                               if (ROOT / rel).exists() else ""))
    check_claude_settings(problems)


def check_claude_settings(problems):
    """Claude Code drops a settings file it cannot parse, and with it every deny rule and the hook."""
    path = ROOT / ".claude" / "settings.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        problems.append(f"INVALID .claude/settings.json ({exc}): Claude Code ignores it, so no deny rules or hooks apply")
        return
    if not (data.get("permissions") or {}).get("deny"):
        problems.append(".claude/settings.json has no permissions.deny rules (secrets are unprotected)")


def check_placeholders(problems, debug, ignore):
    # Same walk as check_links: cache, build and vendored folders are pruned, never opened
    # tools/check_links.ignore applies here too, as the --ignore help says
    for path, rel in check_links.walk(ROOT, tuple(ignore) + tuple(check_links.load_ignore(ROOT))):
        if path.suffix.lower() not in TEXT_EXT:
            continue
        if rel in PLACEHOLDER_ALLOWED or path.name.startswith("doctor.py"):
            continue
        try:
            text = check_links.read_text(path)   # UTF-16 and cp1252 files are read too (#247: they were skipped)
        except OSError as exc:
            log(debug, f"skip unreadable {rel}: {exc}")
            continue
        hits = PLACEHOLDER_RE.findall(text)
        if hits:
            problems.append(f"UNRESOLVED placeholder(s) {sorted(set(hits))} in {rel}")


def check_handoff_age(warnings):
    """Use the **Last updated:** date /end-session writes; file mtime only as a fallback (a clone resets it)."""
    path = ROOT / "docs" / "HANDOFF.md"
    if not path.exists():
        return
    m = re.search(r"\*\*Last updated:\*\*\s*(\d{4}-\d{2}-\d{2})", path.read_text(encoding="utf-8", errors="replace"))
    try:
        when = datetime.date.fromisoformat(m.group(1)) if m else None
    except ValueError:   # a typo such as 2026-02-30: fall back to the file's age
        when = None
    if when:
        age_days = (datetime.date.today() - when).days
        source = f"Last updated {m.group(1)}"
    else:
        age_days = (time.time() - path.stat().st_mtime) / 86400
        source = "file not touched"
    if age_days > HANDOFF_STALE_DAYS:
        warnings.append(f"HANDOFF.md is {age_days:.0f} days old ({source}); run /end-session to refresh it")


def check_assets(warnings, assets_dir, debug):
    """Warn if asset files exist but ASSET_LOG.md still only has the sample row."""
    d = ROOT / assets_dir
    log_file = ROOT / "docs" / "ASSET_LOG.md"
    if not d.exists() or not log_file.exists():
        log(debug, f"assets dir {d} or asset log missing, skipping asset check")
        return
    # .uasset/.umap are left out on purpose: every Unreal Blueprint, map and material is one
    files = [p for p, _ in check_links.walk(d) if p.suffix.lower() in MEDIA_EXT]
    # errors="replace": one cp1252/UTF-16 save must not crash the whole health check
    rows = [l for l in log_file.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("| A-")]
    # A row counts once its "File(s) in repo" column is filled, so filling the sample A-0001 row works
    filled = [r for r in rows if len(r.split("|")) > 3 and r.split("|")[3].strip()]
    log(debug, f"{len(files)} media files, {len(filled)} filled asset log rows")
    if files and not filled:
        # Dotwork packs log themselves from their manifest; point there instead of the hand-written route
        hint = ("run `python tools/art/dotwork/dotwork.py log --pack NAME` for each Dotwork pack, /asset-intake for the rest"
                if list((ROOT / "assets_src" / "dotwork").glob("manifest_*.json")) else "run /asset-intake")
        warnings.append(f"{len(files)} media file(s) under {assets_dir}/ but ASSET_LOG.md has no real entries ({hint})")


def default_assets_dir(root):
    """The first of ASSET_DIRS that exists, matched with exact case at every level (on Linux "assets" and Unity's
    "Assets" are different folders, and Windows would match either); "assets" when none does."""
    for cand in ASSET_DIRS:
        here = root
        for part in cand.split("/"):
            try:
                if part not in os.listdir(here):
                    break
            except OSError:
                break
            here = here / part
        else:
            if here.is_dir():
                return cand
    return "assets"


def resolve_import(src, spec):
    """The source file a relative import names ("./shell/app" -> shell/app.ts), or None outside the tree."""
    base = (src.parent / spec)
    stem = base.with_suffix("") if base.suffix in (".js", ".mjs") else base   # "./a.js" may name a.ts (TS ESM)
    for cand in [base] + [stem.with_name(stem.name + ext) for ext in SOURCE_EXT] + \
                [base / ("index" + ext) for ext in SOURCE_EXT]:
        if cand.suffix in SOURCE_EXT and cand.is_file():
            return cand
    return None


def check_shell_wired(warnings, debug):
    """Web games: warn when src/shell/ is present but the entry module never reaches it (#182: an example kept
    its own main.ts through an upgrade, so the whole front end sat there unused and smoke --drive could not work)."""
    if not (ROOT / SHELL_APP).is_file():
        return
    entry = next((ROOT / e for e in WEB_ENTRIES if (ROOT / e).is_file()), None)
    if entry is None:
        log(debug, f"{SHELL_APP} present but no {' or '.join(WEB_ENTRIES)}, skipping the shell check")
        return
    target = (ROOT / SHELL_APP).resolve()
    seen, todo = set(), [entry.resolve()]
    while todo:                                  # every module the entry loads, through relative imports
        src = todo.pop()
        if src in seen:
            continue
        seen.add(src)
        if src == target:
            log(debug, f"{SHELL_APP} is reached from {entry.relative_to(ROOT).as_posix()}")
            return
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log(debug, f"skip unreadable {src}: {exc}")
            continue
        # Comment lines are dropped (a header's "Usage: import { shell } from ..." loads nothing)
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(("//", "/*", "*")))
        for m in IMPORT_RE.finditer(code):
            found = resolve_import(src, next(g for g in m.groups() if g))
            if found is not None:
                todo.append(found.resolve())
    warnings.append(f"{SHELL_APP} is never imported from {entry.relative_to(ROOT).as_posix()}, so the title, menus, "
                    "settings and pause never run (and `dev.py smoke --drive` cannot): wire it in with /game-shell, "
                    "or delete src/shell/ if the game wants no shell")


def check_doc_links(warnings, debug, ignore):
    """Warn about markdown links and backticked paths that point nowhere (tools/check_links.py)."""
    broken = check_links.scan(ROOT, [], [], ignore)
    for rel, items in broken.items():
        for item in items:
            warnings.append(f"broken doc reference in {rel}: {item}")


def main():
    ap = argparse.ArgumentParser(
        description="Engine-agnostic project health check for the Claude game dev scaffold.",
        epilog="Exit 0 = healthy, 1 = problems, 2 = a check itself failed (a bug: rerun with --debug). Warnings "
               "only fail with --strict.",
    )
    ap.add_argument("--debug", action="store_true", help="print extra detail about what is being checked")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    ap.add_argument("--assets-dir", default=None,
                    help="folder to scan for media files (default: the first of assets, Assets (Unity), Content "
                         "(Unreal), public/assets (web, web-3d), game/img (RPG Maker MZ))")
    ap.add_argument("--ignore", action="append", default=[],
                    help="folder glob to skip in the placeholder and link checks, e.g. --ignore localization (repeatable; "
                         "tools/check_links.ignore is read too)")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # cp1252 pipes on Windows
        except (AttributeError, ValueError):
            pass
    if args.assets_dir is None:
        args.assets_dir = default_assets_dir(ROOT)

    problems, warnings = [], []
    checks = [
        ("required files", lambda: check_required(problems)),
        ("placeholders", lambda: check_placeholders(problems, args.debug, args.ignore)),
        ("handoff age", lambda: check_handoff_age(warnings)),
        ("asset log", lambda: check_assets(warnings, args.assets_dir, args.debug)),
        ("web shell", lambda: check_shell_wired(warnings, args.debug)),
        ("doc links", lambda: check_doc_links(warnings, args.debug, args.ignore)),
    ]
    crashed = False
    for name, check in checks:
        try:
            check()                         # one broken check must not hide the others' results
        except Exception as exc:
            crashed = True
            print(f"[error] the {name} check crashed: {str(exc)[:200]}", file=sys.stderr)
            if args.debug:
                traceback.print_exc()

    for p in problems:
        print(f"[FAIL] {p}")
    for w in warnings:
        print(f"[WARN] {w}")
    if not problems and not warnings and not crashed:
        print("[ OK ] project scaffold looks healthy")
    if crashed:
        return 2
    return 1 if problems or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
