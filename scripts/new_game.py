#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# new_game.py
# Purpose : Scaffold a new game project (or adopt an existing one) from the
#           Claude Code Game Kit: universal core + one engine overlay.
# Usage   : python scripts/new_game.py --name "My Game" --engine godot --dest ../my-game
#           python scripts/new_game.py --name "Moon Hopper" --engine godot --dest ../moon-hopper --git-init
#           python scripts/new_game.py --name "Tank Duel" --engine unreal --dest ../TankDuel --adopt
#           python scripts/new_game.py --list-engines
#           (add -h for every option)
# Notes   : - Core (core/) lands in every project: CLAUDE.md, docs/, SOPs, skills,
#             subagents, hooks, doctor script.
#           - Overlay (engines/<id>/) adds: docs/ENGINE.md, docs/ENGINE_FLOW.md,
#             skeleton files (incl. tools/dev.py), .gitignore additions, permissions.
#           - New engines: copy engines/_template (see its README), no code changes needed.
#           - --adopt never overwrites existing files. Conflicts are written next to
#             the original as <file>.gold (engines ignore it) so you can merge by hand.
#           - --upgrade also replaces kit files you never edited, using the content
#             hashes recorded in .game-kit.json; edited files get a .gold copy.
#           Standard library only, Python 3.8+.
#
# Pseudocode:
#   parse args -> validate (name, engine, dest) -> build placeholder map
#   -> plan {dst: content} from core/, then engine docs and skeleton/ (engine wins)
#   -> for each: new -> write; same -> skip; upgrade + untouched hash -> replace;
#      adopt/upgrade + differs -> <file>.gold; else --force or error (all writes atomic)
#   -> merge .gitignore and .claude/settings.json, write metadata
#   -> verify no unresolved placeholders in written files -> print next steps
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): UTF-8 output, accent-folding slugs
#           and --slug, control-character checks on --name/--author, adopt appends to .gitignore
#           without rewriting it, engine adopt_hints. Audit pass 5: .gold suffix engines ignore,
#           --upgrade with content hashes, atomic writes, stable DATE on re-adopt, dest outside the kit
# ---------------------------------------------------------------------------
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import traceback
import unicodedata
from pathlib import Path

KIT_VERSION = "0.6.0"  # bump with CHANGELOG.md entries
REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "core"
ENGINES_DIR = REPO_ROOT / "engines"
GITIGNORE_MARKER = "# ---- Claude Code Game Kit ----"
LEGACY_GITIGNORE_MARKERS = ("# ---- Claude Game Dev Gold Standard ----",)   # projects made before the rename
GOLD_SUFFIX = ".gold"                     # x.gd -> x.gd.gold: engines do not compile or import it
META_FILE = ".game-kit.json"             # version, profile, history and per-file hashes for --upgrade
LEGACY_META_FILE = ".gold-standard.json" # same file before the 0.3.0 rename; read, then replaced
PROFILES_DIR = REPO_ROOT / "profiles"
FOOTER_LINE = re.compile(r"^(?P<indent>[ \t]*)(?P<mark>#|//|--)[ \t]*\{\{FOOTER\}\}[ \t]*$", re.M)
FOOTER_GONE = re.compile(r"(?:^[ \t]*\n)?^[ \t]*(?:#|//|--)[ \t]*\{\{FOOTER\}\}[ \t]*(?:\n|\Z)", re.M)
STYLE_LINE = re.compile(r"^[ \t]*\{\{PROFILE_STYLE\}\}[ \t]*\n?", re.M)
FOOTER_RULE_LINE = re.compile(r"^[ \t]*\{\{FOOTER_RULE\}\}[ \t]*$", re.M)
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")
# Junk and tool output that may sit in an overlay folder while the kit is being worked on (never ship them)
SKIP_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db", "node_modules", ".godot", "vcpkg_installed", "build", "dist"}
# The slug becomes a CMake target and a C# namespace: these break the build, so they get a _game suffix
RESERVED_SLUGS = {
    # CMake: reserved target names, and the C++ skeleton's own targets
    "all", "clean", "help", "install", "test", "package", "core", "game_lib", "unit_tests", "project_warnings",
    # C# keywords (all lowercase, so any one-word title can hit one)
    "abstract", "as", "base", "bool", "break", "byte", "case", "catch", "char", "checked", "class", "const",
    "continue", "decimal", "default", "delegate", "do", "double", "else", "enum", "event", "explicit", "extern",
    "false", "finally", "fixed", "float", "for", "foreach", "goto", "if", "implicit", "in", "int", "interface",
    "internal", "is", "lock", "long", "namespace", "new", "null", "object", "operator", "out", "override",
    "params", "private", "protected", "public", "readonly", "ref", "return", "sbyte", "sealed", "short",
    "sizeof", "stackalloc", "static", "string", "struct", "switch", "this", "throw", "true", "try", "typeof",
    "uint", "ulong", "unchecked", "unsafe", "ushort", "using", "virtual", "void", "volatile", "while",
    # Rust keywords (cargo refuses them as package names) and crate names a Bevy game's package would clash with
    "async", "await", "become", "box", "crate", "dyn", "final", "fn", "gen", "impl", "let", "loop", "macro",
    "match", "mod", "move", "mut", "priv", "pub", "self", "super", "trait", "type", "unsized", "use", "where",
    "yield", "std", "alloc", "proc_macro", "bevy",
}
SKIP_SUFFIXES = {".pyc"}

