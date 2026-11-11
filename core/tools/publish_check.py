#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# publish_check.py
# Purpose : Pre-flight before a repo goes public (SOP-13). Looks at what git would
#           publish (tracked files plus untracked files that are not ignored) and
#           reports what should not be there: no LICENSE, secret files, token-shaped
#           strings, files GitHub rejects without LFS, personal paths (also the export folder
#           Pixelorama saves inside each .pxo), and personal email addresses in commit history.
#           With --range it reviews commits instead (someone else's, a subagent's, a patch): only the lines those
#           commits add, their messages, and files they must not add.
# Usage   : python tools/publish_check.py [--root DIR] [--terms FILE] [--style] [--debug]
#           python tools/publish_check.py --range main..feature [--terms FILE] [--style] [--trailer TEXT]
#             --range A..B   scan only commits in A..B: every added line, every commit message, local-only or
#                            secret files they add or change (CLAUDE.local.md, .env, captures/), author emails;
#                            findings are grouped per commit (hash, subject). --commits is the same option.
#             --terms FILE   private words or names that must never appear publicly, one per line: a plain term
#                            (whole word, any case) or `re:<regex>`; `#` starts a comment line. Default: the file in
#                            the PUBLISH_CHECK_TERMS environment variable. Keep it OUTSIDE the repo (for example
#                            ~/.config/game-kit/private-terms.txt) or in the gitignored .private-terms.txt: a list
#                            that would be published is a FAIL of its own. Matches name the list's line, never the term.
#             --style        also FAIL on em dashes (the kit's no-em-dash rule) in scanned text
#             --trailer TEXT with --range: WARN for each commit whose message has no line starting with TEXT
#                            (the project's attribution trailer, e.g. "Co-Authored-By:")
# Exit    : 0 no FAIL items (WARN items may remain), 1 FAIL items found, 2 not a git repo / git missing / bad
#           range / unreadable or invalid terms file / bad arguments
# Notes   : Scans the working tree, not old commits (commit messages too, for private terms). A secret that was
#           committed and then deleted is still in history: run a history scanner (gitleaks) before going public,
#           and rotate any key it finds. Pattern matching is a net, not a guarantee. Text with a byte
#           order mark (UTF-8, UTF-16, UTF-32) is decoded and scanned; other files with NUL bytes count as binary.
#           Files over 2 MB are not content-scanned; one that looks like text (no media extension, no NUL near the
#           start) is listed as a WARN so it gets a look by hand. In --range mode, files git shows as binary (UTF-16
#           text included) have no added lines to scan, and a merge commit adds no lines of its own (its message is
#           still scanned). Standard library only, Python 3.8+.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   tree mode (default):
#     list files git would publish (ls-files tracked + others --exclude-standard)
#     FAIL: no LICENSE; secret-named files; token-shaped strings in text files; files > 100 MB not routed to LFS;
#           private terms in file names, text or any commit message; em dashes with --style; the terms list itself
#     WARN: files > 50 MB not in LFS; text files > 2 MB (not content-scanned); home-folder paths in text;
#           a .pxo whose data.json holds an absolute export folder; non-noreply emails in history;
#           PLACEHOLDER rows in docs/ASSET_LOG.md; Unreal's Android File Server token with network connections on
#   range mode (--range A..B): per commit in rev-list order
#     FAIL: tokens, private terms, em dashes (--style) in its added lines (diff-tree -p -U0) or its message;
#           secret-named or local-only files it adds or changes
#     WARN: home-folder paths in added lines or the message; a non-noreply author or committer email;
#           no attribution trailer (--trailer)
#   print grouped results and the reminders that cannot be automated, return exit code
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import traceback
import zipfile
import zlib
from pathlib import Path

LICENSE_NAMES = {"license", "license.md", "license.txt", "copying", "copying.md", "unlicense"}
# File names that are secrets by definition (match on the base name, case-insensitive)
SECRET_GLOBS = (".env", ".env.*", "*.pem", "*.key", "*.keystore", "*.jks", "*.p12", "*.pfx", "*.p8",
                "export_credentials.cfg", "id_rsa", "id_ed25519", "*.ppk", "credentials.json", "service-account*.json")
