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
#   -> verify no unresolved placeholders in the rendered kit content -> print next steps
# Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
# Updated : 2026-10-21 with Claude (Opus 5.5, claude-opus-5-5): UTF-8 output, accent-folding slugs
#           and --slug, control-character checks on --name/--author, adopt appends to .gitignore
#           without rewriting it, engine adopt_hints. Audit pass 5: .gold suffix engines ignore,
#           --upgrade with content hashes, atomic writes, stable DATE on re-adopt, dest outside the kit
#           2026-10-30 with Claude (Opus 5.5, claude-opus-5-5): CRLF folded before profile substitution,
#           placeholder check on the rendered plan (also on re-runs), .gold reuse folds CRLF only for text,
#           backtick and */ rejected in names and authors, more reserved slugs (CMake targets, Windows devices)
#           2026-11-03 with Claude (Opus 5.5, claude-opus-5-5): the slug is recorded; --adopt/--upgrade reuse the
#           recorded name, slug and engine and refuse different ones (--rename opts in for name and slug);
#           --restore PATH puts a deleted kit file back rendered (copying the raw template left placeholders)
#           A .game-kit.json that does not parse stops the run (it was taken as "no record")
# ---------------------------------------------------------------------------
import argparse
import datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import traceback
import unicodedata
from pathlib import Path