DEBUG = False


def dbg(msg):
    """Print only with --debug."""
    if DEBUG:
        print(f"[debug] {msg}")


class ScaffoldError(Exception):
    """A user-facing error: message is shown without a traceback."""


# ---- Engine discovery ---------------------------------------------------------
def load_engines():
    """Return {id: metadata dict} for every engines/*/engine.json (skips _template)."""
    engines = {}
    if not ENGINES_DIR.exists():
        raise ScaffoldError(f"engines folder missing: {ENGINES_DIR}")
    for d in sorted(ENGINES_DIR.iterdir()):
        meta_file = d / "engine.json"
        if d.name.startswith("_") or not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScaffoldError(f"bad engine.json in {d.name}: {exc}")
        meta["_dir"] = d
        engines[meta.get("id", d.name)] = meta
    return engines


# ---- Helpers ------------------------------------------------------------------
def make_slug(name, override=None):
    """'My Cool Game!' -> 'my_cool_game', 'Café Über' -> 'cafe_uber'. Always starts with a letter (CMake/identifier safe)."""
    if override:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", override):
            raise ScaffoldError("--slug must be lowercase letters, digits and _, starting with a letter (e.g. my_game)")
        if override in RESERVED_SLUGS:
            raise ScaffoldError(f"--slug {override!r} is reserved (a CMake target, C# or Rust keyword, or crate name); try {override}_game")
        return override
    # Fold accents to ASCII first so letters are kept, not dropped (é -> e, Ō -> O)
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", folded).strip("_").lower()
    if not slug:
        raise ScaffoldError("the game name has no Latin letters or digits to build a code-safe slug from "
                            "(CMake target, C# namespace). Pass one with --slug, e.g. --slug my_game")
    if not slug[0].isalpha():
        slug = "game_" + slug
    if slug in RESERVED_SLUGS:
        print(f"[info] '{slug}' is reserved (a CMake target, C# or Rust keyword, or crate name); using slug '{slug}_game' "
              f"(pass --slug to choose another)")
        slug += "_game"
    return slug