SECRET_ALLOW = (".env.example", ".env.sample", ".env.template")
# Token shapes from the major providers; each needs the full shape, so docs that mention a prefix do not trip it
TOKEN_PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{30,}")),
    ("OpenAI-style API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    # Cloud shapes (#252). Azure client secret and Google OAuth secret: the formats public scanners (TruffleHog,
    # GitGuardian) match, not a vendor spec (verify against a real key before trusting a miss)
    ("Google OAuth client secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{28}(?![A-Za-z0-9_-])")),
    ("GCP service account key", re.compile(r'"private_key_id"\s*:\s*"[0-9a-f]{40}"')),
    ("Azure client secret", re.compile(r"(?<![A-Za-z0-9_~.-])[A-Za-z0-9_~.-]{3}\dQ~[A-Za-z0-9_~.-]{31,34}"
                                       r"(?![A-Za-z0-9_~.-])")),
    ("Azure storage account key", re.compile(r"\bAccountKey=[A-Za-z0-9+/]{86}==")),
    ("Azure SAS token", re.compile(r"\bsv=\d{4}-\d{2}-\d{2}&[^\s\"'<>]*?\bsig=[A-Za-z0-9%+/]{30,}")),
    ("Slack token", re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{10,}")),
    ("Stripe live key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}")),
    ("Discord webhook", re.compile(r"https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]{20,}")),
    # The keyword may be one part of a longer name (client_secret, AWS_SECRET_ACCESS_KEY, db-password): \b never
    # matches next to "_". The name must start where no identifier character precedes it (keeps the scan linear),
    # and the 16-character value guard keeps labels like password_field_label = "Password" out. Values that start
    # with a scheme (token_url = "https://...", secret_door = "res://...") are addresses, not secrets.
    ("hard-coded secret", re.compile(r"(?i)(?<![A-Za-z0-9_-])(?:[A-Za-z0-9]*[_-])*"
                                     r"(?:api[_-]?key|secret|token|passw(?:or)?d)(?:[_-][A-Za-z0-9]*)*"
                                     r"\s*(?::=|[:=])\s*[\"'](?![A-Za-z][A-Za-z0-9+.-]*://)[^\"'\s<>{}]{16,}[\"']")),
]
# The same names with an unquoted value, as INI, .env, YAML and credentials files write them
# (aws_secret_access_key = wJal...). Only in config-type files: in code an unquoted value is a name, not a secret.
# The value needs a digit and either both letter cases or one of / + = (a key, not a constant like API_KEY_V2_NAME).
UNQUOTED_SECRET = re.compile(r"(?i)^\s*(?:export\s+)?(?:[A-Za-z0-9]*[_-])*"
                             r"(?:api[_-]?key|secret|token|passw(?:or)?d)(?:[_-][A-Za-z0-9]*)*"
                             r"\s*[:=]\s*(?![A-Za-z][A-Za-z0-9+.-]*://)([^\s\"'#;<>{}$()\[\],]{16,})\s*(?:[#;].*)?$")
