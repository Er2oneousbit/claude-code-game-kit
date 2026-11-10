#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# credits.py
# Purpose : Build CREDITS.md and THIRD_PARTY_LICENSES.md from docs/ASSET_LOG.md (and the license texts in
#           docs/licenses/), so what ships with the game always matches the asset log, and refuse when an asset
#           cannot ship (no license, unknown license, or a PLACEHOLDER).
# Usage   : python tools/credits.py                     # write CREDITS.md and THIRD_PARTY_LICENSES.md at the root
#           python tools/credits.py --check             # exit 1 if they are missing or out of date (CI, release)
#           python tools/credits.py --allow-placeholders  # a test build that still has PLACEHOLDER assets
#           python tools/credits.py --out build/windows # write the two files next to a build
# Exit    : 0 ok, 1 an asset cannot ship or --check found the files stale, 2 usage problem (no asset log)
# Notes   : Reads the ASSET_LOG table (ID, Type, File(s), Source, Author, License, Attribution text, AI-assisted,
#           Modified, Date, Notes); empty template rows are skipped. Third-party files the kit ships in a shell
#           (KIT_ASSETS: the readable font, Bevy's text font) are credited when the game still has them. The engine credit comes from .game-kit.json. The
#           files are generated: edit the asset log, not them. Not legal advice: SOP-21 step 6. Standard library only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): K-0002, the Fira Mono font Bevy's shell ships
# ---------------------------------------------------------------------------
#
# Pseudocode
#   rows = the asset log's table rows with an ID and a file or source -> refuse empty / unknown license, PLACEHOLDER
#   CREDITS.md = engine line + rows grouped by type (author, source, license, attribution, AI note)
#   THIRD_PARTY_LICENSES.md = per license: the assets under it + every text in docs/licenses/ verbatim
#   --check: compare with what is on disk; otherwise write (LF, UTF-8)
import argparse
import json
import re
import sys
import traceback
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
LOG = "docs/ASSET_LOG.md"
# Third-party files the kit itself ships in some engines' shells: credited when the game still has them, so a game
# never has to log them by hand and an engine without them never credits them (#167)
KIT_ASSETS = [
    {"id": "K-0001", "type": "font", "find": "AtkinsonHyperlegible-Regular.ttf",
     "source": "https://github.com/googlefonts/atkinson-hyperlegible", "author": "Braille Institute of America",
     "license": "OFL-1.1",
     "attribution": "Atkinson Hyperlegible, Copyright 2020 Braille Institute of America, Inc. (SIL Open Font License 1.1)",
     "ai": "no", "modified": "no", "date": "", "notes": "kit: the shell's readable-font setting"},
    {"id": "K-0002", "type": "font", "find": "FiraMono-Medium.ttf",
     "source": "https://github.com/mozilla/Fira", "author": "The Mozilla Foundation and Telefonica S.A.",
     "license": "OFL-1.1",
     "attribution": "Fira Mono, Copyright (c) 2012-2015, The Mozilla Foundation and Telefonica S.A. "
                    "(SIL Open Font License 1.1)",
     "ai": "no", "modified": "no", "date": "", "notes": "kit: the shell's text font (Bevy)"},
]
SKIP_DIRS = {".git", "node_modules", ".godot", "build", "dist", "Library", "Temp", "Intermediate", "Saved", "target"}


def kit_rows(root, rows):
    """The KIT_ASSETS rows whose file is in the game (outside build and tool folders) and not logged already."""
    logged = " ".join(r.get("files", "") + " " + r.get("source", "") for r in rows)
    out = []
    for asset in KIT_ASSETS:
        if asset["find"] in logged or asset["source"] in logged:
            continue
        for path in Path(root).rglob(asset["find"]):
            rel = path.relative_to(root)
            if not SKIP_DIRS.intersection(rel.parts[:-1]):
                row = {k: v for k, v in asset.items() if k != "find"}
                row["files"] = rel.parent.as_posix() + "/" + asset["find"]
                out.append(row)
                break
    return out
LICENSES = "docs/licenses"
COLUMNS = ["id", "type", "files", "source", "author", "license", "attribution", "ai", "modified", "date", "notes"]
UNKNOWN = {"", "?", "unknown", "n/a", "tbd", "none"}
# the engine's own credit (what its license asks for); check the engine's license page before shipping
ENGINE_CREDITS = {
    "godot": "Godot Engine (MIT license), Godot Engine contributors: https://godotengine.org/license",
    "love2d": "LÖVE (zlib license), the LÖVE Development Team: https://love2d.org (license.txt ships with the build)",
    "web": "Phaser (MIT license), Phaser Studio Inc: https://phaser.io",
    "web-3d": "Three.js (MIT license), three.js authors: https://threejs.org",
    "bevy": "Bevy Engine (MIT or Apache-2.0), Bevy contributors: https://bevy.org",
    "cpp-sdl2": "SDL3 (zlib license), Sam Lantinga and SDL contributors: https://libsdl.org",
    "unity": "Made with Unity: follow the Unity terms for your plan (splash screen and credit rules) (verify)",
    "unreal": "Unreal Engine: follow the Unreal Engine EULA's credit and notice rules (verify)",
    "rpgmaker-mz": "RPG Maker MZ (Gotcha Gotcha Games, KADOKAWA): follow the RPG Maker MZ EULA (verify)",
}


class ToolError(Exception):
    pass