def validate_text_arg(flag, value):
    """Reject values that would corrupt generated files: control characters, or bytes the terminal could not decode."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ScaffoldError(f"{flag} contains bytes that are not valid text in this terminal's encoding. "
                            "Use a UTF-8 terminal (Linux/macOS: LANG=C.UTF-8) or set PYTHONUTF8=1.")
    if any(unicodedata.category(ch) == "Cc" for ch in value):
        raise ScaffoldError(f"{flag} must not contain control characters (newlines, tabs, escapes)")


def validate_name(name):
    if not name or not name.strip():
        raise ScaffoldError("--name must not be empty")
    validate_text_arg("--name", name)
    if any(ch in name for ch in '"\\{}'):
        raise ScaffoldError('--name must not contain quotes, backslashes, or braces (they break generated config files)')


def substitute(text, mapping):
    """Fill placeholders. Profile lines first: a `# {{FOOTER}}` or `// {{FOOTER}}` line becomes the footer comment,
    or disappears when the profile has none; a `{{PROFILE_STYLE}}` line becomes the profile's bullets (or nothing)."""
    footer = mapping.get("_FOOTER", "")
    if footer:
        text = FOOTER_LINE.sub(lambda m: f"{m.group('indent')}{m.group('mark')} {footer}", text)
    else:
        text = FOOTER_GONE.sub("", text)   # drop the line and the blank line above it
    style = mapping.get("_STYLE", [])
    text = STYLE_LINE.sub(lambda m: "".join(f"- {s}\n" for s in style), text)
    rule = (f"Last line of every new source file and tool script, as a comment in the file's syntax: `{footer}`. "
            "Not in generated files, data files, or third-party code." if footer else
            "No footer line is required (the project profile sets none).")
    text = FOOTER_RULE_LINE.sub(lambda _m: rule, text)   # a function: a backslash in the footer is not a regex escape
    for key, val in mapping.items():
        if not key.startswith("_"):
            text = text.replace("{{" + key + "}}", val)
    return text


def load_profile(path):
    """Read and validate a profile JSON (author, footer, style). Returns a dict with those three keys."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScaffoldError(f"cannot read profile {path}: {exc.strerror or exc}")
    except ValueError as exc:
        raise ScaffoldError(f"profile {path} is not valid JSON: {exc}")
    prof = {"author": raw.get("author", ""), "footer": raw.get("footer", ""), "style": raw.get("style", [])}
    if not isinstance(prof["author"], str) or not isinstance(prof["footer"], str) or \
            not isinstance(prof["style"], list) or not all(isinstance(s, str) for s in prof["style"]):
        raise ScaffoldError(f"profile {path}: author and footer must be text, style a list of text lines")
    for flag, val in [("profile author", prof["author"]), ("profile footer", prof["footer"])] + \
            [("profile style line", s) for s in prof["style"]]:
        validate_text_arg(flag, val)
    return prof


def git_user_name():
    """`git config user.name`, or '' when git or the setting is missing."""
    try:
        r = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, timeout=5,
                           encoding="utf-8", errors="replace")   # a name like "Łukasz" crashed cp1252 decoding
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def iter_files(base):
    """Yield (relative_path, absolute_path) for every file under base, skipping junk."""
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        # Filter on the path inside base, never the absolute path (a parent folder may share a name)
        if any(part in SKIP_NAMES for part in rel.parts) or p.suffix in SKIP_SUFFIXES:
            continue
        yield rel, p


def deep_merge(base, patch):
    """Merge patch into base. Lists are unioned (order kept), dicts merged recursively, scalars: patch wins."""
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            out[k] = deep_merge(out[k], v) if k in out else v
        return out
    if isinstance(base, list) and isinstance(patch, list):
        out = list(base)
        out.extend(x for x in patch if x not in out)
        return out
    return patch


def digest(data):
    """Content hash used to tell 'kit file the user never touched' from 'user edited it'."""
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    """Write bytes via a temp file + rename, so a kill or full disk never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".newgame-tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def gold_name(rel, dest, data):
    """Conflict copy name the engines ignore: x.gd -> x.gd.gold, then x.gd.gold2, ...

    Returns (alt, already_there). An existing .gold with the same content is reused; one the user
    edited (mid-merge) is never overwritten: the next free number is used instead.
    """
    for n in range(1, 100):
        alt = rel.with_name(rel.name + GOLD_SUFFIX + ("" if n == 1 else str(n)))
        p = dest / alt
        if not p.exists():
            return alt, False
        if p.is_file() and p.read_bytes().replace(b"\r\n", b"\n") == data:
            return alt, True
    raise ScaffoldError(f"too many .gold copies of {rel}; merge or delete them first")