KIT_VERSION = "0.13.1"  # bump with CHANGELOG.md entries
REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "core"
ENGINES_DIR = REPO_ROOT / "engines"
GITIGNORE_MARKER = "# ---- Claude Code Game Kit ----"
LEGACY_GITIGNORE_MARKERS = ("# ---- Claude Game Dev Gold Standard ----",)   # projects made before the rename
GOLD_SUFFIX = ".gold"                     # x.gd -> x.gd.gold: engines do not compile or import it
META_FILE = ".game-kit.json"             # version, profile, history and per-file hashes for --upgrade
LEGACY_META_FILE = ".gold-standard.json" # same file before the 0.3.0 rename; read, then replaced
PROFILES_DIR = REPO_ROOT / "profiles"
UMASK = os.umask(0)
os.umask(UMASK)                           # read once (os.umask can only be read by setting it)
# Valid-UTF-8 files of these types are still binary: no placeholder substitution, no line-ending changes (#233)
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".wav", ".ogg", ".mp3", ".flac", ".ttf",
                   ".otf", ".woff", ".woff2", ".zip", ".glb", ".fbx", ".blend", ".uasset", ".umap", ".dll", ".exe",
                   ".so", ".dylib", ".pck", ".npz", ".bin", ".pdf"}
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
    # More CMake utility targets (Visual Studio and Ninja generators) a game target must not shadow
    "all_build", "zero_check", "run_tests", "edit_cache", "rebuild_cache",
    # Windows device names: a file or folder named after the slug (con.exe, nul/) cannot be created
    "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
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
            raise ScaffoldError(f"--slug {override!r} is reserved (a CMake target, C# or Rust keyword, crate name, or "
                                f"Windows device name); try {override}_game")
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
        print(f"[info] '{slug}' is reserved (a CMake target, C# or Rust keyword, crate name, or Windows device name); "
              f"using slug '{slug}_game' "
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


def validate_comment_safe(flag, value):
    """Reject `*/`: names and authors land inside /* */ plugin headers (rpgmaker-mz), where it ends the comment early."""
    if "*/" in value:
        raise ScaffoldError(f"{flag} must not contain '*/' (it ends the /* */ comment the value is written into, "
                            "e.g. the RPG Maker MZ plugin header, and breaks the code)")


def validate_name(name):
    if not name or not name.strip():
        raise ScaffoldError("--name must not be empty")
    validate_text_arg("--name", name)
    if any(ch in name for ch in "<>"):
        raise ScaffoldError("--name must not contain < or > (the name lands in HTML, e.g. the web overlays' <title>)")
    if any(ch in name for ch in '"\\{}'):
        raise ScaffoldError('--name must not contain quotes, backslashes, or braces (they break generated config files)')
    if "`" in name:
        raise ScaffoldError("--name must not contain a backtick (the name lands inside JavaScript template literals, "
                            "e.g. the RPG Maker MZ boot log line, where a backtick ends the string)")
    validate_comment_safe("--name", name)


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
    validate_comment_safe("profile author", prof["author"])
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


def case_insensitive(folder):
    """True when the file system under folder ignores case (Windows, default macOS). Probed with a real file."""
    while not folder.is_dir() and folder.parent != folder:   # probe the nearest existing folder: never create dest
        folder = folder.parent
    try:
        fd, probe = tempfile.mkstemp(prefix=".newgame-Case-", dir=str(folder))
        os.close(fd)
        try:
            return os.path.exists(os.path.join(str(folder), os.path.basename(probe).swapcase()))
        finally:
            os.unlink(probe)
    except OSError:
        return os.name == "nt"


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
    """Write bytes via a temp file + rename, so a kill or full disk never leaves a half-written file. The temp file is
    new and unique (created exclusively next to the target): a fixed name could truncate a file of the user's that
    happened to have it, or write through a symlink of that name (#230)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".newgame-tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        # mkstemp makes the file 0600: give it the replaced file's mode, or what a plain open() would have
        try:
            mode = stat.S_IMODE(os.stat(str(path)).st_mode)
        except OSError:
            mode = 0o666 & ~UMASK
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def linked(dest, rel):
    """True when the target or a folder between dest and it is a symlink (or junction): the kit never writes through
    one, nor replaces one with a file (#230)."""
    p = dest
    for part in Path(rel).parts:
        p = p / part
        try:
            st = os.lstat(str(p))
        except OSError:
            return False                    # nothing there yet (so nothing below it either)
        # a symlink, or a Windows junction (a mount-point reparse tag; OneDrive's placeholders are other tags)
        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) == 0xA0000003:
            return True
    return False


def gold_name(rel, dest, data, is_text):
    """Conflict copy name the engines ignore: x.gd -> x.gd.gold, then x.gd.gold2, ...

    Returns (alt, already_there). An existing .gold with the same content is reused; one the user
    edited (mid-merge) is never overwritten: the next free number is used instead. CRLF is folded
    only for text (a PNG's signature holds a CRLF, so folding binary data never matched an identical copy).
    """
    for n in range(1, 100):
        alt = rel.with_name(rel.name + GOLD_SUFFIX + ("" if n == 1 else str(n)))
        p = dest / alt
        if not p.exists():
            return alt, False
        if p.is_file():
            existing = p.read_bytes()
            if is_text:
                existing = existing.replace(b"\r\n", b"\n")
            if existing == data:
                return alt, True
    raise ScaffoldError(f"too many .gold copies of {rel}; merge or delete them first")


# ---- Plan + write -------------------------------------------------------------
class Writer:
    """Writes files honoring --dry-run / --adopt / --upgrade / --force and tracks what happened.

    mode: "new" (empty folder), "adopt" (never overwrite) or "upgrade" (overwrite only files whose
    content still matches the hash recorded when the kit last wrote them).
    """

    def __init__(self, dest, mapping, dry_run, mode, force, prev_hashes, restore=()):
        self.dest, self.mapping = dest, mapping
        self.dry_run, self.mode, self.force = dry_run, mode, force
        self.prev_hashes = prev_hashes
        self.restore = set(restore)  # --restore: kit files to put back rendered, whatever is there now
        self.hashes = {}            # rel -> hash of the kit version now in place (feeds the next --upgrade)
        self.created, self.skipped, self.conflicts, self.overridden, self.upgraded = [], [], [], [], []
        self.kept_deleted = []      # --upgrade: kit files the project deleted on purpose, left out
        self.restored = []          # --restore: kit files put back on request
        self.written = []           # every path this run wrote (listed by --debug)
        self.case_insensitive = case_insensitive(dest)
        self.case_map = {k.casefold(): k for k in prev_hashes}
        self.retired = set()        # recorded keys replaced by a case-only rename

    def _write(self, rel, data):
        dbg(f"write {rel}")
        if linked(self.dest, rel):
            # settings.json, .gitignore, a .gold copy: never written through a symlink (#230)
            raise ScaffoldError(f"{Path(rel).as_posix()} is a symlink or inside a symlinked folder: the kit does not "
                                "write through links. Replace it with a real file or folder, then re-run.")
        if not self.dry_run:
            atomic_write(self.dest / rel, data)
        self.written.append(rel.as_posix())

    def write(self, rel, data, is_text):
        """Place one kit file. Text is compared with CRLF folded to LF on both sides."""
        rel = Path(rel)
        key = rel.as_posix()
        target = self.dest / rel
        new_hash = digest(data)
        if linked(self.dest, rel):
            self.skipped.append(f"{key} (a symlink, or inside a symlinked folder: left alone)")
            if key in self.prev_hashes:
                self.hashes[key] = self.prev_hashes[key]
            return
        if key not in self.prev_hashes and self.case_insensitive:
            # a case-only rename by the kit (Tools/Foo.py -> tools/foo.py): on this file system the file on disk is
            # the recorded one, so it carries that record's hash; the old key is retired (#233)
            old_key = self.case_map.get(key.casefold())
            if old_key is not None:
                self.prev_hashes = {**self.prev_hashes, key: self.prev_hashes[old_key]}
                self.retired.add(old_key)
        if key in self.restore:
            # Asked for by name: the rendered kit version (a file copied from the kit by hand is a raw template)
            self._write(rel, data)
            self.restored.append(key)
            self.hashes[key] = new_hash
            return
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
            alt, already_there = gold_name(rel, self.dest, data, is_text)
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
        # a valid-UTF-8 binary (NUL bytes, or a known binary type) must not get placeholders or CRLF folding (#233)
        if b"\0" in raw or Path(key).suffix.lower() in BINARY_SUFFIXES:
            plan[key] = (raw, False)
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            plan[key] = (raw, False)
            continue
        if key in plan:
            dbg(f"{label} overrides {key}")
        # Generated text is always LF, whatever line endings the kit checkout has. Fold BEFORE substituting: the
        # profile-line patterns ({{FOOTER}}, {{FOOTER_RULE}}, ...) match LF line ends only
        plan[key] = (substitute(text.replace("\r\n", "\n"), mapping).encode("utf-8"), True)


def kit_rules(block):
    """The rule lines of a kit .gitignore block (no comments, no blanks)."""
    return [l.strip() for l in block.splitlines() if l.strip() and not l.lstrip().startswith("#")]


def merge_gitignore(writer, core_text, engine_text, base_rules=None):
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
            # a rule the kit wrote last time (base_rules) and the user then deleted stays deleted; only rules new to
            # the kit are appended (#232). Without a recorded baseline (older records), every missing rule is added.
            base = set(base_rules) if base_rules is not None else set()
            missing = [r for r in kit_rules(block) if r not in have and r not in base]
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


def merge_user(user, base, kit):
    """Merge the kit's settings into the user's, three ways (#232). base is what the kit wrote last time (None when the
    record has none). Dicts: key by key. Lists: the user's entries, minus ones the kit wrote before and has dropped
    since, plus the kit's new ones (an entry the user deleted stays deleted). Scalars: the kit's value only where the
    user still has the kit's previous one; with no baseline the user's value always wins."""
    if isinstance(user, dict) and isinstance(kit, dict):
        base = base if isinstance(base, dict) else None
        out = {}
        for k in list(user) + [k for k in kit if k not in user]:
            if k in user and k in kit:
                out[k] = merge_user(user[k], None if base is None else base.get(k), kit[k])
            elif k in user:                 # not in the kit now: drop it only if the kit wrote it and the user kept it
                if not (base is not None and k in base and base[k] == user[k]):
                    out[k] = user[k]
            elif base is None or k not in base:   # new in the kit (a key the user deleted stays deleted)
                out[k] = kit[k]
        return out
    if isinstance(user, list) and isinstance(kit, list):
        old = base if isinstance(base, list) else []
        out = [x for x in user if not (x in old and x not in kit)]
        out.extend(x for x in kit if x not in out and x not in old)
        return out
    if base is not None and user == base:
        return kit
    return user


def merge_settings(writer, core_settings, patch, base=None):
    """Compose .claude/settings.json from core + engine patch (+ existing file when adopting). Returns the kit's own
    settings, recorded as the next run's baseline."""
    merged = deep_merge(core_settings, patch) if patch else core_settings
    kit = merged
    target = writer.dest / ".claude" / "settings.json"
    if target.exists() and writer.mode in ("adopt", "upgrade"):
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ScaffoldError(f"existing .claude/settings.json is not valid JSON ({exc}). Fix it, then re-run.")
        if not isinstance(existing, dict):
            raise ScaffoldError("existing .claude/settings.json is not a JSON object. Fix it, then re-run.")
        merged = merge_user(existing, base, merged)
        if merged == existing:
            writer.skipped.append(".claude/settings.json (already has every kit rule)")
            return kit
        writer.overridden.append(".claude/settings.json (kit rules merged into yours)")
    elif target.exists() and not writer.force:
        raise ScaffoldError(".claude/settings.json already exists. Use --adopt or --force.")
    writer._write(Path(".claude/settings.json"), (json.dumps(merged, indent=2) + "\n").encode("utf-8"))
    writer.created.append(".claude/settings.json")
    return kit


def verify_no_placeholders(plan):
    """Return 'relpath: [tokens]' for unresolved {{PLACEHOLDERS}} in the kit content this run rendered.

    Scans the in-memory plan {rel: (bytes, is_text)}, not the files on disk: a second --adopt or --upgrade writes
    nothing for files already in place, and a broken kit placeholder must still be reported. Never reads the
    user's own files.
    """
    problems = []
    for rel, (data, is_text) in sorted(plan.items()):
        if not is_text or Path(rel).name == "doctor.py":
            continue  # doctor.py contains the placeholder pattern on purpose
        hits = sorted(set(PLACEHOLDER_RE.findall(data.decode("utf-8", "replace"))))
        if hits:
            problems.append(f"{rel}: {hits}")
    return problems


def load_meta(dest):
    """Existing project metadata (.game-kit.json, or the pre-0.3.0 .gold-standard.json), or {} when neither exists.

    Only a missing file means "no record". One that cannot be read or parsed (truncated by a crash or a bad merge)
    stops the run: taken as no record, --upgrade would .gold every file and rewrite the history from scratch.
    """
    for name in (META_FILE, LEGACY_META_FILE):
        path = dest / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ScaffoldError(f"cannot read {name} ({exc.strerror or exc}): close any program using it, then re-run")
        except ValueError as exc:   # bad JSON or bytes that are not UTF-8
            raise ScaffoldError(f"{name} is not valid JSON ({exc}): fix it (git can show the last good version), "
                                "or delete it to start the record again (the next --upgrade then writes a .gold for "
                                "every file that differs)")
        if not isinstance(data, dict):
            raise ScaffoldError(f"{name} does not hold a JSON object: fix it, or delete it to start the record again")
        validate_meta(name, data)
        data["_read_from"] = name
        return data
    return {}


def validate_meta(name, data):
    """The record's shape, checked before anything is written (a wrong shape used to crash midway, #231)."""
    def bad(what):
        raise ScaffoldError(f"{name}: {what}. Fix it (git can show the last good version), or delete it to start the "
                            "record again")
    files = data.get("files", {})
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        bad("'files' must map paths to hashes")
    if not isinstance(data.get("history", []), list) or not all(isinstance(h, dict) for h in data.get("history", [])):
        bad("'history' must be a list of entries")
    prof = data.get("profile")
    if prof is not None and (not isinstance(prof, dict) or not isinstance(prof.get("style", []), list)
                             or not all(isinstance(prof.get(k, ""), str) for k in ("author", "footer"))):
        bad("'profile' must hold author, footer and style")
    for k in ("kit_version", "game_name", "slug", "engine", "author", "scaffolded"):
        if k in data and not isinstance(data[k], str):
            bad(f"'{k}' must be text")
    if "kit_settings" in data and not isinstance(data["kit_settings"], dict):
        bad("'kit_settings' must be an object")
    if "kit_gitignore" in data and not (isinstance(data["kit_gitignore"], list)
                                        and all(isinstance(r, str) for r in data["kit_gitignore"])):
        bad("'kit_gitignore' must be a list of rules")


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def restore_key(path):
    """--restore argument -> the plan key: forward slashes, relative to the game folder, no leading ./"""
    key = Path(path.replace("\\", "/")).as_posix()
    if Path(key).is_absolute() or re.match(r"^[A-Za-z]:", key) or ".." in key.split("/"):
        raise ScaffoldError(f"--restore {path}: give the path relative to the game folder, e.g. scripts/core/spring.gd")
    return key


def settle_identity(args, old, derived, engines):
    """(name, slug, engine) for this run.

    A new project takes them from the command line. --adopt and --upgrade on a project with a .game-kit.json reuse
    the recorded ones, so the README's "run the same command with --upgrade" cannot change them by accident: a
    different --engine is refused (it would mix a second overlay into the project), a different --name or --slug
    too unless --rename. The slug is the CMake target, the Cargo package, the LÖVE save folder and the Godot export
    names; --rename alone changes only the title and keeps the recorded slug.
    """
    rec_name, rec_slug, rec_engine = old.get("game_name"), old.get("slug"), old.get("engine")
    if rec_engine and args.engine and args.engine != rec_engine:
        raise ScaffoldError(f"this project was made for engine {rec_engine!r} (see {META_FILE}); --engine "
                            f"{args.engine} would mix a second overlay into it. Omit --engine, or pass --engine "
                            f"{rec_engine}.")
    engine_id = args.engine or rec_engine
    if not engine_id:
        raise ScaffoldError(f"--engine is required (this project has no {META_FILE} naming one). "
                            f"Choose one of: {', '.join(engines)}")
    if engine_id not in engines:
        raise ScaffoldError(f"{META_FILE} names engine {engine_id!r}, which this kit does not have. "
                            f"Available: {', '.join(engines)}")
    name = args.name.strip() if args.name else rec_name
    if not name:
        raise ScaffoldError(f"--name is required (this project has no {META_FILE} naming the game)")
    if args.name is None:
        validate_name(name)                 # a hand-edited record gets the same checks as --name
    if rec_name and name != rec_name and not args.rename:
        raise ScaffoldError(f"this project is named {rec_name!r} in {META_FILE}, not {name!r}. Omit --name to keep "
                            "the recorded name, or add --rename to rewrite the kit files you never edited with "
                            "the new one.")
    if args.slug:
        slug = args.slug
    elif rec_slug:
        slug = rec_slug
    else:
        base = rec_name or name             # a renamed project keeps the slug its recorded name gave
        slug = derived if args.name and args.name.strip() == base else make_slug(base)
        if old and args.slug is None:
            print(f"[info] {META_FILE} records no slug (kit 0.8.2 or earlier); using {slug!r}, derived from the "
                  "name. If the project was made with --slug, pass the same --slug.")
    if rec_slug and slug != rec_slug and not args.rename:
        raise ScaffoldError(f"this project's slug is {rec_slug!r} (see {META_FILE}), not {slug!r}: it names the "
                            "build target, the package and the save folder. Omit --slug to keep it, or add "
                            "--rename to change it.")
    return name, slug, engine_id


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

    mode = "upgrade" if args.upgrade else "adopt" if args.adopt else "new"
    # --adopt/--upgrade on a project with a .game-kit.json take the name and engine from it, so only a new project
    # (or one without --dest, whose folder is named after the slug) needs them on the command line
    if not args.name and (mode == "new" or not args.dest):
        raise ScaffoldError("--name is required (or use --list-engines)")
    if not args.engine and mode == "new":
        raise ScaffoldError(f"--engine is required. Choose one of: {', '.join(engines)}")
    if args.rename and mode == "new":
        raise ScaffoldError("--rename only applies with --adopt or --upgrade (a new project takes --name as it is)")
    if args.name is not None:
        validate_name(args.name)
    if args.author is not None:
        validate_text_arg("--author", args.author)
        validate_comment_safe("--author", args.author)
    if args.engine and args.engine not in engines:
        raise ScaffoldError(f"unknown engine {args.engine!r}. Available: {', '.join(engines)}")
    if not CORE_DIR.exists():
        raise ScaffoldError(f"core folder missing: {CORE_DIR}")

    derived = make_slug(args.name, args.slug) if args.name else None   # once: it explains a reserved slug
    if args.slug and not args.name:
        make_slug("", args.slug)                                         # validate it all the same
    dest = Path(args.dest).expanduser().resolve() if args.dest else (Path.cwd() / derived).resolve()

    if dest == REPO_ROOT or REPO_ROOT in dest.parents:
        raise ScaffoldError(f"{dest} is inside the kit. Pass --dest with a folder outside it, "
                            f"e.g. --dest D:/games/{derived or 'my_game'}")
    if dest.exists() and not dest.is_dir():
        raise ScaffoldError(f"{dest} exists and is not a directory")
    if mode == "new" and dest.exists() and any(dest.iterdir()) and not args.force:
        raise ScaffoldError(f"{dest} is not empty. Use --adopt to add the kit to an existing project (never overwrites), "
                            "--upgrade for a project made with an earlier kit, or --force.")
    if mode != "new" and not dest.exists():
        raise ScaffoldError(f"--{mode} needs an existing folder, {dest} does not exist (omit --{mode} for a new project)")

    old = load_meta(dest) if mode != "new" else {}
    read_from = old.pop("_read_from", None)
    recorded = old.get("kit_version")
    if recorded and version_tuple(recorded) > version_tuple(KIT_VERSION) and not args.force:
        # an older kit would replace a newer kit's untouched files with older ones (#231)
        raise ScaffoldError(f"this project was made or upgraded with kit {recorded}, newer than this kit "
                            f"({KIT_VERSION}). Use the newer kit; --force downgrades on purpose.")
    name, slug, engine_id = settle_identity(args, old, derived, engines)
    meta = engines[engine_id]
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
    author = args.author or profile["author"] or old.get("author") or git_user_name() or "the user"
    today = datetime.date.today().isoformat()
    mapping = {
        "GAME_NAME": name,
        "GAME_SLUG": slug,
        "ENGINE": engine_id,
        "ENGINE_LABEL": meta.get("label", engine_id),
        # Re-adopting keeps the original date, so untouched files compare equal on any later day
        "DATE": old.get("scaffolded", today),
        "AUTHOR": author,
        "_FOOTER": profile["footer"],
        "_STYLE": profile["style"],
    }
    dbg(f"mapping: {mapping}")
    dbg(f"dest: {dest} mode: {mode}")

    edir = meta["_dir"]
    restore = [restore_key(r) for r in args.restore]
    if restore and mode != "upgrade":
        raise ScaffoldError("--restore only applies with --upgrade (a new project or --adopt writes every missing "
                            "kit file anyway)")
    writer = Writer(dest, mapping, args.dry_run, mode, args.force, prev_hashes, restore)
    if not args.dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    # 1-4) Plan every kit file first (engine entries replace core ones), then write each once
    plan = {}
    plan_tree(plan, CORE_DIR, mapping, "core")
    for key, out_name in (("engine_md", "docs/ENGINE.md"), ("flow_md", "docs/ENGINE_FLOW.md")):
        src = edir / meta.get(key, "")
        if not src.is_file():
            raise ScaffoldError(f"engine {engine_id}: missing {meta.get(key)!r}")
        # LF first, then substitute (same reason as plan_tree)
        plan[out_name] = (substitute(src.read_text(encoding="utf-8").replace("\r\n", "\n"), mapping).encode("utf-8"), True)
    skel = edir / meta.get("skeleton_dir", "skeleton")
    if skel.is_dir():
        plan_tree(plan, skel, mapping, "engine")
    else:
        print(f"[warn] engine {engine_id} has no skeleton folder, skipping starter files")
    assets_dir = meta.get("assets_dir", "assets")
    if assets_dir != "Content":  # Unreal creates Content itself
        plan.setdefault(f"{assets_dir}/.gitkeep", (b"", True))
    unknown = [r for r in restore if r not in plan]
    if unknown:
        raise ScaffoldError(f"--restore {', '.join(unknown)}: not a file the kit ships to a {engine_id} project "
                            "(give the path relative to the game folder, e.g. --restore scripts/core/spring.gd)")
    for rel, (data, is_text) in plan.items():
        writer.write(rel, data, is_text)

    # 5) Merged files
    core_ignore = (CORE_DIR / ".gitignore").read_text(encoding="utf-8")
    ignore_extra = edir / meta.get("gitignore_append", "gitignore.append")
    engine_ignore = ignore_extra.read_text(encoding="utf-8") if ignore_extra.is_file() else ""
    merge_gitignore(writer, core_ignore, engine_ignore, old.get("kit_gitignore"))
    core_settings = json.loads((CORE_DIR / ".claude" / "settings.json").read_text(encoding="utf-8"))
    patch_file = edir / meta.get("settings_patch", "settings.patch.json")
    patch = json.loads(patch_file.read_text(encoding="utf-8")) if patch_file.is_file() else {}
    kit_settings = merge_settings(writer, core_settings, patch, old.get("kit_settings"))

    # 6) Metadata: kept and extended, never reset (the hashes drive the next --upgrade)
    info = dict(old)
    info.pop("gold_standard_version", None)
    info.update({
        "kit_version": KIT_VERSION,
        "author": author,
        "profile": profile,
        "engine": engine_id,
        "game_name": name,
        "slug": slug,           # the build target, package and save-folder name: reused by --adopt and --upgrade
        "scaffolded": old.get("scaffolded", today),
        "adopted": old.get("adopted", mode != "new"),
    })
    if mode != "new":
        info["last_" + mode] = today
    history = list(old.get("history", []))
    history.append({"version": KIT_VERSION, "date": today, "mode": mode,
                    "unmerged": sorted(o for o, _, _ in writer.conflicts)})
    info["history"] = history
    kept = {k: v for k, v in prev_hashes.items() if k not in writer.retired}     # a case-only rename retires the old key
    info["files"] = dict(sorted({**kept, **writer.hashes}.items()))
    # the next run's baselines for the three-way merges (#232)
    info["kit_settings"] = kit_settings
    info["kit_gitignore"] = kit_rules(core_ignore + "\n" + engine_ignore)
    writer._write(Path(META_FILE), (json.dumps(info, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    legacy = dest / LEGACY_META_FILE
    # only when the old record was the one read and migrated: one kept beside a current record is left alone (#231)
    if read_from == LEGACY_META_FILE and legacy.is_file() and not args.dry_run:
        legacy.unlink()                     # its content now lives in .game-kit.json
        writer.overridden.append(f"{LEGACY_META_FILE} replaced by {META_FILE}")

    # 7) Optional git init (never commits)
    if args.git_init and not args.dry_run:
        git_init(dest)

    # 8) Verify + report
    # Kit content only: the plan, plus the kit's .gitignore text (settings JSON is never substituted)
    plan[".gitignore"] = ((core_ignore + "\n" + engine_ignore).encode("utf-8"), True)
    unresolved = verify_no_placeholders(plan)
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
    if writer.restored:
        print(f"[ OK ] {'would restore' if args.dry_run else 'restored'} {len(writer.restored)} kit file(s): "
              + ", ".join(writer.restored))
    if writer.kept_deleted:
        # Not "copy it from the kit": kit files are templates ({{GAME_NAME}}, the footer line), --restore renders them
        print(f"[info] left out {len(writer.kept_deleted)} kit file(s) you deleted (put one back with --upgrade "
              f"--restore <path>): " + ", ".join(writer.kept_deleted[:5]) + (" ..." if len(writer.kept_deleted) > 5 else ""))
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
            "  python scripts/new_game.py --dest ../my-game --upgrade   (name, slug and engine from .game-kit.json)\n\n"
            "exit codes: 0 ok, 1 finished with warnings (unresolved placeholders), 2 usage or environment error"
        ),
    )
    ap.add_argument("--name", help='game title, e.g. "My Game" (also used to derive the code-safe slug). '
                    "--adopt/--upgrade reuse the one in .game-kit.json when you omit it")
    ap.add_argument("--engine", help="engine overlay id (see --list-engines). --adopt/--upgrade reuse the one in "
                    ".game-kit.json when you omit it; a different one is refused")
    ap.add_argument("--dest", help="destination folder, outside the kit (default: ./<slug> in the current directory)")
    ap.add_argument("--slug", help="code-safe identifier (CMake target, C# namespace); default: derived from --name. "
                    "Needed when the name has no Latin letters, e.g. --slug touhou_quest")
    ap.add_argument("--rename", action="store_true",
                    help="with --adopt/--upgrade: accept a --name (and a --slug) that differs from the one recorded in "
                         ".game-kit.json and rewrite the kit files you never edited with it (refused otherwise; "
                         "without --slug the recorded slug is kept)")
    ap.add_argument("--author", default=None,
                    help="author name for docs and file headers (default: the profile's author, else git config user.name)")
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
    ap.add_argument("--restore", action="append", default=[], metavar="PATH",
                    help="with --upgrade: put the kit's version of PATH (relative to the game folder) back, rendered "
                         "for this project, replacing whatever is there; for a kit file you deleted and want again "
                         "(repeatable)")
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
