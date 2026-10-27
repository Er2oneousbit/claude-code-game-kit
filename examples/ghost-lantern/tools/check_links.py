#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# check_links.py
# Purpose : Find broken references in the project's markdown: relative links like
#           [text](docs/GDD.md) and backticked paths like `docs/sop/SOP-09-testing.md`.
#           Docs that point at files which moved or never existed confuse both
#           humans and Claude, so this runs in doctor.py and before releases.
# Usage   : python tools/check_links.py [--root DIR] [--also DIR ...] [--ignore NAME ...] [--debug]
#           Examples:
#             python tools/check_links.py                       # this project
#             python tools/check_links.py --root ../kit --also core --also core/docs
# Exit    : 0 no broken references, 1 broken references found, 2 usage problem
# Notes   : A backticked token counts as a path only if it contains a slash or ends in
#           .md/.py/.json/.txt/.cfg, and has no spaces, wildcards, <placeholders>, double-brace
#           tokens, or template names (NNNN, snake_case, PascalCase, ...).
#           Paths with a folder resolve against: the file's own folder, the root, every --also
#           folder, and docs/. A bare file name passes if that file exists anywhere in the project.
#           Files that only appear later (CREDITS.md, settings.local.json, engine export
#           presets) are skipped by default. External URLs and #anchors are not checked.
#           Standard library only, Python 3.8+.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-10-21 (audit pass 7): skipped folders pruned while walking (shared with doctor.py), vendored
#           addons/Plugins/Packages and tools/check_links.ignore skipped, URI schemes, anchors, %20, <...>,
#           titles, reference links, ~~~ fences and inline code handled, links resolve from their own file,
#           exact letter case enforced
# ---------------------------------------------------------------------------
#
# Pseudocode
#   collect *.md under root (skip build and cache folders)
#   for each file: strip fenced code blocks, find markdown links and backticked paths
#   for each reference: skip URLs, anchors, placeholders, ignored names
#                       try each search base; if none exists, record it as broken
#   print broken references grouped by file, return exit code
import argparse
import fnmatch
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

# Folders never scanned, at any depth: VCS, engine caches and build output. Shared with doctor.py.
SKIP_DIRS = {".git", ".godot", ".import", "build", "Binaries", "Intermediate", "Saved", "DerivedDataCache", "Packaged",
             "node_modules", "__pycache__", ".venv", "venv", "env", ".mono", "Library", "Temp", "Logs", "obj",
             "UserSettings", "MemoryCaptures", ".vs", "out", "vcpkg_installed"}
SKIP_PREFIXES = ("cmake-build-",)
# Third-party trees engines keep inside the project (their docs are not yours to fix). Relative-path globs.
VENDOR_GLOBS = ("addons/*", "Plugins/*", "Packages/*")
IGNORE_FILE = "tools/check_links.ignore"   # optional: one glob per line, a folder to skip or a target to never report
URI = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)          # http:, res://, user://, mailto:, ...
# [text](dest) or [text](<dest with spaces>), with an optional "title"
MD_LINK = re.compile(r"\[[^\]]*\]\(\s*(<[^>\n]*>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
MD_REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>\n]*>|\S+)", re.M)   # [ref]: dest
BACKTICK = re.compile(r"`([^`\n]+)`")
PATHY_EXT = (".md", ".py", ".json", ".txt", ".cfg", ".gd", ".cs", ".cpp", ".hpp")
# Files the docs mention on purpose before they exist (generated at release time, personal, or engine-made).
LATER_FILES = {"CREDITS.md", "settings.local.json", ".claude/settings.local.json", "check_links.ignore",  # optional
               "export_presets.cfg", "export_credentials.cfg",          # Godot export
               "CMakeUserPresets.json",                                 # personal CMake presets
               "package-lock.json",                                     # web: written by the first npm install
               "Build.cs",                                              # Unreal <Module>.Build.cs
               "DefaultEngine.ini", "DefaultCrypto.ini",                # Unreal Config/, written by the editor
               "ProjectVersion.txt", "ProjectSettings/ProjectVersion.txt",  # written by Unity
               "game/game.rmmzproject", "game/package.json", "Actors.json",  # RPG Maker MZ: from the editor's new
               "js/plugins.js", "game/js/plugins.js", "js/main.js"}           # project (dev.py setup --from)
TEMPLATE_MARKERS = ("NNNN", "snake_case", "PascalCase", "...", "<", "{{", "/.", "Thing")
DEBUG = False


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