# ---- Plan + write -------------------------------------------------------------
class Writer:
    """Writes files honoring --dry-run / --adopt / --upgrade / --force and tracks what happened.

    mode: "new" (empty folder), "adopt" (never overwrite) or "upgrade" (overwrite only files whose
    content still matches the hash recorded when the kit last wrote them).
    """

    def __init__(self, dest, mapping, dry_run, mode, force, prev_hashes):
        self.dest, self.mapping = dest, mapping
        self.dry_run, self.mode, self.force = dry_run, mode, force
        self.prev_hashes = prev_hashes
        self.hashes = {}            # rel -> hash of the kit version now in place (feeds the next --upgrade)
        self.created, self.skipped, self.conflicts, self.overridden, self.upgraded = [], [], [], [], []
        self.kept_deleted = []      # --upgrade: kit files the project deleted on purpose, left out
        self.written = []           # every path this run wrote (placeholder check scans only these)

    def _write(self, rel, data):
        dbg(f"write {rel}")
        if not self.dry_run:
            atomic_write(self.dest / rel, data)
        self.written.append(rel.as_posix())

    def write(self, rel, data, is_text):
        """Place one kit file. Text is compared with CRLF folded to LF on both sides."""
        rel = Path(rel)
        key = rel.as_posix()
        target = self.dest / rel
        new_hash = digest(data)
        if not target.exists():
            # --upgrade: a kit file this project had (it is in the record) and no longer has was deleted on purpose,
            # e.g. a starter test for a rule the game replaced. Leave it out; only files new to the project are added.
            if self.mode == "upgrade" and key in self.prev_hashes:
                self.kept_deleted.append(key)
                return
            self._write(rel, data)
            self.created.append(key)
            self.hashes[key] = new_hash
            return
        current = target.read_bytes()
        if is_text:
            current = current.replace(b"\r\n", b"\n")
        if current == data:
            self.skipped.append(key)
            self.hashes[key] = new_hash
            return
        prev = self.prev_hashes.get(key)    # hash of what the kit wrote here last time, if recorded
        if self.mode == "upgrade" and prev == digest(current):
            # Untouched since the kit wrote it: safe to replace with the new version
            self._write(rel, data)
            self.upgraded.append(key)
            self.hashes[key] = new_hash
            return
        if self.mode in ("adopt", "upgrade") and prev == new_hash:
            # The kit's version has not changed; the difference is the user's own edit (e.g. their GDD)
            self.skipped.append(f"{key} (your edits; kit version unchanged)")
            self.hashes[key] = prev
            return
        if self.mode in ("adopt", "upgrade"):
            alt, already_there = gold_name(rel, self.dest, data)
            if not already_there:
                self._write(alt, data)
            self.conflicts.append((key, alt.as_posix(), not already_there))
            # Baseline = the kit version just offered in the .gold copy: the next --upgrade stays quiet
            # unless the kit changes this file again (otherwise a merged file would conflict forever)
            self.hashes[key] = new_hash
            return
        if not self.force:
            raise ScaffoldError(f"{rel} already exists. Use --adopt to keep existing files or --force to overwrite.")
        self._write(rel, data)
        self.created.append(key)
        self.hashes[key] = new_hash


def plan_tree(plan, base, mapping, label):
    """Add base/ to plan {rel: (bytes, is_text)}; later entries replace earlier ones (engine beats core)."""
    for rel, src in iter_files(base):
        key = rel.as_posix()
        if key in (".gitignore", ".claude/settings.json"):
            continue  # merged separately
        raw = src.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            plan[key] = (raw, False)
            continue
        if key in plan:
            dbg(f"{label} overrides {key}")
        # Generated text is always LF, whatever line endings the kit checkout has
        plan[key] = (substitute(text, mapping).replace("\r\n", "\n").encode("utf-8"), True)