CONFIG_EXTS = {".ini", ".cfg", ".conf", ".toml", ".properties", ".yaml", ".yml", ".env", ".config", ""}
# A real user's home folder (not a <name> placeholder or a generic example)
HOME_PATH = re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+(?!<|\{|Public\b|Default\b|you\b|name\b|USERNAME\b)[^\\/\s\"'`<>]+"
                       r"|/(?:Users|home)/(?!<|\{|you\b|name\b|runner\b|user\b)[A-Za-z0-9][A-Za-z0-9._-]*(?![A-Za-z0-9._-])")
# Pixelorama keeps the folder a .pxo was last exported to in its zipped data.json (export_profile.directory_path,
# written as Godot's var_to_str, so the text sits in double quotes): an absolute one names a folder on your machine
PXO_ABSOLUTE = re.compile(r'^"?(?:[A-Za-z]:[\\/]|[\\/]|~(?:[\\/]|"?$))')
PXO_MAX_JSON = 8 * 1024 * 1024          # a bigger data.json is not read (a real one is well under 1 MB)
PXO_UNREADABLE = "\0unreadable"         # pxo_export_folder's answer for a .pxo whose data.json cannot be read
NOREPLY = re.compile(r"(?i)@users\.noreply\.github\.com$|^noreply@|@noreply\.")
GITHUB_HARD_LIMIT = 100 * 1024 * 1024   # GitHub rejects pushes with a file over 100 MB
GITHUB_WARN_LIMIT = 50 * 1024 * 1024    # and warns over 50 MB
MAX_TEXT_SCAN = 2 * 1024 * 1024         # skip content scans of larger files (assets, not config)
SNIFF_BYTES = 8192                      # a NUL in this much of the start marks a file as binary
# Media and other binary formats: an unscanned big one is expected, a big text file (a log, a dump) is reported
MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tga", ".tif", ".tiff", ".webp", ".psd", ".kra", ".aseprite", ".pxo",
              ".ase", ".exr", ".hdr", ".dds", ".ktx", ".ktx2", ".basis", ".ico", ".icns", ".svgz",
              ".wav", ".ogg", ".mp3", ".flac", ".opus", ".m4a", ".aiff", ".aif", ".mid", ".midi", ".bank", ".wem",
              ".mp4", ".webm", ".mov", ".avi", ".mkv", ".ogv",
              ".glb", ".gltf", ".fbx", ".obj", ".blend", ".blend1", ".dae", ".3ds", ".usd", ".usdz", ".vox", ".ply",
              ".stl", ".abc", ".uasset", ".umap", ".pck", ".res", ".scn", ".ttf", ".otf", ".woff", ".woff2",
              ".zip", ".7z", ".rar", ".gz", ".tgz", ".xz", ".bz2", ".tar", ".pdf",
              ".exe", ".dll", ".so", ".dylib", ".lib", ".a", ".o", ".pdb", ".wasm", ".bin", ".dat", ".pak",
              ".safetensors", ".gguf", ".onnx", ".pt", ".pth", ".ckpt"}
