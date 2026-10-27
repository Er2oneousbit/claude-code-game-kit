#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# publish_check.py
# Purpose : Pre-flight before a repo goes public (SOP-13). Looks at what git would
#           publish (tracked files plus untracked files that are not ignored) and
#           reports what should not be there: no LICENSE, secret files, token-shaped
#           strings, files GitHub rejects without LFS, personal paths, and personal
#           email addresses in commit history.
# Usage   : python tools/publish_check.py [--root DIR] [--debug]
# Exit    : 0 no FAIL items (WARN items may remain), 1 FAIL items found, 2 not a git repo / git missing
# Notes   : Scans the working tree, not old commits. A secret that was committed and then
#           deleted is still in history: run a history scanner (gitleaks) before going public,
#           and rotate any key it finds. Pattern matching is a net, not a guarantee.
#           Standard library only, Python 3.8+.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   list files git would publish (ls-files tracked + others --exclude-standard)
#   FAIL: no LICENSE; secret-named files; token-shaped strings in text files; files > 100 MB not routed to LFS
#   WARN: files > 50 MB not in LFS; home-folder paths in text; non-noreply emails in history;
#         PLACEHOLDER rows in docs/ASSET_LOG.md; Unreal's Android File Server token with network connections on
#   print grouped results and the reminders that cannot be automated, return exit code
import argparse
import fnmatch
import re
import subprocess
import sys
import traceback
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
    ("Slack token", re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{10,}")),
    ("Stripe live key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}")),
    ("Discord webhook", re.compile(r"https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]{20,}")),
    ("hard-coded secret", re.compile(r"(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d)\b\s*[:=]\s*[\"'][^\"'\s<>{}]{16,}[\"']")),
]
# A real user's home folder (not a <name> placeholder or a generic example)
HOME_PATH = re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+(?!<|\{|Public\b|Default\b|you\b|name\b|USERNAME\b)[^\\/\s\"'`<>]+"
                       r"|/(?:Users|home)/(?!<|\{|you\b|name\b|runner\b|user\b)[A-Za-z0-9._-]+/")
NOREPLY = re.compile(r"(?i)@users\.noreply\.github\.com$|^noreply@|@noreply\.")
GITHUB_HARD_LIMIT = 100 * 1024 * 1024   # GitHub rejects pushes with a file over 100 MB
GITHUB_WARN_LIMIT = 50 * 1024 * 1024    # and warns over 50 MB
MAX_TEXT_SCAN = 2 * 1024 * 1024         # skip content scans of larger files (assets, not config)
AFS_SECTION = "[/Script/AndroidFileServerEditor.AndroidFileServerRuntimeSettings]"   # Unreal, from Epic's template


def git(root, *args, check=True):
    """Run git in root; return stdout bytes. Raises RuntimeError with git's message on failure."""
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return r.stdout


def publishable_files(root):
    """Paths (relative, forward slashes) that `git add -A` and a push would publish."""
    out = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted({p for p in out.decode("utf-8", "replace").split("\0") if p})


def lfs_paths(root, paths):
    """Subset of paths whose filter attribute is lfs."""
    if not paths:
        return set()
    r = subprocess.run(["git", "-C", str(root), "check-attr", "-z", "--stdin", "filter"], capture_output=True,
                       input="\0".join(paths).encode("utf-8") + b"\0", timeout=120)
    fields = r.stdout.decode("utf-8", "replace").split("\0")
    return {fields[i] for i in range(0, len(fields) - 2, 3) if fields[i + 2] == "lfs"}


def is_secret_name(rel):
    base = rel.rsplit("/", 1)[-1].lower()
    return base not in SECRET_ALLOW and any(fnmatch.fnmatch(base, g) for g in SECRET_GLOBS)


def scan_text(path):
    """Return (token findings, home-path findings) for one file, or ([], []) for binary or large files."""
    try:
        if path.stat().st_size > MAX_TEXT_SCAN:
            return [], []
        data = path.read_bytes()
    except OSError:
        return [], []
    if b"\0" in data[:8192]:
        return [], []
    text = data.decode("utf-8", "replace")
    tokens, homes = [], []
    for lineno, line in enumerate(text.splitlines(), 1):
        for label, pat in TOKEN_PATTERNS:
            if pat.search(line):
                tokens.append(f"line {lineno}: looks like a {label}")
        m = HOME_PATH.search(line)
        if m:
            homes.append(f"line {lineno}: {m.group(0)}")
    return tokens, homes


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


def run(root):
    fails, warns = [], []
    files = publishable_files(root)
    if not any(f.lower() in LICENSE_NAMES for f in files):
        fails.append("no LICENSE file at the root: without one, nobody may legally reuse the code (SOP-13 step 1)")
    lfs = lfs_paths(root, files)
    for rel in files:
        path = root / rel
        if not path.is_file():
            continue                                  # deleted in the working tree but still in the index
        if is_secret_name(rel):
            fails.append(f"{rel}: secret-type file would be published (remove it and add it to .gitignore)")
        size = path.stat().st_size
        if rel not in lfs and size > GITHUB_HARD_LIMIT:
            fails.append(f"{rel}: {size // 2**20} MB and not in LFS; GitHub rejects files over 100 MB")
        elif rel not in lfs and size > GITHUB_WARN_LIMIT:
            warns.append(f"{rel}: {size // 2**20} MB and not in LFS; GitHub warns over 50 MB")
        tokens, homes = scan_text(path)
        fails += [f"{rel} {t}" for t in tokens]
        warns += [f"{rel} {h} (a personal path; it names your account)" for h in homes]
    for email in history_emails(root):
        if not NOREPLY.search(email):
            warns.append(f"commit history contains {email} (public once pushed; see SOP-13 step 3 for the noreply address)")
    warns += [f"{p}: PLACEHOLDER asset row (license unknown; resolve before publishing)" for p in placeholder_assets(root)]
    warns += [f"{rel}: Unreal's Android File Server SecurityToken (from Epic's template) with network connections on; "
              "set bAllowNetworkConnection=False and clear the token before publishing (SOP-13 step 3)"
              for rel in unreal_afs_token(root, files)]
    return files, fails, warns


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Check a git repo for things that should not go public (SOP-13).")
    ap.add_argument("--root", default=".", help="repository folder (default: current folder)")
    ap.add_argument("--debug", action="store_true", help="print a traceback on unexpected errors")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        git(root, "rev-parse", "--git-dir")
        files, fails, warns = run(root)
    except FileNotFoundError:
        print("publish_check: git is not installed or not on PATH", file=sys.stderr)
        return 2
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        if args.debug:
            traceback.print_exc()
        print(f"publish_check: {root} is not a usable git repository ({exc})", file=sys.stderr)
        return 2
    print(f"publish_check: {len(files)} files would be published from {root}")
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