def merge_gitignore(writer, core_text, engine_text):
    """Compose the .gitignore: universal + engine block. In adopt mode append once to an existing file."""
    block = f"{GITIGNORE_MARKER}\n{core_text.rstrip()}\n\n{engine_text.strip()}\n" if engine_text else f"{GITIGNORE_MARKER}\n{core_text.rstrip()}\n"
    block = block.replace("\r\n", "\n")
    target = writer.dest / ".gitignore"
    if target.exists() and writer.mode in ("adopt", "upgrade"):
        # The user's bytes (any encoding, CRLF or LF) are kept exactly; the block is added after them
        existing = target.read_bytes()
        eol = b"\r\n" if b"\r\n" in existing else b"\n"
        lead = b"" if not existing or existing.endswith(b"\n") else eol
        if any(m.encode("utf-8") in existing for m in (GITIGNORE_MARKER,) + LEGACY_GITIGNORE_MARKERS):
            # The kit block is there. --upgrade appends only the rules a newer kit added (never removes or reorders);
            # --adopt leaves the file alone, so a rule the user deleted on purpose stays deleted.
            have = {l.strip() for l in existing.decode("utf-8", "replace").splitlines()}
            missing = [l.strip() for l in block.splitlines() if l.strip() and not l.lstrip().startswith("#") and l.strip() not in have]
            if writer.mode != "upgrade" or not missing:
                writer.skipped.append(".gitignore (already has the kit block)")
                return
            add = f"# ---- Claude Code Game Kit {KIT_VERSION}: rules added by --upgrade ----\n" + "\n".join(missing) + "\n"
            data = existing + lead + eol + add.replace("\n", eol.decode()).encode("utf-8")
            writer.overridden.append(f".gitignore ({len(missing)} new kit rule(s) appended: {', '.join(missing)})")
            writer._write(Path(".gitignore"), data)
            return
        data = existing + lead + eol + block.replace("\n", eol.decode()).encode("utf-8")
        writer.overridden.append(".gitignore (block appended)")
    elif target.exists() and not writer.force:
        raise ScaffoldError(".gitignore already exists. Use --adopt or --force.")
    else:
        data = block.encode("utf-8")
    writer._write(Path(".gitignore"), data)
    writer.created.append(".gitignore")


def merge_settings(writer, core_settings, patch):
    """Compose .claude/settings.json from core + engine patch (+ existing file when adopting)."""
    merged = deep_merge(core_settings, patch) if patch else core_settings
    target = writer.dest / ".claude" / "settings.json"
    if target.exists() and writer.mode in ("adopt", "upgrade"):
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ScaffoldError(f"existing .claude/settings.json is not valid JSON ({exc}). Fix it, then re-run.")
        merged = deep_merge(existing, merged)
        if merged == existing:
            writer.skipped.append(".claude/settings.json (already has every kit rule)")
            return
        writer.overridden.append(".claude/settings.json (kit rules merged into yours)")
    elif target.exists() and not writer.force:
        raise ScaffoldError(".claude/settings.json already exists. Use --adopt or --force.")
    writer._write(Path(".claude/settings.json"), (json.dumps(merged, indent=2) + "\n").encode("utf-8"))
    writer.created.append(".claude/settings.json")