def parse_log(text):
    """The asset rows of the first table whose header starts with ID."""
    rows, in_table = [], False
    for line in text.splitlines():
        # split on unescaped pipes only: logs write a pipe inside a cell as \| (fetch_asset.md_cell, #247)
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))] \
            if line.strip().startswith("|") else None
        if cells is None:
            if in_table and line.strip():
                break                                       # a heading or prose ends the table; blank lines do not
            continue
        if not in_table:
            if cells and cells[0].lower() == "id":
                in_table = True
            continue
        if all(set(c) <= set("-: ") for c in cells):      # the |---|---| separator
            continue
        row = dict(zip(COLUMNS, cells + [""] * (len(COLUMNS) - len(cells))))
        if not row["id"] or not (row["files"] or row["source"]):
            continue                                        # the template's empty first row
        rows.append(row)
    if not in_table:
        raise ToolError(f"{LOG} has no asset table (a header row starting with | ID |)")
    return rows


def problems(rows, allow_placeholders):
    out = []
    for r in rows:
        if r["license"].lower() in UNKNOWN:
            out.append(f"{r['id']}: no license recorded ({r['files'] or r['source']}): it cannot ship (SOP-04)")
        if "PLACEHOLDER" in r["notes"].upper() and not allow_placeholders:
            out.append(f"{r['id']}: marked PLACEHOLDER: replace it before release (or --allow-placeholders for a "
                       "test build)")
    return out


def engine_line(root):
    """The engine credit, or "" when .game-kit.json is missing, not JSON, not an object or names no engine string
    (a list or a quoted string there was a traceback, #261)."""
    try:
        meta = json.loads((root / ".game-kit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    engine = meta.get("engine", "") if isinstance(meta, dict) else ""
    return ENGINE_CREDITS.get(engine, "") if isinstance(engine, str) else ""


def credits_md(rows, root):
    lines = ["# Credits", "", "<!-- Generated by tools/credits.py from docs/ASSET_LOG.md: edit the asset log, "
             "not this file. -->", ""]
    eng = engine_line(root)
    if eng:
        lines += ["## Engine", "", f"- {eng}", ""]
    by_type = {}
    for r in rows:
        by_type.setdefault(r["type"] or "Other", []).append(r)
    for kind in sorted(by_type, key=str.lower):
        lines += [f"## {kind}", ""]
        for r in by_type[kind]:
            what = r["files"] or r["id"]
            who = r["author"] or "unknown author"
            text = r["attribution"] or f"{what} by {who}"
            extra = [f"license: {r['license']}"]
            if r["source"]:
                extra.append(f"source: {r['source']}")
            if r["ai"].lower() in ("pre-generated", "live"):
                extra.append(f"made with AI assistance ({r['ai']})")
            if r["modified"].lower() not in ("", "no"):
                extra.append("modified")
            lines.append(f"- {text} ({'; '.join(extra)})")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def licenses_md(rows, root):
    lines = ["# Third-party licenses", "", "<!-- Generated by tools/credits.py from docs/ASSET_LOG.md and "
             "docs/licenses/: edit those, not this file. -->", ""]
    by_license = {}
    for r in rows:
        by_license.setdefault(r["license"], []).append(r)
    lines += ["## Assets by license", ""]
    for lic in sorted(by_license, key=str.lower):
        ids = ", ".join(f"{r['id']} ({r['files'] or r['source']})" for r in by_license[lic])
        lines.append(f"- **{lic}**: {ids}")
    lines.append("")
    folder = root / LICENSES
    texts = sorted(p for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []
    if texts:
        lines += ["## License texts", ""]
        for p in texts:
            body = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").rstrip("\n")
            lines += [f"### {p.relative_to(folder).as_posix()}", "", "```", body, "```", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build CREDITS.md and THIRD_PARTY_LICENSES.md from docs/ASSET_LOG.md.")
    ap.add_argument("--root", default=str(ROOT), help="the game's root folder (default: this project)")
    ap.add_argument("--out", default="", help="where to write the two files (default: the root)")
    ap.add_argument("--check", action="store_true", help="exit 1 if the files are missing or out of date")
    ap.add_argument("--allow-placeholders", action="store_true", help="do not fail on PLACEHOLDER rows")
    ap.add_argument("--debug", action="store_true", help="tracebacks on errors")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    out = Path(args.out).resolve() if args.out else root
    try:
        log = root / LOG
        if not log.is_file():
            raise ToolError(f"{log} not found (run from the game's root or pass --root)")
        try:
            rows = parse_log(log.read_text(encoding="utf-8-sig"))   # a BOM hid the table (#258)
        except UnicodeDecodeError:   # a log saved as cp1252 or UTF-16 was a traceback, exit 1 (#247)
            raise ToolError(f"{log} is not UTF-8 text: save it as UTF-8 (in VS Code: the encoding in the status bar)")
        rows += kit_rows(root, rows)
        bad = problems(rows, args.allow_placeholders)
        files = {"CREDITS.md": credits_md(rows, root), "THIRD_PARTY_LICENSES.md": licenses_md(rows, root)}
    except (ToolError, OSError) as exc:
        print(f"[error] {exc}")
        if args.debug:
            traceback.print_exc()
        return 2
    for line in bad:
        print(f"[FAIL] {line}")
    if args.check:
        stale = [n for n, t in files.items() if not (out / n).is_file()
                 or (out / n).read_bytes().replace(b"\r\n", b"\n") != t.encode("utf-8")]
        for n in files:
            print(f"[{'FAIL' if n in stale else ' OK '}] {n}" + (" is out of date: run python tools/credits.py"
                                                                 if n in stale else ""))
        return 1 if stale or bad else 0
    if bad:
        print("[FAIL] nothing written: fix the asset log first")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out / name).write_bytes(text.encode("utf-8"))
        print(f"[ OK ] wrote {(out / name)} ({len(rows)} asset(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