def load_ignore(root):
    """Globs from tools/check_links.ignore (blank lines and # comments skipped)."""
    try:
        lines = (root / IGNORE_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


def skipped_dir(rel, extra_globs):
    """True for a folder (path relative to the root, posix) that must not be walked."""
    name = rel.rsplit("/", 1)[-1]
    if name in SKIP_DIRS or name.startswith(SKIP_PREFIXES):
        return True
    return any(fnmatch.fnmatch(rel, g.rstrip("/")) for g in tuple(VENDOR_GLOBS) + tuple(extra_globs))


def walk(root, extra_globs=()):
    """Yield every file under root as (Path, rel_posix), pruning skipped folders instead of walking them."""
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        rel_dir = base.relative_to(root).as_posix()
        dirnames[:] = [d for d in dirnames
                       if not skipped_dir(d if rel_dir == "." else f"{rel_dir}/{d}", extra_globs)]
        for f in filenames:
            p = base / f
            yield p, p.relative_to(root).as_posix()


def strip_code(text):
    """Remove fenced blocks (``` and ~~~) and inline code spans: they hold examples, not links."""
    text = re.sub(r"^(```|~~~).*?^\1", "", text, flags=re.S | re.M)
    return text


def clean_target(raw):
    """<a b.md> -> a b.md, %20 -> space, drop ?query and #fragment."""
    t = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
    t = re.split(r"[?#]", t, maxsplit=1)[0]
    return unquote(t)


def looks_like_path(token):
    """Heuristic so we only check things a reader would try to open."""
    if URI.match(token):
        return False                       # res://scenes/main.tscn, user://, http:// ...
    token = re.split(r"[?#]", token, maxsplit=1)[0]
    if not token:
        return False
    if any(ch in token for ch in " *<>{}|$=,;()") or token.startswith(("-", "/", "~", "@")):
        return False
    if any(m in token for m in TEMPLATE_MARKERS):
        return False
    if token.endswith("/"):
        token = token[:-1]
    if "/" in token:
        last = token.rsplit("/", 1)[-1]
        return "." in last or last in ("sop", "adr", "resources", "evidence", "skills", "agents", "tools", "docs")
    return token.endswith(PATHY_EXT) and token[0].isalpha() and token.count(".") == 1


def references(text):
    """Yield (kind, target) for every relative link, reference definition and path-like backtick token."""
    body = strip_code(text)
    prose = BACKTICK.sub("", body)        # links inside inline code are examples
    for rx in (MD_LINK, MD_REF_DEF):
        for m in rx.finditer(prose):
            raw = m.group(1)
            if URI.match(raw.strip("<>")) or raw.startswith("#"):
                continue
            target = clean_target(raw)
            if target:
                yield "link", target
    for m in BACKTICK.finditer(body):
        tok = m.group(1).strip()
        if looks_like_path(tok):
            yield "path", tok.rstrip("/").split("#", 1)[0]


def exact_exists(base, target):
    """exists() with the exact letter case: NTFS and APFS ignore case, Linux, CI and GitHub do not."""
    cur = base
    for part in Path(target).parts:
        if part in ("", "."):
            continue
        if part == "..":
            cur = cur.parent
            continue
        try:
            names = os.listdir(cur)
        except OSError:
            return False
        if part not in names:
            return False
        cur = cur / part
    return True


def resolves(kind, target, md_file, bases, all_names):
    """Links resolve from their own file (as GitHub and VS Code do); backticked paths may also resolve from a base."""
    if kind == "link":
        if target.startswith("/"):
            return exact_exists(bases[0], target.lstrip("/"))
        return exact_exists(md_file.parent, target)
    for base in [md_file.parent] + bases:
        if exact_exists(base, target):
            return True
    return "/" not in target and target in all_names


def scan(root, also, ignore, skip_dirs=()):
    """Return {file: [broken targets]} for every markdown file under root (vendored and cache trees skipped)."""
    root = Path(root)
    bases = [root] + [root / a for a in also] + [root / "docs"]
    file_globs = load_ignore(root)
    extra_dirs = tuple(skip_dirs) + tuple(file_globs)
    files = list(walk(root, extra_dirs))
    all_names = {p.name for p, _ in files}
    ignore = set(ignore) | LATER_FILES
    broken = {}
    for md, rel in sorted(files, key=lambda x: x[1]):
        if md.suffix.lower() != ".md":
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            dbg(f"skip {md}: {exc}")
            continue
        for kind, target in references(text):
            name = target.rsplit("/", 1)[-1]
            if name in ignore or target in ignore or any(fnmatch.fnmatch(target, g) for g in file_globs):
                continue
            if target.lstrip("./").split("/", 1)[0] in SKIP_DIRS:
                continue                    # inside a generated folder (node_modules/, build/, ...): exists only after setup
            if not resolves(kind, target, md, bases, all_names):
                broken.setdefault(rel, []).append(f"{kind}: {target}")
    return broken


def main():
    global DEBUG
    ap = argparse.ArgumentParser(description="Find broken relative links and backticked file paths in markdown.",
                                 epilog=f"Folders in {IGNORE_FILE} (one glob per line) are skipped too; vendored "
                                        f"{', '.join(VENDOR_GLOBS)} are skipped by default. "
                                        "Exit 0 clean, 1 broken references, 2 usage problem.")
    ap.add_argument("--root", default=None, help="folder to scan (default: the project root above tools/)")
    ap.add_argument("--also", action="append", default=[], help="extra folder (relative to root) to resolve paths against")
    ap.add_argument("--ignore", action="append", default=[], help="file name or path to never report (repeatable)")
    ap.add_argument("--skip-dir", action="append", default=[], help="folder glob relative to root to skip (repeatable)")
    ap.add_argument("--debug", action="store_true", help="print skipped files")
    args = ap.parse_args()
    DEBUG = args.debug
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows pipes default to cp1252
        except (AttributeError, ValueError):
            pass
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    if not root.is_dir():
        print(f"[ENV ] root is not a folder: {root}", file=sys.stderr)
        return 2
    broken = scan(root, args.also, args.ignore, args.skip_dir)
    total = sum(len(v) for v in broken.values())
    for f, items in broken.items():
        for item in items:
            print(f"[FAIL] {f}: {item}")
    print(f"{total} broken reference(s) in {len(broken)} file(s)" if total else "[ OK ] no broken references")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