def verify_no_placeholders(dest, written):
    """Return 'relpath: [tokens]' for unresolved {{PLACEHOLDERS}} in files this run wrote (never the user's own files)."""
    problems = []
    for rel in written:
        if Path(rel).name.startswith("doctor.py"):
            continue  # doctor.py contains the placeholder pattern on purpose (and so does its .gold copy)
        try:
            text = (dest / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = sorted(set(PLACEHOLDER_RE.findall(text)))
        if hits:
            problems.append(f"{rel}: {hits}")
    return problems


def load_meta(dest):
    """Existing project metadata (.game-kit.json, or the pre-0.3.0 .gold-standard.json), or {}."""
    for name in (META_FILE, LEGACY_META_FILE):
        try:
            return json.loads((dest / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def git_init(dest):
    """git init on branch main (the SOPs assume it); never commits."""
    if (dest / ".git").exists():
        print("[info] .git already exists, skipping git init")
        return
    try:
        if subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest).returncode != 0:
            # git older than 2.28 has no -b
            subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
            subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=dest, check=True)
        print("[ OK ] git init (branch main)")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[warn] git init failed: {exc}", file=sys.stderr)


# ---- Main flow ----------------------------------------------------------------
def scaffold(args):
    engines = load_engines()
    if args.list_engines:
        print("Available engines:")
        for eid, meta in engines.items():
            print(f"  {eid:<10} {meta.get('label', '')}\n             {meta.get('summary', '')}")
        print("\nAdd more by copying engines/_template (see its README).")
        return 0

    if not args.name:
        raise ScaffoldError("--name is required (or use --list-engines)")
    if not args.engine:
        raise ScaffoldError(f"--engine is required. Choose one of: {', '.join(engines)}")
    validate_name(args.name)
    if args.author is not None:
        validate_text_arg("--author", args.author)
    if args.engine not in engines:
        raise ScaffoldError(f"unknown engine {args.engine!r}. Available: {', '.join(engines)}")
    if not CORE_DIR.exists():
        raise ScaffoldError(f"core folder missing: {CORE_DIR}")

    meta = engines[args.engine]
    slug = make_slug(args.name, args.slug)
    dest = Path(args.dest).expanduser().resolve() if args.dest else (Path.cwd() / slug).resolve()
    mode = "upgrade" if args.upgrade else "adopt" if args.adopt else "new"

    if dest == REPO_ROOT or REPO_ROOT in dest.parents:
        raise ScaffoldError(f"{dest} is inside the kit. Pass --dest with a folder outside it, e.g. --dest D:/games/{slug}")
    if dest.exists() and not dest.is_dir():
        raise ScaffoldError(f"{dest} exists and is not a directory")
    if mode == "new" and dest.exists() and any(dest.iterdir()) and not args.force:
        raise ScaffoldError(f"{dest} is not empty. Use --adopt to add the kit to an existing project (never overwrites), "
                            "--upgrade for a project made with an earlier kit, or --force.")
    if mode != "new" and not dest.exists():
        raise ScaffoldError(f"--{mode} needs an existing folder, {dest} does not exist (omit --{mode} for a new project)")

    old = load_meta(dest) if mode != "new" else {}
    prev_hashes = old.get("files", {})
    if mode == "upgrade" and not prev_hashes:
        print("[info] this project has no file hashes (made with kit 0.2.1 or earlier, or never adopted), so --upgrade "
              "cannot tell which files you edited. Every file that differs gets a .gold copy; after merging, the next "
              "--upgrade replaces untouched files automatically.")
    # Profile: --profile wins; on adopt/upgrade reuse the one recorded in the metadata (same render, same hashes)
    if args.profile:
        profile = load_profile(args.profile)
    elif old.get("profile"):
        profile = {"author": old["profile"].get("author", ""), "footer": old["profile"].get("footer", ""),
                   "style": old["profile"].get("style", [])}
    else:
        profile = load_profile(PROFILES_DIR / "default.json")
    author = args.author or profile["author"] or old.get("author") or git_user_name() or "the owner"
    today = datetime.date.today().isoformat()
    mapping = {
        "GAME_NAME": args.name.strip(),
        "GAME_SLUG": slug,
        "ENGINE": args.engine,
        "ENGINE_LABEL": meta.get("label", args.engine),
        # Re-adopting keeps the original date, so untouched files compare equal on any later day
        "DATE": old.get("scaffolded", today),
        "AUTHOR": author,
        "_FOOTER": profile["footer"],
        "_STYLE": profile["style"],
    }
    dbg(f"mapping: {mapping}")
    dbg(f"dest: {dest} mode: {mode}")

    edir = meta["_dir"]
    writer = Writer(dest, mapping, args.dry_run, mode, args.force, prev_hashes)
    if not args.dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    # 1-4) Plan every kit file first (engine entries replace core ones), then write each once
    plan = {}
    plan_tree(plan, CORE_DIR, mapping, "core")
    for key, out_name in (("engine_md", "docs/ENGINE.md"), ("flow_md", "docs/ENGINE_FLOW.md")):
        src = edir / meta.get(key, "")
        if not src.is_file():
            raise ScaffoldError(f"engine {args.engine}: missing {meta.get(key)!r}")
        plan[out_name] = (substitute(src.read_text(encoding="utf-8"), mapping).replace("\r\n", "\n").encode("utf-8"), True)
    skel = edir / meta.get("skeleton_dir", "skeleton")
    if skel.is_dir():
        plan_tree(plan, skel, mapping, "engine")
    else:
        print(f"[warn] engine {args.engine} has no skeleton folder, skipping starter files")
    assets_dir = meta.get("assets_dir", "assets")
    if assets_dir != "Content":  # Unreal creates Content itself
        plan.setdefault(f"{assets_dir}/.gitkeep", (b"", True))
    for rel, (data, is_text) in plan.items():
        writer.write(rel, data, is_text)

    # 5) Merged files
    core_ignore = (CORE_DIR / ".gitignore").read_text(encoding="utf-8")
    ignore_extra = edir / meta.get("gitignore_append", "gitignore.append")
    merge_gitignore(writer, core_ignore, ignore_extra.read_text(encoding="utf-8") if ignore_extra.is_file() else "")
    core_settings = json.loads((CORE_DIR / ".claude" / "settings.json").read_text(encoding="utf-8"))
    patch_file = edir / meta.get("settings_patch", "settings.patch.json")
    patch = json.loads(patch_file.read_text(encoding="utf-8")) if patch_file.is_file() else {}
    merge_settings(writer, core_settings, patch)

    # 6) Metadata: kept and extended, never reset (the hashes drive the next --upgrade)
    info = dict(old)
    info.pop("gold_standard_version", None)
    info.update({
        "kit_version": KIT_VERSION,
        "author": author,
        "profile": profile,
        "engine": args.engine,
        "game_name": old.get("game_name", args.name.strip()),
        "scaffolded": old.get("scaffolded", today),
        "adopted": old.get("adopted", mode != "new"),
    })
    if mode != "new":
        info["last_" + mode] = today
    history = list(old.get("history", []))
    history.append({"version": KIT_VERSION, "date": today, "mode": mode,
                    "unmerged": sorted(o for o, _, _ in writer.conflicts)})
    info["history"] = history
    info["files"] = dict(sorted({**prev_hashes, **writer.hashes}.items()))
    writer._write(Path(META_FILE), (json.dumps(info, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    legacy = dest / LEGACY_META_FILE
    if legacy.is_file() and not args.dry_run:
        legacy.unlink()                     # its content now lives in .game-kit.json
        writer.overridden.append(f"{LEGACY_META_FILE} replaced by {META_FILE}")

    # 7) Optional git init (never commits)
    if args.git_init and not args.dry_run:
        git_init(dest)

    # 8) Verify + report
    unresolved = [] if args.dry_run else verify_no_placeholders(dest, writer.written)
    report(args, dest, writer, unresolved, meta.get("adopt_hints", {}), meta.get("setup_step"))
    return 1 if unresolved else 0


def report(args, dest, writer, unresolved, adopt_hints, setup_step=None):
    """Print what happened. adopt_hints (engine.json) maps a conflicting file to what the user must merge;
    setup_step (engine.json, optional) replaces the generic engine-setup line in the next steps."""
    would = "would " if args.dry_run else ""
    if args.dry_run:
        print(f"\n[dry-run] would create {len(writer.created)} file(s) in {dest}")
    else:
        print(f"\n[ OK ] created {len(writer.created)} file(s) in {dest}")
    if writer.upgraded:
        print(f"[ OK ] {'would upgrade' if args.dry_run else 'upgraded'} {len(writer.upgraded)} file(s) you had not edited:")
        for u in writer.upgraded[:15]:
            print(f"       {u}")
        if len(writer.upgraded) > 15:
            print(f"       ... and {len(writer.upgraded) - 15} more (--debug lists every file)")
    if writer.kept_deleted:
        print(f"[info] left out {len(writer.kept_deleted)} kit file(s) you deleted (copy one back from the kit to restore it): "
              + ", ".join(writer.kept_deleted[:5]) + (" ..." if len(writer.kept_deleted) > 5 else ""))
    if writer.skipped:
        print(f"[info] left untouched (already current): {len(writer.skipped)}")
        for s in writer.skipped[:10]:
            print(f"       {s}")
        if len(writer.skipped) > 10:
            print(f"       ... and {len(writer.skipped) - 10} more")
    for orig, alt, fresh in writer.conflicts:
        verb = (f"would write {alt}" if args.dry_run else f"wrote {alt}") if fresh else f"{alt} is still there from last time"
        print(f"[merge] {orig} differs from the kit; {verb}. Merge by hand, then delete the .gold file.")
        if orig in adopt_hints:
            print(f"        -> {adopt_hints[orig]}")
    for o in writer.overridden:
        print(f"[note] {o}")
    for u in unresolved:
        print(f"[WARN] unresolved placeholder: {u}")
    if args.debug:
        for f in writer.written:
            print(f"       + {f}")
    if args.dry_run:
        return
    print("\nNext steps:")
    print(f'  1. cd "{dest.as_posix()}"')
    print("  2. python tools/dev.py doctor        # verify your environment (python3 on macOS/Linux)")
    print(f"  3. {setup_step or 'Do the engine setup in docs/ENGINE.md and set the exact engine version'}")
    print("  4. Open docs/FIRST_HOUR.md and follow it (it starts Claude Code and the GDD)")
    if writer.conflicts:
        print("  Then merge each *.gold file listed above into your version and delete it (engines ignore .gold files).")


def build_parser():
    ap = argparse.ArgumentParser(
        prog="new_game.py",
        description="Scaffold a game project from the Claude Code Game Kit "
                    "(universal core + engine overlay). Can also adopt or upgrade an existing project without "
                    "overwriting your edits.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python scripts/new_game.py --list-engines\n"
            "  python scripts/new_game.py --name \"My Game\" --engine godot --dest ../my-game --git-init\n"
            "  python scripts/new_game.py --name \"Existing\" --engine unreal --dest D:/games/existing --adopt --dry-run\n"
            "  python scripts/new_game.py --name \"My Game\" --engine godot --dest ../my-game --upgrade\n\n"
            "exit codes: 0 ok, 1 finished with warnings (unresolved placeholders), 2 usage or environment error"
        ),
    )
    ap.add_argument("--name", help='game title, e.g. "My Game" (also used to derive the code-safe slug)')
    ap.add_argument("--engine", help="engine overlay id (see --list-engines)")
    ap.add_argument("--dest", help="destination folder, outside the kit (default: ./<slug> in the current directory)")
    ap.add_argument("--slug", help="code-safe identifier (CMake target, C# namespace); default: derived from --name. "
                    "Needed when the name has no Latin letters, e.g. --slug touhou_quest")
    ap.add_argument("--author", default=None,
                    help="owner name for docs and file headers (default: the profile's author, else git config user.name)")
    ap.add_argument("--profile", metavar="FILE",
                    help="profile JSON with author, footer and extra working-style lines (see profiles/README.md; "
                         "default: profiles/default.json, or the profile recorded in the project on --adopt/--upgrade)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--adopt", action="store_true",
                      help="add the kit to an EXISTING project folder. Never overwrites: a file that differs gets a "
                           "<file>.gold copy next to it (engines ignore .gold files)")
    mode.add_argument("--upgrade", action="store_true",
                      help="like --adopt, but replaces kit files you never edited with the new kit version "
                           "(needs the file hashes this kit records; older projects fall back to .gold copies)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files in dest (dangerous, prefer --adopt)")
    ap.add_argument("--git-init", action="store_true", help="run `git init` on branch main in the destination (does not commit)")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen, write nothing")
    ap.add_argument("--list-engines", action="store_true", help="list available engine overlays and exit")
    ap.add_argument("--debug", action="store_true", help="verbose output, list every file written")
    return ap


def use_utf8_output():
    """Print UTF-8 everywhere: Windows pipes default to cp1252 and crash on names like 'Łukasz' or '東方'."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    global DEBUG
    use_utf8_output()
    args = build_parser().parse_args(argv)
    DEBUG = args.debug
    try:
        return scaffold(args)
    except ScaffoldError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[abort] interrupted", file=sys.stderr)
        return 2
    except OSError as exc:
        # Name the file: a locked or read-only file would otherwise be a mystery
        where = f" {exc.filename}" if exc.filename else ""
        print(f"[error] cannot write{where}: {exc.strerror or exc} (close any program using it, then re-run; "
              "--adopt never overwrites what is already there)", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2
    except Exception as exc:
        detail = repr(exc)
        if len(detail) > 300:               # e.g. a UnicodeEncodeError repr holds the whole file being written
            detail = detail[:300] + "...'"
        print(f"[error] unexpected failure: {detail}. Re-run with --debug for a traceback.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()           # still exit 2: --debug must not change the verdict
        return 2


if __name__ == "__main__":
    sys.exit(main())