# Byte order marks, checked before the NUL test: UTF-16 text is full of NULs (Windows PowerShell 5 writes UTF-16LE
# with "> file" and Out-File by default). UTF-32 LE before UTF-16 LE, its BOM starts with the same two bytes.
BOMS = ((b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"), (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))
AFS_SECTION = "[/Script/AndroidFileServerEditor.AndroidFileServerRuntimeSettings]"   # Unreal, from Epic's template
# --range: files a commit must not add or change, beyond the secret names above (matched lower-case against the
# path relative to the repo root): Claude Code's local-only files, agent worktrees, scratch and capture output
LOCAL_ONLY_GLOBS = ("claude.local.md", "*/claude.local.md", ".claude/settings.local.json", ".claude/worktrees/*",
                    "captures/*", "scratch/*", "*.log", "*.tmp", ".private-terms.txt", "*/.private-terms.txt")
TERMS_ENV = "PUBLISH_CHECK_TERMS"       # where --terms comes from when it is not given
TERM_REGEX_PREFIX = "re:"
EM_DASH = "—"
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
C_ESCAPES = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", '"': '"', "\\": "\\"}


class UsageProblem(Exception):
    """A bad --range, --terms file or option combination: exit 2 with the message."""


# ---- private terms -------------------------------------------------------------------------------------------------
def load_terms(path):
    """[(line number in the list, compiled pattern)] from a terms file. A plain line is a whole word or phrase in any
    case; `re:<regex>` is a regular expression (any case); blank lines and `#` lines are skipped. Raises
    UsageProblem for an unreadable file or a regex that is invalid or matches empty text."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise UsageProblem(f"cannot read the terms file {path} ({exc.strerror or exc.__class__.__name__})")
    except UnicodeDecodeError:
        raise UsageProblem(f"the terms file {path} is not UTF-8 text")
    terms = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(TERM_REGEX_PREFIX):
            try:
                pat = re.compile(line[len(TERM_REGEX_PREFIX):].strip(), re.I)
            except re.error as exc:
                raise UsageProblem(f"terms file line {n}: not a valid regular expression ({exc})")
            if pat.search(""):
                raise UsageProblem(f"terms file line {n}: the regular expression matches empty text")
        else:
            # whole word: no letter or digit right before or after, so "Kraken" finds coral_kraken, not krakens
            pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(line) + r"(?![A-Za-z0-9])", re.I)
        terms.append((n, pat))
    return terms


def term_hits(text, terms):
    """Labels for the private terms found in text. The term itself is never printed: the output may be shared."""
    return [f"private term (terms file line {n})" for n, pat in terms if pat.search(text)]


def resolve_terms(arg):
    """(terms, the list's resolved path or None) from --terms or the PUBLISH_CHECK_TERMS environment variable."""
    path = arg or os.environ.get(TERMS_ENV, "").strip()
    if not path:
        return [], None
    return load_terms(path), Path(path).expanduser().resolve()


def rel_inside(root, path):
    """path relative to root (forward slashes), or None when it lies outside root."""
    if path is None:
        return None
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def git(root, *args, check=True):
    """Run git in root; return stdout bytes. Raises RuntimeError with git's message on failure."""
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return r.stdout


def publishable_files(root):
    """Paths (relative, forward slashes) that `git add -A` and a push would publish."""
    out = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    # surrogateescape, not "replace": a name that is not UTF-8 (.env.\xff on Linux) must stay the real file's name,
    # or it is skipped as missing, secret-name check included (#238)
    return sorted({p for p in out.decode("utf-8", "surrogateescape").split("\0") if p})


def lfs_paths(root, paths):
    """Subset of paths whose filter attribute is lfs."""
    if not paths:
        return set()
    r = subprocess.run(["git", "-C", str(root), "check-attr", "-z", "--stdin", "filter"], capture_output=True,
                       input="\0".join(paths).encode("utf-8", "surrogateescape") + b"\0", timeout=120)
    fields = r.stdout.decode("utf-8", "surrogateescape").split("\0")
    return {fields[i] for i in range(0, len(fields) - 2, 3) if fields[i + 2] == "lfs"}


def lfs_ready(root):
    """True when Git LFS's clean filter is configured: without it, `filter=lfs` in .gitattributes does nothing and
    `git add` stores the raw file, which GitHub rejects over 100 MB (#239)."""
    r = git(root, "config", "--get", "filter.lfs.clean", check=False)
    return bool(r.strip())


def is_secret_name(rel):
    base = rel.rsplit("/", 1)[-1].lower()
    return base not in SECRET_ALLOW and any(fnmatch.fnmatch(base, g) for g in SECRET_GLOBS)


class Unreadable(Exception):
    """A file that could not be read: reported, never taken as clean (#239)."""


def scan_text(path, terms=(), style=False):
    """Return (token findings, home-path findings) for one file, or ([], []) for binary or large files. Private
    terms and (with style) em dashes count as token findings: both FAIL. Raises Unreadable when the file cannot be
    read."""
    try:
        if path.stat().st_size > MAX_TEXT_SCAN:
            return [], []
        data = path.read_bytes()
    except OSError as exc:
        raise Unreadable(exc.strerror or exc.__class__.__name__)
    codec = next((c for bom, c in BOMS if data.startswith(bom)), None)
    if codec:
        text = data.decode(codec, "replace")
    elif b"\0" in data[:SNIFF_BYTES]:
        return [], []
    else:
        text = data.decode("utf-8", "replace")
    return scan_lines(text, config=is_config(path.name), terms=terms, style=style)


def is_config(name):
    """A config-type file name, where an unquoted value after `secret =` is a value, not a name."""
    name = name.rsplit("/", 1)[-1].lower()
    return Path(name).suffix in CONFIG_EXTS or name.startswith(".env")


def scan_line(line, config=False, terms=(), style=False):
    """(problems that FAIL, a home path that WARNs or "") for one line of text."""
    fails = [f"looks like a {label}" for label, pat in TOKEN_PATTERNS if pat.search(line)]
    m = UNQUOTED_SECRET.match(line) if config and not fails else None
    if m:
        v = m.group(1)
        if re.search(r"\d", v) and ((re.search(r"[a-z]", v) and re.search(r"[A-Z]", v)) or re.search(r"[/+=]", v)):
            fails.append("looks like a hard-coded secret (unquoted)")
    fails += term_hits(line, terms)
    if style and EM_DASH in line:
        fails.append("an em dash (style rule: use a colon, a comma or parentheses)")
    m = HOME_PATH.search(line)
    return fails, (m.group(0) if m else "")


def scan_lines(text, config=False, terms=(), style=False):
    """(token findings, home-path findings) in text; config: also unquoted secret values (an INI, a .env)."""
    tokens, homes = [], []
    for lineno, line in enumerate(text.splitlines(), 1):
        fails, home = scan_line(line, config, terms, style)
        tokens += [f"line {lineno}: {x}" for x in fails]
        if home:
            homes.append(f"line {lineno}: {home}")
    return tokens, homes


def unscanned_text(path):
    """True for a file over the scan cap that looks like text: no media extension, and a byte order mark or no NUL
    in its first SNIFF_BYTES. Such a file can hold a token or a path nobody looked at."""
    if path.suffix.lower() in MEDIA_EXTS:
        return False
    try:
        if path.stat().st_size <= MAX_TEXT_SCAN:
            return False
        with open(path, "rb") as fh:
            head = fh.read(SNIFF_BYTES)
    except OSError:
        return False
    return any(head.startswith(bom) for bom, _ in BOMS) or b"\0" not in head


def pxo_export_folder(path):
    """The absolute export folder Pixelorama saved in a .pxo, or "" (none, a relative one, or not a readable .pxo)."""
    try:
        with zipfile.ZipFile(path) as z:
            if z.getinfo("data.json").file_size > PXO_MAX_JSON:
                return ""
            d = json.loads(z.read("data.json").decode("utf-8"))
    except (KeyError, OSError, ValueError, RecursionError, zipfile.BadZipFile, zlib.error):
        return ""
    except (RuntimeError, NotImplementedError, EOFError):
        # encrypted (RuntimeError) or a compression zipfile cannot read: not a git problem, and not clean (#239)
        return PXO_UNREADABLE
    prof = d.get("export_profile") if isinstance(d, dict) else None
    v = prof.get("directory_path") if isinstance(prof, dict) else None
    return v.strip('"') if isinstance(v, str) and PXO_ABSOLUTE.match(v) else ""


def history_emails(root):
    """Distinct author and committer emails across all refs (empty for a repo with no commits)."""
    out = git(root, "log", "--all", "--format=%ae%n%ce", check=False)
    return sorted({e for e in out.decode("utf-8", "replace").splitlines() if e.strip()})


def placeholder_assets(root):
    log = root / "docs" / "ASSET_LOG.md"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [f"docs/ASSET_LOG.md line {i}" for i, l in enumerate(lines, 1) if l.startswith("|") and "PLACEHOLDER" in l]


def unreal_afs_token(root, files):
    """Unreal projects made from Epic's templates carry an Android File Server SecurityToken in
    Config/DefaultEngine.ini. With bAllowNetworkConnection=True a development build on Android trusts whoever holds
    it, so a published token should not stay live. Returns the files where both are set."""
    found = []
    for rel in files:
        if not rel.lower().endswith("config/defaultengine.ini"):
            continue
        try:
            lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        section, token, network = "", False, False
        for line in lines:
            line = line.strip()
            if line.startswith("["):
                section = line
            elif section == AFS_SECTION and "=" in line:
                key, value = (s.strip() for s in line.split("=", 1))
                token = token or (key == "SecurityToken" and value != "")
                network = network or (key == "bAllowNetworkConnection" and value.lower() == "true")
        if token and network:
            found.append(rel)
    return found


def history_messages(root):
    """[(short hash, full message)] for every commit on every ref (empty for a repo with no commits)."""
    out = git(root, "log", "--all", "-z", "--format=%h%x01%B", check=False).decode("utf-8", "replace")
    return [tuple(entry.split("\x01", 1)) for entry in out.split("\0") if "\x01" in entry]


def run(root, terms=(), style=False, terms_path=None):
    """Tree mode. terms: from load_terms; terms_path: the list's resolved path (never scanned, FAIL if published)."""
    fails, warns = [], []
    files = publishable_files(root)
    terms_rel = rel_inside(root, terms_path)
    if terms_rel in files:
        fails.append(f"{terms_rel}: the private term list itself would be published (keep it outside the repo, or "
                     "add it to .gitignore)")
        files = [f for f in files if f != terms_rel]
    for rel in files:
        fails += [f"{rel}: its path contains a {hit}" for hit in term_hits(rel, terms)]
    for short, message in history_messages(root) if terms else ():
        fails += [f"commit {short} message: {hit} (public once pushed; reword it before pushing)"
                  for hit in term_hits(message, terms)]
    if not any(f.lower() in LICENSE_NAMES for f in files):
        fails.append("no LICENSE file at the root: without one, nobody may legally reuse the code (SOP-13 step 1)")
    lfs = lfs_paths(root, files)
    if lfs and not lfs_ready(root):
        warns.append(f"{len(lfs)} file(s) have filter=lfs in .gitattributes, but Git LFS is not set up here "
                     "(`git lfs install`): they would be committed as they are, so their sizes are checked")
        lfs = set()
    for rel in files:
        path = root / rel
        if os.path.islink(path):
            # git publishes the link's own text (where it points), not the file behind it: check that text, and
            # the name; a dangling link is published too (#238)
            if is_secret_name(rel):
                fails.append(f"{rel}: secret-type file would be published (remove it and add it to .gitignore)")
            try:
                tokens, homes = scan_lines(os.readlink(path), terms=terms, style=style)
            except OSError:
                tokens, homes = [], []
            fails += [f"{rel} (symlink) {x}" for x in tokens]
            warns += [f"{rel} (symlink) {h} (a personal path; it names your account)" for h in homes]
            continue
        if not path.is_file():
            continue                                  # deleted in the working tree but still in the index
        if is_secret_name(rel):
            fails.append(f"{rel}: secret-type file would be published (remove it and add it to .gitignore)")
        size = path.stat().st_size
        if rel not in lfs and size > GITHUB_HARD_LIMIT:
            fails.append(f"{rel}: {size // 2**20} MB and not in LFS; GitHub rejects files over 100 MB")
        elif rel not in lfs and size > GITHUB_WARN_LIMIT:
            warns.append(f"{rel}: {size // 2**20} MB and not in LFS; GitHub warns over 50 MB")
        if unscanned_text(path):                      # check it by hand for tokens and personal paths
            warns.append(f"not content-scanned (over {MAX_TEXT_SCAN // 2**20} MB): {rel}")
        try:
            tokens, homes = scan_text(path, terms, style)
        except Unreadable as exc:
            warns.append(f"{rel}: could not be read ({exc}), so it was not scanned: check it by hand")
            tokens, homes = [], []
        fails += [f"{rel} {t}" for t in tokens]
        warns += [f"{rel} {h} (a personal path; it names your account)" for h in homes]
        folder = pxo_export_folder(path) if rel.lower().endswith(".pxo") else ""
        if folder == PXO_UNREADABLE:
            warns.append(f"{rel}: its data.json cannot be read (encrypted, or an unsupported compression), so its "
                         "export folder was not checked: open it in Pixelorama and save it again")
        elif folder:
            warns.append(f"{rel}: Pixelorama saved the folder you last exported to in it, {folder} (a path on your "
                         "machine); blank it with `python tools/art/dotwork/dotwork.py pixelorama --clear-export-path`")
    for email in history_emails(root):
        if not NOREPLY.search(email):
            warns.append(f"commit history contains {email} (public once pushed; see SOP-13 step 3 for the noreply address)")
    warns += [f"{p}: PLACEHOLDER asset row (license unknown; resolve before publishing)" for p in placeholder_assets(root)]
    warns += [f"{rel}: Unreal's Android File Server SecurityToken (from Epic's template) with network connections on; "
              "set bAllowNetworkConnection=False and clear the token before publishing (SOP-13 step 3)"
              for rel in unreal_afs_token(root, files)]
    return files, fails, warns


# ---- range mode ----------------------------------------------------------------------------------------------------
def unquote_path(text):
    """A path as git prints it in a patch header: C-quoted ("a\\tb", octal bytes) when it holds unusual characters."""
    if not (len(text) >= 2 and text[0] == '"' and text[-1] == '"'):
        return text
    raw, i, body = bytearray(), 0, text[1:-1]
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in "01234567" and re.match(r"[0-7]{3}", body[i + 1:i + 4]):
                raw.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
            raw += C_ESCAPES.get(nxt, nxt).encode("utf-8")
            i += 2
            continue
        raw += ch.encode("utf-8")
        i += 1
    return raw.decode("utf-8", "surrogateescape")


def added_lines(patch):
    """Yield (path, new line number, text) for every line a -U0 patch adds. Hunk sizes decide what is content, so an
    added line that itself starts with "++" is never taken for a file header."""
    path, new_no, old_left, new_left = None, 0, 0, 0
    for raw in patch.split("\n"):
        if old_left > 0 or new_left > 0:
            if raw.startswith("+"):
                if path is not None:
                    yield path, new_no, raw[1:].rstrip("\r")
                new_no += 1
                new_left -= 1
            elif raw.startswith("-"):
                old_left -= 1
            elif raw.startswith(" "):
                old_left, new_left, new_no = old_left - 1, new_left - 1, new_no + 1
            elif not raw.startswith("\\"):        # "\ No newline at end of file" belongs to the hunk
                old_left = new_left = 0           # malformed: leave the hunk
            continue
        if raw.startswith("diff --git "):
            path = None
        elif raw.startswith("+++ "):
            name = unquote_path(raw[4:].rstrip("\r"))
            path = None if name == "/dev/null" else (name[2:] if name.startswith("b/") else name)
        elif raw.startswith("@@"):
            m = HUNK.match(raw)
            if m:
                old_left = int(m.group(1)) if m.group(1) is not None else 1
                new_no = int(m.group(2))
                new_left = int(m.group(3)) if m.group(3) is not None else 1


def range_commits(root, rng):
    """Full hashes in rng, oldest first. Raises UsageProblem for something that is not a valid A..B range."""
    if ".." not in rng or rng.startswith("-"):
        raise UsageProblem(f"--range wants A..B (two commits or branches), got {rng!r}")
    try:
        out = git(root, "rev-list", "--reverse", rng, "--")
    except RuntimeError as exc:
        raise UsageProblem(f"git does not know the range {rng}: {exc}")
    return out.decode("utf-8", "replace").split()


def commit_info(root, sha):
    """(short hash, subject, full message, {author and committer emails}) of one commit."""
    out = git(root, "show", "-s", "--format=%h%x00%ae%x00%ce%x00%B", sha).decode("utf-8", "replace")
    short, author, committer, message = (out.split("\0", 3) + ["", "", ""])[:4]
    subject = (message.strip().splitlines() or [""])[0]
    return short.strip(), subject, message, {e for e in (author.strip(), committer.strip()) if e}


def commit_files(root, sha):
    """Paths a commit adds, changes, renames or copies to (deletions left out: a removal publishes nothing new)."""
    out = git(root, "-c", "core.quotepath=off", "diff-tree", "-r", "--root", "--no-commit-id", "-z", "-M",
              "--name-status", sha).decode("utf-8", "surrogateescape")
    fields, paths, i = out.split("\0"), [], 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        count = 2 if status[:1] in ("R", "C") else 1
        names = fields[i + 1:i + 1 + count]
        if status[:1] != "D" and names:
            paths.append(names[-1])
        i += 1 + count
    return paths


def commit_patch(root, sha):
    # explicit prefixes: diff.noprefix or diff.mnemonicPrefix in a user's config would change a/ and b/
    return git(root, "-c", "core.quotepath=off", "diff-tree", "-r", "--root", "-p", "-M", "--unified=0",
               "--no-color", "--no-ext-diff", "--no-textconv", "--no-commit-id", "--src-prefix=a/",
               "--dst-prefix=b/", sha).decode("utf-8", "replace")


def is_local_only(rel):
    low = rel.lower()
    return any(fnmatch.fnmatchcase(low, g) for g in LOCAL_ONLY_GLOBS)


def check_commit(root, sha, terms=(), style=False, trailer=None, terms_rel=None):
    """(short hash, subject, fails, warns, emails) for one commit."""
    short, subject, message, emails = commit_info(root, sha)
    fails, warns = [], []
    for rel in commit_files(root, sha):
        if terms_rel and rel == terms_rel:
            fails.append(f"{rel}: commits the private term list itself")
        elif is_secret_name(rel):
            fails.append(f"{rel}: secret-type file in the commit (remove it and add it to .gitignore)")
        elif is_local_only(rel):
            fails.append(f"{rel}: a local-only or scratch file in the commit (CLAUDE.local.md, settings.local.json, "
                         "captures/, scratch/, logs); take it out and keep it ignored")
        fails += [f"{rel}: its path contains a {hit}" for hit in term_hits(rel, terms)]
    for rel, lineno, text in added_lines(commit_patch(root, sha)):
        if terms_rel and rel == terms_rel:
            continue
        found, home = scan_line(text, is_config(rel), terms, style)
        fails += [f"{rel} line {lineno}: {x}" for x in found]
        if home:
            warns.append(f"{rel} line {lineno}: {home} (a personal path; it names your account)")
    for lineno, text in enumerate(message.splitlines(), 1):
        found, home = scan_line(text, False, terms, style)
        fails += [f"commit message line {lineno}: {x}" for x in found]
        if home:
            warns.append(f"commit message line {lineno}: {home} (a personal path)")
    if trailer and not any(l.strip().lower().startswith(trailer.lower()) for l in message.splitlines()):
        warns.append(f"no {trailer!r} trailer in the commit message")
    return short, subject, fails, warns, emails


def run_range(root, rng, terms=(), style=False, trailer=None, terms_path=None):
    """[(short hash, subject, fails, warns)] per commit in rng, oldest first. Each personal email is reported once,
    at the first commit that carries it."""
    results, seen = [], set()
    terms_rel = rel_inside(root, terms_path)
    for sha in range_commits(root, rng):
        short, subject, fails, warns, emails = check_commit(root, sha, terms, style, trailer, terms_rel)
        for email in sorted(emails - seen):
            if not NOREPLY.search(email):
                warns.append(f"author or committer email {email} (public once pushed; SOP-13 step 3)")
        seen |= emails
        results.append((short, subject, fails, warns))
    return results


def print_range(root, rng, results):
    fails = sum(len(r[2]) for r in results)
    warns = sum(len(r[3]) for r in results)
    print(f"publish_check: {len(results)} commit(s) in {rng} ({root})")
    for short, subject, c_fails, c_warns in results:
        print(f"  {short} {subject[:100]}: {len(c_fails)} FAIL, {len(c_warns)} WARN")
        for item in c_fails:
            print(f"    FAIL  {item}")
        for item in c_warns:
            print(f"    WARN  {item}")
    print("Only the lines these commits add were scanned. Run without --range for the whole tree.")
    print(f"Result: {fails} FAIL, {warns} WARN")
    return 1 if fails else 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="Check a git repo for things that should not go public (SOP-13): the working tree, or with "
                    "--range only the lines and messages of some commits.",
        epilog=f"Private terms: one per line, a plain word or phrase (whole word, any case) or re:<regex>; # starts a "
               f"comment. Keep the list outside the repo (e.g. ~/.config/game-kit/private-terms.txt) and point "
               f"{TERMS_ENV} at it, or use the gitignored .private-terms.txt in the project. Exit 0 no FAIL, "
               f"1 FAIL items, 2 git missing, not a repo, a bad range or terms file.", allow_abbrev=False)
    ap.add_argument("--root", default=".", help="repository folder (default: current folder)")
    ap.add_argument("--range", "--commits", dest="range", metavar="A..B",
                    help="scan only the commits in A..B: added lines, messages, files they must not add")
    ap.add_argument("--terms", metavar="FILE",
                    help=f"private term list that must never appear publicly (default: ${TERMS_ENV}, if set)")
    ap.add_argument("--style", action="store_true", help="also FAIL on em dashes in scanned text")
    ap.add_argument("--trailer", metavar="TEXT",
                    help="with --range: WARN for commits without a message line starting with TEXT")
    ap.add_argument("--debug", action="store_true", help="print a traceback on unexpected errors")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.trailer and not args.range:
        print("publish_check: --trailer only applies with --range", file=sys.stderr)
        return 2
    try:
        terms, terms_path = resolve_terms(args.terms)
        git(root, "rev-parse", "--git-dir")
        if args.range:
            results = run_range(root, args.range, terms, args.style, args.trailer, terms_path)
            return print_range(root, args.range, results)
        files, fails, warns = run(root, terms, args.style, terms_path)
    except UsageProblem as exc:
        print(f"publish_check: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print("publish_check: git is not installed or not on PATH", file=sys.stderr)
        return 2
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        if args.debug:
            traceback.print_exc()
        print(f"publish_check: {root} is not a usable git repository ({exc})", file=sys.stderr)
        return 2
    print(f"publish_check: {len(files)} files would be published from {root}")
    if terms_path:
        print(f"publish_check: {len(terms)} private term(s) checked in files, file names and commit messages")
    for item in fails:
        print(f"  FAIL  {item}")
    for item in warns:
        print(f"  WARN  {item}")
    print("Not checked here: old commits (run `gitleaks git` or similar), asset redistribution rights "
          "(docs/ASSET_LOG.md), and GitHub settings (SOP-13 step 6).")
    print(f"Result: {len(fails)} FAIL, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
